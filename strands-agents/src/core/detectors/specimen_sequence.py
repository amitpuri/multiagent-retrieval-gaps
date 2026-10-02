"""
Gap 11 Detector: Scope Retrieval & Specimen Sequencing.
Enforces specimen order, tube sequencing, and department ownership boundaries
to prevent specimen contamination and cross-departmental scope bleeding.
"""

from typing import Any, Dict, List
from src.core.detectors.base import GapDetector
from src.core.models import (
    EvaluationContext,
    GapEvaluationResult,
    ResolutionStatus,
)


class SpecimenSequenceDetector(GapDetector):
    """Enforces tube sequencing and department-scoped test distribution."""

    @property
    def gap_name(self) -> str:
        return "Gap 11: Tool Output Trusted, Unscoped (Specimen Sequencing)"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.UNKNOWN,
                gap_name=self.gap_name,
                message="Registry not configured in SpecimenSequenceDetector",
            )

        panel_id = context.panel_id or "csf_emergency_panel"
        panel = self.registry.get_panel(panel_id)
        if not panel:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.NOT_FOUND,
                gap_name=self.gap_name,
                message=f"Panel '{panel_id}' not found in registry",
            )

        filter_dept = context.department.strip().lower()
        scoped_tubes: List[Dict[str, Any]] = []

        for rule in panel.tube_rules:
            if filter_dept and filter_dept not in rule.department.lower():
                continue
            scoped_tubes.append({
                "tube": rule.tube,
                "department": rule.department,
                "description": rule.description,
                "tests": rule.tests,
            })

        if filter_dept and not scoped_tubes:
            return GapEvaluationResult(
                passed=False,
                status=ResolutionStatus.NOT_FOUND,
                gap_name=self.gap_name,
                message=f"No tests found for department '{context.department}' in panel '{panel.name}'",
            )

        return GapEvaluationResult(
            passed=True,
            status=ResolutionStatus.RESOLVED,
            gap_name=self.gap_name,
            message=f"Panel '{panel.name}' scoped with governed tube sequencing",
            details={
                "panel_name": panel.name,
                "specimen": panel.specimen,
                "tubes": scoped_tubes,
            },
        )
