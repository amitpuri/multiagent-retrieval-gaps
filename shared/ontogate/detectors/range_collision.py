"""
Range collision: look-alike observables whose reference intervals classify the
same value differently (e.g. Calcium 4.8 mg/dL: Total → CRITICAL_LOW,
Ionized → NORMAL).

Applies only when more than one observable remains after unit and qualifier
narrowing AND those observables share a unit in which the value is compared.
Observables with disjoint units (Hb g/dL vs HbA1c %) are disambiguated by the
unit itself and are reported as AMBIGUOUS by :class:`AmbiguityDetector`.
"""
from __future__ import annotations

from ontogate.detectors.base import GapDetector
from ontogate.models import EvaluationContext, GapEvaluationResult, ResolutionStatus
from ontogate.resolver import assess_collision, classify, collapse, differing_facets


class RangeCollisionDetector(GapDetector):
    """Detects divergent classifications across look-alike numeric tests."""

    @property
    def gap_name(self) -> str:
        return "Range Collision: Look-Alike Divergence"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return self._no_registry()
        if context.panel_id:
            return self._pass("Panel request; observable-level check not applicable")
        if context.patient_value is None:
            return self._pass("No numeric patient value to evaluate for range collisions")

        res = self._resolution(context)
        if res.unit_mismatch or not res.candidates:
            return self._pass("No range collision rules apply to this term/unit combination")

        if len(res.candidates) == 1:
            concept = res.candidates[0]
            unit = res.unit or (concept.units[0] if concept.units else "")
            readings = {}
            if unit:
                collapsed = collapse(classify(self.registry, concept, res.value, unit, res.population))
                if collapsed:
                    readings = {concept.name: collapsed}
            return self._pass("Numeric value classified consistently without collision",
                              readings=readings, value=res.value, unit=context.unit)

        assessment = assess_collision(self.registry, res)
        if not assessment.applicable or not assessment.divergent:
            return self._pass("No range collision rules apply to this term/unit combination",
                              readings=assessment.readings, value=res.value, unit=context.unit)

        analyte = self.registry.analytes.get(res.candidates[0].measures or "")
        family = f"{analyte.label} Assays" if analyte else "Look-alike assays"
        missing = sorted(differing_facets(self.registry, res.candidates)) or ["test"]
        if not res.unit:
            missing.append("unit")
        return GapEvaluationResult(
            passed=False, status=ResolutionStatus.RANGE_COLLISION, gap_name=self.gap_name,
            message=(
                f"Value {res.value} generates conflicting clinical interpretations across {family}: "
                f"{assessment.readings}. Explicit qualifier required."
            ),
            candidates=[c.to_view() for c in res.candidates],
            details={
                "family": family,
                "readings": assessment.readings,
                "readings_unit": assessment.readings_unit,
                "units_checked": assessment.units_checked,
                "value": res.value,
                "unit": context.unit,
                "missing": missing,
                "reading_detail": assessment.detail,
            },
        )
