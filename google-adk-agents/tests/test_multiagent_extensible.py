"""
Comprehensive test suite for the generic, configurable, and multi-agent retrieval-gap framework.
Tests:
  - Declarative YAML configuration loading into OntologyRegistry.
  - Generic GapDetector plugins (Ambiguity, RangeCollision, SpecimenSequence).
  - SafetyGateEngine fail-closed invariant enforcement in pure code.
  - Dynamic loading of new scenarios (Scenario D: Troponin I vs T) without code changes.
  - A2A message contracts and multi-agent workflow routing.
"""

from pathlib import Path
import pytest

from src.a2a.contracts import A2AAction, A2AMessage, AgentRole
from ontogate.config import get_default_registry, load_domain_config, load_scenario_extension
from ontogate.detectors.ambiguity import AmbiguityDetector
from ontogate.detectors.engine import SafetyGateEngine
from ontogate.detectors.range_collision import RangeCollisionDetector
from ontogate.detectors.specimen_sequence import SpecimenSequenceDetector
from ontogate.models import (
    ConceptDefinition,
    EvaluationContext,
    ResolutionStatus,
)
from src.orchestration.a2a_orchestrator import parse_clinician_input


# -------------------------------------------------------------------------
# Test Group 1: Configuration Loading & Registry
# -------------------------------------------------------------------------
def test_registry_loads_baseline_domain():
    """Verify that the declarative YAML configurations load correctly into OntologyRegistry."""
    registry = get_default_registry()
    assert "loinc:718-7" in registry.concepts
    assert "loinc:4548-4" in registry.concepts
    assert "loinc:17861-6" in registry.concepts
    assert "loinc:17864-0" in registry.concepts

    # Check protocol references
    proto_hb = registry.get_protocol("loinc:718-7")
    assert proto_hb is not None
    assert "13.8-17.2 g/dL" in proto_hb.reference_range
    assert "Low < 7.0 g/dL" in proto_hb.panic_limits

    # Check specimen panels
    csf_panel = registry.get_panel("csf_emergency_panel")
    assert csf_panel is not None
    assert len(csf_panel.tube_rules) == 3


def test_dynamic_scenario_extension_loading():
    """Verify that new scenarios (Scenario D) can dynamically register concepts and protocols via YAML."""
    default_reg = get_default_registry()
    assert "loinc:10839-9" not in default_reg.concepts

    scenario_path = Path(__file__).resolve().parent.parent.parent / "config" / "scenarios" / "scenario_d_troponin.yaml"
    ext_registry = load_scenario_extension(scenario_path)

    # Concept now registered dynamically in extended registry
    assert "loinc:10839-9" in ext_registry.concepts
    assert "loinc:6598-7" in ext_registry.concepts

    # Check dynamic protocol
    proto_tni = ext_registry.get_protocol("loinc:10839-9")
    assert proto_tni is not None
    assert "< 0.04 ng/mL" in proto_tni.reference_range

    # Invariant: default registry was NOT mutated
    assert "loinc:10839-9" not in get_default_registry().concepts


# -------------------------------------------------------------------------
# Test Group 2: Generic Gap Detectors
# -------------------------------------------------------------------------
def test_generic_ambiguity_detector():
    """AmbiguityDetector flags multi-concept collisions when unit is missing."""
    registry = get_default_registry()
    detector = AmbiguityDetector(registry)

    # 1. Missing unit -> AMBIGUOUS
    ctx_unqualified = EvaluationContext(term="Hb")
    res1 = detector.evaluate(ctx_unqualified)
    assert not res1.passed
    assert res1.status == ResolutionStatus.AMBIGUOUS
    assert len(res1.candidates) == 2

    # 2. Correct unit -> RESOLVED
    ctx_qualified = EvaluationContext(term="Hb", unit="g/dL")
    res2 = detector.evaluate(ctx_qualified)
    assert res2.passed
    assert res2.status == ResolutionStatus.RESOLVED
    assert res2.candidates[0]["uri"] == "loinc:718-7"

    # 3. Invalid unit -> UNIT_MISMATCH
    ctx_mismatch = EvaluationContext(term="Hb", unit="mg/dL")
    res3 = detector.evaluate(ctx_mismatch)
    assert not res3.passed
    assert res3.status == ResolutionStatus.UNIT_MISMATCH


def test_generic_range_collision_detector():
    """RangeCollisionDetector detects diverging classifications on look-alike assays."""
    registry = get_default_registry()
    detector = RangeCollisionDetector(registry)

    # Calcium 4.8 without qualifier conflicts: Total (Critical Low) vs Ionized (Normal)
    ctx_collision = EvaluationContext(term="calcium", patient_value=4.8)
    res_coll = detector.evaluate(ctx_collision)
    assert not res_coll.passed
    assert res_coll.status == ResolutionStatus.RANGE_COLLISION

    # Calcium 4.8 with qualifier 'total' resolves
    ctx_total = EvaluationContext(term="calcium", qualifier="total", patient_value=4.8)
    res_tot = detector.evaluate(ctx_total)
    assert res_tot.passed
    assert res_tot.status == ResolutionStatus.RESOLVED


def test_generic_specimen_sequence_detector():
    """SpecimenSequenceDetector enforces sequential tube allocation and department scopes."""
    registry = get_default_registry()
    detector = SpecimenSequenceDetector(registry)

    # Full workup
    ctx_full = EvaluationContext(panel_id="csf_emergency_panel")
    res_full = detector.evaluate(ctx_full)
    assert res_full.passed
    tubes = res_full.details["tubes"]
    assert len(tubes) == 3
    assert tubes[0]["tube"] == 1
    assert tubes[0]["department"] == "Clinical Biochemistry"
    assert tubes[1]["tube"] == 2
    assert tubes[1]["department"] == "Microbiology"
    assert tubes[2]["tube"] == 3
    assert tubes[2]["department"] == "Hematology"

    # Scoped to Microbiology only
    ctx_micro = EvaluationContext(panel_id="csf_emergency_panel", department="microbiology")
    res_micro = detector.evaluate(ctx_micro)
    assert res_micro.passed
    assert len(res_micro.details["tubes"]) == 1
    assert res_micro.details["tubes"][0]["department"] == "Microbiology"


# -------------------------------------------------------------------------
# Test Group 3: SafetyGateEngine Fail-Closed Routing
# -------------------------------------------------------------------------
def test_safety_gate_engine_fails_closed():
    """SafetyGateEngine strictly enforces fail-closed policy."""
    engine = SafetyGateEngine()
    assert engine.route_for(ResolutionStatus.RESOLVED) == "PROCEED"
    for st in [
        ResolutionStatus.AMBIGUOUS,
        ResolutionStatus.UNIT_MISMATCH,
        ResolutionStatus.RANGE_COLLISION,
        ResolutionStatus.SCOPE_VIOLATION,
        ResolutionStatus.MISSING_QUALIFIER,
        ResolutionStatus.NOT_FOUND,
        ResolutionStatus.UNKNOWN,
    ]:
        assert engine.route_for(st) == "CLARIFY"


# -------------------------------------------------------------------------
# Test Group 4: A2A Contracts & Parser
# -------------------------------------------------------------------------
def test_a2a_message_contract_serialization():
    """Verify A2A message formatting and serialization."""
    msg = A2AMessage(
        sender=AgentRole.TRIAGE,
        recipient=AgentRole.ONTOLOGY_RESOLVER,
        action=A2AAction.PARSE_REQUEST,
        payload={"term": "Hb", "patient_value": 13.5},
        status=ResolutionStatus.RESOLVED,
    )
    dumped = msg.model_dump()
    assert dumped["sender"] == "triage_orchestrator"
    assert dumped["recipient"] == "ontology_resolver_agent"
    assert dumped["action"] == "PARSE_REQUEST"
    assert dumped["payload"]["term"] == "Hb"


def test_parse_clinician_input_qualifiers():
    """Verify input parser accurately extracts term, unit, qualifier, and value."""
    ev = parse_clinician_input("Calcium 4.8 | total")
    out = ev.output
    assert out["term"] == "Calcium"
    assert out["patient_value"] == 4.8
    assert out["qualifier"] == "total"
    assert "a2a_triage_message" in out


# -------------------------------------------------------------------------
# Test Group 5: Standalone UnitMismatchDetector
# -------------------------------------------------------------------------
def test_unit_mismatch_detector_invalid_unit():
    """UnitMismatchDetector flags reported units not valid for any matched concept."""
    from ontogate.detectors.unit_mismatch import UnitMismatchDetector

    registry = get_default_registry()
    detector = UnitMismatchDetector(registry)

    # mg/dL is not valid for Hb (g/dL or %) or HbA1c (%)
    ctx = EvaluationContext(term="Hb", unit="mg/dL")
    res = detector.evaluate(ctx)
    assert not res.passed
    assert res.status == ResolutionStatus.UNIT_MISMATCH
    assert "mg/dL" in res.message


def test_unit_mismatch_detector_valid_unit_passes():
    """UnitMismatchDetector passes when reported unit is valid for at least one concept."""
    from ontogate.detectors.unit_mismatch import UnitMismatchDetector

    registry = get_default_registry()
    detector = UnitMismatchDetector(registry)

    ctx = EvaluationContext(term="Hb", unit="g/dL")
    res = detector.evaluate(ctx)
    assert res.passed
    assert res.status == ResolutionStatus.RESOLVED


def test_unit_mismatch_detector_no_unit_skips():
    """UnitMismatchDetector passes when no unit is provided (other detectors handle ambiguity)."""
    from ontogate.detectors.unit_mismatch import UnitMismatchDetector

    registry = get_default_registry()
    detector = UnitMismatchDetector(registry)

    ctx = EvaluationContext(term="Hb", unit="")
    res = detector.evaluate(ctx)
    assert res.passed


# -------------------------------------------------------------------------
# Test Group 6: MissingQualifierDetector
# -------------------------------------------------------------------------
def test_missing_qualifier_detector_flags_unqualified_numeric():
    """MissingQualifierDetector flags numeric results whose candidates differ on a facet."""
    from ontogate.detectors.missing_qualifier import MissingQualifierDetector

    registry = get_default_registry()
    detector = MissingQualifierDetector(registry)

    # 'calcium 4.8' without qualifier — belongs to calcium_lookalike family
    ctx = EvaluationContext(term="calcium", patient_value=4.8, qualifier="")
    res = detector.evaluate(ctx)
    assert not res.passed
    assert res.status == ResolutionStatus.MISSING_QUALIFIER


def test_missing_qualifier_detector_passes_with_qualifier():
    """MissingQualifierDetector passes when a qualifier is already supplied."""
    from ontogate.detectors.missing_qualifier import MissingQualifierDetector

    registry = get_default_registry()
    detector = MissingQualifierDetector(registry)

    ctx = EvaluationContext(term="calcium", patient_value=4.8, qualifier="total")
    res = detector.evaluate(ctx)
    assert res.passed


def test_missing_qualifier_detector_passes_without_numeric():
    """MissingQualifierDetector passes for terms with no patient value (ordering without result)."""
    from ontogate.detectors.missing_qualifier import MissingQualifierDetector

    registry = get_default_registry()
    detector = MissingQualifierDetector(registry)

    ctx = EvaluationContext(term="calcium", qualifier="")
    res = detector.evaluate(ctx)
    assert res.passed


# -------------------------------------------------------------------------
# Test Group 7: Scenario YAML Config Files Exist
# -------------------------------------------------------------------------
def test_all_scenario_yaml_files_exist():
    """All four scenario YAML configuration files must exist for the config-driven design to hold."""
    scenarios_dir = Path(__file__).resolve().parent.parent.parent / "config" / "scenarios"
    expected = [
        "scenario_a_hemoglobin.yaml",
        "scenario_b_csf_panel.yaml",
        "scenario_c_calcium_collision.yaml",
        "scenario_d_troponin.yaml",
    ]
    for fname in expected:
        fpath = scenarios_dir / fname
        assert fpath.exists(), f"Missing scenario YAML: {fname}"


# -------------------------------------------------------------------------
# Test Group 8: Triage Agent
# -------------------------------------------------------------------------
def test_triage_agent_make_envelope():
    """Verify the triage agent creates correct A2A envelopes for dispatch."""
    from src.agents.triage_agent import make_triage_envelope
    from src.a2a.contracts import AgentRole, A2AAction

    msg = make_triage_envelope(
        raw_text="Hb 13.5 | g/dL",
        term="Hb",
        unit="g/dL",
        patient_value=13.5,
    )
    assert msg.sender == AgentRole.TRIAGE
    assert msg.recipient == AgentRole.ONTOLOGY_RESOLVER
    assert msg.action == A2AAction.PARSE_REQUEST
    assert msg.payload["term"] == "Hb"
    assert msg.payload["unit"] == "g/dL"
    assert msg.payload["patient_value"] == 13.5
