"""
Blocking safety-gate suite for the ADK implementation (Gap 10: trajectories
tested in pure code). No LLM calls, no network.
"""
import pytest

from ontogate.config import get_default_registry
from ontogate.detectors.ambiguity import AmbiguityDetector
from ontogate.detectors.base import GapDetector
from ontogate.detectors.engine import SafetyGateEngine
from ontogate.detectors.missing_unit import MissingUnitDetector
from ontogate.detectors.range_collision import RangeCollisionDetector
from ontogate.models import EvaluationContext, GapEvaluationResult, ResolutionStatus
from src.tools import classify_lookalikes, evaluate_safety_gate, fetch_grounded_protocol, panel_workup, resolve_lab_term
from src.workflow import parse, route_for


# ---------------------------------------------------------------------------
# Term resolution (Gap 2 & 8)
# ---------------------------------------------------------------------------
def test_hb_without_unit_is_ambiguous():
    """'Hb' denotes Hemoglobin and HbA1c: AMBIGUOUS with both candidates."""
    res = resolve_lab_term("Hb")
    assert res["status"] == "AMBIGUOUS"
    assert {c["uri"] for c in res["candidates"]} == {"loinc:718-7", "loinc:4548-4"}


def test_hb_with_correct_unit_resolves():
    """A valid unit disambiguates to the correct LOINC observable."""
    res_hemo = resolve_lab_term("Hb", "g/dL")
    assert res_hemo["status"] == "RESOLVED"
    assert res_hemo["candidates"][0]["uri"] == "loinc:718-7"
    assert res_hemo["candidates"][0]["department"] == "Hematology"

    res_a1c = resolve_lab_term("Hb", "%")
    assert res_a1c["status"] == "RESOLVED"
    assert res_a1c["candidates"][0]["uri"] == "loinc:4548-4"
    assert res_a1c["candidates"][0]["department"] == "Clinical Biochemistry"


def test_hb_with_invalid_unit_triggers_mismatch():
    """A unit valid for no candidate is UNIT_MISMATCH, never a guess."""
    res = resolve_lab_term("Hb", "mg/dL")
    assert res["status"] == "UNIT_MISMATCH"
    assert res["reported_unit"] == "mg/dL"
    assert len(res["candidates"]) == 2
    assert resolve_lab_term("Hb", "mmol/mol")["status"] == "UNIT_MISMATCH"


def test_unknown_term_returns_not_found():
    """A term outside the pack is NOT_FOUND (troponin is only added by Scenario D)."""
    res = resolve_lab_term("troponin")
    assert res["status"] == "NOT_FOUND"
    assert res["candidates"] == []


def test_qualifier_narrows_calcium():
    """A facet value narrows 'calcium' to one fraction."""
    registry = get_default_registry()
    detector = AmbiguityDetector(registry)
    assert detector.evaluate(EvaluationContext(term="calcium")).status == ResolutionStatus.AMBIGUOUS
    assert detector.evaluate(EvaluationContext(term="calcium", unit="mg/dL")).status == ResolutionStatus.AMBIGUOUS
    total = detector.evaluate(EvaluationContext(term="calcium", qualifier="total"))
    assert total.status == ResolutionStatus.RESOLVED and total.candidates[0]["uri"] == "loinc:17861-6"
    ionized = detector.evaluate(EvaluationContext(term="calcium", qualifier="ionized"))
    assert ionized.status == ResolutionStatus.RESOLVED and ionized.candidates[0]["uri"] == "loinc:17864-0"


def test_contradictory_qualifier_fails_safety_gate():
    """Qualifier 'total' on term 'ionized calcium' is a contradiction → AMBIGUOUS."""
    result = SafetyGateEngine().evaluate(EvaluationContext(term="ionized calcium", qualifier="total", unit="mg/dL"))
    assert result.passed is False
    assert result.status == ResolutionStatus.AMBIGUOUS
    assert "contradicts" in result.message.lower()


# ---------------------------------------------------------------------------
# Look-alike collisions
# ---------------------------------------------------------------------------
def test_calcium_collision():
    """Calcium 4.8 mg/dL without a fraction: total CRITICAL_LOW vs ionized NORMAL."""
    gate = evaluate_safety_gate(term="calcium", unit="mg/dL", patient_value=4.8)
    assert gate["status"] == "RANGE_COLLISION" and gate["route"] == "CLARIFY"
    assert gate["details"]["readings"] == {"Total calcium": "CRITICAL_LOW", "Ionized calcium": "NORMAL"}
    assert classify_lookalikes("calcium", 4.8, "mg/dL")["readings"] == gate["details"]["readings"]


def test_calcium_with_qualifiers_resolves():
    """An explicit fraction removes the collision and keeps the single reading."""
    total = evaluate_safety_gate(term="calcium", unit="mg/dL", qualifier="total", patient_value=4.8)
    assert total["status"] == "RESOLVED"
    assert total["details"]["readings"] == {"Total calcium": "CRITICAL_LOW"}
    ionized = evaluate_safety_gate(term="calcium", unit="mg/dL", qualifier="ionized", patient_value=4.8)
    assert ionized["status"] == "RESOLVED"
    assert ionized["details"]["readings"] == {"Ionized calcium": "NORMAL"}


def test_collision_is_unit_aware():
    """2.4 mmol/L total calcium reads NORMAL; unqualified it collides with ionized (CRITICAL_HIGH)."""
    registry = get_default_registry()
    detector = RangeCollisionDetector(registry)
    total = detector.evaluate(EvaluationContext(term="calcium", unit="mmol/L", qualifier="total", patient_value=2.4))
    assert total.passed and total.details["readings"] == {"Total calcium": "NORMAL"}
    collision = detector.evaluate(EvaluationContext(term="calcium", unit="mmol/L", patient_value=2.4))
    assert collision.status == ResolutionStatus.RANGE_COLLISION


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
def test_missing_unit_detector():
    """A numeric value without a unit is rejected; with a unit, or without a value, it passes."""
    detector = MissingUnitDetector()
    rejected = detector.evaluate(EvaluationContext(term="Calcium", unit="", patient_value=2.4))
    assert rejected.passed is False and rejected.status == ResolutionStatus.UNIT_MISMATCH
    assert "unit" in rejected.message.lower()
    assert detector.evaluate(EvaluationContext(term="Calcium", unit="mg/dL", patient_value=2.4)).passed
    assert detector.evaluate(EvaluationContext(term="Hb", unit="")).passed


def test_engine_rejects_unitless_numeric_end_to_end():
    """'Calcium 2.4 | total' (no unit) is UNIT_MISMATCH: no scale is assumed."""
    result = SafetyGateEngine().evaluate(EvaluationContext(term="Calcium", qualifier="total", patient_value=2.4))
    assert result.passed is False
    assert result.status == ResolutionStatus.UNIT_MISMATCH


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def test_gate_fails_closed():
    """Only RESOLVED proceeds; every other status clarifies."""
    assert route_for("RESOLVED") == "PROCEED"
    for s in ("AMBIGUOUS", "UNIT_MISMATCH", "NOT_FOUND", "RANGE_COLLISION", "MISSING_QUALIFIER",
              "MODEL_UNAVAILABLE", "UNKNOWN"):
        assert route_for(s) == "CLARIFY"
    engine = SafetyGateEngine()
    for status in ResolutionStatus:
        assert engine.route_for(status) == ("PROCEED" if status == ResolutionStatus.RESOLVED else "CLARIFY")


# ---------------------------------------------------------------------------
# Specimen panels (Gap 11)
# ---------------------------------------------------------------------------
def test_panel_workup_tube_order():
    """The CSF panel returns tubes in governed order with their owning departments."""
    workup = panel_workup("csf_emergency_panel")
    assert workup["status"] == "RESOLVED"
    assert [(t["tube"], t["department"]) for t in workup["tubes"]] == [
        (1, "Clinical Biochemistry"), (2, "Microbiology"), (3, "Hematology")]


def test_panel_workup_scoped_by_department():
    """Scoping by a department synonym returns only that department's tube."""
    workup = panel_workup("csf_emergency_panel", "hemat")
    assert [t["department"] for t in workup["tubes"]] == ["Hematology"]
    assert len(workup["tubes"][0]["tests"]) == 2


def test_panel_workup_unknown_department():
    """An unknown department is NOT_FOUND rather than leaking other tubes."""
    assert panel_workup("csf_emergency_panel", "radiology")["status"] == "NOT_FOUND"


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------
def test_fetch_grounded_protocol():
    """Protocols are bound to one canonical URI; unknown URIs are NOT_FOUND."""
    proto = fetch_grounded_protocol("loinc:718-7")
    assert proto["status"] == "RESOLVED"
    assert "13.8-17.2 g/dL" in proto["reference_range"]
    assert "Low < 7.0 g/dL" in proto["panic_limits"]
    assert fetch_grounded_protocol("loinc:0000-0") == {"status": "NOT_FOUND"}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,term,value,qualifier,unit", [
    ("Hb | g/dL", "Hb", None, "", "g/dL"),
    ("Hb", "Hb", None, "", ""),
    ("25-OH vitamin D 18 | ng/mL", "25-OH vitamin D", 18.0, "", "ng/mL"),
    ("Calcium 4,8 | mg/dL", "Calcium", 4.8, "", "mg/dL"),
    ("Na+ -3 | mEq/L", "Na+", -3.0, "", "mEq/L"),
    ("Hb -5 | g/dL", "Hb", -5.0, "", "g/dL"),
    ("Calcium 4.8 | total | mg/dL", "Calcium", 4.8, "total", "mg/dL"),
    ("Calcium 4.8 mg/dL", "Calcium", 4.8, "", "mg/dL"),
])
def test_parse_input_variations(raw, term, value, qualifier, unit):
    """The parser classifies pipe segments by vocabulary and keeps signs and decimals."""
    out = parse(raw).output
    assert (out["term"], out["patient_value"], out["qualifier"], out["unit"]) == (term, value, qualifier, unit)


# ---------------------------------------------------------------------------
# Engine invariants
# ---------------------------------------------------------------------------
def test_engine_raises_on_empty_detector_list():
    """An empty detector list would fail open — it is refused."""
    with pytest.raises(ValueError, match="at least one detector"):
        SafetyGateEngine(detectors=[])


def test_engine_success_result_is_built_from_context():
    """The success result never carries a passing detector's candidates."""

    class AlwaysPassWithSentinel(GapDetector):
        @property
        def gap_name(self) -> str:
            return "AlwaysPassSentinel"

        def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
            return GapEvaluationResult(passed=True, status=ResolutionStatus.RESOLVED, gap_name=self.gap_name,
                                       message="pass", candidates=[{"sentinel": True}])

    result = SafetyGateEngine(detectors=[AlwaysPassWithSentinel()]).evaluate(EvaluationContext(term="Hb", unit="g/dL"))
    assert result.passed is True
    assert result.status == ResolutionStatus.RESOLVED
    assert result.candidates == []


def test_engine_converts_detector_exception_to_unknown():
    """A detector that raises fails closed as UNKNOWN."""

    class Broken(GapDetector):
        @property
        def gap_name(self) -> str:
            return "Broken"

        def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
            raise RuntimeError("boom")

    result = SafetyGateEngine(detectors=[Broken()]).evaluate(EvaluationContext(term="Hb"))
    assert result.passed is False
    assert result.status == ResolutionStatus.UNKNOWN
