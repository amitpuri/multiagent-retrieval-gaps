"""
Specimen panel workup tool for Strands Agents (Gap 11).
``@tool`` wrapper over the canonical ``ontogate.tools.panel_workup``: collection
steps in the ontology's governed order, scoped by a Department entity.
"""
from typing import Any, Dict
from strands import tool
from ontogate.tools import panel_workup as _panel_workup


@tool
def panel_workup(panel: str = "csf_emergency_panel", department: str = "") -> Dict[str, Any]:
    """Return a panel's collection steps in governed tube order, optionally scoped to one department.

    Args:
        panel: Panel id, name or designation (e.g. 'CSF Emergency Panel').
        department: Optional department (id, label or declared synonym, e.g. 'hemat').

    Returns:
        dict with status, panel, specimen and ordered tubes [{tube, department, tests}].
    """
    return _panel_workup(panel=panel, department=department)
