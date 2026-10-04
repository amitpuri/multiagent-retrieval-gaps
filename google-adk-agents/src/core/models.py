"""
Abstract data models and typed schemas for the generic retrieval-gap framework.
Provides typed definitions for concepts, protocols, assays, collision rules,
specimen sequences, and gap evaluation outcomes.

OKF Enhancement (Phase 1):
Concepts and protocols now carry provenance (generated_by, sources),
trust tiers (verified_by → TrustTier), lifecycle (status, stale_after),
typed relationship links (ConceptLink), and an AttestatedComputation stub
per the Open Knowledge Format v0.2 specification.
"""

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# OKF Trust Tier
# ---------------------------------------------------------------------------

class TrustTier(str, Enum):
    """OKF-derived trust classification for concepts and protocols.

    Derived automatically from ``verified_by``:
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
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# OKF: Typed Relationship Links
# ---------------------------------------------------------------------------

class RelationshipKind(str, Enum):
    """Controlled vocabulary of typed edges between OKF concepts.

    Enables multi-hop graph traversal across the knowledge corpus.
    """
    COMPUTED_FROM = "computed_from"   # Metric ← Table or LabTest ← Source
    JOINS_WITH = "joins_with"         # Table ↔ Table
    GOVERNED_BY = "governed_by"       # LabTest → Protocol / Guideline
    PART_OF = "part_of"               # LabTest → Panel
    SEE_ALSO = "see_also"             # Look-alike hazard warning
    SUPERSEDED_BY = "superseded_by"   # Deprecated concept → replacement


class ConceptLink(BaseModel):
    """A directed typed edge from one concept to another (OKF §5.2 links).

    OKF markdown links are untyped; this model adds ``kind`` to enable
    typed graph traversal and ontology-guided inference.
    """
    target_uri: str
    kind: RelationshipKind
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# OKF: Source Provenance
# ---------------------------------------------------------------------------

class ConceptSource(BaseModel):
    """Provenance record for a single source cited by a concept (OKF §5.2).

    Maps directly to a ``sources[]`` entry in OKF YAML frontmatter.
    ``usage_count`` is explicitly a coarse liveness signal, not a ranking score.
    """
    id: str
    author: Optional[str] = None
    last_modified: Optional[str] = None   # ISO date string; kept as str for YAML compat
    usage_count: Optional[int] = None


# ---------------------------------------------------------------------------
# OKF: Attested Computation Stub
# ---------------------------------------------------------------------------

class AttestedComputation(BaseModel):
    """Sanctioned computation descriptor (OKF §5.4).

    The agent may only supply *values for declared parameters*; it must not
    author or edit the computation itself.  A deterministic, no-LLM attester
    checks that what actually ran equals the sanctioned computation bound with
    the claimed parameters, and that the displayed value matches the
    authoritative source.

    Note: The full attestation runtime protocol (receipt/verdict wire formats,
    attester ABI, sandboxing) is deferred to future OKF revisions.
    """
    runtime: str                              # e.g. "bigquery_sql", "python_formula"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    executor: Optional[str] = None            # agent/service ID that runs it
    attester: Optional[str] = None            # deterministic checker identity
    last_attested_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Core Domain Models
# ---------------------------------------------------------------------------

class ConceptDefinition(BaseModel):
    """Canonical ontology concept representation.

    Extended with OKF provenance, trust, freshness, lifecycle, and typed
    relationship links (Phase 1).
    """
    # ---- Identity ----
    uri: str
    label: str
    alt_labels: List[str] = Field(default_factory=list)
    department: str
    units: List[str] = Field(default_factory=list)
    specimen: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)

    # ---- OKF: Lifecycle ----
    status: Literal["draft", "stable", "deprecated"] = "stable"
    stale_after: Optional[datetime] = None

    # ---- OKF: Provenance ----
    generated_by: Optional[str] = None       # e.g. "reference_agent/gemini-2.5-pro"
    generated_at: Optional[datetime] = None
    verified_by: Optional[str] = None        # "human:<id>", "process:<id>", or agent id
    sources: List[ConceptSource] = Field(default_factory=list)

    # ---- OKF: Typed Relationship Links ----
    links: List[ConceptLink] = Field(default_factory=list)

    # ---- Derived Properties ----

    @property
    def trust_tier(self) -> TrustTier:
        """Derive OKF trust tier from ``verified_by`` (OKF §5.2 trust tiers)."""
        if not self.verified_by:
            return TrustTier.UNVERIFIED
        if self.verified_by.startswith("human:"):
            return TrustTier.HUMAN_REVIEWED
        return TrustTier.MACHINE_CONFIRMED

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        """Return True if ``now >= stale_after`` (OKF §5.2 freshness)."""
        if not self.stale_after:
            return False
        now = now or datetime.now(timezone.utc)
        sa = self.stale_after
        if sa.tzinfo is None:
            sa = sa.replace(tzinfo=timezone.utc)
        return now >= sa

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
            "department": self.department,
            "expected_units": self.units,
            "specimen": self.specimen,
            # OKF signals surfaced to agents
            "trust_tier": self.trust_tier.value,
            "status": self.status,
            "is_stale": self.is_stale(),
            "generated_by": self.generated_by,
            "verified_by": self.verified_by,
        }


class ProtocolDefinition(BaseModel):
    """Clinical protocol reference bound to canonical concept URI.

    Extended with OKF lifecycle, trust, and an optional AttestatedComputation
    stub for sanctioned numeric claims (Phase 1).
    """
    reference_range: str
    panic_limits: str
    clinical_guideline: Optional[str] = None

    # ---- OKF: Lifecycle & Trust ----
    status: Literal["draft", "stable", "deprecated"] = "stable"
    stale_after: Optional[datetime] = None
    verified_by: Optional[str] = None

    # ---- OKF: Attested Computation (stub) ----
    attested_computation: Optional[AttestedComputation] = None

    @property
    def trust_tier(self) -> TrustTier:
        """Derive OKF trust tier from ``verified_by``."""
        if not self.verified_by:
            return TrustTier.UNVERIFIED
        if self.verified_by.startswith("human:"):
            return TrustTier.HUMAN_REVIEWED
        return TrustTier.MACHINE_CONFIRMED

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        """Return True if ``now >= stale_after``."""
        if not self.stale_after:
            return False
        now = now or datetime.now(timezone.utc)
        sa = self.stale_after
        if sa.tzinfo is None:
            sa = sa.replace(tzinfo=timezone.utc)
        return now >= sa

    def is_usable(self) -> bool:
        """Return False for deprecated protocols."""
        return self.status != "deprecated"


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
    # Fix 8: optional list of canonical concept URIs (e.g. LOINC) that also
    # identify this collision family.  URI matching takes priority over name-
    # substring matching so that synonyms (e.g. "serum calcium") trigger the
    # same family as "Total calcium" without string overlap.
    uris: List[str] = Field(default_factory=list)


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
        """Fix 4: reject NaN and inf before they reach any detector.

        A NaN patient_value makes every comparison False, so classify(nan)
        returns NORMAL regardless of the actual clinical range.  An inf value
        trivially satisfies CRITICAL_HIGH on every assay.  Both are invalid
        inputs that must be caught at the boundary.
        """
        if v is not None and not math.isfinite(v):
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
