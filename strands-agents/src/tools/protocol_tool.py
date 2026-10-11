"""
Grounded protocol retrieval tool for Strands Agents.
``@tool`` wrapper over the canonical ``ontogate.tools.fetch_grounded_protocol``:
data bound strictly to one observable URI, with the Strands A2A envelope.
"""
from typing import Any, Dict, Optional
from strands import tool
from ontogate.models import ResolutionStatus
from ontogate.tools import fetch_grounded_protocol as _fetch_grounded_protocol
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole


@tool
def fetch_grounded_protocol(
    uri: str,
    concept: Optional[Dict[str, Any]] = None,
    patient_value: Optional[float] = None,
) -> Dict[str, Any]:
    """Fetch the clinical protocol bound to one canonical LOINC URI.

    Args:
        uri: Canonical LOINC URI (e.g. 'loinc:718-7').
        concept: Resolved concept dict (label, department, units), carried forward.
        patient_value: Numeric patient result, carried forward.

    Returns:
        dict with status, protocol (reference_range, panic_limits, clinical_guideline,
        trust_tier, is_stale) and the A2A envelope.
    """
    proto = _fetch_grounded_protocol(uri)
    if proto.get("status") != "RESOLVED":
        return {"status": "NOT_FOUND", "uri": uri}
    concept = concept or {}
    a2a_msg = A2AMessage(
        sender=AgentRole.PROTOCOL_RETRIEVER,
        recipient=AgentRole.CLINICAL_SYNTHESIZER,
        action=A2AAction.SYNTHESIZE_INTERPRETATION,
        payload={"uri": uri, "concept": concept},
        status=ResolutionStatus.RESOLVED,
    )
    return {
        "status": "RESOLVED",
        "uri": uri,
        "concept": concept,
        "protocol": {k: proto[k] for k in ("reference_range", "panic_limits", "clinical_guideline",
                                           "trust_tier", "is_stale")},
        "patient_value": patient_value,
        "a2a_protocol_message": a2a_msg.model_dump(mode="json"),
    }
