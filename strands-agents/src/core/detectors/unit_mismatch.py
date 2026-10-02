"""
Gap 2 Detector: Unit Mismatch.
Detects when a reported unit does not match any valid unit for the matched concept(s).
This is a standalone detector that explicitly catches unit-level errors independent
of multi-concept ambiguity resolution.
"""

from src.core.detectors.base import GapDetector
from src.core.models import (
    EvaluationContext,
    GapEvaluationResult,
    ResolutionStatus,
)


class UnitMismatchDetector(GapDetector):
    """Detects unit constraint violations against registered concept definitions."""

    @property
    def gap_name(self) -> str:
        return "Gap 2: Unit Mismatch"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.UNKNOWN,
                gap_name=self.gap_name,
                message="OntologyRegistry is not configured in UnitMismatchDetector",
            )

        unit = context.unit.strip()
        if not unit:
            # No unit provided — not a unit mismatch (may be ambiguity or missing qualifier)
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message="No unit provided; unit mismatch check skipped",
            )

        term = context.term.strip()
        if not term:
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message="No term provided; unit mismatch check skipped",
            )

        candidates = self.registry.find_concepts(term)
        if not candidates:
            # NOT_FOUND handled by AmbiguityDetector; pass through here
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message=f"No concepts found for '{term}'; unit mismatch check skipped",
            )

        unit_valid_for_any = any(c.supports_unit(unit) for c in candidates)
        if not unit_valid_for_any:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.UNIT_MISMATCH,
                gap_name=self.gap_name,
                message=(
                    f"Reported unit '{unit}' is not valid for any concept matching '{term}'. "
                    f"Valid units: "
                    + ", ".join(
                        f"{c.label}: [{', '.join(c.units)}]" for c in candidates if c.units
                    )
                ),
                candidates=[c.to_view() for c in candidates],
                details={"reported_unit": unit},
            )

        return GapEvaluationResult(
            passed=True,
            status=ResolutionStatus.RESOLVED,
            gap_name=self.gap_name,
            message=f"Unit '{unit}' is valid for at least one candidate concept",
        )
