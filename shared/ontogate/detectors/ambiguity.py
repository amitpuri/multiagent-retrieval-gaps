"""
Gap 2 & Gap 8: lexical ambiguity and silent guessing.

Fails when a term denotes no observable (NOT_FOUND), when the reported unit is
valid for none of its candidates (UNIT_MISMATCH), when several observables
remain after unit and qualifier narrowing (AMBIGUOUS), or when the qualifier
contradicts the observable the term already fixes (AMBIGUOUS + "contradicts").
All decisions come from :func:`ontogate.resolver.resolve`.
"""
from __future__ import annotations

from ontogate.detectors.base import GapDetector
from ontogate.models import EvaluationContext, GapEvaluationResult, ResolutionStatus


class AmbiguityDetector(GapDetector):
    """Detects multi-concept collisions and ungrounded lexical ambiguities."""

    @property
    def gap_name(self) -> str:
        return "Gap 2 & 8: Ambiguity & Silent Guessing"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return self._no_registry()
        if context.panel_id:
            return self._pass("Panel request; observable-level check not applicable")
        term = context.term.strip()
        if not term:
            return GapEvaluationResult(passed=False, status=ResolutionStatus.NOT_FOUND,
                                       gap_name=self.gap_name, message="No search term provided")

        res = self._resolution(context)
        if not res.lexical:
            return GapEvaluationResult(passed=False, status=ResolutionStatus.NOT_FOUND, gap_name=self.gap_name,
                                       message=f"No matching concept found for term '{term}'", candidates=[])
        if res.unit_mismatch:
            return GapEvaluationResult(
                passed=False, status=ResolutionStatus.UNIT_MISMATCH, gap_name="Gap 2: Unit Mismatch",
                message=f"Reported unit '{res.unit}' is not valid for any matching concept",
                candidates=[c.to_view() for c in res.candidates],
                details={"reported_unit": res.unit, "missing": ["unit"]},
            )
        if res.contradiction:
            return GapEvaluationResult(
                passed=False, status=ResolutionStatus.AMBIGUOUS, gap_name=self.gap_name,
                message=f"{res.contradiction} Clarification required.",
                candidates=[c.to_view() for c in res.candidates],
                details={"contradiction": res.contradiction},
            )
        if res.is_ambiguous:
            missing = ["unit"] if not res.unit else []
            from ontogate.resolver import differing_facets
            facets = differing_facets(self.registry, res.candidates)
            missing += sorted(facets)
            return GapEvaluationResult(
                passed=False, status=ResolutionStatus.AMBIGUOUS, gap_name=self.gap_name,
                message=f"Term '{term}' matches {len(res.candidates)} distinct concepts; clarification required",
                candidates=[c.to_view() for c in res.candidates],
                details={"missing": missing or ["test"], "facets": facets,
                         "designation_kind": res.designation.kind if res.designation else None},
            )

        concept = res.candidates[0]
        details = {"resolved_concept": concept.to_view()}
        if res.redirected_from:
            details["superseded"] = res.redirected_from
        return GapEvaluationResult(
            passed=True, status=ResolutionStatus.RESOLVED, gap_name=self.gap_name,
            message=f"Term '{term}' resolved uniquely to {concept.label}",
            candidates=[concept.to_view()], details=details,
        )
