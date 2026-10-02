"""
Clarification Builder Tool using Strands Agents SDK.
Builds structured HITL clarification queries when the deterministic safety gate blocks progression.
"""
from typing import Any, Dict, List, Optional
from strands import tool


@tool
def build_clarification_prompt(
    status: str,
    candidates: List[Dict[str, Any]],
    term: str = "",
    collision_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a structured clarification prompt for the clinician when safety gate fails.

    Args:
        status: Resolution status that triggered clarification.
        candidates: List of candidate concept dicts.
        term: Original lab term queried.
        collision_details: Range collision details if applicable.

    Returns:
        dict with clarification_prompt string and status.
    """
    labels = ", ".join(c.get("label", "") for c in candidates if isinstance(c, dict)) or "none"
    prompt = f"Ambiguity detected (Status: {status}). Candidates: {labels}. Please specify the intended test and unit."

    if collision_details and "readings" in collision_details:
        readings = collision_details["readings"]
        collision_str = "; ".join(f"{k}: {v}" for k, v in readings.items())
        prompt = (
            f"Range collision detected (Status: {status}). Conflicting interpretations: {collision_str}. "
            f"Please clarify the specific assay/qualifier (e.g., total vs. ionized calcium)."
        )

    return {
        "clarification_prompt": prompt,
        "status": status,
        "requires_clarification": True,
    }
