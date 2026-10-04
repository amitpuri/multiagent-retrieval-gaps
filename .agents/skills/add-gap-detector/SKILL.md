---
name: add-gap-detector
description: >-
  Step-by-step workflow for adding a new deterministic Gap Detector to the
  SafetyGateEngine. Use when asked to "add a new detector", "add a gap detector",
  "extend the safety engine", or "implement a new safety check".
---

# Skill: Add a Gap Detector

## Purpose

Gap Detectors are the pluggable, deterministic safety checks inside `SafetyGateEngine`.
Each detector handles one specific clinical hazard (e.g., range collision, look-alike ambiguity).
This skill guides you through implementing a new detector correctly, with tests, without
breaking the fail-closed invariant.

---

## Step 1 — Understand Existing Detectors

Before writing code, read the existing detectors to understand the interface:

- `google-adk-agents/src/core/detectors/` — all detector files
- `google-adk-agents/src/core/detectors/engine.py` — `SafetyGateEngine` that orchestrates them
- `google-adk-agents/src/core/models.py` — `EvaluationContext`, `DetectorResult`, `ResolutionStatus`

Key questions before proceeding:
1. What hazard does this detector catch?
2. What input fields from `EvaluationContext` does it need?
3. What `ResolutionStatus` does it emit on failure?
4. Is there an existing detector that partially covers this?

---

## Step 2 — Create the Detector File

Create `src/core/detectors/<hazard_name>_detector.py`:

```python
"""
<HazardName> Detector: <one-line description of the hazard>.
Fails closed: returns CLARIFY route on detection.
"""
from __future__ import annotations

from typing import Any, Dict
from src.core.models import DetectorResult, EvaluationContext, ResolutionStatus


class <HazardName>Detector:
    """Detects <hazard description>."""

    def evaluate(self, context: EvaluationContext) -> DetectorResult:
        """
        Check for <hazard> in the given evaluation context.
        Returns a passing result if the hazard is not detected.
        """
        # Your detection logic here — pure Python, no LLM calls
        if <hazard_condition(context)>:
            return DetectorResult(
                passed=False,
                status=ResolutionStatus.<APPROPRIATE_STATUS>,
                gap_name="<GapName>",
                message="<Human-readable clarification prompt>",
                candidates=context.candidates if hasattr(context, "candidates") else [],
                details={},  # optional diagnostic dict
            )

        return DetectorResult(
            passed=True,
            status=ResolutionStatus.RESOLVED,
            gap_name="<GapName>",
            message="",
            candidates=[],
            details={},
        )
```

**Rules for detector logic:**
- ❌ No `async`, no `await`, no LLM/model calls
- ❌ No network calls, no I/O
- ✅ Pure Python conditionals only
- ✅ Must return `DetectorResult` in **all** code paths

---

## Step 3 — Register in SafetyGateEngine

Open `google-adk-agents/src/core/detectors/engine.py` and add the detector:

```python
from src.core.detectors.<hazard_name>_detector import <HazardName>Detector

class SafetyGateEngine:
    def __init__(self):
        self._detectors = [
            # ... existing detectors ...
            <HazardName>Detector(),   # ← add here
        ]
```

Verify that the engine iterates all detectors in `evaluate()` and that a single failure
short-circuits to `CLARIFY` (fail-closed).

---

## Step 4 — Write Tests in `test_gate.py`

Add at least these test cases to
`google-adk-agents/tests/test_gate.py`:

```python
def test_<hazard>_triggers_clarify():
    """<Hazard> condition must produce a CLARIFY route, never PROCEED."""
    # Arrange: construct inputs that trigger the hazard
    # Act: call the relevant tool (check_calcium, resolve_lab_term, etc.)
    # Assert: status == "<APPROPRIATE_STATUS>" and route == "CLARIFY"


def test_<hazard>_with_qualifier_resolves():
    """Explicitly qualified inputs must bypass the hazard detector."""
    # Arrange: add the disambiguating qualifier
    # Assert: status == "RESOLVED" and route == "PROCEED"


def test_<hazard>_missing_value_does_not_crash():
    """Detector must not raise if optional fields are None."""
    # Arrange: omit patient_value or qualifier
    # Assert: result is returned (no exception), status is safe default
```

---

## Step 5 — Update the MCP Surface (if needed)

If the new detector surfaces a new `ResolutionStatus` that callers need to handle,
update `src/harness/mcp_server.py::evaluate_safety_gate` to include it in
`triggered_gaps` or `clarification_prompt`.

---

## Step 6 — Run Validation Skills

After implementation, run these skills in order:

1. **`validate-safety-gate`** — confirm the new detector is exercised and fail-closed
2. **`run-test-harness`** — confirm all existing tests still pass (no regression)
3. **`validate-mcp-tools`** — confirm the MCP surface reflects any new status values

```bash
cd google-adk-agents
pytest tests/test_gate.py -v --tb=short 2>&1
```

All tests must pass before committing.

---

## Step 7 — Checklist Before Committing

- [ ] Detector file created in `src/core/detectors/`
- [ ] Detector registered in `SafetyGateEngine.__init__`
- [ ] At least 3 test cases added to `test_gate.py`
- [ ] No LLM calls in detector or engine
- [ ] `route_for` covers any new `ResolutionStatus` → `"CLARIFY"`
- [ ] `validate-safety-gate` skill passes
- [ ] Full test suite passes with 0 failures in `test_gate.py`
