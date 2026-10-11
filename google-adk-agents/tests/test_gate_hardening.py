"""
Gate hardening: the deterministic gate cannot be bypassed by the model, by
malformed input, or by a misbehaving detector, and look-alike handling is
derived from the ontology.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from ontogate.attestation import attest_numeric
from ontogate.config import get_default_registry, load_scenario_extension
from ontogate.detectors.ambiguity import AmbiguityDetector
from ontogate.detectors.base import GapDetector
from ontogate.detectors.engine import SafetyGateEngine
from ontogate.detectors.range_collision import RangeCollisionDetector
from ontogate.models import EvaluationContext, GapEvaluationResult, ReferenceInterval, ResolutionStatus
from src.workflow import fetch_node, gate, parse

SCENARIO_D = Path(__file__).resolve().parent.parent.parent / "config" / "scenarios" / "scenario_d_troponin.yaml"


def _harness_with_reply(parts):
    from src.harness.agent import ClinicalADKHarness

    client = MagicMock()
    resp = MagicMock()
    resp.candidates = [MagicMock(content=MagicMock(parts=parts))]
    resp.text = "".join(getattr(p, "text", "") or "" for p in parts)
    client.models.generate_content.return_value = resp
    return ClinicalADKHarness(client=client, offline=False)


# ---------------------------------------------------------------------------
# The model cannot route
# ---------------------------------------------------------------------------
def test_model_prose_cannot_override_gate():
    """If the model answers in prose without calling the gate, the code-computed verdict still clarifies."""
    harness = _harness_with_reply([MagicMock(text="Calcium 4.8 is normal, no action needed.", function_call=None)])
    res = asyncio.run(harness.run(prompt="Calcium 4.8", session=harness.create_session()))
    assert res.route == "CLARIFY"
    assert res.status == "RANGE_COLLISION"


def test_gated_tools_blocked_before_proceed():
    """fetch_grounded_protocol requested before a PROCEED verdict is never executed."""
    fc = MagicMock(name="fetch_grounded_protocol", args={"uri": "loinc:17861-6"})
    harness = _harness_with_reply([MagicMock(function_call=fc, text=None)])
    res = asyncio.run(harness.run(prompt="Calcium 4.8", session=harness.create_session()))
    assert res.route == "CLARIFY"
    assert not res.protocol


def test_gemini_history_roles():
    """Tool outputs are formatted as role='user' function responses for Gemini."""
    from src.harness.context import ContextWindowManager
    from src.harness.session import HarnessSession, ToolInvocationRecord

    session = HarnessSession()
    session.add_user_message("Hb 13.5 | g/dL")
    session.add_model_message(content="", tool_calls=[ToolInvocationRecord(tool_name="resolve_lab_term",
                                                                          args={"term": "Hb"})])
    session.add_tool_response("resolve_lab_term", {"status": "RESOLVED"})
    roles = [c.role for c in ContextWindowManager().format_history_for_gemini(session)]
    assert roles == ["user", "model", "user"]


# ---------------------------------------------------------------------------
# Input boundary
# ---------------------------------------------------------------------------
def test_reported_unit_is_preserved():
    """The clinician's reported unit (g/L) is carried forward, never replaced by the first expected unit."""
    ev = fetch_node({"candidates": [{"uri": "loinc:718-7", "label": "Hemoglobin", "expected_units": ["g/dL", "g/L"]}],
                     "unit": "g/L", "patient_value": 135.0})
    assert ev.output["reported_unit"] == "g/L"


def test_evaluation_context_rejects_non_finite_values():
    """NaN and ±inf are rejected at construction."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            EvaluationContext(term="Calcium", patient_value=bad)


def test_ambiguous_thousands_routes_clarify():
    """'1,250' is an ambiguous thousands separator: no value is assumed and the gate clarifies."""
    ev = parse("Troponin 1,250 | ng/L")
    assert ev.output["ambiguous_thousands"] is True
    assert ev.output["patient_value"] is None
    gate_ev = gate(ev.output)
    assert gate_ev.actions.route == "CLARIFY"
    assert "thousands separator" in gate_ev.output.get("clarification", "")


def test_negative_value_parsed_correctly():
    """A negative value keeps its sign."""
    ev = parse("Na+ -3 | mEq/L")
    assert (ev.output["term"], ev.output["patient_value"], ev.output["unit"]) == ("Na+", -3.0, "mEq/L")


# ---------------------------------------------------------------------------
# Ontology-derived look-alike handling
# ---------------------------------------------------------------------------
def test_reference_interval_classification_bounds():
    """Interval notation controls boundary inclusion; open bounds are allowed."""
    hba1c = ReferenceInterval(id="i", observable="x", unit="%", normal=(None, 5.7), bounds="[)", critical=(None, 13.0))
    assert hba1c.classify(5.6) == "NORMAL"
    assert hba1c.classify(5.7) == "HIGH"
    assert hba1c.classify(13.5) == "CRITICAL_HIGH"
    with pytest.raises(ValidationError):
        ReferenceInterval(id="i", observable="x", unit="%", normal=("low", 1.0))


def test_serum_calcium_is_ambiguous_by_specimen():
    """'serum calcium' does not fix the fraction: 4.8 mg/dL collides across total and ionized."""
    res = RangeCollisionDetector(get_default_registry()).evaluate(
        EvaluationContext(term="serum calcium", patient_value=4.8, unit="mg/dL"))
    assert res.status == ResolutionStatus.RANGE_COLLISION


def test_workflow_gate_runs_full_engine():
    """The workflow gate node runs the whole engine and reports the collision."""
    ev = gate({"term": "Calcium", "patient_value": 4.8, "unit": "mg/dL", "qualifier": ""})
    assert ev.actions.route == "CLARIFY"
    assert ev.output["status"] == "RANGE_COLLISION"
    assert "gate_message" in ev.output


def test_troponin_subunit_qualifier():
    """The single-letter facet values I / T select Troponin I / Troponin T."""
    detector = AmbiguityDetector(load_scenario_extension(SCENARIO_D))
    res_i = detector.evaluate(EvaluationContext(term="Troponin", qualifier="I"))
    assert res_i.passed and res_i.details["resolved_concept"]["uri"] == "loinc:10839-9"
    res_t = detector.evaluate(EvaluationContext(term="Troponin", qualifier="T"))
    assert res_t.passed and res_t.details["resolved_concept"]["uri"] == "loinc:6598-7"


def test_troponin_high_value_attested_as_panic():
    """High-sensitivity Troponin T 500 ng/L attests (no arbitrary cap) and is flagged as panic."""
    registry = load_scenario_extension(SCENARIO_D)
    result = attest_numeric(500.0, registry.protocols["loinc:6598-7"], unit="ng/L", registry=registry)
    assert result.passed is True and result.verdict == "PASS"
    assert result.is_panic is True


def test_scenario_overlay_does_not_mutate_default_registry():
    """Loading an overlay works on a copy; the default registry is unchanged."""
    assert "loinc:10839-9" not in get_default_registry().concepts
    assert "loinc:10839-9" in load_scenario_extension(SCENARIO_D).concepts
    assert "loinc:10839-9" not in get_default_registry().concepts


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class BrokenDetector(GapDetector):
    @property
    def gap_name(self) -> str:
        return "Broken Detector"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        raise RuntimeError("Simulated detector failure")


def test_detector_exception_fails_closed_unknown():
    """An exception inside any detector fails closed to UNKNOWN / CLARIFY."""
    engine = SafetyGateEngine(detectors=[BrokenDetector()])
    verdict = engine.evaluate(EvaluationContext(term="Hb", unit="g/dL", patient_value=14.0))
    assert verdict.passed is False
    assert verdict.status == ResolutionStatus.UNKNOWN
    assert engine.route_for(verdict.status) == "CLARIFY"
    assert "Detector raised unexpectedly" in verdict.message
