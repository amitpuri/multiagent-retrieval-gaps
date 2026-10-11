"""
Base interface for deterministic gap detectors.

A detector inspects an ``EvaluationContext`` against the ontology and returns a
``GapEvaluationResult``. Detectors never call models or perform I/O. New hazard
classes plug in through the ``ontogate.detectors`` entry-point group.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ontogate.config import OntologyRegistry
from ontogate.models import EvaluationContext, GapEvaluationResult, ResolutionStatus


class GapDetector(ABC):
    """Abstract base class for all retrieval gap detectors."""

    def __init__(self, registry: Optional[OntologyRegistry] = None):
        self.registry = registry

    @property
    @abstractmethod
    def gap_name(self) -> str:
        """Name of the gap handled by this detector (e.g. 'Gap 8: Ambiguity')."""

    @abstractmethod
    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        """Evaluate the context against this detector's invariants."""

    # -- helpers shared by ontology-backed detectors --------------------------
    def _resolution(self, context: EvaluationContext):
        from ontogate.resolver import resolve
        uris = list((context.metadata or {}).get("resolved_uris", []) or [])
        for c in (context.metadata or {}).get("candidates", []) or []:
            if isinstance(c, dict) and "uri" in c:
                uris.append(c["uri"])
            elif isinstance(c, str):
                uris.append(c)
        return resolve(self.registry, context.term, context.unit, context.qualifier,
                       context.patient_value, context.population, candidate_uris=uris)

    def _pass(self, message: str, **details) -> GapEvaluationResult:
        return GapEvaluationResult(passed=True, status=ResolutionStatus.RESOLVED,
                                   gap_name=self.gap_name, message=message, details=details)

    def _no_registry(self) -> GapEvaluationResult:
        return GapEvaluationResult(
            passed=False, status=ResolutionStatus.UNKNOWN, gap_name=self.gap_name,
            message=f"OntologyRegistry is not configured in {type(self).__name__}",
        )
