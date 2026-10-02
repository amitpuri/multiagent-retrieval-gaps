"""
Missing Qualifier Detector: Detects orders requiring explicit qualifying attributes.
Flags when concepts require a qualifier (e.g. 'fasting/non-fasting' state for glucose,
'total' vs 'ionized' for calcium) but none was provided, preventing silent guessing.
"""

from src.core.detectors.base import GapDetector
from src.core.models import (
    EvaluationContext,
    GapEvaluationResult,
    ResolutionStatus,
)


class MissingQualifierDetector(GapDetector):
    """Detects concepts that require a qualifier when none is provided."""

    @property
    def gap_name(self) -> str:
        return "Gap 5: Missing Qualifier"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.UNKNOWN,
                gap_name=self.gap_name,
                message="OntologyRegistry is not configured in MissingQualifierDetector",
            )

        if context.qualifier.strip():
            # Qualifier already supplied; pass through
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message="Qualifier provided; missing qualifier check skipped",
            )

        term = context.term.strip()
        if not term:
            return GapEvaluationResult(
                passed=True,
                status=ResolutionStatus.RESOLVED,
                gap_name=self.gap_name,
                message="No term provided; missing qualifier check skipped",
            )

        # Check if any collision family is active for this term and requires a qualifier
        for fam in self.registry.collision_families.values():
            if not fam.default_qualifier_required:
                continue
            assay_objs = [
                self.registry.assays[a_id]
                for a_id in fam.assays
                if a_id in self.registry.assays
            ]
            # Term match: test if the entered term overlaps any assay in the family
            term_lc = term.lower()
            family_terms = set()
            for a in assay_objs:
                family_terms.add(a.name.lower())
                # Also check if term matches assay qualifiers
                family_terms.update(q.lower() for q in a.qualifiers)

            if any(term_lc in ft or ft in term_lc for ft in family_terms):
                if context.patient_value is not None:
                    # Numeric result present but no qualifier for a multi-assay family
                    available_qualifiers = sorted(
                        set(q for a in assay_objs for q in a.qualifiers)
                    )
                    return GapEvaluationResult(
                        passed=False,
                        status=ResolutionStatus.MISSING_QUALIFIER,
                        gap_name=self.gap_name,
                        message=(
                            f"Term '{term}' belongs to '{fam.family_name}' assay family which requires "
                            f"an explicit qualifier. Provide one of: {available_qualifiers}"
                        ),
                        details={
                            "family": fam.family_name,
                            "available_qualifiers": available_qualifiers,
                        },
                    )

        # Check concept-level qualifier requirements
        concepts = self.registry.find_concepts(term)
        for concept in concepts:
            qualifier_required = concept.attributes.get("qualifier_required", False)
            if qualifier_required:
                valid_qualifiers = concept.attributes.get("valid_qualifiers", [])
                return GapEvaluationResult(
                    passed=False,
                    status=ResolutionStatus.MISSING_QUALIFIER,
                    gap_name=self.gap_name,
                    message=(
                        f"Concept '{concept.label}' requires a qualifier. "
                        f"Valid qualifiers: {valid_qualifiers}"
                    ),
                    candidates=[concept.to_view()],
                    details={"valid_qualifiers": valid_qualifiers},
                )

        return GapEvaluationResult(
            passed=True,
            status=ResolutionStatus.RESOLVED,
            gap_name=self.gap_name,
            message="No qualifier requirement triggered for this term",
        )
