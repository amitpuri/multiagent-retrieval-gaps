"""
Deterministic safety gate invariant tests — no LLM calls, no API keys required.
Tests all Gap 2/5/8/9/11 safety invariants using the plain Python tool functions.

Run: python -m pytest tests/test_gate.py -v
"""
import sys
from pathlib import Path

# Ensure agent-framework and repo root on sys.path
_agent_framework_dir = Path(__file__).resolve().parent.parent
_repo_root = _agent_framework_dir.parent
for p in (str(_repo_root), str(_agent_framework_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
from src.tools.parse_tool import parse_clinician_input
from src.tools.ontology_tool import resolve_ontology
from src.tools.safety_gate_tool import run_safety_gate
from src.tools.clarification_tool import build_clarification_prompt
from src.tools.csf_tool import csf_workup


# ── Core routing invariants ────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected_status,expected_route", [
    # Gap 2 — Unit mismatch: Hb in mg/dL is wrong
    ("Hb 13.5 | mg/dL",    "UNIT_MISMATCH", "CLARIFY"),
    # Gap 8 — Ambiguity: no unit provided
    ("Hb 13.5",             "AMBIGUOUS",     "CLARIFY"),
    # Happy path: Hb with correct unit resolves
    ("Hb 13.5 | g/dL",     "RESOLVED",      "PROCEED"),
    # Gap 8 — Calcium unqualified: two LOINC concepts → AMBIGUOUS route (fail-closed)
    ("Calcium 4.8 | mg/dL", "AMBIGUOUS",    "CLARIFY"),
    # NOTE: Troponin tests require scenario D extension YAML to be loaded first.
    # They are covered in test_offline_pipeline.py::test_scenario_d_*
])
def test_gate_routing(raw, expected_status, expected_route):
    """Safety gate must correctly route each clinical query."""
    parsed = parse_clinician_input(raw)
    resolved = resolve_ontology(
        term=parsed["term"],
        unit=parsed["unit"],
        qualifier=parsed["qualifier"],
        patient_value=parsed["patient_value"],
    )
    gate = run_safety_gate(
        term=resolved["term"],
        unit=resolved["unit"],
        qualifier=resolved["qualifier"],
        patient_value=resolved["patient_value"],
        status=resolved["status"],
    )
    assert gate["route"] == expected_route, (
        f"Expected route={expected_route}, got {gate['route']} for query='{raw}'"
    )
    assert gate["status"] == expected_status, (
        f"Expected status={expected_status}, got {gate['status']} for query='{raw}'"
    )


# ── Gap 9 — Safety gate is never bypassed ─────────────────────────────────────

def test_gate_never_bypassed_on_unit_mismatch():
    """Unit mismatch MUST route to CLARIFY — never proceed to synthesis (Gap 9)."""
    parsed = parse_clinician_input("Hb 13.5 | mg/dL")
    resolved = resolve_ontology(**{k: parsed[k] for k in ("term", "unit", "qualifier", "patient_value")})
    gate = run_safety_gate(**{k: resolved[k] for k in ("term", "unit", "qualifier", "patient_value")}, status=resolved["status"])
    assert gate["route"] == "CLARIFY"
    assert gate["passed"] is False


def test_gate_never_bypassed_on_ambiguous():
    """Ambiguous query MUST route to CLARIFY — never proceed to synthesis (Gap 9)."""
    parsed = parse_clinician_input("Calcium 4.8")
    resolved = resolve_ontology(**{k: parsed[k] for k in ("term", "unit", "qualifier", "patient_value")})
    gate = run_safety_gate(**{k: resolved[k] for k in ("term", "unit", "qualifier", "patient_value")}, status=resolved["status"])
    assert gate["route"] == "CLARIFY"


def test_gate_fails_closed_on_empty_payload():
    """Malformed/empty payload must route to CLARIFY — fail closed (Gap 9)."""
    gate = run_safety_gate(term="", unit="", qualifier="", patient_value=None, status="UNKNOWN")
    assert gate["route"] == "CLARIFY"


# ── Parse tool correctness ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,exp_term,exp_unit,exp_qualifier,exp_value", [
    ("Hb 13.5 | g/dL",    "Hb",      "g/dL",  "",       13.5),
    ("Hb 13.5",            "Hb",      "",      "",       13.5),
    ("Hb",                 "Hb",      "",      "",       None),
    ("Calcium 4.8 | total","Calcium", "",      "total",  4.8),
    ("Calcium 4.8 | ionized","Calcium","",     "ionized",4.8),
])
def test_parse_tool(raw, exp_term, exp_unit, exp_qualifier, exp_value):
    result = parse_clinician_input(raw)
    assert result["term"] == exp_term
    assert result["unit"] == exp_unit
    assert result["qualifier"] == exp_qualifier
    assert result["patient_value"] == exp_value


# ── Clarification builder ──────────────────────────────────────────────────────

def test_clarification_prompt_ambiguous():
    result = build_clarification_prompt(
        status="AMBIGUOUS",
        candidates=[{"label": "Hemoglobin"}, {"label": "HbA1c"}],
        term="Hb",
    )
    assert result["requires_clarification"] is True
    assert "Ambiguity" in result["clarification_prompt"]
    assert "Hemoglobin" in result["clarification_prompt"]


def test_clarification_prompt_collision():
    result = build_clarification_prompt(
        status="RANGE_COLLISION",
        candidates=[{"label": "Total Calcium"}, {"label": "Ionized Calcium"}],
        term="Calcium",
        collision_details={"readings": {"Total Calcium": "Normal", "Ionized Calcium": "Critical Low"}},
    )
    assert "Range collision" in result["clarification_prompt"] or "collision" in result["clarification_prompt"].lower()


# ── Scenario B: CSF Emergency Panel Workup (Gap 11) ───────────────────────────

def test_csf_workup_grouping_and_tube_order():
    workup = csf_workup()
    assert "Clinical Biochemistry" in workup
    assert "Microbiology" in workup
    assert "Hematology" in workup

    for item in workup["Clinical Biochemistry"]:
        assert item["tube"] == 1
    for item in workup["Microbiology"]:
        assert item["tube"] == 2
    for item in workup["Hematology"]:
        assert item["tube"] == 3


def test_csf_workup_scoped_by_department():
    hemat_workup = csf_workup("hemat")
    assert list(hemat_workup.keys()) == ["Hematology"]
    assert len(hemat_workup["Hematology"]) == 2
    assert hemat_workup["Hematology"][0]["tube"] == 3


def test_csf_workup_unknown_department():
    res = csf_workup("radiology")
    assert res == {"status": "NOT_FOUND"}


# ── A2A message schema ─────────────────────────────────────────────────────────

def test_parse_emits_a2a_message():
    result = parse_clinician_input("Hb 13.5 | g/dL")
    msg = result["a2a_triage_message"]
    assert msg["sender"] == "triage_orchestrator"
    assert msg["recipient"] == "ontology_resolver_agent"
    assert msg["action"] == "PARSE_REQUEST"


def test_ontology_emits_a2a_message():
    result = resolve_ontology(term="Hb", unit="g/dL")
    msg = result["a2a_message"]
    assert msg["sender"] == "ontology_resolver_agent"
    assert msg["recipient"] == "safety_guard_agent"
    assert msg["action"] == "RESOLVE_CONCEPT"


# ── YAML agent files parseable ─────────────────────────────────────────────────

def test_all_agent_yamls_parse():
    """All 6 declarative agent YAML files must parse without error."""
    import yaml
    agent_dir = _agent_framework_dir / "declarative-agents"
    yaml_files = list(agent_dir.glob("*.yaml"))
    assert len(yaml_files) >= 6, f"Expected >=6 agent YAMLs, found {len(yaml_files)}"
    for f in yaml_files:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert data.get("kind") == "Prompt", f"{f.name}: missing or wrong 'kind'"
        assert data.get("name"), f"{f.name}: missing 'name'"
        assert data.get("instructions"), f"{f.name}: missing 'instructions'"


def test_safety_guard_yaml_has_gate_tool():
    """safety_guard.yaml must declare run_safety_gate as a tool."""
    import yaml
    f = _agent_framework_dir / "declarative-agents" / "safety_guard.yaml"
    data = yaml.safe_load(f.read_text(encoding="utf-8"))
    tool_names = [t.get("name") for t in data.get("tools", [])]
    assert "run_safety_gate" in tool_names


def test_triage_yaml_has_all_tools():
    """triage_orchestrator.yaml must declare all 5 tool functions."""
    import yaml
    f = _agent_framework_dir / "declarative-agents" / "triage_orchestrator.yaml"
    data = yaml.safe_load(f.read_text(encoding="utf-8"))
    tool_names = {t.get("name") for t in data.get("tools", [])}
    expected = {"parse_clinician_input", "resolve_ontology", "run_safety_gate",
                "fetch_protocol", "build_clarification_prompt"}
    assert expected == tool_names


# ── Workflow YAML parseable ────────────────────────────────────────────────────

def test_workflow_yaml_parses():
    """clinical_decision_workflow.yaml must parse and contain InvokeAgent + If actions."""
    import yaml
    f = _agent_framework_dir / "declarative-workflows" / "clinical_decision_workflow.yaml"
    data = yaml.safe_load(f.read_text(encoding="utf-8"))
    assert data.get("name") == "clinical-decision-workflow"
    kinds = [a.get("kind") for a in data.get("actions", [])]
    assert "InvokeAgent" in kinds
    assert "If" in kinds
