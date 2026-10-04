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
pytest tests/ -v --tb=short 2>&1
```

For a quick smoke-check (deterministic only, no LLM):
```bash
pytest tests/test_gate.py -v --tb=short 2>&1
```

---

## Step 3 — Interpret Results by Test File

| Test File | Covers | Blocking? |
|---|---|---|
| `test_gate.py` | Deterministic safety gate, fail-closed routing, detectors | **YES — hard block** |
| `test_harness.py` | Full harness loop, MCP bridge, offline mode | High priority |
| `test_multiagent_extensible.py` | Multi-agent routing, A2A message flows | High priority |
| `test_okf_phases_5_8.py` | OKF ontology phases 5–8, grounded protocol retrieval | Medium priority |
| `test_okf_refinement.py` | OKF refinement loop, HITL pause/resume | Medium priority |

### Failure Classification

**Blocking failures** (`test_gate.py`):
- Any failure here means a deterministic safety invariant has regressed
- Do NOT commit until these pass
- Root cause: likely a change to `src/core/detectors/`, `src/workflow.py`, or `src/tools.py`

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
