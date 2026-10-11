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

Open and review these files in `shared/ontogate`:

- `shared/ontogate/detectors/engine.py` — `SafetyGateEngine` class
- `shared/ontogate/models.py` — `EvaluationContext`, `ResolutionStatus`

Check:
- All registered detectors in `self.detectors` are enumerated
- Each detector returns a typed result with `passed: bool` and `status: ResolutionStatus`
- `SafetyGateEngine.route_for(status)` covers all `ResolutionStatus` members

```python
# Verify: every non-RESOLVED status maps to CLARIFY
from ontogate.models import ResolutionStatus
from ontogate.detectors.engine import SafetyGateEngine

engine = SafetyGateEngine()
for status in ResolutionStatus:
    expected = "PROCEED" if status == ResolutionStatus.RESOLVED else "CLARIFY"
    assert engine.route_for(status) == expected, f"FAIL: {status} → wrong route"
```

---

## Step 2 — Validate Framework Routing Entrypoints

Check that framework routers follow fail-closed invariants:
- `google-adk-agents/src/workflow.py`
- `strands-agents/src/workflow.py`
- `agent-framework/src/workflow.py`

```python
from ontogate.models import ResolutionStatus

# Invariant: only RESOLVED proceeds
for s in ("AMBIGUOUS", "UNIT_MISMATCH", "NOT_FOUND", "RANGE_COLLISION", "UNKNOWN"):
    assert engine.route_for(s) == "CLARIFY"
```

---

## Step 3 — Validate `safety_guard` Across Frameworks

Confirm that for all three frameworks:
1. No `await`, `async`, or model/LLM calls anywhere in the safety guard node
2. Pure deterministic Python execution
3. `agents/safety_guard.yaml` specifies `uses_model: false`, `skills: []`

---

## Step 4 — Validate Canonical MCP Surface

Open `shared/ontogate/mcp_server.py` and check `evaluate_safety_gate`:
- Calls `SafetyGateEngine`
- Returns `route: "PROCEED"` or `route: "CLARIFY"` — never any other value
- Returns `status`, `passed`, and `triggered_gaps` list

---

## Step 5 — Run the Blocking Test Suite

```bash
python -m pytest shared/tests/test_gate.py -v
```

**All tests in `shared/tests/test_gate.py` must pass.** A failure here is a hard regression.

