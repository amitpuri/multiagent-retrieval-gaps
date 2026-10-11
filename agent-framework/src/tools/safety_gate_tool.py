"""
Deterministic safety gate tool — plain Python function for MAF binding (Gap 9).
Pure code — never calls a model. ``@tool`` wrapper over the canonical
``ontogate.tools.evaluate_safety_gate``.
"""
from typing import Any, Dict, Optional
from ontogate.tools import evaluate_safety_gate as _evaluate_safety_gate


def evaluate_safety_gate(
    term: str,
    unit: str = "",
    qualifier: str = "",
    patient_value: Optional[float] = None,
    status: str = "UNKNOWN",
    sex: str = "",
    age_band: str = "",
    department: str = "",
    panel_id: str = "",
) -> Dict[str, Any]:
    """Run the deterministic safety gate — fail-closed on anything other than RESOLVED.

    Args:
        term: Lab term.
        unit: Reported unit.
        qualifier: Qualifier ('total', 'ionized', etc.).
        patient_value: Numeric patient result.
        status: Incoming resolution status from the ontology resolver.
        sex: Optional population context (male / female).
        age_band: Optional population context (adult / pediatric / neonate).
        department: Optional department scope for panel requests.
        panel_id: Panel identifier for specimen-sequencing requests.

    Returns:
        dict with route ('PROCEED'|'CLARIFY'), status, clarification and details.
    """
    return _evaluate_safety_gate(term=term, unit=unit, qualifier=qualifier, patient_value=patient_value,
                                 status=status, sex=sex, age_band=age_band, department=department,
                                 panel_id=panel_id)


def gate_arguments(parsed: Dict[str, Any], resolved: Dict[str, Any]) -> Dict[str, Any]:
    """Arguments for ``evaluate_safety_gate`` from the parse and resolve results.

    The gate needs the parsed context too — population (sex, age band),
    department scope and panel — not only the resolved term; dropping it sends
    panel requests to term resolution and hides population-dependent intervals.
    """
    population = parsed.get("population") or {}
    return {
        "term": resolved.get("term", parsed.get("term", "")),
        "unit": resolved.get("unit", parsed.get("unit", "")),
        "qualifier": resolved.get("qualifier", parsed.get("qualifier", "")),
        "patient_value": resolved.get("patient_value", parsed.get("patient_value")),
        "status": resolved.get("status", "UNKNOWN"),
        "sex": population.get("sex", ""),
        "age_band": population.get("age_band", ""),
        "department": parsed.get("department") or "",
        "panel_id": parsed.get("panel_id") or "",
    }
