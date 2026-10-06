"""
Unit test suite evaluating agent trajectories in pure code (Closing Gap 10).
Tests the resolver, collision engine, and routing gate deterministically
without any LLM calls or network requests, ensuring safety logic never regresses.
"""

import pytest
from src.tools import (
    check_calcium,
    classify,
    csf_workup,
    fetch_grounded_protocol,
    resolve_lab_term,
)
from src.workflow import parse, route_for


# -------------------------------------------------------------------------
# Gap 10: Pure Code Test Suite from Section 7 of the Article
# -------------------------------------------------------------------------
def test_hb_without_unit_is_ambiguous():
    """Ambiguous lab term without unit must return AMBIGUOUS with both candidate concepts."""
    res = resolve_lab_term("Hb")
    assert res["status"] == "AMBIGUOUS"
    assert len(res["candidates"]) == 2
    uris = {c["uri"] for c in res["candidates"]}
    assert uris == {"loinc:718-7", "loinc:4548-4"}


def test_hb_with_correct_unit_resolves():
    """Providing a valid unit resolves the ambiguity to the correct LOINC concept."""
    # Hematology hemoglobin
    res_hemo = resolve_lab_term("Hb", "g/dL")
    assert res_hemo["status"] == "RESOLVED"
    assert len(res_hemo["candidates"]) == 1
    assert res_hemo["candidates"][0]["uri"] == "loinc:718-7"
    assert res_hemo["candidates"][0]["department"] == "Hematology"

    # Biochemistry HbA1c
    res_a1c = resolve_lab_term("Hb", "%")
    assert res_a1c["status"] == "RESOLVED"
    assert len(res_a1c["candidates"]) == 1
    assert res_a1c["candidates"][0]["uri"] == "loinc:4548-4"
    assert res_a1c["candidates"][0]["department"] == "Clinical Biochemistry"


def test_hb_with_invalid_unit_triggers_mismatch():
    """A unit that does not match any candidate must return UNIT_MISMATCH, not guess."""
    res = resolve_lab_term("Hb", "mg/dL")
    assert res["status"] == "UNIT_MISMATCH"
    assert res["reported_unit"] == "mg/dL"
    assert len(res["candidates"]) == 2

    # IFCC mmol/mol is also a mismatch for the 2-concept demo
    res_mmol = resolve_lab_term("Hb", "mmol/mol")
    assert res_mmol["status"] == "UNIT_MISMATCH"


def test_unknown_term_returns_not_found():
    """An unknown term returns NOT_FOUND rather than empty hallucinated results."""
    res = resolve_lab_term("troponin")
    assert res["status"] == "NOT_FOUND"
    assert res["candidates"] == []


def test_calcium_collision():
    """Calcium 4.8 mg/dL without assay qualifier triggers a critical RANGE_COLLISION."""
    res = check_calcium(4.8)
    assert res["status"] == "RANGE_COLLISION"
    assert res["readings"]["Total calcium"] == "CRITICAL_LOW"
    assert res["readings"]["Ionized calcium"] == "NORMAL"


def test_calcium_with_qualifiers_resolves():
    """Explicitly qualified calcium assays eliminate range collisions."""
    # Total calcium specified
    res_total = check_calcium(4.8, "total")
    assert res_total["status"] == "RESOLVED"
    assert res_total["readings"] == {"Total calcium": "CRITICAL_LOW"}

    # Ionized calcium specified
    res_ionized = check_calcium(4.8, "ionized")
    assert res_ionized["status"] == "RESOLVED"
    assert res_ionized["readings"] == {"Ionized calcium": "NORMAL"}


def test_gate_fails_closed():
    """The workflow gate must strictly fail closed: only RESOLVED proceeds."""
    assert route_for("RESOLVED") == "PROCEED"
    for s in ("AMBIGUOUS", "UNIT_MISMATCH", "NOT_FOUND", "RANGE_COLLISION", "UNKNOWN"):
        assert route_for(s) == "CLARIFY"


# -------------------------------------------------------------------------
# Scenario B & Additional Safety Tests
# -------------------------------------------------------------------------
def test_csf_workup_grouping_and_tube_order():
    """CSF emergency workup must correctly group tests by department and maintain tube ordering."""
    workup = csf_workup()
    assert "Clinical Biochemistry" in workup
    assert "Microbiology" in workup
    assert "Hematology" in workup

    # Verify tube assignments
    for item in workup["Clinical Biochemistry"]:
        assert item["tube"] == 1
    for item in workup["Microbiology"]:
        assert item["tube"] == 2
    for item in workup["Hematology"]:
        assert item["tube"] == 3


def test_csf_workup_scoped_by_department():
    """Scoping CSF workup by department returns only that department's tests."""
    hemat_workup = csf_workup("hemat")
    assert list(hemat_workup.keys()) == ["Hematology"]
    assert len(hemat_workup["Hematology"]) == 2
    assert hemat_workup["Hematology"][0]["tube"] == 3


def test_csf_workup_unknown_department():
    """Querying an unknown department returns NOT_FOUND rather than leaking other data."""
    res = csf_workup("radiology")
    assert res == {"status": "NOT_FOUND"}


def test_fetch_grounded_protocol():
    """Protocols fetched by canonical LOINC URI provide exact reference ranges."""
    proto = fetch_grounded_protocol("loinc:718-7")
    assert "13.8-17.2 g/dL" in proto["reference_range"]
    assert "Low < 7.0 g/dL" in proto["panic_limits"]

    # Unknown URI returns NOT_FOUND
    assert fetch_grounded_protocol("loinc:0000-0") == {"status": "NOT_FOUND"}


def test_parse_input_variations():
    """Parse node extracts term and unit from pipe-delimited strings."""
    ev1 = parse("Hb | g/dL")
    assert ev1.output["term"] == "Hb"
    assert ev1.output["unit"] == "g/dL"

    ev2 = parse("Hb")
    assert ev2.output["term"] == "Hb"
    assert ev2.output["unit"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# Defect #4 parity regressions — Strands engine must match ADK verdicts
# ─────────────────────────────────────────────────────────────────────────────
def test_strands_hb_with_cardiology_department_proceeds():
    """Defect #4: 'Hb 14 g/dL' with department 'Cardiology' must PROCEED in Strands.

    Before the fix, SpecimenSequenceDetector defaulted to the CSF panel and
    returned NOT_FOUND because 'Cardiology' is not a CSF department.
    After the fix, specimen sequencing is skipped when no panel_id is supplied,
    matching the ADK verdict of PROCEED/RESOLVED.
    """
    from src.core.detectors.engine import SafetyGateEngine
    from src.core.models import EvaluationContext

    engine = SafetyGateEngine()
    ctx = EvaluationContext(term="Hb", unit="g/dL", patient_value=14.0, department="Cardiology")
    result = engine.evaluate(ctx)
    assert result.passed is True, (
        f"Strands engine returned {result.status} for 'Hb 14 g/dL' with department='Cardiology'; "
        "expected RESOLVED (defect #4 regression)"
    )


def test_strands_calcium_unqualified_returns_range_collision_not_ambiguous():
    """Defect #4: 'Calcium 4.8 mg/dL' must return RANGE_COLLISION in Strands, not AMBIGUOUS.

    The Strands detector order had RangeCollisionDetector after AmbiguityDetector,
    so calcium hit AMBIGUOUS before the collision check could fire.
    After syncing the order, RangeCollision runs first.
    """
    from src.core.detectors.engine import SafetyGateEngine
    from src.core.models import EvaluationContext, ResolutionStatus

    engine = SafetyGateEngine()
    ctx = EvaluationContext(term="calcium", unit="mg/dL", patient_value=4.8)
    result = engine.evaluate(ctx)
    assert result.status == ResolutionStatus.RANGE_COLLISION, (
        f"Strands engine returned {result.status} for 'Calcium 4.8 mg/dL'; "
        "expected RANGE_COLLISION (defect #4 regression)"
    )


# -------------------------------------------------------------------------
# Defect #6 regression: contradictory term and qualifier must return AMBIGUOUS
# -------------------------------------------------------------------------
def test_contradictory_qualifier_fails_safety_gate():
    """Contradictory qualifier 'total' on term 'ionized calcium' must return AMBIGUOUS."""
    from src.core.detectors.engine import SafetyGateEngine
    from src.core.models import EvaluationContext, ResolutionStatus

    engine = SafetyGateEngine()
    ctx = EvaluationContext(term="ionized calcium", qualifier="total", unit="mg/dL")
    result = engine.evaluate(ctx)
    assert result.passed is False
    assert result.status == ResolutionStatus.AMBIGUOUS
    assert "contradicts" in result.message.lower()
