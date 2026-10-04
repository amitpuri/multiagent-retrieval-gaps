"""
Range Collision Detector: Look-Alike Tests and Divergent Critical Thresholds.
Detects when unqualified orders (e.g. 'Calcium 4.8' or 'Troponin 15') span
look-alike assays with divergent clinical classifications (e.g. Critical Low vs Normal).
"""
from __future__ import annotations

from typing import Dict, List, Optional
from src.core.detectors.base import GapDetector
from src.core.models import (
    CollisionFamily,
    EvaluationContext,
    GapEvaluationResult,
    NumericAssay,
    ResolutionStatus,
)


class RangeCollisionDetector(GapDetector):
    """Detects divergent classifications across look-alike numeric tests."""

    @property
    def gap_name(self) -> str:
        return "Range Collision: Look-Alike Divergence"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.UNKNOWN,
                gap_name=self.gap_name,
                message="Registry not configured in RangeCollisionDetector",
            )

        if context.patient_value is None:
            # Not a numeric result or patient value not extracted
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message="No numeric patient value to evaluate for range collisions",
            )

        val = context.patient_value
        term = context.term.strip().lower()
        qualifier = context.qualifier.strip().lower()
        context_unit = context.unit.strip().lower()

        # Find applicable collision family — must match both term AND unit.
        # Fix 8: match by resolved concept URI first (if candidates were attached
        # to the context), then fall back to name-substring matching.
        # URI-based matching catches synonyms (e.g. "serum calcium" → same URI as
        # "Total calcium") that do not share a substring.
        context_uris: set = set(
            (context.metadata or {}).get("resolved_uris", [])
        )
        for c in (context.metadata or {}).get("candidates", []):
            if isinstance(c, dict) and "uri" in c:
                context_uris.add(c["uri"])
            elif isinstance(c, str):
                context_uris.add(c)
        if "resolved_concept" in (context.metadata or {}):
            rc = context.metadata["resolved_concept"]
            if isinstance(rc, dict) and "uri" in rc:
                context_uris.add(rc["uri"])

        active_family: Optional[CollisionFamily] = None
        for fam in self.registry.collision_families.values():
            # Unit gate: if the family declares a trigger_unit, only activate when
            # the reported unit matches.  An empty trigger_unit means unit-agnostic.
            fam_unit = fam.trigger_unit.strip().lower()
            if fam_unit and context_unit and fam_unit != context_unit:
                continue

            assay_objs = [
                self.registry.assays[a_id]
                for a_id in fam.assays
                if a_id in self.registry.assays
            ]

            # --- Fix 8: URI-first matching ---
            fam_uris: set = set(getattr(fam, "uris", []))
            if not fam_uris:
                fam_uris = {a.uri for a in assay_objs if getattr(a, "uri", None)}

            if fam_uris and context_uris and fam_uris.intersection(context_uris):
                active_family = fam
                break

            # Term match: name must exactly or partially overlap the query term.
            # Require a minimum overlap of 2 characters to avoid spurious matches
            # on very short terms like "ca".
            if any(
                (len(term) >= 2 and term in a.name.lower())
                or (len(a.name) >= 2 and a.name.lower() in term)
                for a in assay_objs
            ):
                active_family = fam
                break

        if not active_family:
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message="No range collision rules apply to this term/unit combination",
            )

        # Get relevant assays in this family
        family_assays: List[NumericAssay] = [
            self.registry.assays[a_id]
            for a_id in active_family.assays
            if a_id in self.registry.assays
        ]

        # If a specific qualifier was provided, filter down to matched assay
        if qualifier:
            matched_assays = [a for a in family_assays if a.matches_qualifier(qualifier)]
            if matched_assays:
                family_assays = matched_assays

        readings: Dict[str, str] = {a.name: a.classify(val) for a in family_assays}
        unique_classifications = set(readings.values())

        if len(unique_classifications) > 1:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.RANGE_COLLISION,
                gap_name=self.gap_name,
                message=(
                    f"Value {val} generates conflicting clinical interpretations "
                    f"across {active_family.family_name}: {readings}. Explicit qualifier required."
                ),
                details={
                    "family": active_family.family_name,
                    "readings": readings,
                    "value": val,
                    "unit": context.unit,
                },
            )

        return GapEvaluationResult(
            passed=True,
            status=ResolutionStatus.RESOLVED,
            gap_name=self.gap_name,
            message="Numeric value classified consistently without collision",
            details={"readings": readings, "value": val, "unit": context.unit},
        )
