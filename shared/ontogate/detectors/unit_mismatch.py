"""
Gap 2: unit mismatch — the reported unit is valid for none of the observables
the term denotes. Independent of ambiguity: ``Hb | mg/dL`` fails here even
though ``Hb`` is ambiguous, because no reading could be meaningful.
"""
from __future__ import annotations

from ontogate.detectors.base import GapDetector
from ontogate.models import EvaluationContext, GapEvaluationResult, ResolutionStatus


class UnitMismatchDetector(GapDetector):
    """Detects unit constraint violations against registered observables."""

    @property
    def gap_name(self) -> str:
        return "Gap 2: Unit Mismatch"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return self._no_registry()
        if context.panel_id:
            return self._pass("Panel request; observable-level check not applicable")
        unit = context.unit.strip()
        if not unit:
            return self._pass("No unit provided; unit mismatch check skipped")
        if not context.term.strip():
            return self._pass("No term provided; unit mismatch check skipped")

        res = self._resolution(context)
        if not res.lexical:
            return self._pass(f"No concepts found for '{context.term.strip()}'; unit mismatch check skipped")
        if not res.unit_mismatch:
            return self._pass(f"Unit '{unit}' is valid for at least one candidate concept")
        valid = ", ".join(f"{c.label}: [{', '.join(c.units)}]" for c in res.lexical if c.units)
        return GapEvaluationResult(
            passed=False, status=ResolutionStatus.UNIT_MISMATCH, gap_name=self.gap_name,
            message=f"Reported unit '{unit}' is not valid for any concept matching '{context.term.strip()}'. "
                    f"Valid units: {valid}",
            candidates=[c.to_view() for c in res.lexical],
            details={"reported_unit": unit, "missing": ["unit"]},
        )
