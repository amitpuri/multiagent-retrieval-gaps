"""
Ontology resolver tool for Strands Agents.
``@tool`` wrapper over the canonical ``ontogate.tools.resolve_lab_term`` with the
Strands A2A envelope.
"""
from typing import Any, Dict, Optional
from strands import tool
from ontogate.models import ResolutionStatus
from ontogate.tools import resolve_lab_term as _resolve_lab_term
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole


@tool
def resolve_lab_term(
    term: str,
    unit: str = "",
    qualifier: str = "",
    patient_value: Optional[float] = None,
) -> Dict[str, Any]:
    """Resolve a lab test name, optional unit and qualifier to canonical LOINC observables.

    Args:
        term: Lab test name (e.g. 'Hb', 'Calcium').
        unit: Reported unit string (e.g. 'g/dL', 'mg/dL').
        qualifier: Qualifier string (e.g. 'total', 'ionized').
        patient_value: Numeric patient result (carried forward to the gate).

    Returns:
        dict with status, candidates, and A2A envelope.
    """
    payload = _resolve_lab_term(term=term, unit=unit, qualifier=qualifier)
    status = payload["status"]
    a2a_msg = A2AMessage(
        sender=AgentRole.ONTOLOGY_RESOLVER,
        recipient=AgentRole.SAFETY_GUARD,
        action=A2AAction.RESOLVE_CONCEPT,
        payload=payload,
        status=ResolutionStatus(status),
    )
    result = {
        "term": term,
        "unit": unit,
        "qualifier": qualifier,
        "patient_value": patient_value,
        "status": status,
        "candidates": payload.get("candidates", []),
        "a2a_message": a2a_msg.model_dump(mode="json"),
    }
    if "contradiction" in payload:
        result["contradiction"] = payload["contradiction"]
    return result
