"""
Retrieval gap detectors package.
Exports all modular GapDetector implementations and the SafetyGateEngine.
"""

from ontogate.detectors.base import GapDetector
from ontogate.detectors.ambiguity import AmbiguityDetector
from ontogate.detectors.unit_mismatch import UnitMismatchDetector
from ontogate.detectors.missing_qualifier import MissingQualifierDetector
from ontogate.detectors.missing_unit import MissingUnitDetector
from ontogate.detectors.range_collision import RangeCollisionDetector
from ontogate.detectors.specimen_sequence import SpecimenSequenceDetector
from ontogate.detectors.population_context import PopulationContextDetector
from ontogate.detectors.engine import SafetyGateEngine

__all__ = [
    "GapDetector",
    "AmbiguityDetector",
    "UnitMismatchDetector",
    "MissingQualifierDetector",
    "MissingUnitDetector",
    "RangeCollisionDetector",
    "SpecimenSequenceDetector",
    "PopulationContextDetector",
    "SafetyGateEngine",
]
