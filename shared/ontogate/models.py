"""
Typed schemas for the ontology (TBox entities), the deterministic gate, and OKF
provenance.

Ontology entities (``ConceptDefinition`` a.k.a. Observable, ``Designation``,
``Facet``, ``Analyte``, ``UnitDef``, ``ReferenceInterval``, ``Department``,
``Specimen``, ``ProtocolDefinition``, ``PanelDefinition``) are strict
(``extra="forbid"``): a typo in a domain pack is a load error, never a silently
empty field.

OKF fields (provenance, trust tier, lifecycle, freshness, typed links,
attested computation) follow the Open Knowledge Format v0.2 specification.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    """Base for ontology entities: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


def _trust_tier_for(verified_by: Optional[str]) -> "TrustTier":
    if not verified_by:
        return TrustTier.UNVERIFIED
    if verified_by.startswith("human:"):
        return TrustTier.HUMAN_REVIEWED
    return TrustTier.MACHINE_CONFIRMED


def _is_stale(stale_after: Optional[datetime], now: Optional[datetime]) -> bool:
    if not stale_after:
        return False
    now = now or datetime.now(timezone.utc)
    sa = stale_after if stale_after.tzinfo else stale_after.replace(tzinfo=timezone.utc)
    return now >= sa


# ---------------------------------------------------------------------------
# OKF Trust Tier
# ---------------------------------------------------------------------------

class TrustTier(str, Enum):
    """OKF-derived trust classification, derived from ``verified_by``.

    - ``unverified``        — no verification record.
    - ``machine-confirmed`` — verified by a process or agent (non-human).
    - ``human-reviewed``    — explicitly verified by a human reviewer.
    """
    UNVERIFIED = "unverified"
    MACHINE_CONFIRMED = "machine-confirmed"
    HUMAN_REVIEWED = "human-reviewed"


# ---------------------------------------------------------------------------
# Resolution Status
# ---------------------------------------------------------------------------

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
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# OKF: Typed Relationship Links
# ---------------------------------------------------------------------------

class RelationshipKind(str, Enum):
    """Typed edges between concepts (characteristics declared in the core ontology).

    ``confusable_with`` (symmetric look-alike hazard), ``governed_by`` (→ protocol
    node), ``member_of`` (→ collection step), ``precedes`` (collection order),
    ``superseded_by`` (lifecycle) and ``see_also`` (informational only — never
    consulted by the gate).
    """
    CONFUSABLE_WITH = "confusable_with"
    GOVERNED_BY = "governed_by"
    MEMBER_OF = "member_of"
    PRECEDES = "precedes"
    SEE_ALSO = "see_also"
    SUPERSEDED_BY = "superseded_by"


class ConceptLink(_Strict):
    """A directed typed edge from one concept to another (OKF §5.2 links)."""
    target_uri: str
    kind: RelationshipKind
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# OKF: Source Provenance
# ---------------------------------------------------------------------------

class ConceptSource(_Strict):
    """Provenance record for a source cited by a concept (OKF §5.2 ``sources[]``).

    ``usage_count`` is a coarse liveness signal, not a ranking score.
    """
    id: str
    author: Optional[str] = None
    last_modified: Optional[str] = None
    usage_count: Optional[int] = None


# ---------------------------------------------------------------------------
# OKF: Attested Computation
# ---------------------------------------------------------------------------

class AttestedComputation(_Strict):
    """Sanctioned computation descriptor (OKF §5.4).

    The agent may only supply values for declared parameters; a deterministic,
    no-LLM attester checks what ran against the sanctioned computation.
    """
    runtime: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    executor: Optional[str] = None
    attester: Optional[str] = None
    last_attested_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

class UnitDef(_Strict):
    """A UCUM unit with its dimension and factor to the dimension's base unit."""
    code: str
    dimension: str
    factor: float


class Analyte(_Strict):
    """What an observable measures; molar mass enables mass ↔ substance conversion."""
    id: str
    label: str
    molar_mass_g_mol: Optional[float] = None


class Department(_Strict):
    """Owning laboratory department (controlled entity, not a free string)."""
    id: str
    label: str
    synonyms: List[str] = Field(default_factory=list)

    def matches(self, text: str) -> bool:
        """Exact (case-insensitive) match on id, label or a declared synonym."""
        t = text.strip().lower()
        return t in {self.id.lower(), self.label.lower(), *(s.lower() for s in self.synonyms)}


class Specimen(_Strict):
    """Specimen type aligned to the LOINC System axis."""
    id: str
    label: str
    loinc_system: Optional[str] = None
    synonyms: List[str] = Field(default_factory=list)


class Facet(_Strict):
    """A differentiating dimension between sibling observables (e.g. calcium fraction)."""
    id: str
    label: str = ""
    question: str = ""
    values: List[str]
    value_synonyms: Dict[str, str] = Field(default_factory=dict)
    mutually_exclusive: bool = True

    def normalize(self, text: str) -> Optional[str]:
        """Map a qualifier to a canonical facet value, or None if it is not one."""
        t = text.strip().lower()
        for v in self.values:
            if t == v.lower():
                return v
        for syn, v in self.value_synonyms.items():
            if t == syn.lower():
                return v
        return None


class Designation(_Strict):
    """A term clinicians type, and the observables it may denote."""
    text: str
    denotes: List[str]
    kind: Literal["preferred", "synonym", "abbreviation", "ambiguous"] = "synonym"
    note: Optional[str] = None

    @property
    def is_ambiguous(self) -> bool:
        return len(self.denotes) > 1


# ---------------------------------------------------------------------------
# Reference intervals
# ---------------------------------------------------------------------------

Bound = Optional[float]


class ReferenceInterval(_Strict):
    """Normal and critical limits for one observable, unit and population."""
    id: str
    observable: str
    unit: str
    population: Dict[str, str] = Field(default_factory=dict)
    normal: Tuple[Bound, Bound] = (None, None)
    critical: Tuple[Bound, Bound] = (None, None)
    bounds: Literal["[]", "[)", "(]", "()"] = "[]"
    note: Optional[str] = None
    derived_from: Optional[str] = None
    generated_by: Optional[str] = None
    verified_by: Optional[str] = None
    clinically_unvalidated: bool = False

    @property
    def trust_tier(self) -> TrustTier:
        return _trust_tier_for(self.verified_by)

    def applies_to(self, population: Dict[str, str]) -> bool:
        """True unless the context explicitly names a different population value."""
        for key, required in self.population.items():
            if required == "any":
                continue
            given = population.get(key)
            if given and given != required:
                return False
        return True

    def population_label(self) -> str:
        parts = [f"{k}={v}" for k, v in sorted(self.population.items()) if v != "any"]
        return ",".join(parts) or "any"

    def classify(self, value: float) -> str:
        """Classify a value already expressed in ``self.unit``."""
        crit_low, crit_high = self.critical
        if crit_low is not None and value < crit_low:
            return "CRITICAL_LOW"
        if crit_high is not None and value > crit_high:
            return "CRITICAL_HIGH"
        low, high = self.normal
        if low is not None and (value < low if self.bounds[0] == "[" else value <= low):
            return "LOW"
        if high is not None and (value > high if self.bounds[1] == "]" else value >= high):
            return "HIGH"
        return "NORMAL"


# ---------------------------------------------------------------------------
# Observable (ConceptDefinition)
# ---------------------------------------------------------------------------

class ConceptDefinition(_Strict):
    """Canonical observable (LOINC-coded lab test) with OKF provenance.

    ``alt_labels`` is a derived view of the designations that denote this
    observable; the term mapping itself is ``OntologyRegistry.designations``.
    """
    # ---- Identity ----
    uri: str
    label: str
    display_name: Optional[str] = None
    alt_labels: List[str] = Field(default_factory=list)
    department: str
    department_id: Optional[str] = None
    units: List[str] = Field(default_factory=list)
    specimen: Optional[str] = None
    specimen_id: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)

    # ---- Semantics (LOINC axes, facets, relations) ----
    axes: Dict[str, str] = Field(default_factory=dict)
    axes_verified: bool = False
    measures: Optional[str] = None
    facets: Dict[str, str] = Field(default_factory=dict)
    property_codings: Dict[str, Optional[str]] = Field(default_factory=dict)
    confusable_with: List[str] = Field(default_factory=list)
    governed_by: Optional[str] = None
    superseded_by: Optional[str] = None
    intervals_not_applicable: Optional[str] = None

    # ---- OKF: Lifecycle ----
    status: Literal["draft", "stable", "deprecated"] = "stable"
    stale_after: Optional[datetime] = None

    # ---- OKF: Provenance ----
    generated_by: Optional[str] = None
    generated_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    sources: List[ConceptSource] = Field(default_factory=list)

    # ---- OKF: Typed Relationship Links ----
    links: List[ConceptLink] = Field(default_factory=list)

    @property
    def name(self) -> str:
        """Short clinician-facing name (falls back to the LOINC label)."""
        return self.display_name or self.label

    @property
    def trust_tier(self) -> TrustTier:
        """Derive OKF trust tier from ``verified_by`` (OKF §5.2 trust tiers)."""
        return _trust_tier_for(self.verified_by)

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        """Return True if ``now >= stale_after`` (OKF §5.2 freshness)."""
        return _is_stale(self.stale_after, now)

    def is_usable(self) -> bool:
        """Return False for deprecated concepts (OKF §5.2 lifecycle)."""
        return self.status != "deprecated"

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
        """Project view for agent and tool consumption, including OKF signals."""
        return {
            "uri": self.uri,
            "label": self.label,
            "name": self.name,
            "department": self.department,
            "expected_units": self.units,
            "specimen": self.specimen,
            "facets": dict(self.facets),
            # OKF signals surfaced to agents
            "trust_tier": self.trust_tier.value,
            "status": self.status,
            "is_stale": self.is_stale(),
            "generated_by": self.generated_by,
            "verified_by": self.verified_by,
        }


# Ontology name for a concept; both names refer to the same class.
Observable = ConceptDefinition


class ProtocolDefinition(_Strict):
    """Clinical protocol node, bound to exactly one observable URI (invariant 7)."""
    id: Optional[str] = None
    governs: Optional[str] = None
    reference_range: str
    panic_limits: str
    clinical_guideline: Optional[str] = None

    # ---- OKF: Lifecycle & Trust ----
    status: Literal["draft", "stable", "deprecated"] = "stable"
    stale_after: Optional[datetime] = None
    verified_by: Optional[str] = None

    # ---- OKF: Attested Computation ----
    attested_computation: Optional[AttestedComputation] = None

    @property
    def trust_tier(self) -> TrustTier:
        return _trust_tier_for(self.verified_by)

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        return _is_stale(self.stale_after, now)

    def is_usable(self) -> bool:
        return self.status != "deprecated"


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

class SpecimenTubeRule(_Strict):
    """One ordered collection step (tube) of a panel."""
    tube: int
    department: str
    description: Optional[str] = None
    tests: List[Dict[str, str]] = Field(default_factory=list)
    id: Optional[str] = None
    department_id: Optional[str] = None
    includes: List[str] = Field(default_factory=list)
    precedes: Optional[str] = None


class PanelDefinition(_Strict):
    """Panel specification grouping ordered collection steps."""
    name: str
    specimen: str
    tube_rules: List[SpecimenTubeRule] = Field(default_factory=list)
    specimen_id: Optional[str] = None
    collection_method: Optional[str] = None
    designations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Gate I/O
# ---------------------------------------------------------------------------

class EvaluationContext(BaseModel):
    """Input payload and state context passed to gap detectors."""
    term: str = ""
    unit: str = ""
    qualifier: str = ""
    patient_value: Optional[float] = None
    department: str = ""
    panel_id: Optional[str] = None
    population: Dict[str, str] = Field(default_factory=dict)
    raw_text: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("patient_value", mode="before")
    @classmethod
    def reject_non_finite(cls, v: Optional[float]) -> Optional[float]:
        """Reject NaN, inf, booleans and non-numeric strings before any detector.

        A NaN makes every comparison False (classify → NORMAL); inf trivially
        satisfies CRITICAL_HIGH; bool would coerce to 1.0/0.0. All are invalid
        clinical measurements and are rejected at the boundary.
        """
        if v is None:
            return v
        if isinstance(v, bool):
            raise ValueError(
                f"patient_value must be a numeric type, got bool ({v!r}). "
                "Booleans are not valid clinical measurements."
            )
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
