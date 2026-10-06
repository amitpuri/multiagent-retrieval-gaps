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


# -------------------------------------------------------------------------
# Regression tests — bugs fixed in this patch
# -------------------------------------------------------------------------

def test_parse_25oh_vitamin_d_does_not_steal_leading_digits():
    """'25-OH vitamin D 18' must not parse 25 as the value (B3)."""
    ev = parse("25-OH vitamin D 18 | ng/mL")
    assert ev.output["term"] == "25-OH vitamin D"
    assert ev.output["patient_value"] == 18.0
    assert ev.output["unit"] == "ng/mL"


def test_parse_comma_decimal_normalised():
    """'Calcium 4,8' must normalise to value 4.8, not truncate to 4 (B3)."""
    ev = parse("Calcium 4,8 | mg/dL")
    assert ev.output["patient_value"] == 4.8
    assert ev.output["term"] == "Calcium"


def test_parse_negative_value_preserved():
    """A negative numeric value must retain its sign (B3)."""
    ev = parse("Na+ -3 | mEq/L")
    assert ev.output["patient_value"] == -3.0
    assert ev.output["unit"] == "mEq/L"


def test_parse_qualifier_extracted_from_second_pipe():
    """Three-segment 'term value | qualifier | unit' must set qualifier field."""
    ev = parse("Calcium 4.8 | total | mg/dL")
    assert ev.output["term"] == "Calcium"
    assert ev.output["qualifier"] == "total"
    assert ev.output["unit"] == "mg/dL"
    assert ev.output["patient_value"] == 4.8


def test_engine_raises_on_empty_detector_list():
    """SafetyGateEngine([]) must raise ValueError — not silently return RESOLVED (B4)."""
    from src.core.detectors.engine import SafetyGateEngine
    import pytest as _pytest
    with _pytest.raises(ValueError, match="at least one detector"):
        SafetyGateEngine(detectors=[])


def test_engine_success_result_does_not_reference_last_detector_result():
    """Engine success branch must not use 'result' from detector loop scope (B4)."""
    from src.core.detectors.engine import SafetyGateEngine
    from src.core.detectors.base import GapDetector
    from src.core.models import EvaluationContext, GapEvaluationResult, ResolutionStatus

    class AlwaysPassDetector(GapDetector):
        @property
        def gap_name(self) -> str:
            return "AlwaysPass"

        def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message="pass",
            )

    engine = SafetyGateEngine(detectors=[AlwaysPassDetector()])
    ctx = EvaluationContext(term="Hb", unit="g/dL")
    result = engine.evaluate(ctx)
    assert result.passed is True
    assert result.status == ResolutionStatus.RESOLVED


def test_ambiguity_detector_resolves_with_qualifier():
    """AmbiguityDetector must resolve calcium when a valid qualifier narrows to one concept (B1)."""
    from src.core.detectors.ambiguity import AmbiguityDetector
    from src.core.config import get_default_registry
    from src.core.models import EvaluationContext, ResolutionStatus

    registry = get_default_registry()
    detector = AmbiguityDetector(registry)

    # Without qualifier: ambiguous (total calcium vs ionized calcium)
    ctx_ambig = EvaluationContext(term="calcium")
    r_ambig = detector.evaluate(ctx_ambig)
    assert r_ambig.status == ResolutionStatus.AMBIGUOUS

    # With unit that both share: still ambiguous
    ctx_unit = EvaluationContext(term="calcium", unit="mg/dL")
    r_unit = detector.evaluate(ctx_unit)
    assert r_unit.status == ResolutionStatus.AMBIGUOUS

    # With qualifier "total": should resolve to total calcium (loinc:17861-6)
    ctx_total = EvaluationContext(term="calcium", qualifier="total")
    r_total = detector.evaluate(ctx_total)
    assert r_total.status == ResolutionStatus.RESOLVED
    assert r_total.candidates[0]["uri"] == "loinc:17861-6"

    # With qualifier "ionized": should resolve to ionized calcium (loinc:17864-0)
    ctx_ion = EvaluationContext(term="calcium", qualifier="ionized")
    r_ion = detector.evaluate(ctx_ion)
    assert r_ion.status == ResolutionStatus.RESOLVED
    assert r_ion.candidates[0]["uri"] == "loinc:17864-0"


def test_range_collision_unit_aware_mmol_not_misclassified():
    """2.4 mmol/L total calcium must NOT classify as CRITICAL_LOW (B2).

    Before the fix, the mg/dL ranges were applied to the mmol/L value,
    making a normal calcium appear critical.
    """
    from src.core.detectors.range_collision import RangeCollisionDetector
    from src.core.config import get_default_registry
    from src.core.models import EvaluationContext, ResolutionStatus

    registry = get_default_registry(reload=True)
    detector = RangeCollisionDetector(registry)

    # 2.4 mmol/L is a normal total calcium — must NOT be CRITICAL_LOW
    ctx = EvaluationContext(
        term="calcium",
        unit="mmol/L",
        qualifier="total",
        patient_value=2.4,
    )
    result = detector.evaluate(ctx)
    # Qualified + single assay family match → should be RESOLVED, not RANGE_COLLISION
    assert result.passed, (
        f"2.4 mmol/L total calcium wrongly failed: {result.status} — {result.message}"
    )
    if result.details.get("readings"):
        classification = list(result.details["readings"].values())[0]
        assert classification == "NORMAL", (
            f"2.4 mmol/L total calcium classified as {classification!r} instead of 'NORMAL'. "
            "Unit conversion may be missing."
        )


def test_range_collision_unqualified_mmol_still_collides():
    """Unqualified calcium in mmol/L must still trigger RANGE_COLLISION (B2)."""
    from src.core.detectors.range_collision import RangeCollisionDetector
    from src.core.config import get_default_registry
    from src.core.models import EvaluationContext, ResolutionStatus

    registry = get_default_registry(reload=True)
    detector = RangeCollisionDetector(registry)

    # 2.4 mmol/L unqualified calcium — total is NORMAL, ionized is HIGH → collision
    ctx = EvaluationContext(
        term="calcium",
        unit="mmol/L",
        patient_value=2.4,
    )
    result = detector.evaluate(ctx)
    assert result.status == ResolutionStatus.RANGE_COLLISION, (
        f"Expected RANGE_COLLISION for unqualified 2.4 mmol/L calcium, got {result.status}"
    )


# -------------------------------------------------------------------------
# B1 regression: unitless numeric value must be rejected, not silently RESOLVED
# -------------------------------------------------------------------------

def test_missing_unit_detector_rejects_unitless_numeric():
    """'Calcium 2.4' with no unit must return UNIT_MISMATCH via MissingUnitDetector (B1)."""
    from src.core.detectors.missing_unit import MissingUnitDetector
    from src.core.models import EvaluationContext, ResolutionStatus

    detector = MissingUnitDetector()
    ctx = EvaluationContext(term="Calcium", unit="", patient_value=2.4)
    result = detector.evaluate(ctx)
    assert result.passed is False
    assert result.status == ResolutionStatus.UNIT_MISMATCH
    assert "unit" in result.message.lower()


def test_missing_unit_detector_passes_when_unit_present():
    """MissingUnitDetector must pass when a unit accompanies the numeric value (B1)."""
    from src.core.detectors.missing_unit import MissingUnitDetector
    from src.core.models import EvaluationContext, ResolutionStatus

    detector = MissingUnitDetector()
    ctx = EvaluationContext(term="Calcium", unit="mg/dL", patient_value=2.4)
    result = detector.evaluate(ctx)
    assert result.passed is True
    assert result.status == ResolutionStatus.RESOLVED


def test_missing_unit_detector_skips_when_no_value():
    """MissingUnitDetector must not fire when patient_value is None (non-numeric queries)."""
    from src.core.detectors.missing_unit import MissingUnitDetector
    from src.core.models import EvaluationContext, ResolutionStatus

    detector = MissingUnitDetector()
    ctx = EvaluationContext(term="Hb", unit="")
    result = detector.evaluate(ctx)
    assert result.passed is True


def test_engine_rejects_unitless_numeric_end_to_end():
    """Full engine must return UNIT_MISMATCH for unitless 'Calcium 2.4 | total' (B1)."""
    from src.core.detectors.engine import SafetyGateEngine
    from src.core.models import EvaluationContext, ResolutionStatus

    engine = SafetyGateEngine()
    ctx = EvaluationContext(term="Calcium", unit="", qualifier="total", patient_value=2.4)
    result = engine.evaluate(ctx)
    assert result.passed is False
    assert result.status == ResolutionStatus.UNIT_MISMATCH, (
        f"Expected UNIT_MISMATCH for unitless numeric, got {result.status}: {result.message}"
    )


# -------------------------------------------------------------------------
# B2 regression: negative numeric values must not be dropped by the parser
# -------------------------------------------------------------------------

def test_parse_negative_hb_value():
    """'Hb -5 | g/dL' must parse patient_value as -5.0, not 5.0 (B2)."""
    ev = parse("Hb -5 | g/dL")
    assert ev.output["patient_value"] == -5.0, (
        "Expected -5.0 but got {} — minus sign was stripped".format(
            ev.output["patient_value"]
        )
    )
    assert ev.output["term"] == "Hb"
    assert ev.output["unit"] == "g/dL"


# -------------------------------------------------------------------------
# B5 regression: engine must not leak last detector result on success path
# -------------------------------------------------------------------------

def test_engine_success_does_not_leak_last_detector_result_adk():
    """Engine success branch must build result from context, not last detector locals (B5)."""
    from src.core.detectors.engine import SafetyGateEngine
    from src.core.detectors.base import GapDetector
    from src.core.models import EvaluationContext, GapEvaluationResult, ResolutionStatus

    class AlwaysPassWithSentinel(GapDetector):
        """Passes but includes a sentinel candidates list to detect leaks."""

        @property
        def gap_name(self) -> str:
            return "AlwaysPassSentinel"

        def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message="pass",
                candidates=[{"sentinel": True}],
            )

    engine = SafetyGateEngine(detectors=[AlwaysPassWithSentinel()])
    ctx = EvaluationContext(term="Hb", unit="g/dL")
    result = engine.evaluate(ctx)
    assert result.passed is True
    assert result.status == ResolutionStatus.RESOLVED
    assert result.candidates == [], (
        "Engine success branch leaked last detector's candidates into the final result"
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
