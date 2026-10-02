"""
Safety Gate Engine: The central deterministic policy evaluation engine.
Executes configured Gap Detectors and strictly enforces fail-closed routing:
only 'RESOLVED' proceeds to clinical synthesis; all uncertainties route to 'CLARIFY'.
"""

from typing import List, Optional
from src.core.config import OntologyRegistry, get_default_registry
from src.core.detectors.ambiguity import AmbiguityDetector
from src.core.detectors.base import GapDetector
from src.core.detectors.range_collision import RangeCollisionDetector
from src.core.detectors.specimen_sequence import SpecimenSequenceDetector
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
    ):
        self.registry = registry or get_default_registry()
        if detectors is not None:
            self.detectors = detectors
        else:
            # Default suite of detectors
            self.detectors = [
                RangeCollisionDetector(self.registry),
                AmbiguityDetector(self.registry),
                SpecimenSequenceDetector(self.registry),
            ]

    def add_detector(self, detector: GapDetector):
        self.detectors.append(detector)

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        """Evaluate context across all registered gap detectors.
        
        Fails closed on first failing detector.
        """
        for detector in self.detectors:
            result = detector.evaluate(context)
            if not result.passed:
                return result

        # All passed
        return GapEvaluationResult(
            passed=True,
            status=ResolutionStatus.RESOLVED,
            gap_name="SafetyGate: All Invariants Satisfied",
            message="Input safely validated against all ontological constraints",
            candidates=result.candidates if 'result' in locals() else [],
            details=result.details if 'result' in locals() else {},
        )

    def route_for(self, status: ResolutionStatus) -> str:
        """Deterministic routing: fails closed on anything other than RESOLVED."""
        return "PROCEED" if status == ResolutionStatus.RESOLVED else "CLARIFY"
