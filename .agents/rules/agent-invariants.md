---
trigger: always_on
---

# Agent Invariants — Enforce on Every Turn

These constraints are **non-negotiable** and apply to all code edits, refactors, and
new implementations in this repository. Violating any of these is a regression.

---

## 1. Safety Gate Is Deterministic — No LLM Calls Inside

`safety_guard_node` in `src/agents/safety_guard_agent.py` and `SafetyGateEngine` in
`src/core/detectors/engine.py` must **never** contain LLM calls, `await` on model
completions, or probabilistic branching. The gate is pure Python.

```python
# CORRECT — deterministic only
result = engine.evaluate(context)
route = engine.route_for(result.status)

# WRONG — never do this inside safety_guard_node
response = await model.generate_content(...)
```

---

## 2. Fail-Closed Routing: Only RESOLVED Proceeds

`route_for()` in `src/workflow.py` must return `"CLARIFY"` for **every** status except
`"RESOLVED"`. Adding a new `ResolutionStatus` requires a corresponding `"CLARIFY"` mapping.

```python
# Invariant — must always hold:
assert route_for("RESOLVED") == "PROCEED"
for status in ("AMBIGUOUS", "UNIT_MISMATCH", "NOT_FOUND", "RANGE_COLLISION", "UNKNOWN"):
    assert route_for(status) == "CLARIFY"
```

---

## 3. MCP Tools Must Return `Dict[str, Any]` With a `"status"` Field

Every function registered with `@mcp_server.tool(...)` in `src/harness/mcp_server.py`
must return a `Dict[str, Any]` that includes a `"status"` key. Never return `None`,
bare strings, or untyped dicts.

---

## 4. A2A Messages Use Typed Enums — Never Raw Strings

All `A2AMessage` constructions must use `AgentRole` and `A2AAction` enum members.
Raw string literals for sender/recipient/action are forbidden.

```python
# CORRECT
A2AMessage(sender=AgentRole.SAFETY_GUARD, action=A2AAction.REQUEST_CLARIFICATION, ...)

# WRONG
A2AMessage(sender="safety_guard", action="request_clarification", ...)
```

---

## 5. `attest_computation` Must Include `"badge"` on Pass

A passing `attest_computation` result must always include:
```python
{"badge": "[Attested ✓]", "verdict": "PASS", "passed": True, ...}
```
This badge is consumed by downstream agents for OKF §5.4 compliance marking.

---

## 6. `test_gate.py` Is a Blocking Test Suite

All tests in `google-adk-agents/tests/test_gate.py` must pass at all times.
A failure there means a safety invariant has regressed. Do not skip or xfail
tests in that file without an explicit documented justification.

---

## 7. Protocols Are URI-Bound — No Cross-Concept Data

`fetch_grounded_protocol(uri)` must return data bound strictly to the provided
LOINC URI. Never aggregate, interpolate, or merge data from multiple URIs in a
single protocol response.
