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
        # Canonical tool contract (ontogate.tools).
        expected = {
            "parse_clinician_input",
            "resolve_lab_term",
            "evaluate_safety_gate",
            "fetch_grounded_protocol",
            "attest_computation",
            "build_clarification_prompt",
            "panel_workup",
        }
        assert expected == set(CLINICAL_MCP_TOOLS.keys())

    def test_gemini_declarations_generated(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        decls = bridge.get_tool_declarations_for_gemini()
        names = {d.name for d in decls}
        assert "resolve_lab_term" in names
        assert "evaluate_safety_gate" in names
        assert "panel_workup" in names

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

    def test_dispatch_panel_workup_all_departments(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("panel_workup", {"panel": "csf_emergency_panel"})
        assert result["status"] == "RESOLVED"
        assert len(result["tubes"]) == 3

    def test_dispatch_panel_workup_hematology_filter(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("panel_workup", {"panel": "csf_emergency_panel", "department": "hemat"})
        assert [t["department"] for t in result["tubes"]] == ["Hematology"]

    def test_dispatch_gate_calcium_collision(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("evaluate_safety_gate",
                                     {"term": "calcium", "unit": "mg/dL", "patient_value": 4.8})
        assert result["status"] == "RANGE_COLLISION"

    def test_dispatch_gate_calcium_total_qualified(self):
        from src.harness.mcp_client import MCPToolBridge
        bridge = MCPToolBridge()
        result = bridge.execute_tool("evaluate_safety_gate",
                                     {"term": "calcium", "unit": "mg/dL", "qualifier": "total", "patient_value": 9.5})
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
    def test_panel_workup_proceeds_with_governed_sequence(self):
        res = self._run("CSF workup | hematology")
        assert res.route == "PROCEED"
        assert res.status == "RESOLVED"
        assert any(tc.tool_name == "panel_workup" for tc in res.tool_calls)
        assert "Tube" in res.text

    # Scenario C: Calcium collision
    def test_calcium_unqualified_range_collision(self):
        res = self._run("Calcium 4.8 mg/dL")
        assert res.route == "CLARIFY"
        assert res.status == "RANGE_COLLISION"
        assert res.is_hitl_paused is True
        assert res.clarification is not None
        # Clarification is generated from the ontology (display names), not hard-coded text.
        assert "total calcium" in res.clarification.lower()

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


# ─────────────────────────────────────────────────────────────────────────────
# Offline safety behaviour (no Gemini API key required)
# ─────────────────────────────────────────────────────────────────────────────
class TestOfflineSafetyBehaviour:
    """Fail-closed behaviour of the offline harness pipeline."""

    def setup_method(self):
        from src.harness.agent import ClinicalADKHarness
        self.harness = ClinicalADKHarness(offline=True)

    def _run(self, prompt, session=None):
        import asyncio
        return asyncio.run(self.harness.run(prompt=prompt, session=session))

    # ── Panel requests ───────────────────────────────────────────────────────
    def test_panel_with_unit_instead_of_department_clarifies(self):
        """'CSF workup | mg/dL': a unit is not a department filter — fail closed with a HITL pause."""
        res = self._run("CSF workup | mg/dL")
        assert res.route == "CLARIFY", (
            "CSF workup with non-department unit should route to CLARIFY, not crash"
        )
        assert res.is_hitl_paused is True
        assert "mg/dL" in (res.clarification or "") or "department" in (res.clarification or "").lower()

    def test_csf_protein_analyte_resolves_and_proceeds(self):
        """'CSF protein 45 | mg/dL' is a single observable, not a panel: it resolves, gates and attests."""
        res = self._run("CSF protein 45 | mg/dL")
        assert res.route == "PROCEED"
        assert res.attested is True
        assert "loinc:2880-3" in res.text

    def test_csf_with_valid_department_proceeds(self):
        """CSF workup with a valid department filter must still PROCEED."""
        res = self._run("CSF workup | hematology")
        assert res.route == "PROCEED"
        assert res.status == "RESOLVED"

    def test_csf_with_no_department_returns_full_panel(self):
        """CSF workup with no department filter must return the full panel."""
        res = self._run("CSF workup")
        assert res.route == "PROCEED"
        # Should mention at least two departments in the output
        assert res.text.count("Department:") >= 2

    # ── Panic values ─────────────────────────────────────────────────────────
    def test_panic_value_includes_critical_warning_in_output(self):
        """Hb 5.0 g/dL is below the 7.0 g/dL critical limit: the attested answer carries a PANIC warning."""
        res = self._run("Hb 5.0 | g/dL")
        assert res.attested is True
        assert "PANIC" in res.text

    def test_attested_normal_value_has_no_spurious_panic_warning(self):
        """Normal Hb value must not trigger a panic warning."""
        res = self._run("Hb 13.5 | g/dL")
        assert res.route == "PROCEED"
        assert res.attested is True
        assert "PANIC" not in res.text

    # ── Units in look-alike clarifications ───────────────────────────────────
    def test_calcium_mmol_is_classified_in_the_reported_unit(self):
        """'Calcium 4.8 | mmol/L' is read in mmol/L (both fractions critical-high): ask for the fraction."""
        res = self._run("Calcium 4.8 | mmol/L")
        assert res.status == "MISSING_QUALIFIER"
        assert "4.8 mg/dL" not in (res.clarification or "")

    def test_calcium_mmol_collision_shows_reported_unit(self):
        """'Calcium 1.2 | mmol/L' (≈4.8 mg/dL) collides and the clarification names the reported unit."""
        res = self._run("Calcium 1.2 | mmol/L")
        assert res.route == "CLARIFY"
        assert res.status == "RANGE_COLLISION"
        assert "1.2 mmol/L" in (res.clarification or "")

    # ── Qualifier contradictions ─────────────────────────────────────────────
    def test_contradictory_qualifier_is_flagged(self):
        """'ionized calcium' with qualifier 'total' is a contradiction, not a narrowing → AMBIGUOUS."""
        from src.tools import resolve_lab_term
        res = resolve_lab_term(term="ionized calcium", unit="mg/dL", qualifier="total")
        assert res["status"] == "AMBIGUOUS"
        assert "contradiction" in res

    def test_consistent_qualifier_and_term_resolves(self):
        """'ionized calcium' with qualifier 'ionized' resolves cleanly."""
        from src.tools import resolve_lab_term
        res = resolve_lab_term(term="ionized calcium", qualifier="ionized")
        assert res["status"] == "RESOLVED"

    # ── Unknown terms ────────────────────────────────────────────────────────
    def test_unknown_term_clarifies(self):
        """'csfzzz' is not a panel or an observable: the gate returns NOT_FOUND."""
        res = self._run("csfzzz")
        assert res.route == "CLARIFY"
        assert res.status == "NOT_FOUND"

    # ── Thousands separator guard ────────────────────────────────────────────
    def test_ambiguous_thousands_separator_clarifies(self):
        """'Hb 1,250 | g/L' must trigger thousands-separator clarification, not nonsense term."""
        res = self._run("Hb 1,250 | g/L")
        assert res.route == "CLARIFY"
        assert res.status == "AMBIGUOUS"
        assert "thousands separator" in (res.clarification or "").lower()

    # ── Implausible values ───────────────────────────────────────────────────
    def test_negative_value_fails_attestation_and_clarifies(self):
        """'Hb -5 | g/dL' fails attestation and clarifies."""
        res = self._run("Hb -5 | g/dL")
        assert res.route == "CLARIFY"
        assert res.attested is False
        assert "attestation failed" in (res.clarification or "").lower()

    def test_implausible_high_value_fails_attestation_and_clarifies(self):
        """'Hb 140 | g/dL' exceeds the protocol's expected_max (25 g/dL) and clarifies."""
        res = self._run("Hb 140 | g/dL")
        assert res.route == "CLARIFY"
        assert res.attested is False
        assert "attestation failed" in (res.clarification or "").lower()
