"""
Abstract data models and typed schemas for the generic retrieval-gap framework.
Provides typed definitions for concepts, protocols, assays, collision rules,
specimen sequences, and gap evaluation outcomes.
"""
from __future__ import annotations

import math
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class ResolutionStatus(str, Enum):
    """Status flags emitted by ontology resolvers and safety gates.
    
    Any status other than RESOLVED triggers fail-closed routing (CLARIFY).
    """
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    RANGE_COLLISION = "RANGE_COLLISION"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    MISSING_QUALIFIER = "MISSING_QUALIFIER"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


class ConceptDefinition(BaseModel):
    """Canonical ontology concept representation."""
    uri: str
    label: str
    alt_labels: List[str] = Field(default_factory=list)
    department: str
    units: List[str] = Field(default_factory=list)
    specimen: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)

    def matches(self, term: str) -> bool:
        """Case-insensitive lexical match against canonical label or alternate labels."""
        t = term.strip().lower()
        if t == self.label.lower():
            return True
        return any(t == alt.lower() for alt in self.alt_labels)

    def supports_unit(self, unit: str) -> bool:
        """Check if concept supports a given unit."""
        if not unit:
            return True
        u = unit.strip().lower()
        return any(u == valid_u.lower() for valid_u in self.units)

    def to_view(self) -> Dict[str, Any]:
        """Project view for agent and tool consumption."""
        return {
            "uri": self.uri,
            "label": self.label,
            "department": self.department,
            "expected_units": self.units,
            "specimen": self.specimen,
        }


class ProtocolDefinition(BaseModel):
    """Clinical protocol reference bound to canonical concept URI."""
    reference_range: str
    panic_limits: str
    clinical_guideline: Optional[str] = None


class NumericAssay(BaseModel):
    """Numeric assay reference parameters for collision detection."""
    uri: str
    name: str
    qualifiers: List[str] = Field(default_factory=list)
    unit: str
    ref_low: float
    ref_high: float
    crit_low: float
    crit_high: float

    def matches_qualifier(self, q: str) -> bool:
        """Check if an assay qualifier applies."""
        if not q:
            return False
        clean_q = q.strip().lower()
        return any(clean_q == qual.lower() for qual in self.qualifiers)

    def classify(self, value: float) -> str:
        """Classify numeric result into clinical tier."""
        if value < self.crit_low:
            return "CRITICAL_LOW"
        if value > self.crit_high:
            return "CRITICAL_HIGH"
        if value < self.ref_low:
            return "LOW"
        if value > self.ref_high:
            return "HIGH"
        return "NORMAL"


class CollisionFamily(BaseModel):
    """Group of look-alike assays that trigger range collision evaluation."""
    family_name: str
    assays: List[str]
    trigger_unit: str = ""
    default_qualifier_required: bool = True


class SpecimenTubeRule(BaseModel):
    """Specimen container/aliquot sequencing rule."""
    tube: int
    department: str
    description: Optional[str] = None
    tests: List[Dict[str, str]] = Field(default_factory=list)


class PanelDefinition(BaseModel):
    """Panel specification grouping specimen sequencing rules."""
    name: str
    specimen: str
    tube_rules: List[SpecimenTubeRule] = Field(default_factory=list)


class EvaluationContext(BaseModel):
    """Input payload and state context passed to gap detectors."""
    term: str = ""
    unit: str = ""
    qualifier: str = ""
    patient_value: Optional[float] = None
    department: str = ""
    panel_id: Optional[str] = None
    raw_text: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("patient_value", mode="before")
    @classmethod
    def reject_non_finite(cls, v: Optional[float]) -> Optional[float]:
        """Reject NaN, inf, booleans, and non-numeric strings before any detector.

        A NaN patient_value makes every comparison False, so classify(nan)
        returns NORMAL regardless of the actual clinical range.  An inf value
        trivially satisfies CRITICAL_HIGH on every assay.  Both are invalid
        inputs that must be caught at the boundary.

        Fix Issue 6: explicitly reject bool (True/False), which Pydantic would
        otherwise silently coerce to 1.0 / 0.0.  Also convert strings to float
        here so the resulting TypeError becomes a ValueError (and therefore a
        Pydantic ValidationError), not a raw TypeError that callers may miss.
        """
        if v is None:
            return v
        # Reject booleans before numeric check — bool is a subclass of int.
        if isinstance(v, bool):
            raise ValueError(
                f"patient_value must be a numeric type, got bool ({v!r}). "
                "Booleans are not valid clinical measurements."
            )
        # Pre-convert strings/ints so math.isfinite never sees a non-float.
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise ValueError(
                f"patient_value must be a finite number, got {v!r}. "
                "Only numeric values are accepted."
            )
        if not math.isfinite(v):
            raise ValueError(
                f"patient_value must be a finite number, got {v!r}. "
                "NaN and infinite values are not valid clinical measurements."
            )
        return v


class GapEvaluationResult(BaseModel):
    """Outcome of evaluating one or more retrieval gap detectors."""
    passed: bool
    status: ResolutionStatus
    gap_name: str
    message: str
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)
