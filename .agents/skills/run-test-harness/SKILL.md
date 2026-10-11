---
name: run-test-harness
description: >-
  Runs the full pytest test suite for google-adk-agents and interprets results.
  Use when asked to "run tests", "run the test suite", "check all tests pass",
  "did my change break anything", or "what's the test coverage".
---

# Skill: Run Test Harness

## Purpose

This skill executes the complete test suite, interprets failures, and tells you
which failures are **blocking** (safety regressions) vs. non-blocking (feature gaps).

---

## Step 1 — Set Up the Environment

```bash
# From the repo root:
cd google-adk-agents
```

Ensure you are inside a virtual environment before installing:

```bash
# Create and activate (Linux / macOS)
python3 -m venv .venv
source .venv/bin/activate

# Create and activate (Windows)
python -m venv .venv
.venv\Scripts\activate
```

Then install dependencies:
```bash
pip install -r requirements.txt
```

If a `.env` file exists with API keys, export the variables (for live-mode tests):
```bash
# Linux / macOS
source load_env.sh

# Windows — set each key manually or use a tool like dotenv
# Most tests use offline mode and need no credentials
```

---

## Step 2 — Run the Full Suite

```bash
# Run all test suites across shared, ADK, Strands, and MAF (372+ tests)
./run-all-tests.sh
```

For a quick smoke-check (deterministic shared core only, no LLM):
```bash
python -m pytest shared/tests/ -v --tb=short
```

---

## Step 3 — Interpret Results by Test Suite

| Test Suite | Covers | Blocking? |
|---|---|---|
| `shared/tests/` | Deterministic safety gate, ontology registry, resolver, units, attestation, skills lock | **YES — hard block** |
| `google-adk-agents/tests/` | Google ADK workflow, runner, A2A messaging | High priority |
| `strands-agents/tests/` | AWS Bedrock Strands agents, MCP integration | High priority |
| `agent-framework/tests/` | Azure AI Agent Framework agents | High priority |

### Failure Classification

**Blocking failures** (`test_gate.py`):
- Any failure here means a deterministic safety invariant has regressed
- Do NOT commit until these pass
- Root cause: likely a change to `shared/ontogate/detectors/`, the ontology pack, or a framework `src/workflow.py`

**High-priority failures** (harness / multiagent):
- Indicate broken MCP tool wiring, A2A message shapes, or harness loop logic
- Fix before merging

**Medium-priority failures** (OKF phases):
- Often indicate a new feature is needed or a protocol data change
- Can be tracked as issues if not immediately fixable

---

## Step 4 — Diagnose a Specific Failure

If a test fails, run it in isolation with full traceback:
```bash
pytest tests/<test_file>.py::test_<function_name> -v --tb=long 2>&1
```

Common failure patterns:

| Symptom | Likely Cause |
|---|---|
| `AssertionError: AMBIGUOUS != RESOLVED` | Term lookup changed in `src/tools.py` |
| `AssertionError: PROCEED != CLARIFY` | `route_for()` mapping changed |
| `KeyError: 'candidates'` | MCP tool return shape missing field |
| `ValidationError` from Pydantic | A2A message constructed with wrong types |
| `AttributeError: 'NoneType'` | `get_mcp_server()` not initialized correctly |

---

## Step 5 — Check for Missing Test Coverage

After a passing run, identify what isn't tested:
```bash
pytest tests/ --co -q 2>&1
```

Look for gaps:
- New `ResolutionStatus` values without a `route_for` test
- New MCP tools not present in `test_harness.py`
- New gap detectors without a dedicated test in `test_gate.py`

---

## Step 6 — Report Summary

Provide:
- Total: N passed, M failed, K errors
- List of failed tests with one-line root cause each
- Blocking vs. non-blocking classification
- Recommended next steps (fix order)
