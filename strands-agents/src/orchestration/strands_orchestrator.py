"""
Multi-Agent Orchestration Layer for Laboratory Medicine Decision Support.
Implements the Supervisor Orchestrator using Strands Agents SDK and Amazon Bedrock AgentCore.
"""
import logging
import re
from typing import Any, Dict, Optional

from src.models.provider import get_strands_model
from src.memory.session import get_agentcore_session_manager
from src.tools.parse_tool import parse_clinician_input
from src.tools.ontology_tool import resolve_lab_term
from src.tools.safety_gate_tool import evaluate_safety_gate
from src.tools.protocol_tool import fetch_grounded_protocol
from src.tools.clarification_tool import build_clarification_prompt
from src.agents.triage_agent import create_triage_orchestrator
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole


class ParsedEvent(dict):
    """Parsed fields as a dict that also exposes ``.output`` (ADK-style event access)."""

    @property
    def output(self) -> "ParsedEvent":
        return self


def parse_clinician_input_direct(raw_text: str) -> ParsedEvent:
    """Direct input parser — delegates to the shared ontology-aware parser.

    Pipe segments are classified by vocabulary (unit, facet qualifier,
    population, department), e.g. ``Calcium 4.8 | total | mg/dL``.
    """
    from ontogate.parsing import parse_clinician_text

    parsed = parse_clinician_text(raw_text)
    a2a_msg = A2AMessage(
        sender=AgentRole.TRIAGE,
        recipient=AgentRole.ONTOLOGY_RESOLVER,
        action=A2AAction.PARSE_REQUEST,
        payload={k: parsed[k] for k in ("raw_text", "term", "unit", "qualifier", "patient_value")},
    )
    return ParsedEvent({**parsed, "a2a_triage_message": a2a_msg.model_dump(mode="json")})


# Public name used by the A2A intake step
parse_clinician_input = parse_clinician_input_direct


class StrandsDecisionSupportOrchestrator:
    """Coordinates multi-agent retrieval and deterministic safety gating with Bedrock AgentCore."""

    def __init__(
        self,
        session_id: str = "clinical-session-default",
        offline: Optional[bool] = None,
        memory_id: Optional[str] = None,
    ):
        self.session_id = session_id
        self.offline = offline
        self.model = get_strands_model(offline=offline)
        self.session_manager = get_agentcore_session_manager(
            session_id=session_id, memory_id=memory_id, offline=offline
        )
        self.supervisor = create_triage_orchestrator(model=self.model)

    def process_query_direct(self, raw_text: str) -> Dict[str, Any]:
        """Execute deterministic pipeline for fast evaluation and unit testing."""
        # Step 1: Parse
        parsed = parse_clinician_input_direct(raw_text)

        # Step 2: Resolve Ontology
        resolved = resolve_lab_term(
            term=parsed["term"],
            unit=parsed["unit"],
            qualifier=parsed["qualifier"],
            patient_value=parsed["patient_value"],
        )

        # Step 3: Mandatory Deterministic Safety Gate (Gap 9)
        population = parsed.get("population") or {}
        gate = evaluate_safety_gate(
            term=resolved["term"],
            unit=resolved["unit"],
            qualifier=resolved["qualifier"],
            patient_value=resolved["patient_value"],
            status=resolved["status"],
            sex=population.get("sex", ""),
            age_band=population.get("age_band", ""),
            department=parsed.get("department", ""),
            panel_id=parsed.get("panel_id") or "",
        )

        # Step 4: Routing Check
        if gate["route"] == "CLARIFY":
            clarification = {"clarification_prompt": gate.get("clarification_prompt")}                 if gate.get("clarification_prompt") else build_clarification_prompt(
                    status=gate["status"],
                    candidates=gate.get("candidates") or resolved["candidates"],
                    term=parsed["term"],
                    collision_details=gate.get("details"),
                )
            result = {
                "route": "CLARIFY",
                "status": gate["status"],
                "clarification": clarification["clarification_prompt"],
                "parsed": parsed,
                "resolved": resolved,
                "gate": gate,
            }
            if hasattr(self.session_manager, "add_turn"):
                self.session_manager.add_turn(
                    role="system", content=clarification["clarification_prompt"], metadata=result
                )
            return result

        # Step 5: Fetch Clinical Protocol
        concept = resolved["candidates"][0] if resolved.get("candidates") else {}
        protocol = fetch_grounded_protocol(
            uri=concept.get("uri", ""),
            concept=concept,
            patient_value=parsed["patient_value"],
        )

        result = {
            "route": "PROCEED",
            "status": "RESOLVED",
            "concept": concept,
            "protocol": protocol,
            "parsed": parsed,
            "gate": gate,
        }
        if hasattr(self.session_manager, "add_turn"):
            self.session_manager.add_turn(
                role="system",
                content=f"Resolved LOINC: {concept.get('uri')}",
                metadata={"resolved_uri": concept.get("uri")},
            )
        return result

    def process_query_agentic(self, raw_text: str) -> str:
        """Run the full Strands Supervisor Agent in an AgentCore session context.

        Falls back to the deterministic offline pipeline with a clear warning when
        the upstream LLM is unavailable (no credits, bad auth, rate-limit, network).
        """
        if hasattr(self.session_manager, "add_turn"):
            self.session_manager.add_turn(role="user", content=raw_text)

        try:
            with self.session_manager:
                output = self.supervisor(raw_text)
            output_str = str(output)
        except Exception as exc:
            # Classify the error so the caller sees a useful message.
            exc_type = type(exc).__name__
            exc_str = str(exc)

            # Anthropic-specific signals (credit exhaustion, bad key, rate-limit).
            _ANTHROPIC_SIGNALS = (
                "credit balance is too low",
                "invalid_api_key",
                "authentication_error",
                "rate_limit_error",
                "overloaded",
            )
            is_api_err = any(sig in exc_str.lower() for sig in _ANTHROPIC_SIGNALS)

            if is_api_err:
                reason = "Anthropic API unavailable (credit/auth/rate-limit)"
            else:
                reason = f"{exc_type}: {exc_str[:120]}"

            logging.warning(
                "[Strands] Live agentic call failed — falling back to offline pipeline. Reason: %s",
                reason,
            )

            # Fall back to the deterministic pipeline.
            det = self.process_query_direct(raw_text)
            route = det.get("route", "CLARIFY")
            status = det.get("status", "UNKNOWN")
            fallback_note = (
                f"[OFFLINE-FALLBACK] Live synthesis unavailable ({reason}).\n"
                f"  Deterministic result — Route: {route} | Status: {status}"
            )
            if route == "PROCEED":
                concept = det.get("concept", {})
                protocol = det.get("protocol", {}).get("protocol", {})
                fallback_note += (
                    f"\n  Concept: {concept.get('label')} [{concept.get('uri')}]"
                    f"\n  Ref range: {protocol.get('reference_range')}"
                    f"\n  Panic limits: {protocol.get('panic_limits')}"
                )
            else:
                fallback_note += f"\n  Clarification: {det.get('clarification', '')}"

            output_str = fallback_note

        if hasattr(self.session_manager, "add_turn"):
            self.session_manager.add_turn(role="assistant", content=output_str)

        return output_str


def build_strands_orchestrator(
    offline: Optional[bool] = None, session_id: str = "default-session"
) -> StrandsDecisionSupportOrchestrator:
    """Build and return a StrandsDecisionSupportOrchestrator instance."""
    return StrandsDecisionSupportOrchestrator(session_id=session_id, offline=offline)
