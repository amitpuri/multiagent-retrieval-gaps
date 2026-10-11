---
name: add-hazard-detector
description: >-
  Step-by-step workflow for adding a new deterministic Hazard/Gap Detector to the
  SafetyGateEngine. Use when asked to "add a new detector", "add a hazard detector",
  "extend the safety engine", or "implement a new safety check".
---

# Skill: Add a Hazard Detector

## Purpose

Hazard Detectors are the pluggable, deterministic safety checks inside `SafetyGateEngine`.
Each detector handles one specific clinical hazard class (e.g. range collision, look-alike ambiguity, unit mismatch).
This skill guides you through implementing a new detector correctly in `shared/ontogate`, with tests, without breaking the fail-closed invariant.

---

## Step 1 — Understand the Detector Contract

In `shared/ontogate`:
- Base class: `GapDetector` in `ontogate.detectors.base`
- Engine: `SafetyGateEngine` in `ontogate.detectors.engine`
- Models: `EvaluationContext`, `GapEvaluationResult`, `ResolutionStatus` in `ontogate.models`

Key invariants:
1. Subclass `GapDetector`.
2. Define class attribute `gap_name: str`.
3. Implement `evaluate(self, context: EvaluationContext) -> GapEvaluationResult`.
4. Pure Python: **no LLM calls, no async/await, no network I/O**.
5. Must return `GapEvaluationResult` in all code paths.

---

## Step 2 — Create the Detector File

Create `shared/ontogate/detectors/<hazard_name>_detector.py`:

```python
"""
<HazardName> Detector: <one-line description of the hazard>.
Fails closed: returns CLARIFY route on detection.
"""
from __future__ import annotations

from typing import Any, Dict
from ontogate.detectors.base import GapDetector
from ontogate.models import EvaluationContext, GapEvaluationResult, ResolutionStatus


class <HazardName>Detector(GapDetector):
    """Detects <hazard description>."""
    gap_name = "<GapName>"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        """
        Check for <hazard> in the given evaluation context.
        Returns a passing result if the hazard is not detected.
        """
        if <hazard_condition(context)>:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.<APPROPRIATE_STATUS>,
                gap_name=self.gap_name,
                message="<Human-readable clarification prompt>",
                candidates=context.candidates if hasattr(context, "candidates") else [],
                details={},
            )

        return GapEvaluationResult(
            passed=True,
            status=ResolutionStatus.RESOLVED,
            gap_name=self.gap_name,
            message="",
            candidates=[],
            details={},
        )
```

---

## Step 3 — Register in SafetyGateEngine

Open `shared/ontogate/detectors/engine.py`:
1. Import `<HazardName>Detector`.
2. Append `<HazardName>Detector()` to `self.detectors`.
3. Verify that `SafetyGateEngine.route_for(status)` returns `"CLARIFY"` for any non-`RESOLVED` status.

---

## Step 4 — Write Tests in `shared/tests/test_gate.py`

Add at least these test cases to `shared/tests/test_gate.py`:

```python
def test_<hazard>_triggers_clarify():
    """<Hazard> condition must produce a CLARIFY route, never PROCEED."""
    # Arrange: construct inputs that trigger the hazard
    # Act: evaluate through engine or detector
    # Assert: result.passed is False and route == "CLARIFY"


def test_<hazard>_with_qualifier_resolves():
    """Explicitly qualified inputs must bypass the hazard detector."""
    # Arrange: add the disambiguating qualifier
    # Assert: status == ResolutionStatus.RESOLVED and route == "PROCEED"


def test_<hazard>_missing_value_does_not_crash():
    """Detector must not raise if optional fields are None."""
    # Arrange: omit patient_value or qualifier
    # Assert: result is returned (no exception), status is safe default
```

---

## Step 5 — Verify All Test Suites

```bash
python -m pytest shared/tests/test_gate.py -v
./run-all-tests.sh
```

All gate tests must pass with zero failures.
