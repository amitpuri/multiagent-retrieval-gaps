"""
Gap 2 & Gap 8 Detector: Lexical Ambiguity and Silent Guessing.
Detects when a clinical query matches multiple candidate concepts across
departments and lacks the necessary unit or contextual constraints to disambiguate.
"""
from __future__ import annotations

from typing import List
from src.core.detectors.base import GapDetector
from src.core.models import (
    ConceptDefinition,
    EvaluationContext,
    GapEvaluationResult,
    ResolutionStatus,
)


class AmbiguityDetector(GapDetector):
    """Detects multi-concept collisions and ungrounded lexical ambiguities."""

    @property
    def gap_name(self) -> str:
        return "Gap 2 & 8: Ambiguity & Silent Guessing"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.UNKNOWN,
                gap_name=self.gap_name,
                message="OntologyRegistry is not configured in AmbiguityDetector",
            )

        term = context.term.strip()
        if not term:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.NOT_FOUND,
                gap_name=self.gap_name,
                message="No search term provided",
            )

        candidates: List[ConceptDefinition] = self.registry.find_concepts(term)
        if not candidates:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.NOT_FOUND,
                gap_name=self.gap_name,
                message=f"No matching concept found for term '{term}'",
                candidates=[],
            )

        # If unit is supplied, filter candidates by supported units
        unit = context.unit.strip()
        if unit:
            matched_by_unit = [c for c in candidates if c.supports_unit(unit)]
            if not matched_by_unit:
                return GapEvaluationResult(
                    passed=False,
                    status=ResolutionStatus.UNIT_MISMATCH,
                    gap_name="Gap 2: Unit Mismatch",
                    message=f"Reported unit '{unit}' is not valid for any matching concept",
                    candidates=[c.to_view() for c in candidates],
                    details={"reported_unit": unit},
                )
            candidates = matched_by_unit

        # If a qualifier is supplied and we are still ambiguous, use it to narrow.
        # This is the fix for Bug 1: a clinician who says "total" after being asked
        # for a qualifier must not be asked again.
        qualifier = context.qualifier.strip()
        if qualifier and len(candidates) > 1:
            q = qualifier.lower()
            qualifier_matched = [
                c for c in candidates
                if any(q in alt.lower() for alt in [c.label] + c.alt_labels)
            ]
            if qualifier_matched:
                candidates = qualifier_matched

        # Check for ambiguity
        if len(candidates) > 1:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.AMBIGUOUS,
                gap_name=self.gap_name,
                message=f"Term '{term}' matches {len(candidates)} distinct concepts; clarification required",
                candidates=[c.to_view() for c in candidates],
            )

        # Single concept resolved
        return GapEvaluationResult(
            passed=True,
            status=ResolutionStatus.RESOLVED,
            gap_name=self.gap_name,
            message=f"Term '{term}' resolved uniquely to {candidates[0].label}",
            candidates=[candidates[0].to_view()],
            details={"resolved_concept": candidates[0].to_view()},
        )
