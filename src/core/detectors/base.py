"""
Base abstract interface for retrieval gap detectors.
Any new retrieval gap (e.g. ambiguity, look-alike collision, scope sequencing)
implements this interface to plug into the safety gate engine.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.core.config import OntologyRegistry
from src.core.models import EvaluationContext, GapEvaluationResult


class GapDetector(ABC):
    """Abstract base class for all retrieval gap detectors."""

    def __init__(self, registry: Optional[OntologyRegistry] = None):
        self.registry = registry

    @property
    @abstractmethod
    def gap_name(self) -> str:
        """Name of the gap handled by this detector (e.g. 'Gap 8: Ambiguity')."""
        pass

    @abstractmethod
    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        """Evaluate the context against this detector's invariants.
        
        Returns:
            GapEvaluationResult indicating passed=True/False, status, and diagnostic messages.
        """
        pass
