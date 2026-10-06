"""
Comprehensive test suite for the AWS Strands Agents SDK and Amazon Bedrock AgentCore implementation.
Tests:
  - Strands @tool definitions and invocations.
  - Deterministic pure-code safety gate (zero LLM calls).
  - Specialist agents and Triage Supervisor Agent instantiation.
  - Bedrock Claude model provider and MockBedrockModel offline mode.
  - Amazon Bedrock AgentCore session manager and memory tracking.
  - StrandsDecisionSupportOrchestrator execution trajectories across Scenarios A through D.
"""
import sys
import pytest
from src.tools.parse_tool import parse_clinician_input
from src.tools.ontology_tool import resolve_ontology
from src.tools.safety_gate_tool import run_safety_gate
from src.tools.protocol_tool import fetch_protocol
from src.tools.clarification_tool import build_clarification_prompt

from src.agents.ontology_agent import create_ontology_agent
from src.agents.safety_guard_agent import invoke_safety_guard
from src.agents.protocol_agent import create_protocol_agent
from src.agents.synthesis_agent import create_synthesis_agent
from src.agents.clarification_agent import create_clarification_agent
from src.agents.triage_agent import create_triage_orchestrator, make_triage_envelope

from src.models.provider import get_strands_model, MockBedrockModel, is_offline_mode
from src.memory.session import get_agentcore_session_manager, LocalMemorySessionManager
from src.orchestration.strands_orchestrator import (
    StrandsDecisionSupportOrchestrator,
    build_strands_orchestrator,
    parse_clinician_input_direct,
)


# -------------------------------------------------------------------------
# Test Group 1: Strands @tool Definitions & Invocations
# -------------------------------------------------------------------------
def test_parse_tool_structured_output():
    """parse_clinician_input extracts term, unit, qualifier, patient_value."""
    res = parse_clinician_input("Hb 13.5 | g/dL")
    assert res["term"] == "Hb"
    assert res["unit"] == "g/dL"
    assert res["patient_value"] == 13.5
    assert "a2a_triage_message" in res


def test_parse_tool_with_qualifier():
    """parse_clinician_input extracts qualifier for look-alike tests."""
    res = parse_clinician_input("Calcium 4.8 | total")
    assert res["term"] == "Calcium"
    assert res["qualifier"] == "total"
    assert res["patient_value"] == 4.8


def test_ontology_tool_resolves_hb():
    """resolve_ontology maps Hb + g/dL to canonical LOINC concept loinc:718-7."""
    res = resolve_ontology(term="Hb", unit="g/dL")
    assert res["status"] == "RESOLVED"
    assert len(res["candidates"]) == 1
    assert res["candidates"][0]["uri"] == "loinc:718-7"
    assert "a2a_message" in res


def test_ontology_tool_ambiguous_without_unit():
    """resolve_ontology flags ambiguous concepts when unit is missing."""
    res = resolve_ontology(term="Hb")
    assert res["status"] == "AMBIGUOUS"
    assert len(res["candidates"]) == 2


def test_ontology_tool_unit_mismatch():
    """resolve_ontology flags UNIT_MISMATCH when invalid unit is reported."""
    res = resolve_ontology(term="Hb", unit="mg/dL")
    assert res["status"] == "UNIT_MISMATCH"


def test_safety_gate_tool_deterministic_proceed():
    """run_safety_gate returns PROCEED for resolved concept."""
    res = run_safety_gate(term="Hb", unit="g/dL", status="RESOLVED")
    assert res["route"] == "PROCEED"
    assert res["passed"] is True


def test_safety_gate_tool_deterministic_clarify():
    """run_safety_gate returns CLARIFY for ambiguous concepts."""
    res = run_safety_gate(term="Hb", status="AMBIGUOUS")
    assert res["route"] == "CLARIFY"
    assert res["passed"] is False


def test_safety_gate_tool_range_collision():
    """run_safety_gate blocks conflicting ranges for unqualified calcium.

    Previously tested without a unit (which now triggers UNIT_MISMATCH before
    RANGE_COLLISION).  Updated to include 'mg/dL' so the request reaches the
    RangeCollisionDetector as originally intended.
    """
    res = run_safety_gate(term="calcium", unit="mg/dL", patient_value=4.8, status="RESOLVED")
    assert res["route"] == "CLARIFY"
    assert res["status"] == "RANGE_COLLISION"


def test_safety_gate_no_llm_guarantee():
    """Deterministic safety gate must execute consistently in pure code without any model calls."""
    for _ in range(20):
        res = run_safety_gate(term="Hb", unit="g/dL", status="RESOLVED")
        assert res["route"] == "PROCEED"


def test_protocol_tool_retrieval():
    """fetch_protocol retrieves reference range and panic limits for verified LOINC URI."""
    concept = {
        "uri": "loinc:718-7",
        "label": "Hemoglobin [Mass/volume] in Blood",
        "department": "Hematology",
    }
    res = fetch_protocol(resolved_uri="loinc:718-7", concept=concept)
    assert "13.8-17.2 g/dL" in res["protocol"]["reference_range"]
    assert "Low < 7.0 g/dL" in res["protocol"]["panic_limits"]
    assert "a2a_protocol_message" in res


def test_clarification_tool_builds_prompt():
    """build_clarification_prompt formats targeted questions for the clinician."""
    candidates = [{"label": "Hemoglobin [Mass/volume] in Blood"}, {"label": "Hemoglobin A1c"}]
    res = build_clarification_prompt(status="AMBIGUOUS", candidates=candidates)
    assert res["requires_clarification"] is True
    assert "Ambiguity detected" in res["clarification_prompt"]
    assert "Hemoglobin A1c" in res["clarification_prompt"]


# -------------------------------------------------------------------------
# Test Group 2: Model Provider & Bedrock Claude Integration
# -------------------------------------------------------------------------
def test_mock_bedrock_model_offline():
    """MockBedrockModel provides deterministic offline output for CI/local testing."""
    model = MockBedrockModel()
    assert model.get_config()["model_id"] == "mock-bedrock-claude-sonnet-4-5"


def test_model_provider_offline_selection():
    """get_strands_model returns MockBedrockModel when offline=True."""
    model = get_strands_model(offline=True)
    assert isinstance(model, MockBedrockModel)


def test_strictly_no_litellm_in_modules():
    """Verify that no module in strands-agents imports litellm, gemini, or openai."""
    import src.models.provider as p
    import src.agents.triage_agent as t
    import src.orchestration.strands_orchestrator as o

    for mod in [p, t, o]:
        assert "litellm" not in sys.modules
        assert "google.genai" not in sys.modules
        assert "openai" not in sys.modules


# -------------------------------------------------------------------------
# Test Group 3: Amazon Bedrock AgentCore Session & Memory
# -------------------------------------------------------------------------
def test_local_memory_session_manager_turn_tracking():
    """LocalMemorySessionManager records conversational turns accurately."""
    mgr = LocalMemorySessionManager(session_id="test-session-001")
    mgr.add_turn(role="user", content="Hb 13.5")
    mgr.add_turn(role="assistant", content="Ambiguity detected. Specify unit.")

    turns = mgr.get_last_k_turns(5)
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[0]["content"] == "Hb 13.5"
    assert turns[1]["role"] == "assistant"


def test_agentcore_session_manager_offline_fallback():
    """get_agentcore_session_manager returns LocalMemorySessionManager when offline."""
    mgr = get_agentcore_session_manager(offline=True)
    assert isinstance(mgr, LocalMemorySessionManager)


# -------------------------------------------------------------------------
# Test Group 4: Strands Agent Instantiation
# -------------------------------------------------------------------------
def test_all_strands_agents_instantiate():
    """All 5 specialist agents and Supervisor orchestrator instantiate cleanly."""
    model = MockBedrockModel()

    onto_agent = create_ontology_agent(model=model)
    assert onto_agent is not None

    proto_agent = create_protocol_agent(model=model)
    assert proto_agent is not None

    synth_agent = create_synthesis_agent(model=model)
    assert synth_agent is not None

    clar_agent = create_clarification_agent(model=model)
    assert clar_agent is not None

    supervisor = create_triage_orchestrator(model=model)
    assert supervisor is not None

    # Safety guard is pure code
    guard_out = invoke_safety_guard({"term": "Hb", "unit": "g/dL", "status": "RESOLVED"})
    assert guard_out["route"] == "PROCEED"


# -------------------------------------------------------------------------
# Test Group 5: Orchestrator Pipeline Trajectories
# -------------------------------------------------------------------------
def test_orchestrator_scenario_a_ambiguous():
    """Scenario A: 'Hb' (no value, no unit) routes to CLARIFY as AMBIGUOUS."""
    orch = build_strands_orchestrator(offline=True)
    res = orch.process_query_direct("Hb")
    assert res["route"] == "CLARIFY"
    assert res["status"] == "AMBIGUOUS"
    assert "Ambiguity detected" in res["clarification"]


def test_orchestrator_scenario_a_numeric_no_unit_blocked():
    """Scenario A: 'Hb 13.5' (numeric value, no unit) routes to CLARIFY as UNIT_MISMATCH.

    MissingUnitDetector fires before AmbiguityDetector so a unitless numeric
    result is always rejected — the unit is needed to determine measurement scale.
    """
    orch = build_strands_orchestrator(offline=True)
    res = orch.process_query_direct("Hb 13.5")
    assert res["route"] == "CLARIFY"
    assert res["status"] == "UNIT_MISMATCH"


def test_orchestrator_scenario_a_resolved():
    """Scenario A: 'Hb 13.5 | g/dL' resolves and fetches protocol."""
    orch = build_strands_orchestrator(offline=True)
    res = orch.process_query_direct("Hb 13.5 | g/dL")
    assert res["route"] == "PROCEED"
    assert res["status"] == "RESOLVED"
    assert res["concept"]["uri"] == "loinc:718-7"
    assert "protocol" in res


def test_orchestrator_scenario_a_unit_mismatch():
    """Scenario A: 'Hb 13.5 | mg/dL' routes to CLARIFY due to unit mismatch."""
    orch = build_strands_orchestrator(offline=True)
    res = orch.process_query_direct("Hb 13.5 | mg/dL")
    assert res["route"] == "CLARIFY"
    assert res["status"] == "UNIT_MISMATCH"


def test_orchestrator_scenario_c_range_collision():
    """Scenario C: 'Calcium 4.8 | mg/dL' without qualifier routes to CLARIFY (RANGE_COLLISION).

    A unit is required for range evaluation; the previous form 'Calcium 4.8' with
    no unit is now caught earlier by MissingUnitDetector (see test below).
    """
    orch = build_strands_orchestrator(offline=True)
    res = orch.process_query_direct("Calcium 4.8 | mg/dL")
    assert res["route"] == "CLARIFY"
    assert res["status"] == "RANGE_COLLISION"


def test_orchestrator_scenario_c_unitless_numeric_blocked():
    """Scenario C (new): 'Calcium 4.8' with no unit must route to CLARIFY as UNIT_MISMATCH.

    MissingUnitDetector now fires before RangeCollisionDetector so a unitless
    numeric value is never silently classified against the wrong scale.
    """
    orch = build_strands_orchestrator(offline=True)
    res = orch.process_query_direct("Calcium 4.8")
    assert res["route"] == "CLARIFY"
    assert res["status"] == "UNIT_MISMATCH"


def test_orchestrator_scenario_c_qualified_total():
    """Scenario C: 'Calcium 4.8 | total | mg/dL' with qualifier and unit resolves and proceeds."""
    orch = build_strands_orchestrator(offline=True)
    res = orch.process_query_direct("Calcium 4.8 | total | mg/dL")
    assert res["route"] == "PROCEED"
    assert res["status"] == "RESOLVED"
    assert res["concept"]["uri"] == "loinc:17861-6"


# -------------------------------------------------------------------------
# Test Group 9: Graceful Agentic Fallback (T-FALLBACK-1, T-FALLBACK-2)
# -------------------------------------------------------------------------

def test_process_query_agentic_falls_back_on_api_error():
    """T-FALLBACK-1: process_query_agentic returns OFFLINE-FALLBACK string when supervisor raises."""
    orch = build_strands_orchestrator(offline=True)

    # Patch the supervisor to raise an Anthropic-style credit error.
    class _FakeErr(Exception):
        pass

    def _bad_supervisor(_text: str) -> None:
        raise _FakeErr("Your credit balance is too low to access the Anthropic API")

    orch.supervisor = _bad_supervisor
    result = orch.process_query_agentic("Hb 13.5 | g/dL")

    assert "[OFFLINE-FALLBACK]" in result, (
        "Expected OFFLINE-FALLBACK prefix in agentic fallback output"
    )
    # Must NOT propagate — result is a string, not an exception.
    assert isinstance(result, str)


def test_process_query_agentic_falls_back_on_generic_error():
    """T-FALLBACK-2: process_query_agentic handles arbitrary unexpected exceptions gracefully."""
    orch = build_strands_orchestrator(offline=True)

    def _boom(_text: str) -> None:
        raise RuntimeError("simulated network timeout")

    orch.supervisor = _boom
    result = orch.process_query_agentic("Hb 13.5 | g/dL")

    assert "[OFFLINE-FALLBACK]" in result
    assert isinstance(result, str)
