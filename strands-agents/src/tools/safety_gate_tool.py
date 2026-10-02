"""
Deterministic Safety Gate Tool using Strands Agents SDK.
CRITICAL: Pure-code deterministic execution. NEVER calls an LLM.
Enforces fail-closed clinical safety (Gap 9).
"""
from typing import Any, Dict, Optional
from strands import tool
from src.core.detectors.engine import SafetyGateEngine
from src.core.models import EvaluationContext, ResolutionStatus


@tool
def run_safety_gate(
    term: str,
    unit: str = "",
    qualifier: str = "",
    patient_value: Optional[float] = None,
    status: str = "UNKNOWN",
) -> Dict[str, Any]:
    """Run the deterministic safety gate — fail-closed on anything other than RESOLVED.

    Evaluates RangeCollisionDetector, AmbiguityDetector, and SpecimenSequenceDetector
    in pure code. No LLM. Routes to PROCEED or CLARIFY.

    Args:
        term: Lab term.
        unit: Reported unit.
        qualifier: Qualifier ('total', 'ionized', etc.).
        patient_value: Numeric patient result.
        status: Incoming resolution status from ontology resolver.

    Returns:
        dict with route ('PROCEED'|'CLARIFY'), status, and evaluation details.
    """
    engine = SafetyGateEngine()
    ctx = EvaluationContext(
        term=term,
        unit=unit,
        qualifier=qualifier,
        patient_value=patient_value,
    )
    result = engine.evaluate(ctx)

    eval_status = result.status.value

    # Preserve explicit upstream mismatch or not found if downstream didn't detect collision
    if status in (ResolutionStatus.UNIT_MISMATCH.value, "UNIT_MISMATCH") and result.status in (
        ResolutionStatus.RESOLVED,
        ResolutionStatus.AMBIGUOUS,
    ):
        eval_status = ResolutionStatus.UNIT_MISMATCH.value

    route = engine.route_for(
        ResolutionStatus(eval_status)
        if eval_status in ResolutionStatus._value2member_map_
        else result.status
    )

    return {
        "route": route,
        "status": eval_status,
        "passed": result.passed and (route == "PROCEED"),
        "details": result.details,
        "candidates": result.candidates,
    }
