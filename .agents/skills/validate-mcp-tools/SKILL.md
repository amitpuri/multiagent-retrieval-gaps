---
name: validate-mcp-tools
description: >-
  Validates MCP tool registrations, return shapes, and contract compliance in
  mcp_server.py. Use when asked to "verify MCP tools", "check tool registration",
  "did I break the MCP contract", or "test the MCP server".
---

# Skill: Validate MCP Tools

## Purpose

The MCP server (`src/harness/mcp_server.py`) is the structured tool dispatch layer.
Every registered tool must have a correct decorator, delegate to `src/tools.py` or
`src/core/`, and return the expected shape. This skill validates all of that.

---

## Step 1 — Audit Tool Registrations

Open `google-adk-agents/src/harness/mcp_server.py`.

For each entry in `CLINICAL_MCP_TOOLS`, verify:

| Tool Name | Required Return Fields |
|---|---|
| `resolve_lab_term` | `status`, `candidates` |
| `evaluate_safety_gate` | `route`, `status`, `passed`, `triggered_gaps`, `clarification_prompt`, `candidates` |
| `fetch_grounded_protocol` | `status` or `reference_range` + `panic_limits` |
| `csf_workup` | Dept keys with tube-ordered lists, or `{"status": "NOT_FOUND"}` |
| `check_calcium` | `status`, `readings` |
| `attest_computation` | `passed`, `verdict`, and `badge: "[Attested ✓]"` on pass |

Check that:
1. Every tool in `CLINICAL_MCP_TOOLS` dict has a matching `@mcp_server.tool(name=...)` decorator
2. The `name=` argument matches the dict key exactly
3. Tool bodies are thin wrappers — business logic lives in `src/tools.py` or `src/core/`

---

## Step 2 — Check `get_mcp_server()` Exports

Verify:
```python
from src.harness.mcp_server import get_mcp_server, CLINICAL_MCP_TOOLS
from mcp.server.fastmcp import FastMCP

server = get_mcp_server()
assert isinstance(server, FastMCP)
assert set(CLINICAL_MCP_TOOLS.keys()) == {
    "resolve_lab_term",
    "evaluate_safety_gate",
    "fetch_grounded_protocol",
    "csf_workup",
    "check_calcium",
    "attest_computation",
}
```

---

## Step 3 — Spot-Check `attest_computation`

This is the only tool with a protocol fetch + physiological plausibility check baked in.
Validate the two special cases:

```python
from src.harness.mcp_server import attest_computation

# Case 1: unknown URI → FAIL
result = attest_computation(value=10.0, uri="loinc:0000-0", unit="g/dL")
assert result["passed"] is False
assert result["verdict"] == "FAIL"

# Case 2: implausible value → FAIL
result = attest_computation(value=99999.0, uri="loinc:718-7", unit="g/dL")
assert result["passed"] is False

# Case 3: valid → badge present
result = attest_computation(value=15.0, uri="loinc:718-7", unit="g/dL")
assert result["passed"] is True
assert result["badge"] == "[Attested ✓]"
```

---

## Step 4 — Check MCPToolBridge Wiring

Open `google-adk-agents/src/harness/mcp_client.py` and verify:

- `MCPToolBridge` references `CLINICAL_MCP_TOOLS` (not a hardcoded internal list)
- Tool dispatch goes through the bridge (not called directly by the harness)

---

## Step 5 — Run MCP-Related Tests

```bash
cd google-adk-agents
pytest tests/test_harness.py -v --tb=short
```

Look specifically for failures in test cases that invoke MCP tool paths.

---

## Step 6 — Report

- ✅ / ❌ for each tool registration check
- Any tools missing from `CLINICAL_MCP_TOOLS`
- Any tools with business logic embedded directly in `mcp_server.py`
- Any missing required return fields
