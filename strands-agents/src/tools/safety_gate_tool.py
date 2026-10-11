"""
Deterministic safety gate tool for Strands Agents (Gap 9).
Pure code — never calls a model. ``@tool`` wrapper over the canonical
``ontogate.tools.evaluate_safety_gate``.
"""
from typing import Any, Dict, Optional
from strands import tool
from ontogate.tools import evaluate_safety_gate as _evaluate_safety_gate


@tool
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
