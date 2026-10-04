---
name: validate-safety-gate
description: >-
  Validates the deterministic SafetyGateEngine and fail-closed routing invariants.
  Use when asked to "validate the safety gate", "check fail-closed behavior",
  "verify gap detectors", or "test the engine". Runs the pure-code test suite
  and inspects the engine without any LLM calls.
---

# Skill: Validate Safety Gate

## Purpose

The `SafetyGateEngine` is the core deterministic safety component of this repo.
It must always fail-closed — any status except `RESOLVED` must produce a `CLARIFY` route.
This skill validates that invariant end-to-end, from engine internals to the MCP tool surface.

---

## Step 1 — Locate and Inspect the Engine

Open and review these files:

- `google-adk-agents/src/core/detectors/engine.py` — `SafetyGateEngine` class
- `google-adk-agents/src/core/models.py` — `EvaluationContext`, `ResolutionStatus`

Check:
- All registered detectors are enumerated (no hidden/orphaned detectors)
- Each detector returns a typed result with a `passed: bool` and `status: ResolutionStatus`
- `SafetyGateEngine.route_for(status)` covers all `ResolutionStatus` members

```python
# Verify: every non-RESOLVED status maps to CLARIFY
from src.core.models import ResolutionStatus
from src.core.detectors.engine import SafetyGateEngine

engine = SafetyGateEngine()
for status in ResolutionStatus:
    expected = "PROCEED" if status == ResolutionStatus.RESOLVED else "CLARIFY"
    assert engine.route_for(status) == expected, f"FAIL: {status} → wrong route"
```

---

## Step 2 — Validate the Routing Entrypoint

Open `google-adk-agents/src/workflow.py` and verify `route_for()`:

```python
from src.workflow import route_for

assert route_for("RESOLVED") == "PROCEED"
for s in ("AMBIGUOUS", "UNIT_MISMATCH", "NOT_FOUND", "RANGE_COLLISION", "UNKNOWN"):
    assert route_for(s) == "CLARIFY", f"FAIL: {s} should CLARIFY"
```

---

## Step 3 — Validate `safety_guard_node`

Open `google-adk-agents/src/agents/safety_guard_agent.py` and confirm:

1. No `await`, `async`, or model/LLM calls anywhere in the function body
2. All three branches (pre-existing failure, engine failure, pass) emit an `A2AMessage`
3. The function returns `Event(output=node_input, route=route)` in all branches

---

## Step 4 — Validate the MCP Surface

Open `google-adk-agents/src/harness/mcp_server.py` and check `evaluate_safety_gate`:

- Calls the same `SafetyGateEngine` (not a separate copy)
- Returns `route: "PROCEED"` or `route: "CLARIFY"` — never any other value
- Returns `triggered_gaps` as a list (empty on pass, one-element on fail)
- `clarification_prompt` is `None` on pass

---

## Step 5 — Run the Blocking Test Suite

```bash
cd google-adk-agents
pytest tests/test_gate.py -v --tb=short
```

**All tests in `test_gate.py` must pass.** A failure here is a hard regression.

Expected passing tests:
- `test_hb_without_unit_is_ambiguous`
- `test_hb_with_correct_unit_resolves`
- `test_hb_with_invalid_unit_triggers_mismatch`
- `test_unknown_term_returns_not_found`
- `test_calcium_collision`
- `test_calcium_with_qualifiers_resolves`
- `test_gate_fails_closed`

---

## Step 6 — Report

Summarize findings:
- ✅ or ❌ for each step above
- List any detectors that lack test coverage in `test_gate.py`
- Flag any LLM calls found inside deterministic nodes
- Recommend new test cases for uncovered edge cases
