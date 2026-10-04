"""
Safety Gate Engine: The central deterministic policy evaluation engine.
Executes configured Gap Detectors and strictly enforces fail-closed routing:
only 'RESOLVED' proceeds to clinical synthesis; all uncertainties route to 'CLARIFY'.
"""
from __future__ import annotations

from typing import List, Optional
from src.core.config import OntologyRegistry, get_default_registry
from src.core.detectors.base import GapDetector
from src.core.models import (
    EvaluationContext,
    GapEvaluationResult,
    ResolutionStatus,
)


class SafetyGateEngine:
    """Aggregates and executes retrieval gap detectors in pure code."""

    def __init__(
        self,
        registry: Optional[OntologyRegistry] = None,
        detectors: Optional[List[GapDetector]] = None,
    ) -> None:
        self.registry = registry or get_default_registry()
        if detectors is not None:
            # Invariant: an empty detector list would fail-open — explicitly forbidden.
            if not detectors:
                raise ValueError(
                    "SafetyGateEngine requires at least one detector. "
                    "An empty detector list would cause the engine to return RESOLVED "
                    "for every input, which is a safety regression. "
                    "Pass detectors=None to use the default suite."
                )
            self.detectors: List[GapDetector] = detectors
        else:
            # Deferred imports avoid circular imports at module level.
            from src.core.detectors.ambiguity import AmbiguityDetector
            from src.core.detectors.unit_mismatch import UnitMismatchDetector
            from src.core.detectors.missing_qualifier import MissingQualifierDetector
            from src.core.detectors.missing_unit import MissingUnitDetector
            from src.core.detectors.range_collision import RangeCollisionDetector
            from src.core.detectors.specimen_sequence import SpecimenSequenceDetector

            # Default suite: all 6 pluggable detectors.
            # MissingUnitDetector is placed before RangeCollisionDetector so that
            # unitless numeric values are rejected before scale-sensitive thresholds run.
            self.detectors = [
                AmbiguityDetector(self.registry),
                UnitMismatchDetector(self.registry),
                MissingQualifierDetector(self.registry),
                MissingUnitDetector(self.registry),
                RangeCollisionDetector(self.registry),
                SpecimenSequenceDetector(self.registry),
            ]

    def add_detector(self, detector: GapDetector) -> None:
        """Append a detector to the evaluation chain."""
        self.detectors.append(detector)

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        """Evaluate context across all registered gap detectors.

        Fails closed on first failing detector.
        The success branch does NOT reference any detector-local ``result``
        variable — that would be a NameError if the list is empty or all
        detectors pass without ever assigning ``result`` in the current scope.
        """
        for detector in self.detectors:
            result = detector.evaluate(context)
            if not result.passed:
                return result

        # All detectors passed.  Build the success result from the *context*,
        # not from whichever detector happened to run last.
        return GapEvaluationResult(
            passed=True,
            status=ResolutionStatus.RESOLVED,
            gap_name="SafetyGate: All Invariants Satisfied",
            message="Input safely validated against all ontological constraints",
            candidates=[],
            details={
                "term": context.term,
                "unit": context.unit,
                "qualifier": context.qualifier,
            },
        )

    def route_for(self, status: ResolutionStatus) -> str:
        """Deterministic routing: fails closed on anything other than RESOLVED."""
        return "PROCEED" if status == ResolutionStatus.RESOLVED else "CLARIFY"
