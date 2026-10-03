"""
Unit and integration tests for the Microsoft Agent Framework (MAF) Clinical Harness.
Tests cover:
- Harness agent creation and configuration
- Session state management and history persistence
- Todo provider lifecycle and checklist formatting
- Operating mode provider (PLAN vs EXECUTE)
- Tool approval policy and HITL safeguards
- Deterministic safety gate execution through the harness
- Full scenario execution through the harness
"""
import sys
from pathlib import Path

_agent_framework_dir = Path(__file__).resolve().parent.parent
_repo_root = _agent_framework_dir.parent
for p in (str(_repo_root), str(_agent_framework_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
import anyio

from src.harness import (
    ClinicalHarnessAgent,
    create_clinical_harness_agent,
    HarnessSession,
    AgentMode,
    ClinicalModeProvider,
    ClinicalTodoProvider,
    SafetyGateApprovalPolicy,
    TodoStatus,
)
from src.harness.console import run_scenario_through_harness


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def harness_agent():
    return create_clinical_harness_agent()


@pytest.fixture
def session():
    return HarnessSession()


# ── Initialization & Components ────────────────────────────────────────────────

def test_harness_agent_initialization(harness_agent):
    assert harness_agent.name == "clinical_decision_harness"
    assert "parse_clinician_input" in harness_agent.tools
    assert "resolve_ontology" in harness_agent.tools
    assert "run_safety_gate" in harness_agent.tools
    assert "fetch_protocol" in harness_agent.tools
    assert "build_clarification_prompt" in harness_agent.tools
    assert "csf_workup" in harness_agent.tools
    assert harness_agent.mode_provider.mode == AgentMode.EXECUTE


def test_harness_session_lifecycle(session):
    assert session.session_id.startswith("session_")
    session.add_message(role="user", content="Hb 13.5")
    session.add_message(role="assistant", content="Clarification required")
    history = session.get_history()
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hb 13.5"
    assert history[1]["role"] == "assistant"

    session.set_state("patient_id", "P-12345")
    assert session.get_state("patient_id") == "P-12345"

    session.clear()
    assert len(session.get_history()) == 0
    assert session.get_state("patient_id") is None


def test_harness_todo_provider():
    provider = ClinicalTodoProvider()
    todos = provider.get_todos()
    assert len(todos) == 4
    assert todos[0].status == TodoStatus.PENDING

    provider.mark_in_progress(1)
    assert provider.get_todos()[0].status == TodoStatus.IN_PROGRESS

    provider.mark_completed(1, {"result": "parsed"})
    assert provider.get_todos()[0].status == TodoStatus.COMPLETED

    formatted = provider.format_todos()
    assert "[x] **Step 1**" in formatted
    assert "[ ] **Step 2**" in formatted


def test_harness_mode_provider():
    provider = ClinicalModeProvider(initial_mode=AgentMode.PLAN)
    assert provider.is_plan_mode()
    assert not provider.is_execute_mode()

    provider.set_mode(AgentMode.EXECUTE)
    assert provider.is_execute_mode()
    assert not provider.is_plan_mode()

    provider.set_mode("plan")
    assert provider.is_plan_mode()


def test_harness_approval_policy():
    policy = SafetyGateApprovalPolicy()

    # Standing approvals
    assert policy.check_approval("parse_clinician_input", {})["approved"] is True
    assert policy.check_approval("resolve_ontology", {})["approved"] is True
    assert policy.check_approval("run_safety_gate", {})["approved"] is True

    # Protocol fetching allowed only on validated route
    proceed_check = policy.check_approval("fetch_protocol", {}, context={"gate_route": "PROCEED"})
    assert proceed_check["approved"] is True
    assert proceed_check["requires_hitl"] is False

    clarify_check = policy.check_approval("fetch_protocol", {}, context={"gate_route": "CLARIFY"})
    assert clarify_check["approved"] is False
    assert clarify_check["requires_hitl"] is True


# ── Async Pipeline Executions ──────────────────────────────────────────────────

@pytest.mark.anyio
async def test_harness_run_proceed(harness_agent):
    res = await harness_agent.run("Hb 13.5 | g/dL")
    assert res.route == "PROCEED"
    assert res.status == "RESOLVED"
    assert "protocol" in res.protocol
    assert "Standardized LOINC concept" in res.text
    assert len(res.tool_calls) >= 4  # parse, resolve, gate, fetch_protocol


@pytest.mark.anyio
async def test_harness_run_ambiguous_clarify(harness_agent):
    res = await harness_agent.run("Hb 13.5")
    assert res.route == "CLARIFY"
    assert res.status == "AMBIGUOUS"
    assert res.clarification is not None
    assert "Clarification Required" in res.text


@pytest.mark.anyio
async def test_harness_run_unit_mismatch_clarify(harness_agent):
    res = await harness_agent.run("Hb 13.5 | mg/dL")
    assert res.route == "CLARIFY"
    assert res.status == "UNIT_MISMATCH"
    assert "Safety Gate Intercepted Query" in res.text


@pytest.mark.anyio
async def test_harness_plan_mode_stops_before_protocol(harness_agent):
    res = await harness_agent.run("Hb 13.5 | g/dL", mode=AgentMode.PLAN)
    assert res.mode == AgentMode.PLAN
    assert "[PLAN MODE]" in res.text
    # In plan mode, protocol retrieval should not have run
    tool_names = [call.tool_name for call in res.tool_calls]
    assert "fetch_protocol" not in tool_names


@pytest.mark.anyio
async def test_harness_scenario_c_collision(harness_agent):
    # Unqualified calcium causes look-alike collision -> CLARIFY
    res = await harness_agent.run("Calcium 4.8 | mg/dL")
    assert res.route == "CLARIFY"
    assert res.status in ("AMBIGUOUS", "RANGE_COLLISION")

    # Qualified calcium with total qualifier — AmbiguityDetector does NOT use qualifier
    # to reduce candidates (only unit filtering). Both concepts accept mg/dL so still CLARIFY.
    # This is correct fail-closed Gap 8 behavior: qualifier alone is insufficient disambiguation.
    res_total = await harness_agent.run("Calcium 4.8 | mg/dL | total")
    assert res_total.route == "CLARIFY", (
        "Calcium with qualifier alone still ambiguous — Gap 8 fail-closed invariant. "
        "Qualifier disambiguation requires concept-level qualifier attributes (future extension)."
    )

    # Ionised qualifier similarly stays CLARIFY under current engine
    res_ionized = await harness_agent.run("Calcium 4.8 | mg/dL | ionized")
    assert res_ionized.route == "CLARIFY"


@pytest.mark.anyio
async def test_harness_run_all_scenarios_helper(harness_agent):
    for scen in ["A", "B", "C", "D"]:
        await run_scenario_through_harness(harness_agent, scen)
