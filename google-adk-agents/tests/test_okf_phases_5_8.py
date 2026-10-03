"""
Test Suite for OKF Refinements (Phases 5 to 8).
Validates:
  - Phase 5: OKF Progressive Disclosure Index (build_index, search_index, pre-scoping)
  - Phase 6: Typed Concept Graph Walk (neighbors, find_lookalikes, multi-hop BFS)
  - Phase 7: Knowledge Writeback (record_concept_update, log.md maintenance)
  - Phase 8: Attested Computation Gate (attest_numeric, range bounds, synthesis gate)
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from src.core.attestation import AttestationResult, attest_numeric, parse_range_bounds
from src.core.concept_graph import (
    concept_subgraph,
    find_governing_protocols,
    find_lookalikes,
    get_direct_links,
    neighbors,
)
from src.core.config import OntologyRegistry, get_default_registry
from src.core.models import (
    AttestedComputation,
    ConceptDefinition,
    ConceptLink,
    ProtocolDefinition,
    RelationshipKind,
    TrustTier,
)
from src.core.okf_index import (
    ConceptIndexEntry,
    build_index,
    export_index_markdown,
    inspect_index_scope,
    search_index,
)
from src.core.okf_writer import format_log_entry, read_update_log, record_concept_update
from src.agents.synthesis_agent import (
    synthesis_gate_node,
    verify_attestation_for_payload,
)
from src.orchestration.a2a_orchestrator import parse_clinician_input


@pytest.fixture(scope="module")
def registry():
    return get_default_registry(reload=True)


# ===========================================================================
# Phase 5: OKF Index Tests
# ===========================================================================

class TestOKFIndex:
    def test_build_index_excludes_deprecated_concepts(self):
        reg = OntologyRegistry()
        reg.register_concept(
            ConceptDefinition(
                uri="c:active",
                label="Active Test",
                department="Hematology",
                status="stable",
            )
        )
        reg.register_concept(
            ConceptDefinition(
                uri="c:deprecated",
                label="Old Deprecated Test",
                department="Hematology",
                status="deprecated",
            )
        )
        index = build_index(reg)
        uris = [e.uri for e in index]
        assert "c:active" in uris
        assert "c:deprecated" not in uris

    def test_index_contains_tags_and_trust_tier(self, registry):
        index = build_index(registry)
        hb_entry = next((e for e in index if e.uri == "loinc:718-7"), None)
        assert hb_entry is not None
        assert hb_entry.label == "Hemoglobin [Mass/volume] in Blood"
        assert "Hematology" in hb_entry.tags
        assert hb_entry.trust_tier == TrustTier.HUMAN_REVIEWED.value
        assert hb_entry.status == "stable"

    def test_search_index_matches_label_and_alt_labels(self, registry):
        index = build_index(registry)
        # Search by alias "Hb"
        matches = search_index(index, "Hb")
        uris = {m.uri for m in matches}
        assert "loinc:718-7" in uris
        assert "loinc:4548-4" in uris

        # Search by exact full label substring
        matches_ca = search_index(index, "Calcium")
        assert any("17861-6" in m.uri for m in matches_ca)

    def test_inspect_index_scope_department(self, registry):
        index = build_index(registry)
        # Calcium tests (total & ionized) are all in Clinical Biochemistry
        scope = inspect_index_scope(index, "Calcium")
        assert not scope["is_empty"]
        assert scope["match_count"] >= 2
        assert scope["department_scope"] == "Clinical Biochemistry"

    def test_export_index_markdown_table(self, registry):
        index = build_index(registry)
        md = export_index_markdown(index)
        assert "# Concept Index (OKF Progressive Disclosure)" in md
        assert "| `loinc:718-7` |" in md
        assert "| Hematology" in md

    def test_parse_clinician_input_enriches_index_scope(self):
        ev = parse_clinician_input("Calcium 9.5 | mg/dL")
        assert ev.output["term"] == "Calcium"
        assert ev.output["unit"] == "mg/dL"
        assert ev.output["patient_value"] == 9.5
        # Pre-scoping signals
        assert ev.output["department_scope"] == "Clinical Biochemistry"
        assert ev.output["index_match_count"] >= 2
        msg = ev.output["a2a_triage_message"]
        assert msg["payload"]["department_scope"] == "Clinical Biochemistry"


# ===========================================================================
# Phase 6: Typed Concept Graph Tests
# ===========================================================================

class TestConceptGraph:
    def test_get_direct_links_all_and_filtered(self, registry):
        all_links = get_direct_links("loinc:718-7", registry)
        assert len(all_links) >= 2

        see_also_links = get_direct_links("loinc:718-7", registry, kind=RelationshipKind.SEE_ALSO)
        assert len(see_also_links) >= 1
        assert all(lk.kind == RelationshipKind.SEE_ALSO for lk in see_also_links)

        governed_links = get_direct_links("loinc:718-7", registry, kind="governed_by")
        assert len(governed_links) >= 1
        assert all(lk.kind == RelationshipKind.GOVERNED_BY for lk in governed_links)

    def test_neighbors_depth1_retrieval(self, registry):
        reach = neighbors("loinc:718-7", registry, depth=1)
        # Should include look-alike HbA1c and governing protocol
        assert "loinc:4548-4" in reach
        assert "loinc:718-7-protocol" in reach

    def test_find_lookalikes_helper(self, registry):
        lookalikes = find_lookalikes("loinc:718-7", registry)
        assert "loinc:4548-4" in lookalikes
        assert "loinc:718-7-protocol" not in lookalikes

    def test_find_governing_protocols_helper(self, registry):
        protocols = find_governing_protocols("loinc:718-7", registry)
        assert "loinc:718-7-protocol" in protocols
        assert "loinc:4548-4" not in protocols

    def test_multi_hop_bfs_traversal(self):
        # Build synthetic 3-hop graph: NodeA -> NodeB -> NodeC
        reg = OntologyRegistry()
        reg.register_concept(
            ConceptDefinition(
                uri="c:A",
                label="Node A",
                department="Lab",
                links=[ConceptLink(target_uri="c:B", kind=RelationshipKind.SEE_ALSO)],
            )
        )
        reg.register_concept(
            ConceptDefinition(
                uri="c:B",
                label="Node B",
                department="Lab",
                links=[ConceptLink(target_uri="c:C", kind=RelationshipKind.SEE_ALSO)],
            )
        )
        reg.register_concept(
            ConceptDefinition(
                uri="c:C",
                label="Node C",
                department="Lab",
            )
        )

        depth1 = neighbors("c:A", reg, depth=1)
        assert depth1 == ["c:B"]

        depth2 = neighbors("c:A", reg, depth=2)
        assert depth2 == ["c:B", "c:C"]

    def test_concept_subgraph_structure(self, registry):
        sub = concept_subgraph("loinc:718-7", registry, depth=1)
        assert "loinc:718-7" in sub
        targets = [lk["target_uri"] for lk in sub["loinc:718-7"]]
        assert "loinc:4548-4" in targets


# ===========================================================================
# Phase 7: Knowledge Writeback Tests
# ===========================================================================

class TestOKFWriter:
    def test_format_log_entry(self):
        fixed_time = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)
        entry = format_log_entry(
            uri="loinc:718-7",
            change="verified reference range",
            agent_id="human:dr_puri",
            timestamp=fixed_time,
        )
        assert entry.startswith("- 2026-10-03T12:00:00+00:00 | `loinc:718-7` |")
        assert "generated_by=human:dr_puri" in entry

    def test_record_concept_update_and_read_log(self, tmp_path: Path):
        test_log = tmp_path / "test_knowledge" / "log.md"

        entry1 = record_concept_update(
            uri="loinc:718-7",
            change="added alias 'total hb'",
            agent_id="curator_agent",
            log_path=test_log,
        )
        entry2 = record_concept_update(
            uri="loinc:4548-4",
            change="verified NGSP reference method",
            agent_id="human:dr_smith",
            log_path=test_log,
        )

        assert test_log.exists()
        lines = read_update_log(test_log)
        assert len(lines) == 2
        assert "loinc:718-7" in lines[0]
        assert "loinc:4548-4" in lines[1]

        # Test limit
        recent = read_update_log(test_log, limit=1)
        assert len(recent) == 1
        assert "loinc:4548-4" in recent[0]


# ===========================================================================
# Phase 8: Attestation Gate Tests
# ===========================================================================

class TestAttestationGate:
    def test_parse_range_bounds(self):
        low, high = parse_range_bounds("8.6 to 10.2 mg/dL")
        assert low == 8.6
        assert high == 10.2

        low_p, high_p = parse_range_bounds("Low < 6.5 mg/dL; high > 14.0 mg/dL")
        assert low_p == 6.5
        assert high_p == 14.0

    def test_attest_numeric_passes_in_range(self, registry):
        proto = registry.get_protocol("loinc:17861-6")
        assert proto is not None
        assert proto.attested_computation is not None

        # 9.5 is within 8.6 to 10.2 mg/dL
        res = attest_numeric(9.5, proto)
        assert res.passed is True
        assert res.verdict == "PASS"
        assert "[Attested ✓]" in res.message
        assert res.is_panic is False

    def test_attest_numeric_flags_panic_value(self, registry):
        proto = registry.get_protocol("loinc:17861-6")
        # 5.0 is below panic limit of 6.5 mg/dL
        res = attest_numeric(5.0, proto)
        # Basic attestation succeeds physiologically, but flags panic
        assert res.passed is True
        assert res.is_panic is True

    def test_attest_numeric_fails_on_implausible_negative(self, registry):
        proto = registry.get_protocol("loinc:17861-6")
        res = attest_numeric(-2.5, proto)
        assert res.passed is False
        assert res.verdict == "FAIL"
        assert "implausible or negative" in res.message

    def test_attest_numeric_fails_on_stale_protocol(self):
        proto = ProtocolDefinition(
            reference_range="8.6 to 10.2 mg/dL",
            panic_limits="Low < 6.5; high > 14.0",
            status="stable",
            stale_after=datetime.now(timezone.utc) - timedelta(days=1),
            attested_computation=AttestedComputation(runtime="python_formula"),
        )
        res = attest_numeric(9.0, proto)
        assert res.passed is False
        assert res.verdict == "STALE"
        assert "stale" in res.message.lower()

    def test_attest_numeric_respects_require_in_range_param(self):
        proto = ProtocolDefinition(
            reference_range="8.6 to 10.2 mg/dL",
            panic_limits="Low < 6.5; high > 14.0",
            attested_computation=AttestedComputation(
                runtime="python_formula",
                parameters={"require_in_range": True},
            ),
        )
        # 12.0 is outside 8.6 to 10.2
        res = attest_numeric(12.0, proto)
        assert res.passed is False
        assert res.verdict == "FAIL"
        assert "outside reference range" in res.message

    def test_verify_attestation_for_payload_pass(self):
        payload = {
            "resolved_uri": "loinc:17861-6",
            "patient_value": 9.2,
            "protocol": {"has_attested_computation": True},
        }
        passed, att = verify_attestation_for_payload(payload)
        assert passed is True
        assert att is not None
        assert att.verdict == "PASS"

    def test_verify_attestation_for_payload_negative_fails(self):
        payload = {
            "resolved_uri": "loinc:17861-6",
            "patient_value": -1.0,
            "protocol": {"has_attested_computation": True},
        }
        passed, att = verify_attestation_for_payload(payload)
        assert passed is False
        assert att is not None
        assert att.verdict == "FAIL"

    def test_synthesis_gate_node_proceeds_with_badge(self):
        payload = {
            "resolved_uri": "loinc:17861-6",
            "patient_value": 9.2,
            "protocol": {"has_attested_computation": True},
        }
        ev = synthesis_gate_node(payload)
        assert ev.output["status"] == "PROCEED"
        assert ev.output["attestation_badge"] == "[Attested ✓]"
        assert ev.output["attestation"]["passed"] is True

    def test_synthesis_gate_node_routes_to_clarify_on_failure(self):
        payload = {
            "resolved_uri": "loinc:17861-6",
            "patient_value": -5.0,
            "protocol": {"has_attested_computation": True},
        }
        ev = synthesis_gate_node(payload)
        assert ev.output["status"] == "CLARIFY"
        assert "Attestation failed" in ev.output["reason"]
        assert ev.output["attestation"]["passed"] is False
