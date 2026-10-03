"""
OKF Refinement Tests (Phases 1–4).

Tests verifying that OKF provenance, trust tiers, freshness, lifecycle, and
trust-calibrated synthesis are correctly implemented across:
  - ConceptDefinition / ProtocolDefinition models (Phase 1)
  - YAML config loader (Phase 2)
  - Ontology resolver trust filtering (Phase 3)
  - Synthesis agent trust-calibrated instruction (Phase 4)
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from src.core.models import (
    AttestedComputation,
    ConceptDefinition,
    ConceptLink,
    ConceptSource,
    ProtocolDefinition,
    RelationshipKind,
    ResolutionStatus,
    TrustTier,
)
from src.core.config import load_domain_config, get_default_registry
from src.agents.ontology_agent import resolve_term_with_registry
from src.agents.synthesis_agent import (
    create_synthesize_agent,
    create_synthesize_agent_from_payload,
    _TRUST_PHRASES,
    _STATUS_PHRASES,
)


@pytest.fixture(scope="module")
def registry():
    return get_default_registry(reload=True)


# ---------------------------------------------------------------------------
# Phase 1: ConceptDefinition OKF field tests
# ---------------------------------------------------------------------------

class TestTrustTierDerivation:
    """OKF §5.2: Trust tier derived from verified_by field."""

    def test_no_verified_by_is_unverified(self):
        c = ConceptDefinition(uri="u:1", label="X", department="D")
        assert c.trust_tier == TrustTier.UNVERIFIED

    def test_human_prefix_gives_human_reviewed(self):
        c = ConceptDefinition(uri="u:2", label="X", department="D", verified_by="human:dr_puri")
        assert c.trust_tier == TrustTier.HUMAN_REVIEWED

    def test_process_prefix_gives_machine_confirmed(self):
        c = ConceptDefinition(uri="u:3", label="X", department="D", verified_by="process:auto-import")
        assert c.trust_tier == TrustTier.MACHINE_CONFIRMED

    def test_agent_id_gives_machine_confirmed(self):
        c = ConceptDefinition(uri="u:4", label="X", department="D", verified_by="reference_agent/gemini-2.5-pro")
        assert c.trust_tier == TrustTier.MACHINE_CONFIRMED


class TestStalenessCheck:
    """OKF §5.2: is_stale derived from stale_after timestamp."""

    def test_no_stale_after_is_never_stale(self):
        c = ConceptDefinition(uri="u:1", label="X", department="D")
        assert not c.is_stale()

    def test_future_stale_after_is_not_stale(self):
        future = datetime.now(timezone.utc) + timedelta(days=365)
        c = ConceptDefinition(uri="u:2", label="X", department="D", stale_after=future)
        assert not c.is_stale()

    def test_past_stale_after_is_stale(self):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        c = ConceptDefinition(uri="u:3", label="X", department="D", stale_after=past)
        assert c.is_stale()

    def test_is_stale_respects_custom_now(self):
        stale_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
        c = ConceptDefinition(uri="u:4", label="X", department="D", stale_after=stale_date)
        before = datetime(2024, 12, 31, tzinfo=timezone.utc)
        after = datetime(2025, 1, 2, tzinfo=timezone.utc)
        assert not c.is_stale(now=before)
        assert c.is_stale(now=after)


class TestLifecycleUsability:
    """OKF §5.2: is_usable returns False for deprecated concepts."""

    def test_stable_is_usable(self):
        c = ConceptDefinition(uri="u:1", label="X", department="D", status="stable")
        assert c.is_usable()

    def test_draft_is_usable(self):
        c = ConceptDefinition(uri="u:2", label="X", department="D", status="draft")
        assert c.is_usable()

    def test_deprecated_is_not_usable(self):
        c = ConceptDefinition(uri="u:3", label="X", department="D", status="deprecated")
        assert not c.is_usable()


class TestConceptLinks:
    """OKF §5.2: Typed concept links."""

    def test_concept_link_round_trip(self):
        link = ConceptLink(target_uri="loinc:4548-4", kind=RelationshipKind.SEE_ALSO,
                           description="Look-alike HbA1c")
        assert link.kind == RelationshipKind.SEE_ALSO
        assert link.target_uri == "loinc:4548-4"

    def test_concept_stores_links(self):
        c = ConceptDefinition(
            uri="loinc:718-7", label="Hemoglobin", department="Hematology",
            links=[ConceptLink(target_uri="loinc:4548-4", kind=RelationshipKind.SEE_ALSO)],
        )
        assert len(c.links) == 1
        assert c.links[0].kind == RelationshipKind.SEE_ALSO


class TestConceptSource:
    """OKF §5.2: Source provenance records."""

    def test_source_round_trip(self):
        s = ConceptSource(id="loinc-2026", author="Regenstrief", usage_count=412)
        assert s.id == "loinc-2026"
        assert s.usage_count == 412


class TestAttestedComputation:
    """OKF §5.4: Attested Computation stub."""

    def test_attested_computation_stored_on_protocol(self):
        ac = AttestedComputation(runtime="bigquery_sql", executor="protocol_agent",
                                  attester="deterministic_checker")
        proto = ProtocolDefinition(reference_range="8.5-10.5", panic_limits="<6 or >13",
                                   attested_computation=ac)
        assert proto.attested_computation is not None
        assert proto.attested_computation.runtime == "bigquery_sql"

    def test_protocol_without_attestation_is_none(self):
        proto = ProtocolDefinition(reference_range="8.5-10.5", panic_limits="<6 or >13")
        assert proto.attested_computation is None


class TestProtocolTrustTier:
    """OKF §5.2: Trust tier on ProtocolDefinition."""

    def test_protocol_unverified_by_default(self):
        proto = ProtocolDefinition(reference_range="8.5-10.5", panic_limits="<6 or >13")
        assert proto.trust_tier == TrustTier.UNVERIFIED

    def test_protocol_human_reviewed(self):
        proto = ProtocolDefinition(reference_range="8.5-10.5", panic_limits="<6 or >13",
                                   verified_by="human:dr_puri")
        assert proto.trust_tier == TrustTier.HUMAN_REVIEWED


# ---------------------------------------------------------------------------
# Phase 2: YAML config loader integration tests
# ---------------------------------------------------------------------------

class TestYAMLOKFLoading:
    """OKF fields are correctly loaded from concepts.yaml and protocols.yaml."""

    def test_hemoglobin_verified_by_human(self, registry):
        c = registry.concepts["loinc:718-7"]
        assert c.verified_by == "human:dr_puri"
        assert c.trust_tier == TrustTier.HUMAN_REVIEWED

    def test_csf_protein_machine_confirmed(self, registry):
        c = registry.concepts["loinc:2880-3"]
        assert c.verified_by is not None
        assert c.trust_tier == TrustTier.MACHINE_CONFIRMED

    def test_hemoglobin_has_see_also_link(self, registry):
        c = registry.concepts["loinc:718-7"]
        see_also = [lk for lk in c.links if lk.kind == RelationshipKind.SEE_ALSO]
        assert len(see_also) >= 1
        assert any("4548-4" in lk.target_uri for lk in see_also)

    def test_hemoglobin_has_source(self, registry):
        c = registry.concepts["loinc:718-7"]
        assert len(c.sources) >= 1
        assert c.sources[0].id == "loinc-2026"

    def test_concept_status_is_stable(self, registry):
        c = registry.concepts["loinc:718-7"]
        assert c.status == "stable"

    def test_hemoglobin_to_view_includes_trust_fields(self, registry):
        view = registry.concepts["loinc:718-7"].to_view()
        assert "trust_tier" in view
        assert "status" in view
        assert "is_stale" in view
        assert "verified_by" in view

    def test_protocol_verified_by_human(self, registry):
        proto = registry.protocols["loinc:718-7"]
        assert proto.verified_by == "human:dr_puri"
        assert proto.trust_tier == TrustTier.HUMAN_REVIEWED

    def test_calcium_protocol_has_attested_computation(self, registry):
        proto = registry.protocols.get("loinc:17861-6")
        assert proto is not None
        assert proto.attested_computation is not None
        assert proto.attested_computation.runtime == "python_formula"


# ---------------------------------------------------------------------------
# Phase 3: Ontology resolver OKF filtering tests
# ---------------------------------------------------------------------------

class TestOntologyResolverOKFFiltering:
    """Deprecated/stale concepts are excluded; candidates ranked by trust tier."""

    @pytest.fixture
    def registry_with_deprecated(self):
        from src.core.config import OntologyRegistry
        reg = OntologyRegistry()
        # stable + human-reviewed
        reg.register_concept(ConceptDefinition(
            uri="t:stable", label="mytest", alt_labels=[], department="D",
            units=["mg/dL"], status="stable", verified_by="human:reviewer",
        ))
        # deprecated — must be excluded
        reg.register_concept(ConceptDefinition(
            uri="t:deprecated", label="mytest", alt_labels=[], department="D",
            units=["mg/dL"], status="deprecated",
        ))
        return reg

    @pytest.fixture
    def registry_with_stale(self):
        from src.core.config import OntologyRegistry
        past = datetime.now(timezone.utc) - timedelta(days=1)
        reg = OntologyRegistry()
        reg.register_concept(ConceptDefinition(
            uri="t:fresh", label="freshtest", alt_labels=[], department="D",
            units=[], status="stable", verified_by="human:reviewer",
        ))
        reg.register_concept(ConceptDefinition(
            uri="t:stale", label="freshtest", alt_labels=[], department="D",
            units=[], status="stable", stale_after=past,
        ))
        return reg

    def test_deprecated_concept_never_returned(self, registry_with_deprecated):
        result = resolve_term_with_registry("mytest", registry=registry_with_deprecated)
        uris = [c["uri"] for c in result["candidates"]]
        assert "t:deprecated" not in uris

    def test_deprecated_uri_in_deprecated_dropped(self, registry_with_deprecated):
        result = resolve_term_with_registry("mytest", registry=registry_with_deprecated)
        assert "t:deprecated" in result["deprecated_dropped"]

    def test_resolved_concept_returns_trust_tier(self, registry_with_deprecated):
        result = resolve_term_with_registry("mytest", registry=registry_with_deprecated)
        assert result["status"] == ResolutionStatus.RESOLVED.value
        assert result["trust_tier"] == TrustTier.HUMAN_REVIEWED.value

    def test_stale_concept_excluded_when_fresh_available(self, registry_with_stale):
        result = resolve_term_with_registry("freshtest", registry=registry_with_stale)
        uris = [c["uri"] for c in result["candidates"]]
        assert "t:stale" not in uris
        assert "t:stale" in result["stale_dropped"]

    def test_trust_tier_ranking_most_trusted_first(self):
        from src.core.config import OntologyRegistry
        reg = OntologyRegistry()
        # Add two matching concepts with different trust tiers
        reg.register_concept(ConceptDefinition(
            uri="t:unverified", label="ranktest", alt_labels=[], department="D", units=[],
        ))
        reg.register_concept(ConceptDefinition(
            uri="t:human", label="ranktest", alt_labels=[], department="D", units=[],
            verified_by="human:reviewer",
        ))
        reg.register_concept(ConceptDefinition(
            uri="t:machine", label="ranktest", alt_labels=[], department="D", units=[],
            verified_by="process:auto",
        ))
        result = resolve_term_with_registry("ranktest", registry=reg)
        # Status is AMBIGUOUS (3 candidates) but ranked: human first
        tiers = [c["trust_tier"] for c in result["candidates"]]
        assert tiers[0] == TrustTier.HUMAN_REVIEWED.value
        assert tiers[1] == TrustTier.MACHINE_CONFIRMED.value
        assert tiers[2] == TrustTier.UNVERIFIED.value

    def test_concept_status_returned_when_resolved(self):
        from src.core.config import OntologyRegistry
        reg = OntologyRegistry()
        reg.register_concept(ConceptDefinition(
            uri="t:one", label="singletest", alt_labels=[], department="D", units=[],
            status="draft", verified_by="human:x",
        ))
        result = resolve_term_with_registry("singletest", registry=reg)
        assert result["status"] == ResolutionStatus.RESOLVED.value
        assert result["concept_status"] == "draft"

    def test_real_registry_hemoglobin_has_trust_tier(self):
        """End-to-end: real YAML config loads human-reviewed Hb concept."""
        reg = get_default_registry(reload=True)
        result = resolve_term_with_registry("hb", registry=reg)
        # Hb is ambiguous (718-7 + 4548-4) — trust_tier is None for ambiguous
        assert result["status"] == ResolutionStatus.AMBIGUOUS.value
        assert result["trust_tier"] is None  # AMBIGUOUS → no single winner

    def test_real_registry_hb_with_unit_resolves_with_trust(self):
        """Hb + g/dL resolves to loinc:718-7 (human-reviewed)."""
        reg = get_default_registry(reload=True)
        result = resolve_term_with_registry("hb", unit="g/dL", registry=reg)
        assert result["status"] == ResolutionStatus.RESOLVED.value
        assert result["trust_tier"] == TrustTier.HUMAN_REVIEWED.value


# ---------------------------------------------------------------------------
# Phase 4: Synthesis agent trust-calibrated instruction tests
# ---------------------------------------------------------------------------

class TestSynthesisAgentTrustCalibration:
    """OKF §9: Trust tier drives phrasing in synthesis agent instruction."""

    def test_human_reviewed_phrase_in_instruction(self):
        agent = create_synthesize_agent(trust_tier="human-reviewed")
        assert "human-reviewed" in agent.instruction.lower()

    def test_machine_confirmed_phrase_in_instruction(self):
        agent = create_synthesize_agent(trust_tier="machine-confirmed")
        assert "machine-confirmed" in agent.instruction.lower()

    def test_unverified_warning_in_instruction(self):
        agent = create_synthesize_agent(trust_tier="unverified")
        assert "unverified" in agent.instruction.lower()

    def test_draft_status_phrase_in_instruction(self):
        agent = create_synthesize_agent(concept_status="draft")
        assert "draft" in agent.instruction.lower()

    def test_deprecated_status_phrase_in_instruction(self):
        agent = create_synthesize_agent(concept_status="deprecated")
        assert "deprecated" in agent.instruction.lower()

    def test_stale_flag_in_instruction(self):
        agent = create_synthesize_agent(is_stale=True)
        assert "stale" in agent.instruction.lower()

    def test_no_stale_flag_when_not_stale(self):
        agent = create_synthesize_agent(is_stale=False)
        # "stale" should only appear in generic "deprecated or stale" warning, not stale_after alert
        assert "stale_after date" not in agent.instruction

    def test_create_from_payload_human_reviewed(self):
        payload = {"trust_tier": "human-reviewed", "concept_status": "stable", "is_stale": False}
        agent = create_synthesize_agent_from_payload(payload)
        assert "human-reviewed" in agent.instruction.lower()

    def test_create_from_payload_defaults_to_unverified(self):
        payload = {}
        agent = create_synthesize_agent_from_payload(payload)
        assert "unverified" in agent.instruction.lower()

    def test_create_from_payload_unknown_trust_tier_defaults_to_unverified(self):
        payload = {"trust_tier": "invented-tier"}
        agent = create_synthesize_agent_from_payload(payload)
        assert "unverified" in agent.instruction.lower()

    def test_citation_rule_in_instruction(self):
        agent = create_synthesize_agent(trust_tier="human-reviewed")
        assert "[Source:" in agent.instruction

    def test_stable_status_no_extra_caveat(self):
        agent = create_synthesize_agent(trust_tier="human-reviewed", concept_status="stable")
        # Stable status phrase is empty — no "DRAFT" or "DEPRECATED" noise
        assert "DRAFT" not in agent.instruction
        assert "DEPRECATED" not in agent.instruction
