"""
Gap 2 & Gap 8 Detector: Lexical Ambiguity and Silent Guessing.
Detects when a clinical query matches multiple candidate concepts across
departments and lacks the necessary unit or contextual constraints to disambiguate.
"""
from __future__ import annotations

import re
from typing import List
from src.core.detectors.base import GapDetector
from src.core.models import (
    ConceptDefinition,
    EvaluationContext,
    GapEvaluationResult,
    ResolutionStatus,
)


class AmbiguityDetector(GapDetector):
    """Detects multi-concept collisions and ungrounded lexical ambiguities."""

    @property
    def gap_name(self) -> str:
        return "Gap 2 & 8: Ambiguity & Silent Guessing"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.UNKNOWN,
                gap_name=self.gap_name,
                message="OntologyRegistry is not configured in AmbiguityDetector",
            )

        term = context.term.strip()
        if not term:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.NOT_FOUND,
                gap_name=self.gap_name,
                message="No search term provided",
            )

        candidates: List[ConceptDefinition] = self.registry.find_concepts(term)
        if not candidates:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.NOT_FOUND,
                gap_name=self.gap_name,
                message=f"No matching concept found for term '{term}'",
                candidates=[],
            )

        # If unit is supplied, filter candidates by supported units
        unit = context.unit.strip()
        if unit:
            matched_by_unit = [c for c in candidates if c.supports_unit(unit)]
            if not matched_by_unit:
                return GapEvaluationResult(
                    passed=False,
                    status=ResolutionStatus.UNIT_MISMATCH,
                    gap_name="Gap 2: Unit Mismatch",
                    message=f"Reported unit '{unit}' is not valid for any matching concept",
                    candidates=[c.to_view() for c in candidates],
                    details={"reported_unit": unit},
                )
            candidates = matched_by_unit

        # If a qualifier is supplied and we are still ambiguous, use it to narrow.
        # Fix 13: whole-word matching using word boundaries (synced from ADK).
        qualifier = context.qualifier.strip()
        if qualifier and len(candidates) > 1:
            q = qualifier.lower()
            pattern = (
                re.compile(rf"(?:^|\s){re.escape(q)}\b", re.IGNORECASE)
                if len(q) == 1
                else re.compile(rf"\b{re.escape(q)}\b", re.IGNORECASE)
            )
            qualifier_matched = [
                c for c in candidates
                if any(pattern.search(alt) for alt in [c.label] + c.alt_labels)
            ]
            if qualifier_matched:
                candidates = qualifier_matched

        # Check for ambiguity
        if len(candidates) > 1:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.AMBIGUOUS,
                gap_name=self.gap_name,
                message=f"Term '{term}' matches {len(candidates)} distinct concepts; clarification required",
                candidates=[c.to_view() for c in candidates],
            )

        # Defect #6: Check for qualifier contradiction against resolved concept/term.
        # A qualifier must not contradict the resolved concept or explicit term.
        # e.g. term='ionized calcium' with qualifier='total' or vice versa.
        if qualifier and len(candidates) == 1:
            q_lower = qualifier.strip().lower()
            opposites = {
                "total": ("ionized", "free"),
                "ionized": ("total",),
                "free": ("total",),
            }.get(q_lower, ())
            target_text = (term + " " + candidates[0].label + " " + " ".join(candidates[0].alt_labels)).lower()
            if any(re.search(rf"\b{re.escape(opp)}\b", target_text) for opp in opposites):
                return GapEvaluationResult(
                    passed=False,
                    status=ResolutionStatus.AMBIGUOUS,
                    gap_name=self.gap_name,
                    message=(
                        f"Qualifier '{qualifier}' contradicts term or concept '{candidates[0].label}'. "
                        "Clarification required."
                    ),
                    candidates=[c.to_view() for c in candidates],
                )

        # Single concept resolved
        return GapEvaluationResult(
            passed=True,
            status=ResolutionStatus.RESOLVED,
            gap_name=self.gap_name,
            message=f"Term '{term}' resolved uniquely to {candidates[0].label}",
            candidates=[candidates[0].to_view()],
            details={"resolved_concept": candidates[0].to_view()},
        )
