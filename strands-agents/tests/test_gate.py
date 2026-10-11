"""
Blocking safety-gate suite for the Strands implementation — the Strands
``@tool`` wrappers over the canonical contract, tested in pure code.
"""
import pytest

from ontogate.detectors.engine import SafetyGateEngine
from ontogate.models import EvaluationContext, ResolutionStatus
from src.tools import evaluate_safety_gate, fetch_grounded_protocol, panel_workup, resolve_lab_term
from src.workflow import parse, route_for


def test_hb_without_unit_is_ambiguous():
    """'Hb' denotes Hemoglobin and HbA1c: AMBIGUOUS with both candidates."""
    res = resolve_lab_term(term="Hb")
    assert res["status"] == "AMBIGUOUS"
    assert {c["uri"] for c in res["candidates"]} == {"loinc:718-7", "loinc:4548-4"}


def test_hb_with_correct_unit_resolves():
    """A valid unit disambiguates; the A2A envelope is attached."""
    res = resolve_lab_term(term="Hb", unit="g/dL")
    assert res["status"] == "RESOLVED"
    assert res["candidates"][0]["uri"] == "loinc:718-7"
    assert res["a2a_message"]["action"] == "RESOLVE_CONCEPT"


def test_hb_with_invalid_unit_triggers_mismatch():
    """A unit valid for no candidate is UNIT_MISMATCH."""
    assert resolve_lab_term(term="Hb", unit="mg/dL")["status"] == "UNIT_MISMATCH"


def test_unknown_term_returns_not_found():
    """A term outside the pack is NOT_FOUND."""
    res = resolve_lab_term(term="troponin")
    assert res["status"] == "NOT_FOUND" and res["candidates"] == []


def test_calcium_collision_and_qualified_resolution():
    """Unqualified calcium collides; a fraction qualifier resolves with one reading."""
    gate = evaluate_safety_gate(term="calcium", unit="mg/dL", patient_value=4.8)
    assert (gate["status"], gate["route"]) == ("RANGE_COLLISION", "CLARIFY")
    assert gate["details"]["readings"] == {"Total calcium": "CRITICAL_LOW", "Ionized calcium": "NORMAL"}
    total = evaluate_safety_gate(term="calcium", unit="mg/dL", qualifier="total", patient_value=4.8)
    assert total["status"] == "RESOLVED"
    assert total["details"]["readings"] == {"Total calcium": "CRITICAL_LOW"}


def test_contradictory_qualifier_fails_safety_gate():
    """Qualifier 'total' on term 'ionized calcium' is a contradiction → AMBIGUOUS."""
    result = SafetyGateEngine().evaluate(EvaluationContext(term="ionized calcium", qualifier="total", unit="mg/dL"))
    assert result.status == ResolutionStatus.AMBIGUOUS
    assert "contradicts" in result.message.lower()


def test_department_outside_a_panel_request_is_ignored():
    """A department on a non-panel request does not affect observable resolution."""
    result = SafetyGateEngine().evaluate(
        EvaluationContext(term="Hb", unit="g/dL", patient_value=14.0, department="Cardiology"))
    assert result.passed is True


def test_gate_fails_closed():
    """Only RESOLVED proceeds."""
    assert route_for("RESOLVED") == "PROCEED"
    for s in ("AMBIGUOUS", "UNIT_MISMATCH", "NOT_FOUND", "RANGE_COLLISION", "MISSING_QUALIFIER", "UNKNOWN"):
        assert route_for(s) == "CLARIFY"


def test_panel_workup_tube_order_and_scope():
    """Tubes come back in governed order; a department synonym scopes to one tube; unknown → NOT_FOUND."""
    full = panel_workup(panel="csf_emergency_panel")
    assert [(t["tube"], t["department"]) for t in full["tubes"]] == [
        (1, "Clinical Biochemistry"), (2, "Microbiology"), (3, "Hematology")]
    assert [t["department"] for t in panel_workup(department="hemat")["tubes"]] == ["Hematology"]
    assert panel_workup(department="radiology")["status"] == "NOT_FOUND"


def test_fetch_grounded_protocol():
    """Protocols are bound to one URI and returned with the A2A envelope."""
    proto = fetch_grounded_protocol(uri="loinc:718-7", concept={"uri": "loinc:718-7"})
    assert proto["status"] == "RESOLVED"
    assert "13.8-17.2 g/dL" in proto["protocol"]["reference_range"]
    assert fetch_grounded_protocol(uri="loinc:0000-0")["status"] == "NOT_FOUND"


@pytest.mark.parametrize("raw,term,unit", [("Hb | g/dL", "Hb", "g/dL"), ("Hb", "Hb", "")])
def test_parse_input_variations(raw, term, unit):
    """The shared parser extracts term and unit."""
    out = parse(raw).output
    assert (out["term"], out["unit"]) == (term, unit)
