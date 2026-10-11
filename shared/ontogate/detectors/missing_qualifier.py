"""
Gap 5: missing qualifier — a numeric result whose remaining candidates differ on
a facet (e.g. calcium fraction: total vs ionized). The clarification offers
exactly the facet's values from the ontology; there is no substring matching
against assay names, so ``total calcium`` and ``ica`` resolve directly.
"""
from __future__ import annotations

from ontogate.detectors.base import GapDetector
from ontogate.models import EvaluationContext, GapEvaluationResult, ResolutionStatus
from ontogate.resolver import differing_facets, shared_units


class MissingQualifierDetector(GapDetector):
    """Detects numeric results that need a facet value the clinician did not give."""

    @property
    def gap_name(self) -> str:
        return "Gap 5: Missing Qualifier"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return self._no_registry()
        if context.panel_id:
            return self._pass("Panel request; observable-level check not applicable")
        if context.qualifier.strip():
            return self._pass("Qualifier provided; missing qualifier check skipped")
        if not context.term.strip():
            return self._pass("No term provided; missing qualifier check skipped")

        res = self._resolution(context)
        # Candidates with disjoint units are disambiguated by the unit itself
        # (e.g. Troponin I ng/mL vs T ng/L): AmbiguityDetector asks for it.
        unit_disambiguates = not res.unit and not shared_units(res.candidates)
        if context.patient_value is not None and len(res.candidates) > 1 and not unit_disambiguates:
            facets = differing_facets(self.registry, res.candidates)
            if facets:
                fid, values = next(iter(facets.items()))
                facet = self.registry.facets[fid]
                return GapEvaluationResult(
                    passed=False, status=ResolutionStatus.MISSING_QUALIFIER, gap_name=self.gap_name,
                    message=(
                        f"Term '{context.term.strip()}' requires an explicit qualifier ({facet.label or fid}). "
                        f"Provide one of: {values}"
                    ),
                    candidates=[c.to_view() for c in res.candidates],
                    details={"facet": fid, "question": facet.question, "available_qualifiers": values,
                             "family": facet.label or fid, "missing": [fid]},
                )

        return self._pass("No qualifier requirement triggered for this term")
