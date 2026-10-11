"""
Clarification Builder Tool using Strands Agents SDK.
Deterministic HITL clarification text generated from the ontology
(``ontogate.clarify``) when the safety gate blocks progression.
"""
from typing import Any, Dict, List, Optional
from strands import tool
from ontogate.tools import build_clarification_prompt as _build


@tool
def build_clarification_prompt(
    status: str,
    candidates: List[Dict[str, Any]],
    term: str = "",
    collision_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a structured clarification prompt for the clinician when the safety gate fails.

    Args:
        status: Resolution status that triggered clarification.
        candidates: List of candidate concept dicts.
        term: Original lab term queried.
        collision_details: Gate details (readings, missing facets) if applicable.

    Returns:
        dict with clarification_prompt string, status and the missing facets.
    """
    return _build(status=status, candidates=candidates, details=collision_details or {}, term=term)
