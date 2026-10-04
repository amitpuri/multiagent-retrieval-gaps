"""
Gap 6 Detector: Missing Unit on Numeric Value.

Whenever a patient_value is present (i.e. a numeric result was supplied),
a unit MUST also be present.  Without a unit the downstream range-collision
detector cannot know which measurement scale is being used, so any value
could be silently judged against the wrong clinical ranges (e.g. a normal
mmol/L calcium value classified as CRITICAL_LOW against mg/dL thresholds).

This detector is intentionally placed *before* RangeCollisionDetector in the
default engine suite so the gate rejects unitless numeric inputs early,
before any scale-sensitive comparison is attempted.
"""
from __future__ import annotations

from src.core.detectors.base import GapDetector
from src.core.models import (
    EvaluationContext,
    GapEvaluationResult,
    ResolutionStatus,
)


class MissingUnitDetector(GapDetector):
    """Rejects numeric patient values that arrive without a unit."""

    @property
    def gap_name(self) -> str:
        return "Gap 6: Missing Unit on Numeric Value"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        """Fail when patient_value is set but unit is absent or whitespace-only."""
        if context.patient_value is None:
            # No numeric value — nothing to check here.
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message="No numeric patient value present; unit check skipped",
            )

        if context.unit.strip():
            # Unit is present — pass through.
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message=f"Unit '{context.unit.strip()}' present for numeric value",
            )

        # Numeric value with no unit — ambiguous and potentially dangerous.
        return GapEvaluationResult(
            passed=False,
            status=ResolutionStatus.UNIT_MISMATCH,
            gap_name=self.gap_name,
            message=(
                f"Numeric patient value {context.patient_value} was provided without a unit. "
                "A unit is required to determine the correct measurement scale before "
                "range classification.  Provide the unit (e.g. 'mg/dL', 'mmol/L', 'g/dL')."
            ),
            details={"patient_value": context.patient_value},
        )
