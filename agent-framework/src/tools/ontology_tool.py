"""
Canonical Ontology Resolver — plain Python function for MAF binding.
Maps clinician terminology and units to canonical LOINC identifiers with A2A envelope.
No framework decorator — bound to agents via YAML 'bindings: {function: resolve_ontology}'.
"""
from typing import Any, Dict, Optional
from src.core.config import get_default_registry
from src.core.models import ResolutionStatus
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole


def resolve_ontology(
    term: str,
    unit: str = "",
    qualifier: str = "",
    patient_value: Optional[float] = None,
) -> Dict[str, Any]:
    """Resolve a lab test name and optional unit to canonical LOINC concepts.

    Args:
        term: Lab test name (e.g. 'Hb', 'Calcium').
        unit: Reported unit string (e.g. 'g/dL', 'mg/dL').
        qualifier: Qualifier string (e.g. 'total', 'ionized').
        patient_value: Numeric patient result.

    Returns:
        dict with status, candidates, and A2A envelope.
    """
    reg = get_default_registry()
    candidates = reg.find_concepts(term.strip())

    status = ""
    if not candidates:
        status = ResolutionStatus.NOT_FOUND.value
        payload: Dict[str, Any] = {"status": status, "candidates": []}
    elif unit:
        matched = [c for c in candidates if c.supports_unit(unit.strip())]
        if not matched:
            status = ResolutionStatus.UNIT_MISMATCH.value
            payload = {
                "status": status,
                "reported_unit": unit,
                "candidates": [c.to_view() for c in candidates],
            }
        else:
            candidates = matched

    if not status:
        if qualifier and candidates:
            q = qualifier.strip().lower()
            matched_q = [
                c
                for c in candidates
                if q in c.label.lower()
                or any(q in alt.lower() for alt in c.alt_labels)
                or q in c.uri.lower()
            ]
            if matched_q:
                candidates = matched_q

        status = (
            ResolutionStatus.RESOLVED.value
            if len(candidates) == 1
            else ResolutionStatus.AMBIGUOUS.value
        )
        payload = {"status": status, "candidates": [c.to_view() for c in candidates]}

    a2a_msg = A2AMessage(
        sender=AgentRole.ONTOLOGY_RESOLVER,
        recipient=AgentRole.SAFETY_GUARD,
        action=A2AAction.RESOLVE_CONCEPT,
        payload=payload,
        status=ResolutionStatus(status),
    )

    return {
        "term": term,
        "unit": unit,
        "qualifier": qualifier,
        "patient_value": patient_value,
        "status": status,
        "candidates": payload.get("candidates", []),
        "a2a_message": a2a_msg.model_dump(mode="json"),
    }
