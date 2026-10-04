"""
Retrieval gap detectors package.
Exports all modular GapDetector implementations and the SafetyGateEngine.
"""

from src.core.detectors.base import GapDetector
from src.core.detectors.ambiguity import AmbiguityDetector
from src.core.detectors.unit_mismatch import UnitMismatchDetector
from src.core.detectors.missing_qualifier import MissingQualifierDetector
from src.core.detectors.missing_unit import MissingUnitDetector
from src.core.detectors.range_collision import RangeCollisionDetector
from src.core.detectors.specimen_sequence import SpecimenSequenceDetector
from src.core.detectors.engine import SafetyGateEngine

__all__ = [
    "GapDetector",
    "AmbiguityDetector",
    "UnitMismatchDetector",
    "MissingQualifierDetector",
    "MissingUnitDetector",
    "RangeCollisionDetector",
    "SpecimenSequenceDetector",
    "SafetyGateEngine",
]
