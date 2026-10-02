"""
Multi-Agent Orchestration Layer for Laboratory Medicine Decision Support.
Implements the Supervisor Orchestrator using Strands Agents SDK and Amazon Bedrock AgentCore.
"""
import re
from typing import Any, Dict, Optional

from src.models.provider import get_strands_model
from src.memory.session import get_agentcore_session_manager
from src.tools.parse_tool import parse_clinician_input
from src.tools.ontology_tool import resolve_ontology
from src.tools.safety_gate_tool import run_safety_gate
from src.tools.protocol_tool import fetch_protocol
from src.tools.clarification_tool import build_clarification_prompt
from src.agents.triage_agent import create_triage_orchestrator
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole


class ParsedEvent(dict):
    """Dictionary supporting .output attribute for backwards compatibility."""

    @property
    def output(self) -> "ParsedEvent":
        return self


def parse_clinician_input_direct(raw_text: str) -> ParsedEvent:
    """Direct, pure-Python input parser for unit tests and deterministic scenarios."""
    left, _, right = raw_text.partition("|")
    left_str, right_str = left.strip(), right.strip()

    qualifier, unit = "", ""
    if right_str.lower() in ("total", "tca", "ionized", "ica", "free", "i", "t"):
        qualifier = right_str.lower()
    else:
        unit = right_str

    val_match = re.search(r"\b(\d+(?:\.\d+)?)\b", left_str)
    patient_value = float(val_match.group(1)) if val_match else None
    term = re.sub(r"\b\d+(?:\.\d+)?\b", "", left_str).strip() or left_str

    a2a_msg = A2AMessage(
        sender=AgentRole.TRIAGE,
        recipient=AgentRole.ONTOLOGY_RESOLVER,
        action=A2AAction.PARSE_REQUEST,
        payload={
            "raw_text": raw_text,
            "term": term,
            "unit": unit,
            "qualifier": qualifier,
            "patient_value": patient_value,
        },
    )

    return ParsedEvent(
        {
            "term": term,
            "unit": unit,
            "qualifier": qualifier,
            "patient_value": patient_value,
            "raw_text": raw_text,
            "a2a_triage_message": a2a_msg.model_dump(mode="json"),
        }
    )


# Alias parse_clinician_input for backward-compatible test imports
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
        resolved = resolve_ontology(
            term=parsed["term"],
            unit=parsed["unit"],
            qualifier=parsed["qualifier"],
            patient_value=parsed["patient_value"],
        )

        # Step 3: Mandatory Deterministic Safety Gate (Gap 9)
        gate = run_safety_gate(
            term=resolved["term"],
            unit=resolved["unit"],
            qualifier=resolved["qualifier"],
            patient_value=resolved["patient_value"],
            status=resolved["status"],
        )

        # Step 4: Routing Check
        if gate["route"] == "CLARIFY":
            clarification = build_clarification_prompt(
                status=gate["status"],
                candidates=resolved["candidates"],
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
        protocol = fetch_protocol(
            resolved_uri=concept.get("uri", ""),
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
        """Run the full Strands Supervisor Agent in an AgentCore session context."""
        if hasattr(self.session_manager, "add_turn"):
            self.session_manager.add_turn(role="user", content=raw_text)

        with self.session_manager:
            output = self.supervisor(raw_text)

        output_str = str(output)
        if hasattr(self.session_manager, "add_turn"):
            self.session_manager.add_turn(role="assistant", content=output_str)

        return output_str


def build_strands_orchestrator(
    offline: Optional[bool] = None, session_id: str = "default-session"
) -> StrandsDecisionSupportOrchestrator:
    """Build and return a StrandsDecisionSupportOrchestrator instance."""
    return StrandsDecisionSupportOrchestrator(session_id=session_id, offline=offline)
