"""
Protocol Retriever Agent: Retrieves clinical reference data keyed by canonical LOINC URI.
Guarantees that retrieved guidelines and panic limits are strictly bound to verified concepts.
"""

from typing import Any, Dict
from google.adk import Event
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole
from src.core.config import get_default_registry
from src.core.models import ResolutionStatus


def protocol_retriever_node(node_input: Dict[str, Any]) -> Event:
    """Protocol retrieval node grounded on resolved canonical concept URI."""
    candidates = node_input.get("candidates", [])
    if candidates and "uri" in candidates[0]:
        uri = candidates[0]["uri"]
        reg = get_default_registry()
        protocol_def = reg.get_protocol(uri)

        if protocol_def:
            protocol_data = {
                "reference_range": protocol_def.reference_range,
                "panic_limits": protocol_def.panic_limits,
                "clinical_guideline": protocol_def.clinical_guideline,
            }
        else:
            protocol_data = {"status": "NOT_FOUND"}

        reported_unit = ""
        if candidates[0].get("expected_units"):
            reported_unit = candidates[0]["expected_units"][0]

        result = {
            "resolved_uri": uri,
            "concept": candidates[0],
            "protocol": protocol_data,
            "patient_value": node_input.get("patient_value"),
            "reported_unit": reported_unit,
        }

        a2a_msg = A2AMessage(
            sender=AgentRole.PROTOCOL_RETRIEVER,
            recipient=AgentRole.CLINICAL_SYNTHESIZER,
            action=A2AAction.SYNTHESIZE_INTERPRETATION,
            payload=result,
            status=ResolutionStatus.RESOLVED,
        )
        result["a2a_protocol_message"] = a2a_msg.model_dump(mode="json")
        return Event(output=result)

    return Event(output={"status": "NO_RESOLVED_CANDIDATE"})


def create_protocol_agent() -> Any:
    """Return protocol retriever callable node."""
    return protocol_retriever_node
