"""
Population context: a resolved numeric value whose classification depends on a
population facet (sex, age band) the clinician did not supply.

Governed by ``gate_policy.population_required_when`` in the core ontology:

- ``critical_divergence`` (default): fail only when a CRITICAL classification
  differs between populations; otherwise pass and surface per-population
  readings so synthesis can caveat them.
- ``any_divergence``: fail whenever any classification differs.
"""
from __future__ import annotations

from ontogate.detectors.base import GapDetector
from ontogate.models import EvaluationContext, GapEvaluationResult, ResolutionStatus
from ontogate.resolver import assess_population


class PopulationContextDetector(GapDetector):
    """Requests sex / age band when it changes the clinical classification."""

    @property
    def gap_name(self) -> str:
        return "Population Context: Interval Selection"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return self._no_registry()
        if context.panel_id:
            return self._pass("Panel request; observable-level check not applicable")
        if context.patient_value is None or not context.unit.strip():
            return self._pass("No unit-qualified numeric value; population check skipped")

        res = self._resolution(context)
        concept = res.resolved
        if concept is None or res.unit_mismatch:
            return self._pass("No single resolved concept; population check skipped")

        pa = assess_population(self.registry, concept, res.value, res.unit, res.population)
        policy = self.registry.gate_policy.get("population_required_when", "critical_divergence")
        must_ask = pa.critical_divergent if policy == "critical_divergence" else pa.divergent
        if must_ask and pa.facets:
            facet = self.registry.population_facets.get(pa.facets[0])
            values = facet.values if facet else []
            return GapEvaluationResult(
                passed=False, status=ResolutionStatus.MISSING_QUALIFIER, gap_name=self.gap_name,
                message=(
                    f"The reference interval for {concept.name} depends on {', '.join(pa.facets)}, "
                    f"and the classification differs: {pa.readings}. Provide one of: {values}"
                ),
                candidates=[concept.to_view()],
                details={"facet": pa.facets[0], "available_qualifiers": values,
                         "population_readings": pa.readings, "missing": pa.facets},
            )
        return self._pass("Population context sufficient for classification",
                          population_readings=pa.readings, population_divergent=pa.divergent)
