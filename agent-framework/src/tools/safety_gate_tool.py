"""
Deterministic Safety Gate — plain Python function for MAF binding.
CRITICAL: Pure-code deterministic execution. NEVER calls an LLM.
Enforces fail-closed clinical safety (Gap 9).
No framework decorator — bound to agents via YAML 'bindings: {function: run_safety_gate}'.
"""
from typing import Any, Dict, Optional
from src.core.detectors.engine import SafetyGateEngine
from src.core.models import EvaluationContext, ResolutionStatus


def run_safety_gate(
    term: str,
    unit: str = "",
    qualifier: str = "",
    patient_value: Optional[float] = None,
    status: str = "UNKNOWN",
) -> Dict[str, Any]:
    """Run the deterministic safety gate — fail-closed on anything other than RESOLVED.

    Evaluates RangeCollisionDetector, AmbiguityDetector, and SpecimenSequenceDetector
    in pure Python code. No LLM. Routes to PROCEED or CLARIFY.

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

    # Preserve explicit upstream unit mismatch if downstream didn't detect collision
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
