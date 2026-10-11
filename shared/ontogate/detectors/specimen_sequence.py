"""
Gap 11: unscoped tool output — specimen sequencing and department ownership.

A panel's collection steps are returned in their governed ``precedes`` order,
optionally scoped to one Department entity. The department is matched by id,
controlled label or declared synonym — never by substring.
"""
from __future__ import annotations

from typing import Any, Dict, List

from ontogate.detectors.base import GapDetector
from ontogate.models import EvaluationContext, GapEvaluationResult, ResolutionStatus


def ordered_steps(panel) -> List[Any]:
    """Return tube rules in ``precedes`` order (falls back to tube number)."""
    rules = list(panel.tube_rules)
    by_id = {r.id: r for r in rules if r.id}
    targets = {r.precedes for r in rules if r.precedes}
    heads = [r for r in rules if r.id and r.id not in targets]
    if by_id and len(heads) == 1:
        order, seen, cur = [], set(), heads[0]
        while cur is not None and cur.id not in seen:
            order.append(cur)
            seen.add(cur.id)
            cur = by_id.get(cur.precedes) if cur.precedes else None
        if len(order) == len(rules):
            return order
    return sorted(rules, key=lambda r: r.tube)


class SpecimenSequenceDetector(GapDetector):
    """Enforces tube sequencing and department-scoped test distribution."""

    @property
    def gap_name(self) -> str:
        return "Gap 11: Tool Output Trusted, Unscoped (Specimen Sequencing)"

    def evaluate(self, context: EvaluationContext) -> GapEvaluationResult:
        if not self.registry:
            return self._no_registry()
        if not context.panel_id:
            return self._pass("No panel_id in context; specimen sequencing check skipped")

        panel = self.registry.get_panel(context.panel_id)
        if not panel:
            found = self.registry.find_panel(context.panel_id)
            panel = found[1] if found else None
        if not panel:
            return GapEvaluationResult(passed=False, status=ResolutionStatus.NOT_FOUND, gap_name=self.gap_name,
                                       message=f"Panel '{context.panel_id}' not found in registry")

        wanted = context.department.strip()
        dept = self.registry.department(wanted) if wanted else None
        if wanted and dept is None:
            return GapEvaluationResult(
                passed=False, status=ResolutionStatus.NOT_FOUND, gap_name=self.gap_name,
                message=f"No tests found for department '{context.department}' in panel '{panel.name}'",
            )

        scoped: List[Dict[str, Any]] = []
        for rule in ordered_steps(panel):
            if dept is not None and rule.department_id not in (None, dept.id) and rule.department != dept.label:
                continue
            if dept is not None and rule.department_id is None and rule.department != dept.label:
                continue
            scoped.append({"tube": rule.tube, "department": rule.department,
                           "description": rule.description, "tests": rule.tests})

        if wanted and not scoped:
            return GapEvaluationResult(
                passed=False, status=ResolutionStatus.NOT_FOUND, gap_name=self.gap_name,
                message=f"No tests found for department '{context.department}' in panel '{panel.name}'",
            )
        return self._pass(f"Panel '{panel.name}' scoped with governed tube sequencing",
                          panel_name=panel.name, specimen=panel.specimen, tubes=scoped)
