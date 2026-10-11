---
name: add-gap-detector
description: >-
  Step-by-step workflow for adding a new deterministic Gap Detector to the
  SafetyGateEngine. Use when asked to "add a new detector", "add a gap detector",
  "extend the safety engine", or "implement a new safety check".
---

# Skill: Add a Gap Detector

> [!NOTE]
> This skill has been superseded by [`add-hazard-detector`](file:///c:/repositories/repos/multiagent-retrieval-gaps/.agents/skills/add-hazard-detector/SKILL.md).
> All core detector logic lives in `shared/ontogate/detectors/`.

## Purpose

Gap/Hazard Detectors are the pluggable, deterministic safety checks inside `SafetyGateEngine`.
Each detector handles one specific clinical hazard (e.g., range collision, look-alike ambiguity).
This skill guides you through implementing a new detector correctly in `shared/ontogate`, with tests, without breaking the fail-closed invariant.

---

## Step 1 — Understand Existing Detectors

Read the detectors in `shared/ontogate`:
- `shared/ontogate/detectors/base.py` — `GapDetector` base class
- `shared/ontogate/detectors/engine.py` — `SafetyGateEngine` that orchestrates them
- `shared/ontogate/models.py` — `EvaluationContext`, `GapEvaluationResult`, `ResolutionStatus`

---

## Step 2 — Create the Detector File

Create `shared/ontogate/detectors/<hazard_name>_detector.py`:

```python
"""
<HazardName> Detector: <one-line description of the hazard>.
Fails closed: returns CLARIFY route on detection.
"""
from __future__ import annotations

from ontogate.detectors.base import GapDetector
from ontogate.models import EvaluationContext, GapEvaluationResult, ResolutionStatus


class <HazardName>Detector(GapDetector):
    """Detects <hazard description>."""
    gap_name = "<GapName>"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        """Check for hazard in the given context."""
        if <hazard_condition(context)>:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.<APPROPRIATE_STATUS>,
                gap_name=self.gap_name,
                message="<Clarification prompt>",
                candidates=context.candidates if hasattr(context, "candidates") else [],
            )

        return GapEvaluationResult(
            passed=True,
            status=ResolutionStatus.RESOLVED,
            gap_name=self.gap_name,
            message="",
            candidates=[],
        )
```

---

## Step 3 — Register in SafetyGateEngine

In `shared/ontogate/detectors/engine.py`, add `<HazardName>Detector()` to `self.detectors`.

---

## Step 4 — Run Tests

```bash
python -m pytest shared/tests/test_gate.py -v
```

