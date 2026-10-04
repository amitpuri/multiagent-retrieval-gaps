---
name: validate-agent-routing
description: >-
  Traces and validates the full multi-agent routing pipeline from parse through
  safety_guard_node. Use when asked to "trace agent routing", "validate the workflow",
  "check routing decisions", or "verify the agent pipeline".
---

# Skill: Validate Agent Routing

## Purpose

The clinical agent pipeline routes every query through a deterministic sequence:
`parse → ontology_agent → safety_guard_node → [PROCEED | CLARIFY]`.

This skill traces that pipeline statically and dynamically, checking that routing
is fully deterministic and that no step introduces LLM variance into gate decisions.

---

## Step 1 — Map the Pipeline

Open these files and trace the call graph:

1. `google-adk-agents/src/workflow.py` — `parse()`, `route_for()`
2. `google-adk-agents/src/agents/ontology_agent.py` — ontology resolution node
3. `google-adk-agents/src/agents/safety_guard_agent.py` — `safety_guard_node`
4. `google-adk-agents/src/agents/protocol_agent.py` — downstream PROCEED branch
5. `google-adk-agents/src/agents/clarification_agent.py` — downstream CLARIFY branch

Draw or describe the routing graph:
```
Input
  └─ parse()
       └─ ontology_agent (LLM-assisted resolution)
            └─ safety_guard_node  ← deterministic gate
                 ├─ PROCEED → protocol_agent
                 └─ CLARIFY → clarification_agent
```

---

## Step 2 — Verify parse() Output Shape

```python
from src.workflow import parse

ev = parse("Hb | g/dL")
assert ev.output["term"] == "Hb"
assert ev.output["unit"] == "g/dL"

ev2 = parse("Hb")
assert ev2.output["term"] == "Hb"
assert ev2.output["unit"] == ""
```

---

## Step 3 — Confirm safety_guard_node Is Synchronous and LLM-Free

In `google-adk-agents/src/agents/safety_guard_agent.py`, search for:

- ❌ `async def` — must NOT be present
- ❌ `await` — must NOT be present
- ❌ `Client`, `generate_content`, `model` — must NOT be present
- ✅ `SafetyGateEngine()` — must be present
- ✅ `Event(output=..., route=...)` — returned in all three branches

---

## Step 4 — Validate All Routing Branches

Ensure every `ResolutionStatus` flows through the correct branch:

```python
from src.workflow import route_for

# Gate invariant
assert route_for("RESOLVED") == "PROCEED"
for s in ("AMBIGUOUS", "UNIT_MISMATCH", "NOT_FOUND", "RANGE_COLLISION", "UNKNOWN"):
    assert route_for(s) == "CLARIFY"
```

Also check the safety guard node's three branches:
1. **Pre-existing failure** — `current_status != RESOLVED.value` → direct CLARIFY
2. **Engine failure** — `result.passed == False` → CLARIFY with collision details
3. **Pass** — all clear → PROCEED with A2A to protocol_agent

---

## Step 5 — Validate Harness Routing Integration

Open `google-adk-agents/src/harness/agent.py` and check:

- The harness respects the `route` returned by `safety_guard_node`
- It does not override or re-derive routing from the LLM response text
- `is_hitl_paused` is set correctly when route is `CLARIFY`

---

## Step 6 — Run Pipeline Tests

```bash
cd google-adk-agents
pytest tests/test_okf_phases_5_8.py tests/test_okf_refinement.py -v --tb=short
```

These tests exercise the full routing pipeline across OKF phases 5–8.

---

## Step 7 — Report

- Full routing graph as traced
- ✅ / ❌ for each determinism check
- Any LLM calls found inside deterministic nodes
- Any routing branches that lack test coverage
- Suggestions for additional routing edge case tests
