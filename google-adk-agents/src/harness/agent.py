"""
Clinical ADK Agent Harness.
Implements the 4-step Agent Harness architecture wrapping Google Gemini & ADK:
Step 1: Continuous reasoning loop that manages inputs, model turns, and tool completions.
Step 2: MCP tool interception and execution via FastMCP bridge.
Step 3: Context window tracking, tool output caching, and progressive disclosure.
Step 4: Production-ready harness execution supporting live Gemini and offline deterministic modes.

Safety invariants
-----------------
* The deterministic SafetyGateEngine verdict is computed from parsed input BEFORE any
  Gemini turn.  last_route and last_status therefore always start as "CLARIFY" /
  "UNKNOWN" — never as "PROCEED" / "RESOLVED".
* Protocol-retrieval tools (fetch_grounded_protocol, attest_computation) are blocked
  until the gate verdict is PROCEED.  The model cannot bypass them by calling those
  tools directly.
* A missing GEMINI_API_KEY causes a WARNING log and selects offline/stub mode
  explicitly — no silent degradation.
* The blanket except-Exception around Gemini API calls has been narrowed; unexpected
  errors are re-raised rather than silently swallowed.
"""
from __future__ import annotations

import logging
import os
import warnings
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from google.genai import Client, types

from src.harness.context import ContextWindowManager
from src.harness.mcp_client import MCPToolBridge
from src.harness.session import HarnessSession, SessionMessage, ToolInvocationRecord

log = logging.getLogger(__name__)

# Tools that are only reachable after a PROCEED gate verdict.
_GATE_GUARDED_TOOLS: frozenset = frozenset({"fetch_grounded_protocol", "attest_computation"})


class HarnessResponse(BaseModel):
    """Structured response returned by the Clinical ADK Harness."""
    text: str
    route: str  # "PROCEED" | "CLARIFY"
    status: str  # "RESOLVED" | "AMBIGUOUS" | "UNIT_MISMATCH" | "RANGE_COLLISION" | etc.
    session_id: str
    tool_calls: List[ToolInvocationRecord] = Field(default_factory=list)
    protocol: Dict[str, Any] = Field(default_factory=dict)
    clarification: Optional[str] = None
    is_hitl_paused: bool = False
    attested: bool = False


class ClinicalADKHarness:
    """
    Google ADK Clinical Decision Support Agent Harness.
    Wraps the language model in a continuous reasoning loop with MCP tool interception,
    deterministic safety gate enforcement, and context window management.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        client: Optional[Client] = None,
        mcp_bridge: Optional[MCPToolBridge] = None,
        context_mgr: Optional[ContextWindowManager] = None,
        offline: Optional[bool] = None,
        max_turns: int = 10,
    ):
        from ontogate.catalog import model_for

        self.model_name = model_name or model_for("gcp")["id"]  # config/models.yaml
        self.mcp_bridge = mcp_bridge or MCPToolBridge()
        self.context_mgr = context_mgr or ContextWindowManager()
        self.max_turns = max_turns

        # Check offline mode preference or missing credentials
        if offline is not None:
            self.offline = offline
        else:
            api_key = os.environ.get("GEMINI_API_KEY", "").strip()
            if not api_key:
                warnings.warn(
                    "No GEMINI_API_KEY found — running in offline/stub mode. "
                    "Gate-bypassing vulnerabilities are masked in this mode. "
                    "Set GEMINI_API_KEY for live Gemini execution.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            self.offline = (not api_key) or ("--offline" in os.sys.argv)

        self.client = client
        if not self.offline and self.client is None:
            try:
                self.client = Client()
            except Exception:
                log.warning(
                    "Gemini Client init failed — falling back to offline/stub mode.",
                    exc_info=True,
                )
                self.offline = True

    def create_session(self, session_id: Optional[str] = None) -> HarnessSession:
        """Create a fresh conversation session."""
        if session_id:
            return HarnessSession(session_id=session_id)
        return HarnessSession()

    def parse_clinician_query(self, prompt: str) -> Dict[str, Any]:
        """Parse clinician input with the shared ontology-aware parser (``ontogate.parsing``).

        Pipe segments are classified by vocabulary (unit, facet qualifier,
        population, department); a term naming a panel sets ``panel_id``. A comma
        followed by exactly three digits (``1,250``) is an ambiguous thousands
        separator: ``patient_value`` is None and the gate routes to CLARIFY.
        """
        from ontogate.parsing import parse_clinician_text

        return parse_clinician_text(prompt)

    def _compute_gate_verdict(
        self,
        parsed: Dict[str, Any],
        all_tool_calls: List[ToolInvocationRecord],
        session: HarnessSession,
    ) -> Dict[str, Any]:
        """
        Compute the safety-gate verdict in pure code from parsed input.

        This is called BEFORE any Gemini turn so the gate cannot be bypassed by
        a model that chooses not to call evaluate_safety_gate.

        Returns the raw gate result dict (route, status, clarification_prompt, …).
        """
        # Ambiguous thousands separator → immediate CLARIFY before the gate runs
        if parsed.get("ambiguous_thousands"):
            return {
                "route": "CLARIFY",
                "status": "AMBIGUOUS",
                "passed": False,
                "clarification_prompt": (
                    f"Value '{parsed['raw_text']}' contains a comma that looks like "
                    "a thousands separator (e.g. '1,250'). Please resend with an "
                    "unambiguous decimal format."
                ),
                "triggered_gaps": ["AmbiguousThousandsSeparator"],
                "candidates": [],
            }

        # Panel requests (e.g. "CSF Emergency Panel") are evaluated by the gate too,
        # via panel_id — there is no synthetic PROCEED bypass.
        population = parsed.get("population") or {}
        gate_args = {
            "term": parsed["term"],
            "unit": parsed["unit"],
            "qualifier": parsed["qualifier"],
            "patient_value": parsed["patient_value"],
            "status": "UNKNOWN",
            "sex": population.get("sex", ""),
            "age_band": population.get("age_band", ""),
            "department": parsed.get("department", ""),
            "panel_id": parsed.get("panel_id") or "",
        }
        gate_res = self.mcp_bridge.execute_tool("evaluate_safety_gate", gate_args)
        rec = ToolInvocationRecord(
            tool_name="evaluate_safety_gate", args=gate_args, result=gate_res
        )
        all_tool_calls.append(rec)
        self.context_mgr.append_tool_result_to_session(session, "evaluate_safety_gate", gate_res)
        return gate_res

    def _clarify(self, session: HarnessSession, tool_calls: List[ToolInvocationRecord], status: str,
                 clarification: str) -> HarnessResponse:
        """Fail-closed HITL pause response."""
        output_text = f"[CLARIFY - HITL Pause]\n{clarification}"
        session.add_model_message(content=output_text, tool_calls=tool_calls)
        return HarnessResponse(text=output_text, route="CLARIFY", status=status, session_id=session.session_id,
                               tool_calls=tool_calls, clarification=clarification, is_hitl_paused=True)

    async def run(
        self,
        prompt: str,
        session: Optional[HarnessSession] = None,
    ) -> HarnessResponse:
        """
        Execute the agent harness reasoning cycle (Step 1).
        Accepts user prompt, evaluates continuous reasoning loop, intercepts MCP tools (Step 2),
        appends tool outputs to context history (Step 3), and returns verified clinical response.
        """
        if session is None:
            session = self.create_session()

        # Append initial user prompt to session history
        session.add_user_message(content=prompt)

        # If running offline or without live credentials, execute deterministic pipeline
        if self.offline or self.client is None:
            return self._run_deterministic_pipeline(prompt, session)

        # Live Gemini execution loop
        return await self._run_gemini_loop(prompt, session)

    def _run_deterministic_pipeline(
        self,
        prompt: str,
        session: HarnessSession,
    ) -> HarnessResponse:
        """
        Deterministic harness execution loop for offline CI/CD and safety verification.
        Executes tools through the MCP bridge and enforces fail-closed routing.
        """
        parsed = self.parse_clinician_query(prompt)
        term = parsed["term"]
        unit = parsed["unit"]
        qualifier = parsed["qualifier"]
        val = parsed["patient_value"]

        all_tool_calls: List[ToolInvocationRecord] = []

        # Ambiguous thousands separator guard: "1,250" → CLARIFY
        if parsed.get("ambiguous_thousands"):
            clarification_msg = (
                f"Value '{parsed['raw_text']}' contains a comma that looks like "
                "a thousands separator (e.g. '1,250'). Please resend with an "
                "unambiguous decimal format."
            )
            output_text = f"[CLARIFY - HITL Pause]\n{clarification_msg}"
            session.add_model_message(content=output_text, tool_calls=all_tool_calls)
            return HarnessResponse(
                text=output_text,
                route="CLARIFY",
                status="AMBIGUOUS",
                session_id=session.session_id,
                tool_calls=all_tool_calls,
                clarification=clarification_msg,
                is_hitl_paused=True,
            )

        # Panel requests: deterministic gate (panel_id) → ordered, department-scoped workup.
        if parsed.get("panel_id"):
            gate_res = self._compute_gate_verdict(parsed, all_tool_calls, session)
            if gate_res.get("route") != "PROCEED":
                return self._clarify(session, all_tool_calls, gate_res.get("status", "NOT_FOUND"),
                                     gate_res.get("clarification_prompt") or "Panel request could not be scoped.")
            panel_args = {"panel": parsed["panel_id"], "department": parsed.get("department", "")}
            panel_res = self.mcp_bridge.execute_tool("panel_workup", panel_args)
            all_tool_calls.append(ToolInvocationRecord(tool_name="panel_workup", args=panel_args, result=panel_res))
            self.context_mgr.append_tool_result_to_session(session, "panel_workup", panel_res)
            if panel_res.get("status") != "RESOLVED":
                return self._clarify(session, all_tool_calls, "NOT_FOUND",
                                     f"No tests found for department filter '{parsed.get('department', '')}'. "
                                     "Please verify the department name or omit it to receive the full panel.")
            output_text = f"[PROCEED] {panel_res['panel']} (Governed Tube Sequence Enforced):\n"
            for tube in panel_res["tubes"]:
                output_text += f"\nDepartment: {tube['department']}\n"
                for t in tube["tests"]:
                    output_text += f"  - Tube {tube['tube']}: {t['test_name']} [{t['uri']}]\n"
            session.add_model_message(content=output_text, tool_calls=all_tool_calls)
            return HarnessResponse(text=output_text.strip(), route="PROCEED", status="RESOLVED",
                                   session_id=session.session_id, tool_calls=all_tool_calls)

        # Standard Clinical Laboratory Workflow:
        # Step 1: Resolve ontology via MCP
        resolve_args = {"term": term, "unit": unit, "qualifier": qualifier}
        resolve_res = self.mcp_bridge.execute_tool("resolve_lab_term", resolve_args)
        record_resolve = ToolInvocationRecord(tool_name="resolve_lab_term", args=resolve_args, result=resolve_res)
        all_tool_calls.append(record_resolve)
        self.context_mgr.append_tool_result_to_session(session, "resolve_lab_term", resolve_res)
        candidates = resolve_res.get("candidates", [])

        # Step 2: Deterministic safety gate (the only routing authority)
        gate_res = self._compute_gate_verdict(parsed, all_tool_calls, session)
        status = gate_res.get("status", "UNKNOWN")
        route = gate_res.get("route", "CLARIFY")

        # Step 3: Branch on Safety Gate Verdict
        if route == "CLARIFY":
            clarification = gate_res.get("clarification_prompt") or (
                f"Clarification required for laboratory order '{term}' (status {status})."
            )
            return self._clarify(session, all_tool_calls, status, clarification)

        # Step 4: Route == PROCEED -> Fetch Grounded Protocol & Attest
        candidate = candidates[0] if candidates else {}
        uri = candidate.get("uri", "")

        proto_args = {"uri": uri}
        proto_res = self.mcp_bridge.execute_tool("fetch_grounded_protocol", proto_args)
        record_proto = ToolInvocationRecord(tool_name="fetch_grounded_protocol", args=proto_args, result=proto_res)
        all_tool_calls.append(record_proto)
        self.context_mgr.append_tool_result_to_session(session, "fetch_grounded_protocol", proto_res)
        proto_detail = proto_res.get("protocol", proto_res)

        # Step 5: Attest computation
        attested = False
        badge = ""
        panic_warning = ""
        attest_failure_msg = ""
        if val is not None and uri:
            attest_args = {"value": val, "uri": uri, "unit": unit}
            attest_res = self.mcp_bridge.execute_tool("attest_computation", attest_args)
            record_attest = ToolInvocationRecord(tool_name="attest_computation", args=attest_args, result=attest_res)
            all_tool_calls.append(record_attest)
            self.context_mgr.append_tool_result_to_session(session, "attest_computation", attest_res)
            if attest_res.get("passed"):
                attested = True
                badge = " [Attested ✓]"
                # a panic value passes attestation but must never receive
                # a clean badge without a CRITICAL WARNING visible to the clinician.
                if attest_res.get("is_panic"):
                    panic_warning = (
                        f"\n⚠️  CRITICAL — PANIC VALUE: {val} {unit} is outside the panic "
                        f"limits for {candidate.get('label', uri)}. "
                        f"Panic limits: {attest_res.get('panic_limits', proto_detail.get('panic_limits', 'N/A'))}. "
                        "Immediate clinical escalation required."
                    )
            else:
                attest_fail_reason = attest_res.get("message", "Value failed deterministic attestation.")
                clarification_msg = (
                    f"Attestation failed for {candidate.get('label', uri)}: {attest_fail_reason} "
                    "Value is outside plausible clinical parameters or protocol is stale. "
                    "Please verify and resend the order."
                )
                output_text = f"[CLARIFY - HITL Pause]\n{clarification_msg}"
                session.add_model_message(content=output_text, tool_calls=all_tool_calls)
                return HarnessResponse(
                    text=output_text,
                    route="CLARIFY",
                    status="ATTESTATION_FAILED",
                    session_id=session.session_id,
                    tool_calls=all_tool_calls,
                    protocol=proto_res,
                    attested=False,
                    clarification=clarification_msg,
                    is_hitl_paused=True,
                )

        output_text = (
            f"[PROCEED - Grounded Interpretation]{badge}\n"
            f"Resolved Concept: {candidate.get('label')} ({uri})\n"
            f"Department: {candidate.get('department')}\n"
            f"Patient Value: {val} {unit}\n"
            f"Reference Range: {proto_detail.get('reference_range', 'N/A')}\n"
            f"Panic Limits: {proto_detail.get('panic_limits', 'N/A')}\n"
            f"Clinical Guidance: Verified against canonical ontology and governed protocols."
            f"{panic_warning}{attest_failure_msg}"
        )

        session.add_model_message(content=output_text, tool_calls=all_tool_calls)
        return HarnessResponse(
            text=output_text,
            route="PROCEED",
            status=status,
            session_id=session.session_id,
            tool_calls=all_tool_calls,
            protocol=proto_res,
            attested=attested,
        )

    async def _run_gemini_loop(
        self,
        prompt: str,
        session: HarnessSession,
    ) -> HarnessResponse:
        """
        Continuous reasoning loop with live Gemini model.

        Safety guarantees
        -----------------
        1. The deterministic gate is computed from parsed input BEFORE any Gemini
           turn.  ``last_route`` and ``last_status`` start as CLARIFY / UNKNOWN.
        2. Gate-guarded tools (fetch_grounded_protocol, attest_computation) are
           blocked until the gate verdict is PROCEED.
        3. Exceptions from the Gemini API are narrowed: only transient API errors
           trigger a fallback; unexpected errors are re-raised.
        """
        all_tool_calls: List[ToolInvocationRecord] = []

        # --- compute gate verdict in code BEFORE any Gemini turn ---
        parsed = self.parse_clinician_query(prompt)
        gate_res = self._compute_gate_verdict(parsed, all_tool_calls, session)

        # Fail-closed defaults: CLARIFY / UNKNOWN until gate explicitly clears.
        last_route: str = gate_res.get("route", "CLARIFY")
        last_status: str = gate_res.get("status", "UNKNOWN")
        clarification_msg: Optional[str] = gate_res.get("clarification_prompt")

        # If gate already fails, short-circuit before any model call.
        if last_route == "CLARIFY":
            clarify_text = (
                f"[CLARIFY - Safety Gate]\n"
                f"{clarification_msg or 'Ambiguity detected. Clarification required.'}"
            )
            session.add_model_message(content=clarify_text)
            return HarnessResponse(
                text=clarify_text,
                route="CLARIFY",
                status=last_status,
                session_id=session.session_id,
                tool_calls=all_tool_calls,
                clarification=clarification_msg,
                is_hitl_paused=True,
            )

        protocol_data: Dict[str, Any] = {}
        attested = False
        turn = 0

        gemini_tools = self.mcp_bridge.get_gemini_tools()

        while turn < self.max_turns:
            turn += 1
            # Step 3: Format updated history into Gemini types.Content list
            contents = self.context_mgr.format_history_for_gemini(session)

            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        tools=gemini_tools,
                        system_instruction=self.context_mgr.system_instruction,
                        temperature=0.0,
                    ),
                )
            except Exception as e:
                # Narrow the fallback: only swallow API-level errors (network,
                # quota, retryable).  Re-raise programming errors.
                err_name = type(e).__name__
                _retryable = ("GoogleAPICallError", "ServiceUnavailable", "DeadlineExceeded",
                              "ResourceExhausted", "InternalServerError", "BadGateway",
                              "TooManyRequests", "ConnectionError", "TimeoutError")
                if not any(err_name.endswith(n) for n in _retryable):
                    raise
                log.warning(
                    "[WARN] Gemini API error (%s) — falling back to deterministic pipeline: %s",
                    err_name, e,
                )
                return self._run_deterministic_pipeline(prompt, session)

            # Check if Gemini issued tool calls
            candidate = response.candidates[0] if response.candidates else None
            if not candidate or not candidate.content or not candidate.content.parts:
                break

            function_calls = [
                p.function_call
                for p in candidate.content.parts
                if hasattr(p, "function_call") and p.function_call
            ]

            if function_calls:
                # Model requested tool calls: intercept and execute via MCP (Step 2)
                executed_records = []
                for fc in function_calls:
                    tool_name = fc.name
                    tool_args = dict(fc.args) if fc.args else {}

                    # --- gate-guard protocol retrieval tools ---
                    if tool_name in _GATE_GUARDED_TOOLS and last_route != "PROCEED":
                        blocked_result: Dict[str, Any] = {
                            "status": "BLOCKED",
                            "error": (
                                f"Tool '{tool_name}' is only reachable after a PROCEED "
                                "safety-gate verdict. Current gate status: "
                                f"{last_status}. Provide qualifying information first."
                            ),
                        }
                        rec = ToolInvocationRecord(
                            tool_name=tool_name, args=tool_args, result=blocked_result
                        )
                        executed_records.append(rec)
                        all_tool_calls.append(rec)
                        self.context_mgr.append_tool_result_to_session(
                            session, tool_name, blocked_result
                        )
                        log.warning(
                            "[SECURITY] Model attempted to call gate-guarded tool '%s' "
                            "before PROCEED verdict (status=%s). Request blocked.",
                            tool_name, last_status,
                        )
                        continue

                    tool_result = self.mcp_bridge.execute_tool(tool_name, tool_args)

                    rec = ToolInvocationRecord(tool_name=tool_name, args=tool_args, result=tool_result)
                    executed_records.append(rec)
                    all_tool_calls.append(rec)

                    # Step 3: Append tool output to conversation history
                    self.context_mgr.append_tool_result_to_session(session, tool_name, tool_result)

                    # Intercept safety gate verdicts from model-requested gate calls
                    if tool_name == "evaluate_safety_gate":
                        new_route = tool_result.get("route", "CLARIFY")
                        new_status = tool_result.get("status", "UNKNOWN")
                        # Gate can only stay-or-narrow — never upgrade to PROCEED if
                        # the pre-computed verdict was already CLARIFY.
                        if last_route == "PROCEED":
                            last_route = new_route
                            last_status = new_status
                        if new_route == "CLARIFY":
                            clarification_msg = tool_result.get("clarification_prompt")

                    elif tool_name == "resolve_lab_term":
                        res_status = tool_result.get("status")
                        if res_status in ("AMBIGUOUS", "UNIT_MISMATCH", "NOT_FOUND"):
                            last_status = res_status

                    elif tool_name == "fetch_grounded_protocol":
                        protocol_data = tool_result

                    elif tool_name == "attest_computation":
                        if tool_result.get("passed"):
                            attested = True

                # Record model's function calls in history
                session.add_model_message(content="", tool_calls=executed_records)

                # If hard safety gate collision occurred, stop and pause for HITL
                if last_route == "CLARIFY":
                    clarify_text = (
                        f"[CLARIFY - HITL Pause]\n"
                        f"{clarification_msg or 'Ambiguity detected. Clarification required.'}"
                    )
                    session.add_model_message(content=clarify_text)
                    return HarnessResponse(
                        text=clarify_text,
                        route="CLARIFY",
                        status=last_status,
                        session_id=session.session_id,
                        tool_calls=all_tool_calls,
                        clarification=clarification_msg,
                        is_hitl_paused=True,
                    )

                # Otherwise, continue loop to let Gemini synthesize based on tool output
                continue

            else:
                # Model formulated final text response (or loop completed all tools)
                final_text = response.text or ""

                # If Gemini returned no prose (common when its last turn was tool calls),
                # synthesise a structured summary from accumulated tool results.
                if not final_text.strip():
                    proto = protocol_data.get("protocol", protocol_data) if protocol_data else {}
                    badge = " [Attested ✓]" if attested else ""
                    if last_route == "PROCEED" and proto:
                        final_text = (
                            f"[PROCEED{badge}]\n"
                            f"Status: {last_status}\n"
                            + (f"Resolved URI: {proto.get('uri', proto.get('loinc_uri', ''))}\n" if proto.get("uri") or proto.get("loinc_uri") else "")
                            + (f"Reference Range: {proto.get('reference_range', 'N/A')}\n" if proto.get("reference_range") else "")
                            + (f"Panic Limits: {proto.get('panic_limits', 'N/A')}" if proto.get("panic_limits") else "")
                        ).strip()
                    elif last_route == "PROCEED":
                        panel_calls = [tc for tc in all_tool_calls if tc.tool_name == "panel_workup"]
                        resolve_calls = [
                            tc for tc in all_tool_calls
                            if tc.tool_name == "resolve_lab_term" and isinstance((tc.result or {}), dict)
                        ]
                        if panel_calls and isinstance(panel_calls[-1].result, dict):
                            tubes = panel_calls[-1].result.get("tubes", [])
                            summary = [
                                f"Tube {t['tube']} {t['department']}: "
                                + ", ".join(x["test_name"] for x in t["tests"][:2])
                                for t in tubes
                            ]
                            final_text = f"[PROCEED] {last_status}" + ("".join(f" | {x}" for x in summary))
                        elif resolve_calls:
                            r = resolve_calls[-1].result or {}
                            cands = r.get("candidates", [])
                            if cands and isinstance(cands[0], dict):
                                c = cands[0]
                                label = c.get("label", "")
                                uri = c.get("uri", "")
                                units = c.get("expected_units", [])
                                unit_str = f" ({', '.join(units)})" if units else ""
                                final_text = (
                                    f"[PROCEED] {last_status}"
                                    + (f" | {label}{unit_str}" if label else "")
                                    + (f" | URI: {uri}" if uri else "")
                                )
                            else:
                                final_text = f"[PROCEED] {last_status}"
                        else:
                            final_text = f"[PROCEED] {last_status}"

                session.add_model_message(content=final_text)
                return HarnessResponse(
                    text=final_text,
                    route=last_route,
                    status=last_status,
                    session_id=session.session_id,
                    tool_calls=all_tool_calls,
                    protocol=protocol_data,
                    attested=attested,
                )

        # Loop completed or max turns reached — synthesise from accumulated state
        final_msg = session.messages[-1].content if session.messages else ""
        if not final_msg.strip() and protocol_data:
            proto = protocol_data.get("protocol", protocol_data)
            badge = " [Attested ✓]" if attested else ""
            final_msg = (
                f"[PROCEED{badge}] {last_status}\n"
                + (f"Reference Range: {proto.get('reference_range', 'N/A')}" if proto.get("reference_range") else "")
            ).strip()
        elif not final_msg.strip():
            resolve_calls = [
                tc for tc in all_tool_calls
                if tc.tool_name == "resolve_lab_term" and isinstance((tc.result or {}), dict)
            ]
            if resolve_calls:
                r = resolve_calls[-1].result or {}
                cands = r.get("candidates", [])
                if cands and isinstance(cands[0], dict):
                    c = cands[0]
                    label = c.get("label", "")
                    uri = c.get("uri", "")
                    units = c.get("expected_units", [])
                    unit_str = f" ({', '.join(units)})" if units else ""
                    final_msg = (
                        f"[{last_route}] {last_status}"
                        + (f" | {label}{unit_str}" if label else "")
                        + (f" | URI: {uri}" if uri else "")
                    )
                else:
                    final_msg = f"[{last_route}] {last_status}"
            else:
                final_msg = f"[{last_route}] {last_status}"

        return HarnessResponse(
            text=final_msg,
            route=last_route,
            status=last_status,
            session_id=session.session_id,
            tool_calls=all_tool_calls,
            protocol=protocol_data,
            attested=attested,
        )


def create_clinical_harness(
    model_name: Optional[str] = None,
    offline: Optional[bool] = None,
    **kwargs: Any,
) -> ClinicalADKHarness:
    """Factory function to instantiate ClinicalADKHarness."""
    return ClinicalADKHarness(model_name=model_name, offline=offline, **kwargs)
