"""Regression test suite for audit findings:
1. Basic ADK workflow end-to-end pipeline (parse -> resolve_node -> gate -> fetch_node -> synthesis_gate_node).
2. Unit-aware attestation across alternate clinical units (mmol/L for calcium, g/L for hemoglobin).
3. Parser parity between workflow.parse and a2a_orchestrator.parse_clinician_input.
4. Protection of tracked knowledge/log.md during test execution.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from src.workflow import parse, resolve_node, gate, fetch_node, synthesis_gate_node
from src.orchestration.a2a_orchestrator import parse_clinician_input
from src.harness.mcp_server import attest_computation
from src.core.attestation import attest_numeric, convert_unit, detect_protocol_unit
from src.core.config import get_default_registry


# =========================================================================
# 1. End-to-End ADK Workflow Pipeline Tests
# =========================================================================

def test_workflow_pipeline_reaches_synthesis_for_clean_hb():
    """Clean Hb 13.5 | g/dL must proceed from parse through gate to fetch and synthesis."""
    # 1. Parse
    e_parse = parse("Hb 13.5 | g/dL")
    assert e_parse.output["term"] == "Hb"
    assert e_parse.output["patient_value"] == 13.5
    assert e_parse.output["unit"] == "g/dL"

    # 2. Resolve
    e_resolve = resolve_node(e_parse.output)
    assert e_resolve.output.get("term") == "Hb"
    assert e_resolve.output["status"] == "RESOLVED"
    assert len(e_resolve.output["candidates"]) == 1
    assert e_resolve.output["candidates"][0]["uri"] == "loinc:718-7"

    # 3. Gate
    e_gate = gate(e_resolve.output)
    assert e_gate.actions.route == "PROCEED"
    assert e_gate.output["status"] == "RESOLVED"

    # 4. Fetch
    e_fetch = fetch_node(e_gate.output)
    assert e_fetch.output["resolved_uri"] == "loinc:718-7"
    assert e_fetch.output["reported_unit"] == "g/dL"

    # 5. Synthesis Gate
    e_synth = synthesis_gate_node(e_fetch.output)
    assert e_synth.actions.route == "PROCEED"
    assert e_synth.output["attestation"]["passed"] is True
    assert e_synth.output["attestation"]["badge"] == "[Attested ✓]"


def test_workflow_pipeline_ionized_calcium_qualifier_forwarded():
    """Ionized calcium qualifier must be forwarded so fetch_node retrieves 17864-0."""
    e_parse = parse("Calcium 5.0 | ionized | mg/dL")
    assert e_parse.output["qualifier"] == "ionized"
    assert e_parse.output["unit"] == "mg/dL"

    e_resolve = resolve_node(e_parse.output)
    assert e_resolve.output["term"] == "Calcium"
    assert e_resolve.output["qualifier"] == "ionized"
    assert e_resolve.output["status"] == "RESOLVED"
    assert len(e_resolve.output["candidates"]) == 1
    assert e_resolve.output["candidates"][0]["uri"] == "loinc:17864-0"

    e_gate = gate(e_resolve.output)
    assert e_gate.actions.route == "PROCEED"

    e_fetch = fetch_node(e_gate.output)
    assert e_fetch.output["resolved_uri"] == "loinc:17864-0"
    assert "ionized" in e_fetch.output["concept"]["label"].lower()


def test_workflow_pipeline_total_calcium_qualifier_forwarded():
    """Total calcium qualifier must be forwarded so fetch_node retrieves 17861-6."""
    e_parse = parse("Calcium 9.2 | total | mg/dL")
    e_resolve = resolve_node(e_parse.output)
    assert e_resolve.output["term"] == "Calcium"
    assert e_resolve.output["status"] == "RESOLVED"
    assert e_resolve.output["candidates"][0]["uri"] == "loinc:17861-6"

    e_gate = gate(e_resolve.output)
    assert e_gate.actions.route == "PROCEED"

    e_fetch = fetch_node(e_gate.output)
    assert e_fetch.output["resolved_uri"] == "loinc:17861-6"


def test_workflow_pipeline_unqualified_calcium_routes_to_clarify():
    """Unqualified calcium 'Calcium 4.8 | mg/dL' must route to CLARIFY."""
    e_parse = parse("Calcium 4.8 | mg/dL")
    e_resolve = resolve_node(e_parse.output)
    assert e_resolve.output["term"] == "Calcium"

    e_gate = gate(e_resolve.output)
    assert e_gate.actions.route == "CLARIFY"
    assert e_gate.output["status"] in ("AMBIGUOUS", "RANGE_COLLISION")


# =========================================================================
# 2. Unit-Aware Attestation Tests
# =========================================================================

def test_unit_conversion_helpers():
    """Direct tests for convert_unit and detect_protocol_unit."""
    reg = get_default_registry()
    proto_ca = reg.get_protocol("loinc:17861-6")
    proto_hb = reg.get_protocol("loinc:718-7")

    assert detect_protocol_unit(proto_ca) == "mg/dL"
    assert detect_protocol_unit(proto_hb) == "g/dL"

    # mmol/L -> mg/dL for calcium
    assert pytest.approx(convert_unit(2.4, "mmol/L", "mg/dL"), 0.01) == 9.6192
    # g/L -> g/dL for hemoglobin
    assert pytest.approx(convert_unit(135.0, "g/L", "g/dL"), 0.01) == 13.5


def test_attestation_normal_calcium_mmol():
    """Normal total calcium of 2.4 mmol/L must pass without panic flag."""
    res = attest_computation(2.4, "loinc:17861-6", unit="mmol/L")
    assert res["passed"] is True
    assert res["is_panic"] is False
    assert res["badge"] == "[Attested ✓]"
    assert res["status"] == "PASS"


def test_attestation_critical_high_calcium_mmol():
    """Critically high total calcium of 3.5 mmol/L (~14 mg/dL) must trigger panic."""
    res = attest_computation(3.5, "loinc:17861-6", unit="mmol/L")
    assert res["passed"] is True
    assert res["is_panic"] is True
    assert res["badge"] == "[Attested ✓]"


def test_attestation_normal_hb_grams_per_liter():
    """Normal Hb of 135 g/L (13.5 g/dL) must pass within expected_max 25.0."""
    res = attest_computation(135.0, "loinc:718-7", unit="g/L")
    assert res["passed"] is True
    assert res["is_panic"] is False
    assert res["badge"] == "[Attested ✓]"


def test_attestation_extreme_hb_grams_per_liter_rejected():
    """Extreme Hb of 300 g/L (30.0 g/dL) must exceed expected_max 25.0."""
    res = attest_computation(300.0, "loinc:718-7", unit="g/L")
    assert res["passed"] is False
    assert res["status"] == "FAIL"
    assert "exceeds expected maximum" in res["message"]


# =========================================================================
# 3. Parser Alignment Tests (workflow.parse vs parse_clinician_input)
# =========================================================================

@pytest.mark.parametrize(
    "raw_input,expected_term,expected_val,expected_qualifier,expected_unit",
    [
        ("25-OH vitamin D 18", "25-OH vitamin D", 18.0, "", ""),
        ("Hb -13.5 | g/dL", "Hb", -13.5, "", "g/dL"),
        ("Calcium 4,8 | mg/dL", "Calcium", 4.8, "", "mg/dL"),
        ("Calcium 5.0 | ionized | mg/dL", "Calcium", 5.0, "ionized", "mg/dL"),
        ("Calcium 9.2 | total | mg/dL", "Calcium", 9.2, "total", "mg/dL"),
    ],
)
def test_parser_parity_between_workflow_and_a2a(
    raw_input, expected_term, expected_val, expected_qualifier, expected_unit
):
    """Both parsers must extract identical tokens across challenging clinical inputs."""
    wf_out = parse(raw_input).output
    a2a_out = parse_clinician_input(raw_input).output

    assert wf_out["term"] == expected_term
    assert a2a_out["term"] == expected_term

    assert wf_out["patient_value"] == expected_val
    assert a2a_out["patient_value"] == expected_val

    assert wf_out["qualifier"] == expected_qualifier
    assert a2a_out["qualifier"] == expected_qualifier

    assert wf_out["unit"] == expected_unit
    assert a2a_out["unit"] == expected_unit


def test_ambiguous_thousands_parity():
    """Both parsers must flag ambiguous thousands separators."""
    raw = "Troponin 1,250 | ng/L"
    wf_out = parse(raw).output
    a2a_out = parse_clinician_input(raw).output

    assert wf_out["ambiguous_thousands"] is True
    assert a2a_out["ambiguous_thousands"] is True
    assert wf_out["patient_value"] is None
    assert a2a_out["patient_value"] is None


# =========================================================================
# 4. Tracked Log File Protection Test
# =========================================================================

def test_tracked_knowledge_log_is_not_modified_by_suite():
    """Verify that synthesis_gate_node writes to redirected OKF log, not repo log.md."""
    # Read repo root log.md mtime or content
    repo_log = Path(__file__).resolve().parent.parent.parent / "knowledge" / "log.md"
    content_before = repo_log.read_text(encoding="utf-8") if repo_log.exists() else ""

    # Exercise node that logs concept update
    e_parse = parse("Hb 13.5 | g/dL")
    e_res = resolve_node(e_parse.output)
    e_gate = gate(e_res.output)
    e_fetch = fetch_node(e_gate.output)
    e_synth = synthesis_gate_node(e_fetch.output)

    assert e_synth.actions.route == "PROCEED"

    # Repo log must not have been modified
    content_after = repo_log.read_text(encoding="utf-8") if repo_log.exists() else ""
    assert content_before == content_after
