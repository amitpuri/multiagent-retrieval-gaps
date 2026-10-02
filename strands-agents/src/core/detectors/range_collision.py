"""
Range Collision Detector: Look-Alike Tests and Divergent Critical Thresholds.
Detects when unqualified orders (e.g. 'Calcium 4.8' or 'Troponin 15') span
look-alike assays with divergent clinical classifications (e.g. Critical Low vs Normal).
"""

from typing import Dict, List, Optional
from src.core.detectors.base import GapDetector
from src.core.models import (
    CollisionFamily,
    EvaluationContext,
    GapEvaluationResult,
    NumericAssay,
    ResolutionStatus,
)


class RangeCollisionDetector(GapDetector):
    """Detects divergent classifications across look-alike numeric tests."""

    @property
    def gap_name(self) -> str:
        return "Range Collision: Look-Alike Divergence"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.UNKNOWN,
                gap_name=self.gap_name,
                message="Registry not configured in RangeCollisionDetector",
            )

        if context.patient_value is None:
            # Not a numeric result or patient value not extracted
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message="No numeric patient value to evaluate for range collisions",
            )

        val = context.patient_value
        term = context.term.strip().lower()
        qualifier = context.qualifier.strip().lower()

        # Find applicable collision family
        active_family: Optional[CollisionFamily] = None
        for fam in self.registry.collision_families.values():
            # Check if term or assay names belong to this family
            assay_objs = [self.registry.assays[a_id] for a_id in fam.assays if a_id in self.registry.assays]
            if any(term in a.name.lower() or a.name.lower() in term for a in assay_objs):
                active_family = fam
                break

        if not active_family:
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message="No range collision rules apply to this term",
            )

        # Get relevant assays in this family
        family_assays: List[NumericAssay] = [
            self.registry.assays[a_id]
            for a_id in active_family.assays
            if a_id in self.registry.assays
        ]

        # If a specific qualifier was provided, filter down to matched assay
        if qualifier:
            matched_assays = [a for a in family_assays if a.matches_qualifier(qualifier)]
            if matched_assays:
                family_assays = matched_assays

        readings: Dict[str, str] = {a.name: a.classify(val) for a in family_assays}
        unique_classifications = set(readings.values())

        if len(unique_classifications) > 1:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.RANGE_COLLISION,
                gap_name=self.gap_name,
                message=(
                    f"Value {val} generates conflicting clinical interpretations "
                    f"across {active_family.family_name}: {readings}. Explicit qualifier required."
                ),
                details={
                    "family": active_family.family_name,
                    "readings": readings,
                    "value": val,
                },
            )

        return GapEvaluationResult(
            passed=True,
            status=ResolutionStatus.RESOLVED,
            gap_name=self.gap_name,
            message="Numeric value classified consistently without collision",
            details={"readings": readings, "value": val},
        )
