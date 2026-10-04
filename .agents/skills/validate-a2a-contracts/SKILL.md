---
name: validate-a2a-contracts
description: >-
  Validates A2A (Agent-to-Agent) message shapes, enum usage, and payload contracts
  across all agents. Use when asked to "check A2A messages", "verify agent contracts",
  "validate A2A payloads", or "check inter-agent communication".
---

# Skill: Validate A2A Contracts

## Purpose

Agents in this system communicate via typed `A2AMessage` contracts. Every message
must use `AgentRole` and `A2AAction` enums — never raw strings. Payload keys must
match the consuming agent's expectations. This skill validates all of that.

---

## Step 1 — Inspect the Contract Definitions

Open `google-adk-agents/src/a2a/contracts.py` and enumerate:

- All `AgentRole` enum members
- All `A2AAction` enum members
- `A2AMessage` Pydantic model fields and their types

Verify:
- `sender` and `recipient` are typed `AgentRole` (not `str`)
- `action` is typed `A2AAction` (not `str`)
- `payload` is `Dict[str, Any]`
- `status` is typed `ResolutionStatus`

---

## Step 2 — Audit Each Agent's A2A Emissions

Check every agent file that creates an `A2AMessage`:

### `safety_guard_agent.py`

| Scenario | sender | recipient | action |
|---|---|---|---|
| Pre-existing failure | `SAFETY_GUARD` | `CLARIFICATION_COORDINATOR` | `REQUEST_CLARIFICATION` |
| Engine failure (collision) | `SAFETY_GUARD` | `CLARIFICATION_COORDINATOR` | `REQUEST_CLARIFICATION` |
| Pass | `SAFETY_GUARD` | `PROTOCOL_RETRIEVER` | `FETCH_PROTOCOL` |

For each, verify the message is stored as:
```python
node_input["a2a_safety_message"] = a2a_msg.model_dump(mode="json")
```

### Other agents

Repeat for `ontology_agent.py`, `synthesis_agent.py`, `triage_agent.py`:
- Sender matches the agent's own role
- Recipient is a valid downstream agent
- `model_dump(mode="json")` is called before storing (never store the Pydantic object raw)

---

## Step 3 — Verify Payload Key Contracts

For each `A2AAction`, the `payload` dict must contain expected keys:

| Action | Required payload keys |
|---|---|
| `REQUEST_CLARIFICATION` | `term`, `unit`, `status` |
| `FETCH_PROTOCOL` | `term`, `unit`, `status` (RESOLVED) |

Check that the consuming agent reads these keys with `.get(key)` (safe) rather than `[key]` (hard failure on missing).

---

## Step 4 — Static Enum Coverage Check

Ensure every `AgentRole` member appears as either a `sender` or `recipient` in at least one message:

```python
# Pseudo-check — do this by reading the agent files
from src.a2a.contracts import AgentRole, A2AAction

# All roles should be used somewhere
# All actions should be used somewhere
# Orphaned enums indicate dead code or missing agent integration
```

---

## Step 5 — Run Multi-Agent Tests

```bash
cd google-adk-agents
pytest tests/test_multiagent_extensible.py -v --tb=short
```

These tests exercise inter-agent message flows end-to-end.

---

## Step 6 — Report

- ✅ / ❌ for each agent's A2A emission audit
- Any raw strings found where enums are required
- Any agents that store raw Pydantic objects (missing `model_dump`)
- Any orphaned `AgentRole` or `A2AAction` enum members
- Any missing payload keys for a given action type
