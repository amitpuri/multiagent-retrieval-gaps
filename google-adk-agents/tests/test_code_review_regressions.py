"""
Regression test suite for all code review fixes (Waves 1-3, T1 through T15).
Ensures patient-safety invariants, deterministic gate enforcement, and fail-closed routing.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest
from pydantic import ValidationError

from src.core.attestation import parse_range_bounds, attest_numeric
from src.core.config import get_default_registry, load_domain_config, load_scenario_extension
from src.core.detectors.ambiguity import AmbiguityDetector
from src.core.detectors.base import GapDetector
from src.core.detectors.engine import SafetyGateEngine
from src.core.detectors.range_collision import RangeCollisionDetector
from src.core.models import (
    EvaluationContext,
    GapEvaluationResult,
    NumericAssay,
    ProtocolDefinition,
    ResolutionStatus,
)
from src.workflow import parse, gate, fetch_node


# ---------------------------------------------------------------------------
# T1: Stub Gemini returns prose -> assert route == "CLARIFY"
# ---------------------------------------------------------------------------
def test_t1_stub_gemini_prose_routes_clarify():
    """T1: If the model never calls the gate and returns prose, the gate verdict computed in code enforces CLARIFY."""
    from src.harness.agent import ClinicalADKHarness
    from unittest.mock import MagicMock

    mock_client = MagicMock()
    # Model generates prose only without calling tools
    mock_resp = MagicMock()
    mock_resp.candidates = [
        MagicMock(
            content=MagicMock(
                parts=[MagicMock(text="Calcium 4.8 is normal, no action needed.", function_call=None)]
            )
        )
    ]
    mock_resp.text = "Calcium 4.8 is normal, no action needed."
    mock_client.models.generate_content.return_value = mock_resp

    harness = ClinicalADKHarness(client=mock_client, offline=False)
    session = harness.create_session()
    
    import asyncio
    res = asyncio.run(harness.run(prompt="Calcium 4.8", session=session))
    
    assert res.route == "CLARIFY"
    assert res.status in ("RANGE_COLLISION", "MISSING_QUALIFIER", "AMBIGUOUS")


# ---------------------------------------------------------------------------
# T2: Stub Gemini calls fetch_grounded_protocol before gate -> blocked
# ---------------------------------------------------------------------------
def test_t2_stub_gemini_calls_protocol_before_gate_blocked():
    """T2: Gated tools (fetch_grounded_protocol) are unreachable before a PROCEED gate verdict."""
    from src.harness.agent import ClinicalADKHarness
    from unittest.mock import MagicMock

    mock_client = MagicMock()
    mock_fc = MagicMock(name="fetch_grounded_protocol", args={"uri": "loinc:17861-6"})
    mock_resp = MagicMock()
    mock_resp.candidates = [
        MagicMock(content=MagicMock(parts=[MagicMock(function_call=mock_fc, text=None)]))
    ]
    mock_client.models.generate_content.return_value = mock_resp

    harness = ClinicalADKHarness(client=mock_client, offline=False)
    session = harness.create_session()

    import asyncio
    # Prompt is ambiguous / unqualified -> gate computes CLARIFY
    res = asyncio.run(harness.run(prompt="Calcium 4.8", session=session))

    assert res.route == "CLARIFY"
    # fetch_grounded_protocol must NOT have run or succeeded
    assert not res.protocol


# ---------------------------------------------------------------------------
# T3: Hb 135 | g/L -> reported_unit == "g/L"
# ---------------------------------------------------------------------------
def test_t3_reported_unit_preserved():
    """T3: The clinician's reported unit (g/L) is preserved and not replaced by expected_units[0] (g/dL)."""
    ev = fetch_node({
        "candidates": [{
            "uri": "loinc:718-7",
            "label": "Hemoglobin",
            "expected_units": ["g/dL", "g/L"],
        }],
        "unit": "g/L",
        "patient_value": 135.0,
    })
    assert ev.output["reported_unit"] == "g/L"


# ---------------------------------------------------------------------------
# T4: parse_range_bounds extracts limits correctly
# ---------------------------------------------------------------------------
def test_t4_parse_range_bounds():
    """T4: One-sided and compound range bounds parse correctly."""
    # High > 52 ng/L -> no low bound, high is 52.0
    low, high = parse_range_bounds("High > 52 ng/L")
    assert low is None
    assert high == 52.0

    # Low < 6.5 mg/dL -> low bound is 6.5, no high bound
    low, high = parse_range_bounds("Low < 6.5 mg/dL")
    assert low == 6.5
    assert high is None

    # Two-sided range
    low, high = parse_range_bounds("8.6 to 10.2 mg/dL")
    assert low == 8.6
    assert high == 10.2

    # Compound semicolon string
    low, high = parse_range_bounds("Low < 6.5 mg/dL; high > 14.0 mg/dL")
    assert low == 6.5
    assert high == 14.0


# ---------------------------------------------------------------------------
# T5: attest_computation with high troponin not capped at 1000
# ---------------------------------------------------------------------------
def test_t5_attest_troponin_high_value():
    """T5: High values (e.g. Troponin 500 ng/L) are not blocked by an arbitrary 1000 cap."""
    proto = ProtocolDefinition(
        reference_range="< 14 ng/L",
        panic_limits="High > 52 ng/L",
        clinical_guideline="High-sensitivity Troponin T elevation.",
    )
    result = attest_numeric(500.0, proto)
    assert result.passed is True
    assert result.is_panic is True
    assert result.verdict == "PASS"


# ---------------------------------------------------------------------------
# T6: EvaluationContext rejects NaN and Inf
# ---------------------------------------------------------------------------
def test_t6_evaluation_context_rejects_nan_and_inf():
    """T6: EvaluationContext rejects non-finite patient values at construction."""
    with pytest.raises(ValidationError):
        EvaluationContext(term="Calcium", patient_value=float("nan"))

    with pytest.raises(ValidationError):
        EvaluationContext(term="Calcium", patient_value=float("inf"))

    with pytest.raises(ValidationError):
        EvaluationContext(term="Calcium", patient_value=float("-inf"))


# ---------------------------------------------------------------------------
# T7: Troponin 1,250 | ng/L -> ambiguous thousands guard -> CLARIFY
# ---------------------------------------------------------------------------
def test_t7_ambiguous_thousands_routes_clarify():
    """T7: Ambiguous comma-decimal (e.g. 1,250) flags ambiguous_thousands and routes to CLARIFY."""
    ev = parse("Troponin 1,250 | ng/L")
    assert ev.output["ambiguous_thousands"] is True
    assert ev.output["patient_value"] is None

    gate_ev = gate(ev.output)
    assert gate_ev.actions.route == "CLARIFY"
    assert "thousands separator" in gate_ev.output.get("clarification", "")


# ---------------------------------------------------------------------------
# T8: Na+ -3 | mEq/L -> patient_value == -3.0
# ---------------------------------------------------------------------------
def test_t8_negative_value_parsed_correctly():
    """T8: Negative values preserve minus sign and are not dropped."""
    ev = parse("Na+ -3 | mEq/L")
    assert ev.output["patient_value"] == -3.0
    assert ev.output["term"] == "Na+"
    assert ev.output["unit"] == "mEq/L"


# ---------------------------------------------------------------------------
# T9: Two-turn session history roles formatted for Gemini
# ---------------------------------------------------------------------------
def test_t9_gemini_history_roles():
    """T9: Tool outputs are formatted with role='user' and Part.from_function_response for Gemini."""
    from src.harness.context import ContextWindowManager
    from src.harness.session import HarnessSession, ToolInvocationRecord

    session = HarnessSession()
    session.add_user_message("Hb 13.5 | g/dL")
    session.add_model_message(
        content="",
        tool_calls=[ToolInvocationRecord(tool_name="resolve_lab_term", args={"term": "Hb"})],
    )
    session.add_tool_response("resolve_lab_term", {"status": "RESOLVED"})

    mgr = ContextWindowManager()
    contents = mgr.format_history_for_gemini(session)

    # Gemini requires role sequence: user -> model -> user (with function_response)
    roles = [c.role for c in contents]
    assert "tool" not in roles
    assert roles == ["user", "model", "user"]


# ---------------------------------------------------------------------------
# T10: "serum calcium 4.8 | mg/dL" -> RANGE_COLLISION
# ---------------------------------------------------------------------------
def test_t10_range_collision_by_uri():
    """T10: Synonyms like 'serum calcium' match collision families by URI first."""
    registry = get_default_registry()
    detector = RangeCollisionDetector(registry)

    # Attach candidate matching total calcium URI
    candidates = [{"uri": "loinc:17861-6", "label": "Calcium [Mass/volume] in Serum or Plasma"}]
    ctx = EvaluationContext(
        term="serum calcium",
        patient_value=4.8,
        unit="mg/dL",
        qualifier="",
        metadata={"candidates": candidates},
    )
    res = detector.evaluate(ctx)
    assert not res.passed
    assert res.status == ResolutionStatus.RANGE_COLLISION


# ---------------------------------------------------------------------------
# T11: "Ca 4.8 | mg/dL" via gate() -> SafetyGateEngine called
# ---------------------------------------------------------------------------
def test_t11_workflow_gate_calls_safety_gate_engine():
    """T11: Workflow gate node evaluates full SafetyGateEngine, detecting collision."""
    node_input = {
        "term": "Calcium",
        "patient_value": 4.8,
        "unit": "mg/dL",
        "qualifier": "",
    }
    ev = gate(node_input)
    assert ev.actions.route == "CLARIFY"
    assert ev.output["status"] in ("AMBIGUOUS", "RANGE_COLLISION", "MISSING_QUALIFIER")
    assert "gate_message" in ev.output


# ---------------------------------------------------------------------------
# T12: Missing crit_low in YAML -> ValueError on load
# ---------------------------------------------------------------------------
def test_t12_missing_threshold_in_yaml_raises_value_error(tmp_path):
    """T12: Missing threshold keys in ranges.yaml raise ValueError rather than defaulting to 0.0."""
    bad_yaml = tmp_path / "ranges.yaml"
    bad_yaml.write_text(
        """
domain: "test_domain"
assays:
  incomplete_assay:
    uri: "loinc:9999-9"
    name: "Incomplete Assay"
    unit: "mg/dL"
    ref_low: 1.0
    ref_high: 5.0
    crit_high: 10.0
    # crit_low is missing!
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required threshold 'crit_low'"):
        load_domain_config(tmp_path)


# ---------------------------------------------------------------------------
# T13: "Troponin 15 | I" qualifier matching -> whole-word boundary
# ---------------------------------------------------------------------------
def test_t13_troponin_qualifier_word_boundary():
    """T13: Single-character qualifier 'I' matches Troponin I, not Troponin T."""
    scenario_path = Path(__file__).resolve().parent.parent.parent / "config" / "scenarios" / "scenario_d_troponin.yaml"
    ext_registry = load_scenario_extension(scenario_path)
    detector = AmbiguityDetector(ext_registry)

    # Qualifier "I"
    ctx_i = EvaluationContext(term="Troponin", qualifier="I")
    res_i = detector.evaluate(ctx_i)
    assert res_i.passed is True
    assert res_i.details["resolved_concept"]["uri"] == "loinc:10839-9"

    # Qualifier "T"
    ctx_t = EvaluationContext(term="Troponin", qualifier="T")
    res_t = detector.evaluate(ctx_t)
    assert res_t.passed is True
    assert res_t.details["resolved_concept"]["uri"] == "loinc:6598-7"


# ---------------------------------------------------------------------------
# T14: Scenario D extension does not mutate default registry
# ---------------------------------------------------------------------------
def test_t14_scenario_extension_does_not_mutate_default_registry():
    """T14: load_scenario_extension operates on a copy and leaves _DEFAULT_REGISTRY clean."""
    default_before = get_default_registry()
    assert "loinc:10839-9" not in default_before.concepts

    scenario_path = Path(__file__).resolve().parent.parent.parent / "config" / "scenarios" / "scenario_d_troponin.yaml"
    ext_reg = load_scenario_extension(scenario_path)

    assert "loinc:10839-9" in ext_reg.concepts
    # Global singleton unaffected
    assert "loinc:10839-9" not in get_default_registry().concepts


# ---------------------------------------------------------------------------
# T15: Detector raises -> engine.evaluate returns UNKNOWN / CLARIFY
# ---------------------------------------------------------------------------
class BrokenDetector(GapDetector):
    @property
    def gap_name(self) -> str:
        return "Broken Detector"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        raise RuntimeError("Simulated detector failure")


def test_t15_detector_exception_fails_closed_unknown():
    """T15: Unhandled exceptions inside any detector fail closed to UNKNOWN / CLARIFY."""
    engine = SafetyGateEngine(detectors=[BrokenDetector()])
    ctx = EvaluationContext(term="Hb", unit="g/dL", patient_value=14.0)

    verdict = engine.evaluate(ctx)
    assert verdict.passed is False
    assert verdict.status == ResolutionStatus.UNKNOWN
    assert engine.route_for(verdict.status) == "CLARIFY"
    assert "Detector raised unexpectedly" in verdict.message
