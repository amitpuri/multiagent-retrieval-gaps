"""
Clinical ADK Agent Harness.
Implements the 4-step Agent Harness architecture wrapping Google Gemini & ADK:
Step 1: Continuous reasoning loop that manages inputs, model turns, and tool completions.
Step 2: MCP tool interception and execution via FastMCP bridge.
Step 3: Context window tracking, tool output caching, and progressive disclosure.
Step 4: Production-ready harness execution supporting live Gemini and offline deterministic modes.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from google.genai import Client, types

from src.harness.context import ContextWindowManager
from src.harness.mcp_client import MCPToolBridge
from src.harness.session import HarnessSession, SessionMessage, ToolInvocationRecord


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
        model_name: str = "gemini-2.5-flash",
        client: Optional[Client] = None,
        mcp_bridge: Optional[MCPToolBridge] = None,
        context_mgr: Optional[ContextWindowManager] = None,
        offline: Optional[bool] = None,
        max_turns: int = 10,
    ):
        self.model_name = model_name
        self.mcp_bridge = mcp_bridge or MCPToolBridge()
        self.context_mgr = context_mgr or ContextWindowManager()
        self.max_turns = max_turns

        # Check offline mode preference or missing credentials
        if offline is not None:
            self.offline = offline
        else:
            api_key = os.environ.get("GEMINI_API_KEY", "").strip()
            self.offline = (not api_key) or ("--offline" in os.sys.argv)

        self.client = client
        if not self.offline and self.client is None:
            try:
                self.client = Client()
            except Exception:
                # Fall back gracefully to offline deterministic mode if client fails init
                self.offline = True

    def create_session(self, session_id: Optional[str] = None) -> HarnessSession:
        """Create a fresh conversation session."""
        if session_id:
            return HarnessSession(session_id=session_id)
        return HarnessSession()

    def parse_clinician_query(self, prompt: str) -> Dict[str, Any]:
        """Utility parser to extract test term, value, qualifier, and reported unit."""
        left, _, unit = prompt.partition("|")
        left_str = left.strip()
        unit_str = unit.strip()

        # Extract qualifier if present (e.g. 'total', 'ionized')
        qualifier = ""
        low_left = left_str.lower()
        if "total" in low_left:
            qualifier = "total"
        elif "ionized" in low_left or "free" in low_left:
            qualifier = "ionized"

        # Extract numeric value
        val_match = re.search(r"\b(\d+(?:\.\d+)?)\b", left_str)
        patient_value = float(val_match.group(1)) if val_match else None

        # Clean term
        cleaned_term = re.sub(r"\b\d+(?:\.\d+)?\b", "", left_str)
        cleaned_term = re.sub(r"\b(total|ionized|free)\b", "", cleaned_term, flags=re.IGNORECASE).strip()
        cleaned_term = re.sub(r"\b(mg/dl|g/dl|mmol/l|ng/ml|ng/l)\b", "", cleaned_term, flags=re.IGNORECASE).strip()
        term = cleaned_term if cleaned_term else left_str

        return {
            "term": term,
            "unit": unit_str,
            "qualifier": qualifier,
            "patient_value": patient_value,
            "raw_text": prompt,
        }

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

        # Special case: CSF panel workup
        if "csf" in term.lower():
            csf_args = {"department": unit or qualifier}
            csf_res = self.mcp_bridge.execute_tool("csf_workup", csf_args)
            record = ToolInvocationRecord(tool_name="csf_workup", args=csf_args, result=csf_res)
            all_tool_calls.append(record)
            self.context_mgr.append_tool_result_to_session(session, "csf_workup", csf_res)

            output_text = "[PROCEED] Emergency CSF Workup (Governed Tube Sequence Enforced):\n"
            for dept, tests in csf_res.items():
                output_text += f"\nDepartment: {dept}\n"
                for t in tests:
                    output_text += f"  - Tube {t.get('tube')}: {t.get('test')} [{t.get('uri')}]\n"

            session.add_model_message(content=output_text, tool_calls=all_tool_calls)
            return HarnessResponse(
                text=output_text.strip(),
                route="PROCEED",
                status="RESOLVED",
                session_id=session.session_id,
                tool_calls=all_tool_calls,
            )

        # Special case: Calcium collision check
        if "calcium" in term.lower() and val is not None:
            calc_args = {"value_mg_dl": val, "qualifier": qualifier}
            calc_res = self.mcp_bridge.execute_tool("check_calcium", calc_args)
            record = ToolInvocationRecord(tool_name="check_calcium", args=calc_args, result=calc_res)
            all_tool_calls.append(record)
            self.context_mgr.append_tool_result_to_session(session, "check_calcium", calc_res)

            status = calc_res.get("status", "RESOLVED")
            if status == "RANGE_COLLISION":
                clarification_msg = (
                    f"Calcium value {val} mg/dL is ambiguous without qualification: "
                    f"CRITICAL LOW for Total Calcium vs NORMAL for Ionized Calcium. "
                    f"Please specify qualifier ('total' or 'ionized')."
                )
                output_text = f"[CLARIFY] Safety Collision Intercepted: {clarification_msg}"
                session.add_model_message(content=output_text, tool_calls=all_tool_calls)
                return HarnessResponse(
                    text=output_text,
                    route="CLARIFY",
                    status="RANGE_COLLISION",
                    session_id=session.session_id,
                    tool_calls=all_tool_calls,
                    clarification=clarification_msg,
                    is_hitl_paused=True,
                )

        # Standard Clinical Laboratory Workflow:
        # Step 1: Resolve ontology via MCP
        resolve_args = {"term": term, "unit": unit, "qualifier": qualifier}
        resolve_res = self.mcp_bridge.execute_tool("resolve_lab_term", resolve_args)
        record_resolve = ToolInvocationRecord(tool_name="resolve_lab_term", args=resolve_args, result=resolve_res)
        all_tool_calls.append(record_resolve)
        self.context_mgr.append_tool_result_to_session(session, "resolve_lab_term", resolve_res)

        status = resolve_res.get("status", "UNKNOWN")
        candidates = resolve_res.get("candidates", [])

        # Step 2: Evaluate deterministic safety gate via MCP
        gate_args = {
            "term": term,
            "unit": unit,
            "qualifier": qualifier,
            "patient_value": val,
            "status": status,
        }
        gate_res = self.mcp_bridge.execute_tool("evaluate_safety_gate", gate_args)
        record_gate = ToolInvocationRecord(tool_name="evaluate_safety_gate", args=gate_args, result=gate_res)
        all_tool_calls.append(record_gate)
        self.context_mgr.append_tool_result_to_session(session, "evaluate_safety_gate", gate_res)

        route = gate_res.get("route", "CLARIFY")

        # Step 3: Branch on Safety Gate Verdict
        if route == "CLARIFY":
            clarification = gate_res.get("clarification_prompt") or (
                f"Clarification required for ambiguous laboratory order '{term}'. "
                f"Reported status: {status}. Please provide valid measurement units."
            )
            output_text = f"[CLARIFY - HITL Pause]\n{clarification}"
            session.add_model_message(content=output_text, tool_calls=all_tool_calls)
            return HarnessResponse(
                text=output_text,
                route="CLARIFY",
                status=status,
                session_id=session.session_id,
                tool_calls=all_tool_calls,
                clarification=clarification,
                is_hitl_paused=True,
            )

        # Step 4: Route == PROCEED -> Fetch Grounded Protocol & Attest
        candidate = candidates[0] if candidates else {}
        uri = candidate.get("uri", "")

        proto_args = {"uri": uri}
        proto_res = self.mcp_bridge.execute_tool("fetch_grounded_protocol", proto_args)
        record_proto = ToolInvocationRecord(tool_name="fetch_grounded_protocol", args=proto_args, result=proto_res)
        all_tool_calls.append(record_proto)
        self.context_mgr.append_tool_result_to_session(session, "fetch_grounded_protocol", proto_res)

        # Step 5: Attest computation
        attested = False
        badge = ""
        if val is not None and uri:
            attest_args = {"value": val, "uri": uri, "unit": unit}
            attest_res = self.mcp_bridge.execute_tool("attest_computation", attest_args)
            record_attest = ToolInvocationRecord(tool_name="attest_computation", args=attest_args, result=attest_res)
            all_tool_calls.append(record_attest)
            self.context_mgr.append_tool_result_to_session(session, "attest_computation", attest_res)
            if attest_res.get("passed"):
                attested = True
                badge = " [Attested ✓]"

        proto_detail = proto_res.get("protocol", proto_res)
        output_text = (
            f"[PROCEED - Grounded Interpretation]{badge}\n"
            f"Resolved Concept: {candidate.get('label')} ({uri})\n"
            f"Department: {candidate.get('department')}\n"
            f"Patient Value: {val} {unit}\n"
            f"Reference Range: {proto_detail.get('reference_range', 'N/A')}\n"
            f"Panic Limits: {proto_detail.get('panic_limits', 'N/A')}\n"
            f"Clinical Guidance: Verified against canonical ontology and governed protocols."
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
        Loops while Gemini requests tool calls, dispatches to FastMCP, and appends to history.
        """
        all_tool_calls: List[ToolInvocationRecord] = []
        turn = 0
        last_route = "PROCEED"
        last_status = "RESOLVED"
        clarification_msg = None
        protocol_data: Dict[str, Any] = {}
        attested = False

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
                # If live generation fails, fall back to deterministic pipeline
                return self._run_deterministic_pipeline(prompt, session)

            # Check if Gemini issued tool calls
            candidate = response.candidates[0] if response.candidates else None
            if not candidate or not candidate.content or not candidate.content.parts:
                break

            function_calls = [p.function_call for p in candidate.content.parts if hasattr(p, "function_call") and p.function_call]

            if function_calls:
                # Model requested tool calls: intercept and execute via MCP (Step 2)
                executed_records = []
                for fc in function_calls:
                    tool_name = fc.name
                    tool_args = dict(fc.args) if fc.args else {}
                    tool_result = self.mcp_bridge.execute_tool(tool_name, tool_args)

                    rec = ToolInvocationRecord(tool_name=tool_name, args=tool_args, result=tool_result)
                    executed_records.append(rec)
                    all_tool_calls.append(rec)

                    # Step 3: Append tool output to conversation history
                    self.context_mgr.append_tool_result_to_session(session, tool_name, tool_result)

                    # Intercept safety gate verdicts immediately
                    if tool_name == "evaluate_safety_gate":
                        last_route = tool_result.get("route", "CLARIFY")
                        last_status = tool_result.get("status", "UNKNOWN")
                        if last_route == "CLARIFY":
                            clarification_msg = tool_result.get("clarification_prompt")

                    elif tool_name == "resolve_lab_term":
                        res_status = tool_result.get("status")
                        if res_status in ("AMBIGUOUS", "UNIT_MISMATCH", "NOT_FOUND"):
                            last_status = res_status

                    elif tool_name == "check_calcium":
                        if tool_result.get("status") == "RANGE_COLLISION":
                            last_route = "CLARIFY"
                            last_status = "RANGE_COLLISION"
                            clarification_msg = (
                                "Ambiguous calcium qualification: CRITICAL LOW for Total vs NORMAL for Ionized. "
                                "Please specify qualifier."
                            )

                    elif tool_name == "fetch_grounded_protocol":
                        protocol_data = tool_result

                    elif tool_name == "attest_computation":
                        if tool_result.get("passed"):
                            attested = True

                # Record model's function calls in history
                session.add_model_message(content="", tool_calls=executed_records)

                # If hard safety gate collision occurred, stop and pause for HITL
                if last_route == "CLARIFY":
                    clarify_text = f"[CLARIFY - HITL Pause]\n{clarification_msg or 'Ambiguity detected. Clarification required.'}"
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
                    badge = " [Attested \u2713]" if attested else ""
                    if last_route == "PROCEED" and proto:
                        final_text = (
                            f"[PROCEED{badge}]\n"
                            f"Status: {last_status}\n"
                            + (f"Resolved URI: {proto.get('uri', proto.get('loinc_uri', ''))}\n" if proto.get('uri') or proto.get('loinc_uri') else "")
                            + (f"Reference Range: {proto.get('reference_range', 'N/A')}\n" if proto.get('reference_range') else "")
                            + (f"Panic Limits: {proto.get('panic_limits', 'N/A')}" if proto.get('panic_limits') else "")
                        ).strip()
                    elif last_route == "PROCEED":
                        # If csf_workup was called, summarize tube sequence
                        csf_calls = [tc for tc in all_tool_calls if tc.tool_name == "csf_workup"]
                        resolve_calls = [tc for tc in all_tool_calls if tc.tool_name == "resolve_lab_term" and isinstance((tc.result or {}), dict)]
                        if csf_calls and isinstance(csf_calls[-1].result, dict):
                            csf_res = csf_calls[-1].result
                            dept_tubes = []
                            for dept, tests in csf_res.items():
                                if isinstance(tests, list):
                                    tube_names = {f"Tube {t.get('tube', '')}" for t in tests if isinstance(t, dict)}
                                    test_names = [str(t.get("test", "")) for t in tests if isinstance(t, dict)]
                                    dept_tubes.append(f"{dept} ({', '.join(sorted(tube_names))}): {', '.join(test_names[:2])}")
                            if dept_tubes:
                                final_text = f"[PROCEED] {last_status} | " + " | ".join(dept_tubes)
                            else:
                                final_text = f"[PROCEED] {last_status}"
                        elif resolve_calls:
                            # Enrich from last resolved lab term candidate
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
            badge = " [Attested \u2713]" if attested else ""
            final_msg = (
                f"[PROCEED{badge}] {last_status}\n"
                + (f"Reference Range: {proto.get('reference_range', 'N/A')}" if proto.get('reference_range') else "")
            ).strip()
        elif not final_msg.strip():
            # Try to enrich from resolve_lab_term results
            resolve_calls = [tc for tc in all_tool_calls if tc.tool_name == "resolve_lab_term" and isinstance((tc.result or {}), dict)]
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
    model_name: str = "gemini-2.5-flash",
    offline: Optional[bool] = None,
    **kwargs: Any,
) -> ClinicalADKHarness:
    """Factory function to instantiate ClinicalADKHarness."""
    return ClinicalADKHarness(model_name=model_name, offline=offline, **kwargs)
