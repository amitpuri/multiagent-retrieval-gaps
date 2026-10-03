"""
Scenario B: CSF Emergency Panel Workup tool.
Implements governed tube sequencing and department-scoped retrieval (closing Gap 11).
Uses the declarative OntologyRegistry panel definition.
"""
from typing import Any, Dict, List
from src.core.config import get_default_registry


def csf_workup(department: str = "") -> Dict[str, Any]:
    """Return CSF tests grouped by owning department, with tube assignments.

    Pre-scopes results by department ownership and governed tube sequence:
      Tube 1: Clinical Biochemistry (Protein, Glucose)
      Tube 2: Microbiology (Gram stain, Culture)
      Tube 3: Hematology (Leukocytes, Neutrophils)

    Args:
        department: Optional filter substring (e.g. 'hemat', 'biochem').

    Returns:
        Dict mapping department to list of test objects with uri, test, tube.
    """
    reg = get_default_registry()
    panel = reg.get_panel("csf_emergency_panel")
    if not panel:
        return {"status": "NOT_FOUND"}

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for rule in panel.tube_rules:
        if department and department.lower() not in rule.department.lower():
            continue
        for test in rule.tests:
            grouped.setdefault(rule.department, []).append(
                {"uri": test["uri"], "test": test["test_name"], "tube": rule.tube}
            )
    return grouped or {"status": "NOT_FOUND"}
