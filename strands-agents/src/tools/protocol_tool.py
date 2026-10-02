"""
Clinical Protocol Retrieval Tool using Strands Agents SDK.
Fetches reference ranges and panic limits for canonical LOINC identifiers.
"""
from typing import Any, Dict, Optional
from strands import tool
from src.core.config import get_default_registry
from src.core.models import ResolutionStatus
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole


@tool
def fetch_protocol(
    resolved_uri: str,
    concept: Dict[str, Any],
    patient_value: Optional[float] = None,
) -> Dict[str, Any]:
    """Fetch clinical reference protocol for a resolved canonical LOINC URI.

    Args:
        resolved_uri: Canonical LOINC URI (e.g. 'loinc:718-7').
        concept: Resolved concept dict with label, department, units.
        patient_value: Numeric patient result.

    Returns:
        dict with reference_range, panic_limits, clinical_guideline.
    """
    reg = get_default_registry()
    proto = reg.get_protocol(resolved_uri)
    if not proto:
        return {"status": "NOT_FOUND", "resolved_uri": resolved_uri}

    a2a_msg = A2AMessage(
        sender=AgentRole.PROTOCOL_RETRIEVER,
        recipient=AgentRole.CLINICAL_SYNTHESIZER,
        action=A2AAction.SYNTHESIZE_INTERPRETATION,
        payload={"resolved_uri": resolved_uri, "concept": concept},
        status=ResolutionStatus.RESOLVED,
    )

    return {
        "resolved_uri": resolved_uri,
        "concept": concept,
        "protocol": {
            "reference_range": proto.reference_range,
            "panic_limits": proto.panic_limits,
            "clinical_guideline": proto.clinical_guideline,
        },
        "patient_value": patient_value,
        "a2a_protocol_message": a2a_msg.model_dump(mode="json"),
    }
