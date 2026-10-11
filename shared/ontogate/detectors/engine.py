"""
Safety Gate Engine: the central deterministic policy evaluation engine.

Runs gap detectors in a fixed order and fails closed on the first failure:
only ``RESOLVED`` proceeds to clinical synthesis; every other status — including
a detector raising — routes to ``CLARIFY``. The same order serves every framework.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ontogate.config import OntologyRegistry, get_default_registry
from ontogate.detectors.base import GapDetector
from ontogate.models import EvaluationContext, GapEvaluationResult, ResolutionStatus

logger = logging.getLogger(__name__)

#: Default suite order. Look-alike checks precede the generic ambiguity check so
#: the most informative clarification wins; the unit check runs once a single
#: observable is resolved; population context last among value checks.
DEFAULT_ORDER = (
    "unit_mismatch",
    "range_collision",
    "missing_qualifier",
    "ambiguity",
    "missing_unit",
    "population_context",
    "specimen_sequence",
)


def builtin_detectors(registry: OntologyRegistry) -> List[GapDetector]:
    """Instantiate the built-in suite in :data:`DEFAULT_ORDER`."""
    from ontogate.detectors.ambiguity import AmbiguityDetector
    from ontogate.detectors.missing_qualifier import MissingQualifierDetector
    from ontogate.detectors.missing_unit import MissingUnitDetector
    from ontogate.detectors.population_context import PopulationContextDetector
    from ontogate.detectors.range_collision import RangeCollisionDetector
    from ontogate.detectors.specimen_sequence import SpecimenSequenceDetector
    from ontogate.detectors.unit_mismatch import UnitMismatchDetector

    classes = {
        "unit_mismatch": UnitMismatchDetector,
        "range_collision": RangeCollisionDetector,
        "missing_qualifier": MissingQualifierDetector,
        "ambiguity": AmbiguityDetector,
        "missing_unit": MissingUnitDetector,
        "population_context": PopulationContextDetector,
        "specimen_sequence": SpecimenSequenceDetector,
    }
    return [classes[name](registry) for name in DEFAULT_ORDER]


def plugin_detectors(registry: OntologyRegistry) -> List[GapDetector]:
    """Instantiate third-party detectors registered under ``ontogate.detectors``.

    Built-in names are skipped (they are already in the default suite). A plugin
    that fails to load is logged and skipped; it can never open the gate because
    the built-in suite still runs.
    """
    from importlib.metadata import entry_points

    out: List[GapDetector] = []
    try:
        eps = entry_points(group="ontogate.detectors")
    except Exception:  # pragma: no cover - importlib edge cases
        return out
    for ep in eps:
        if ep.name in DEFAULT_ORDER:
            continue
        try:
            out.append(ep.load()(registry))
        except Exception as exc:
            logger.warning("Skipping detector plugin %s: %s", ep.name, exc)
    return out


class SafetyGateEngine:
    """Aggregates and executes retrieval gap detectors in pure code."""

    def __init__(
        self,
        registry: Optional[OntologyRegistry] = None,
        detectors: Optional[List[GapDetector]] = None,
        include_plugins: bool = True,
    ) -> None:
        self.registry = registry or get_default_registry()
        if detectors is not None:
            # Invariant: an empty detector list would fail open — explicitly forbidden.
            if not detectors:
                raise ValueError(
                    "SafetyGateEngine requires at least one detector. "
                    "An empty detector list would cause the engine to return RESOLVED "
                    "for every input, which is a safety regression. "
                    "Pass detectors=None to use the default suite."
                )
            self.detectors: List[GapDetector] = detectors
        else:
            self.detectors = builtin_detectors(self.registry)
            if include_plugins:
                self.detectors.extend(plugin_detectors(self.registry))

    def add_detector(self, detector: GapDetector) -> None:
        """Append a detector to the evaluation chain."""
        self.detectors.append(detector)

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        """Evaluate context across all detectors; fail closed on the first failure.

        Detector exceptions become a fail-closed UNKNOWN result. The success
        result is built from the context and the passing detectors' readings —
        never from a detector's candidates (no leakage).
        """
        readings: dict = {}
        population_readings: dict = {}
        resolved_uri = None
        for detector in self.detectors:
            try:
                result = detector.evaluate(context)
            except Exception as exc:
                return GapEvaluationResult(
                    passed=False,
                    status=ResolutionStatus.UNKNOWN,
                    gap_name=detector.gap_name,
                    message=f"Detector raised unexpectedly: {exc}",
                )
            if not result.passed:
                return result
            details = result.details or {}
            readings.update(details.get("readings") or {})
            population_readings.update(details.get("population_readings") or {})
            rc = details.get("resolved_concept")
            if isinstance(rc, dict):
                resolved_uri = rc.get("uri", resolved_uri)

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
                "resolved_uri": resolved_uri,
                "readings": readings,
                "population_readings": population_readings,
            },
        )

    def route_for(self, status: ResolutionStatus) -> str:
        """Deterministic routing: fails closed on anything other than RESOLVED."""
        return "PROCEED" if status == ResolutionStatus.RESOLVED else "CLARIFY"
