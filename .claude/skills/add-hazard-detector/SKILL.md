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

Create `shared/ontogate/detectors/<hazard_name>.py` (the example below is `negative_value.py`):

```python
"""
Negative Value Detector: a concentration below zero is a transcription error.
Fails closed: a negative value routes to CLARIFY.
"""
from __future__ import annotations

from ontogate.detectors.base import GapDetector
from ontogate.models import EvaluationContext, GapEvaluationResult, ResolutionStatus


class NegativeValueDetector(GapDetector):
    """Rejects negative patient values (no observable in the pack admits them)."""

    @property
    def gap_name(self) -> str:
        return "Negative Value"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        """Fail closed on a negative value; pass everything else through."""
        if context.patient_value is not None and context.patient_value < 0:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.UNIT_MISMATCH,  # the status whose clarification fits the hazard
                gap_name=self.gap_name,
                message=f"A value of {context.patient_value} cannot be a concentration; please re-check it.",
                details={"missing": ["patient_value"]},
            )
        return self._pass("Value is non-negative")
```

---

## Step 3 — Register the Detector

Detectors plug in through the `ontogate.detectors` entry-point group; the engine
code is not edited.

- **Built-in detector** (part of the default suite): add the entry point to
  `shared/pyproject.toml` and its name to `DEFAULT_ORDER` in
  `shared/ontogate/detectors/engine.py` at the position where its clarification
  is the most informative one.

  ```toml
  [project.entry-points."ontogate.detectors"]
  negative_value = "ontogate.detectors.negative_value:NegativeValueDetector"
  ```

- **Plugin detector** (another package): declare the same entry point in that
  package. Plugins run after the built-in suite and can never open the gate.

`SafetyGateEngine.route_for(status)` stays fail-closed: only `RESOLVED` proceeds.

---

## Step 4 — Write Tests in `shared/tests/test_<hazard_name>.py`

Add at least these cases (one failing fixture, one pass, one missing-field):

```python
from ontogate.config import get_default_registry
from ontogate.detectors.engine import SafetyGateEngine
from ontogate.models import EvaluationContext


def test_negative_value_routes_to_clarify():
    """A negative value never proceeds."""
    reg = get_default_registry()
    result = NegativeValueDetector(reg).evaluate(EvaluationContext(term="Hb", unit="g/dL", patient_value=-1.0))
    assert not result.passed
    assert SafetyGateEngine(reg).route_for(result.status) == "CLARIFY"


def test_non_negative_value_passes():
    """A plausible value is left to the other detectors."""
    reg = get_default_registry()
    assert NegativeValueDetector(reg).evaluate(EvaluationContext(term="Hb", unit="g/dL", patient_value=13.5)).passed


def test_missing_value_does_not_crash():
    """Optional fields may be absent."""
    assert NegativeValueDetector(get_default_registry()).evaluate(EvaluationContext(term="Hb")).passed
```

---

## Step 5 — Verify All Test Suites

```bash
python -m pytest shared/tests/test_negative_value.py -v
./run-all-tests.sh   # includes the competency questions and cross-cloud conformance
```

Add a competency question to a scenario in `config/scenarios/` that exercises the hazard end to end.
