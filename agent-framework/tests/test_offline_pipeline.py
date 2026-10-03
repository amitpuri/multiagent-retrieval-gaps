"""
Offline pipeline integration tests — run the full deterministic pipeline
without any API calls using the _offline_pipeline fast-path.

Run: python -m pytest tests/test_offline_pipeline.py -v
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

from src.orchestration.workflow_runner import run_scenario, _offline_pipeline


# ── Helper: run async fn synchronously in tests ────────────────────────────────
def _run(coro):
    return anyio.from_thread.run_sync(lambda: anyio.run(coro))


def _run_async(coro):
    """Run a coroutine synchronously for test assertions."""
    return anyio.run(lambda: coro)


# ── Scenario A — Hemoglobin ────────────────────────────────────────────────────

def test_scenario_a_ambiguous():
    """Hb without unit → CLARIFY (Gap 8 — ambiguity)."""
    result = _offline_pipeline("Hb 13.5")
    assert result["route"] == "CLARIFY", f"Expected CLARIFY, got {result['route']}"


def test_scenario_a_unit_mismatch():
    """Hb in mg/dL → CLARIFY (Gap 2 — unit mismatch)."""
    result = _offline_pipeline("Hb 13.5 | mg/dL")
    assert result["route"] == "CLARIFY"
    assert result["status"] == "UNIT_MISMATCH"


def test_scenario_a_resolves():
    """Hb with correct unit g/dL → PROCEED."""
    result = _offline_pipeline("Hb 13.5 | g/dL")
    assert result["route"] == "PROCEED"
    assert result["status"] == "RESOLVED"


# ── Scenario C — Calcium ───────────────────────────────────────────────────────

def test_scenario_c_ambiguous():
    """Calcium 4.8 mg/dL unqualified → CLARIFY (two LOINC concepts, Gap 8)."""
    result = _offline_pipeline("Calcium 4.8 | mg/dL")
    assert result["route"] == "CLARIFY"


# ── Scenario D — Troponin (NOT_FOUND without extension — still CLARIFY) ────────

def test_scenario_d_not_found_still_clarify():
    """Troponin without scenario extension → NOT_FOUND → still routed CLARIFY (fail-closed)."""
    result = _offline_pipeline("Troponin 15")
    assert result["route"] == "CLARIFY", \
        "NOT_FOUND must route CLARIFY — fail-closed invariant (Gap 9)"


def test_scenario_d_unit_mismatch_still_clarify():
    """Troponin with wrong unit and no extension → CLARIFY."""
    result = _offline_pipeline("Troponin 15 | mg/dL")
    assert result["route"] == "CLARIFY"


# ── Result schema invariants ───────────────────────────────────────────────────

def test_result_always_has_route():
    """Every pipeline result must have a 'route' key."""
    for query in ["Hb 13.5", "Hb 13.5 | g/dL", "Calcium 4.8 | mg/dL"]:
        result = _offline_pipeline(query)
        assert "route" in result, f"No 'route' key for query='{query}'"
        assert result["route"] in ("PROCEED", "CLARIFY"), \
            f"route must be PROCEED or CLARIFY, got {result['route']}"


def test_clarify_has_clarification_field():
    """CLARIFY results must include a clarification message."""
    result = _offline_pipeline("Hb 13.5")
    assert result["route"] == "CLARIFY"
    assert result.get("clarification") or result.get("output"), \
        "CLARIFY result missing clarification message"


def test_proceed_has_protocol():
    """PROCEED results must include protocol or output."""
    result = _offline_pipeline("Hb 13.5 | g/dL")
    assert result["route"] == "PROCEED"
    assert "protocol" in result or "output" in result


# ── Gate never bypassed for PROCEED when status != RESOLVED ────────────────────

def test_proceed_only_on_resolved():
    """PROCEED must only occur when status == RESOLVED."""
    for query in ["Hb 13.5", "Hb 13.5 | mg/dL", "Calcium 4.8 | mg/dL"]:
        result = _offline_pipeline(query)
        if result["route"] == "PROCEED":
            assert result["status"] == "RESOLVED", \
                f"PROCEED with non-RESOLVED status '{result['status']}' for '{query}'"
