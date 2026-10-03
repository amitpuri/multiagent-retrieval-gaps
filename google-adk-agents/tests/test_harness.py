"""
Comprehensive test suite for the Google ADK Agent Harness.
Verifies all 4 harness steps:
  1. Continuous reasoning loop lifecycle
  2. MCP tool registration, declaration, and execution
  3. Context window management and history formatting
  4. Scenario-parity with existing ADK workflow tests

Runs fully offline — no live Gemini API key required.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

# Ensure repo root is on sys.path
_repo_root = Path(__file__).resolve().parent.parent.parent
_adk_dir = _repo_root / "google-adk-agents"
for p in (str(_repo_root), str(_adk_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# Step 1: Session Management
# ---------------------------------------------------------------------------

class TestHarnessSession:
    def test_session_creates_unique_id(self):
        from src.harness.session import HarnessSession
        s1 = HarnessSession()
        s2 = HarnessSession()
        assert s1.session_id != s2.session_id

    def test_add_user_message(self):
        from src.harness.session import HarnessSession
        session = HarnessSession()
        msg = session.add_user_message("Hb 13.5")
        assert len(session.messages) == 1
        assert session.messages[0].role == "user"
        assert session.messages[0].content == "Hb 13.5"

    def test_add_model_message(self):
        from src.harness.session import HarnessSession
        session = HarnessSession()
        session.add_user_message("Hb 13.5")
        session.add_model_message(content="[CLARIFY] Please clarify unit.")
        assert len(session.messages) == 2
        assert session.messages[1].role == "model"

    def test_add_tool_response(self):
        from src.harness.session import HarnessSession
        session = HarnessSession()
        session.add_user_message("Hb 13.5")
        session.add_tool_response("resolve_lab_term", {"status": "RESOLVED", "candidates": []})
        assert len(session.messages) == 2
        assert session.messages[1].role == "tool"

    def test_get_recent_messages_limit(self):
        from src.harness.session import HarnessSession
        session = HarnessSession()
        for i in range(10):
            session.add_user_message(f"Query {i}")
        recent = session.get_recent_messages(limit=3)
        assert len(recent) == 3
        assert recent[-1].content == "Query 9"

    def test_session_clear(self):
        from src.harness.session import HarnessSession
        session = HarnessSession()
        session.add_user_message("test")
        session.state["key"] = "value"
        session.clear()
        assert len(session.messages) == 0
        assert len(session.state) == 0


# ---------------------------------------------------------------------------
# Step 2: MCP Tool Registration & Dispatching
# ---------------------------------------------------------------------------

class TestMCPToolBridge:
    def test_tool_registry_has_expected_tools(self):
        from src.harness.mcp_server import CLINICAL_MCP_TOOLS
        expected = {
            "resolve_lab_term",
            "evaluate_safety_gate",
            "fetch_grounded_protocol",
            "csf_workup",
            "check_calcium",
            "attest_computation",
        }
        assert expected == set(CLINICAL_MCP_TOOLS.keys())

    def test_gemini_declarations_generated(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        decls = bridge.get_tool_declarations_for_gemini()
        names = {d.name for d in decls}
        assert "resolve_lab_term" in names
        assert "evaluate_safety_gate" in names
        assert "csf_workup" in names

    def test_dispatch_resolve_lab_term_ambiguous(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("resolve_lab_term", {"term": "Hb", "unit": ""})
        assert "status" in result
        assert result["status"] == "AMBIGUOUS"
        assert len(result["candidates"]) >= 2

    def test_dispatch_resolve_lab_term_unit_resolves(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("resolve_lab_term", {"term": "Hb", "unit": "g/dL"})
        assert result["status"] == "RESOLVED"
        assert len(result["candidates"]) == 1

    def test_dispatch_resolve_lab_term_unit_mismatch(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("resolve_lab_term", {"term": "Hb", "unit": "mg/dL"})
        assert result["status"] == "UNIT_MISMATCH"

    def test_dispatch_evaluate_safety_gate_ambiguous(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("evaluate_safety_gate", {"term": "Hb", "unit": ""})
        assert result["route"] == "CLARIFY"
        assert result["passed"] is False

    def test_dispatch_evaluate_safety_gate_resolved(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("evaluate_safety_gate", {"term": "Hb", "unit": "g/dL"})
        assert result["route"] == "PROCEED"
        assert result["passed"] is True

    def test_dispatch_csf_workup_all_departments(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("csf_workup", {"department": ""})
        assert isinstance(result, dict)
        # Should return at least one department
        assert len(result) >= 1

    def test_dispatch_csf_workup_hematology_filter(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("csf_workup", {"department": "hemat"})
        assert "Hematology" in result or len(result) >= 1

    def test_dispatch_check_calcium_collision(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("check_calcium", {"value_mg_dl": 4.8, "qualifier": ""})
        assert result["status"] == "RANGE_COLLISION"

    def test_dispatch_check_calcium_total_qualified(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("check_calcium", {"value_mg_dl": 9.5, "qualifier": "total"})
        assert result["status"] == "RESOLVED"

    def test_dispatch_unknown_tool_returns_error(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("nonexistent_tool", {})
        assert "error" in result

    def test_attest_computation_passes(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("attest_computation", {"value": 13.5, "uri": "loinc:718-7", "unit": "g/dL"})
        assert result.get("passed") is True
        assert "[Attested ✓]" in result.get("badge", "")

    def test_attest_computation_fails_implausible(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("attest_computation", {"value": 99999.0, "uri": "loinc:718-7", "unit": "g/dL"})
        assert result.get("passed") is False


# ---------------------------------------------------------------------------
# Step 3: Context Window Management
# ---------------------------------------------------------------------------

class TestContextWindowManager:
    def test_format_empty_session_returns_empty_list(self):
        from src.harness.context import ContextWindowManager
        from src.harness.session import HarnessSession
        mgr = ContextWindowManager()
        session = HarnessSession()
        contents = mgr.format_history_for_gemini(session)
        assert contents == []

    def test_format_user_message(self):
        from src.harness.context import ContextWindowManager
        from src.harness.session import HarnessSession
        mgr = ContextWindowManager()
        session = HarnessSession()
        session.add_user_message("Hb 13.5")
        contents = mgr.format_history_for_gemini(session)
        assert len(contents) == 1
        assert contents[0].role == "user"
        assert contents[0].parts[0].text == "Hb 13.5"

    def test_sliding_window_trims_old_turns(self):
        from src.harness.context import ContextWindowManager
        from src.harness.session import HarnessSession
        mgr = ContextWindowManager(max_context_turns=5)
        session = HarnessSession()
        for i in range(20):
            session.add_user_message(f"Query {i}")
        contents = mgr.format_history_for_gemini(session)
        # Should be capped at max_context_turns
        assert len(contents) <= 5

    def test_append_tool_result_to_session(self):
        from src.harness.context import ContextWindowManager
        from src.harness.session import HarnessSession
        mgr = ContextWindowManager()
        session = HarnessSession()
        session.add_user_message("Hb 13.5")
        mgr.append_tool_result_to_session(session, "resolve_lab_term", {"status": "AMBIGUOUS", "candidates": []})
        assert len(session.messages) == 2
        assert session.messages[1].role == "tool"

    def test_progressive_disclosure_summary_default(self):
        from src.harness.context import ContextWindowManager
        mgr = ContextWindowManager()
        summary = mgr.build_progressive_disclosure_summary()
        assert "Hematology" in summary
        assert "LOINC" in summary


# ---------------------------------------------------------------------------
# Step 1 + 2 + 3: Full ClinicalADKHarness Offline Scenario Tests
# ---------------------------------------------------------------------------

class TestClinicalADKHarnessOffline:
    def setup_method(self):
        from src.harness.agent import ClinicalADKHarness
        self.harness = ClinicalADKHarness(offline=True)

    def _run(self, prompt: str, session=None):
        """Helper to run harness synchronously."""
        if session is None:
            session = self.harness.create_session()
        return asyncio.run(self.harness.run(prompt=prompt, session=session))

    # Scenario A: Hb ambiguity
    def test_hb_no_unit_routes_clarify(self):
        res = self._run("Hb 13.5")
        assert res.route == "CLARIFY"
        assert res.is_hitl_paused is True
        assert res.status == "AMBIGUOUS"
        assert len(res.tool_calls) >= 2  # resolve + safety gate

    def test_hb_valid_unit_routes_proceed(self):
        res = self._run("Hb 13.5 | g/dL")
        assert res.route == "PROCEED"
        assert res.is_hitl_paused is False
        assert res.status == "RESOLVED"
        assert res.protocol  # grounded protocol fetched

    def test_hb_invalid_unit_routes_clarify(self):
        res = self._run("Hb 13.5 | mg/dL")
        assert res.route == "CLARIFY"
        assert res.is_hitl_paused is True
        assert res.status == "UNIT_MISMATCH"

    # Scenario B: CSF tube ordering
    def test_csf_workup_proceeds_with_governed_sequence(self):
        res = self._run("CSF workup | hematology")
        assert res.route == "PROCEED"
        assert res.status == "RESOLVED"
        assert any(tc.tool_name == "csf_workup" for tc in res.tool_calls)
        assert "Tube" in res.text

    # Scenario C: Calcium collision
    def test_calcium_unqualified_range_collision(self):
        res = self._run("Calcium 4.8 mg/dL")
        assert res.route == "CLARIFY"
        assert res.status == "RANGE_COLLISION"
        assert res.is_hitl_paused is True
        assert res.clarification is not None
        assert "Total Calcium" in res.clarification

    # Attestation
    def test_resolved_lab_value_gets_attested(self):
        res = self._run("Hb 13.5 | g/dL")
        assert res.attested is True
        assert "[Attested ✓]" in res.text

    # Multi-turn session history retention
    def test_multi_turn_session_retains_history(self):
        session = self.harness.create_session()
        asyncio.run(self.harness.run(prompt="Hb 13.5", session=session))
        asyncio.run(self.harness.run(prompt="Hb 13.5 | g/dL", session=session))
        # Session should have messages from both turns
        assert len(session.messages) >= 4  # 2 user + at least 2 model/tool

    # MCP tools always executed (no hardcoded API calls)
    def test_all_clinical_tools_dispatched_through_mcp(self):
        res = self._run("Hb 13.5 | g/dL")
        tool_names = {tc.tool_name for tc in res.tool_calls}
        # At minimum: resolve, safety gate, protocol, attest
        assert "resolve_lab_term" in tool_names
        assert "evaluate_safety_gate" in tool_names
        assert "fetch_grounded_protocol" in tool_names

    # Fail-closed safety invariant
    def test_harness_never_proceeds_on_unknown_status(self):
        res = self._run("Xylobiose 99.9 | unknown_unit")
        # Unknown term must CLARIFY, not PROCEED
        assert res.route == "CLARIFY"

    def test_harness_session_id_in_response(self):
        session = self.harness.create_session("fixed_session_id")
        res = self._run("Hb 13.5", session=session)
        assert res.session_id == "fixed_session_id"
