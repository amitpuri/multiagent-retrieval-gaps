"""
Deterministic clarification text, generated from a gate result and the ontology.

This is the fallback (and the offline) wording for every framework. The LLM
clarification coordinator may rephrase it under the ``clarification-dialogue``
skill, but the facts — which facet is missing, which values are allowed, what
the look-alike readings are — always come from here.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _fmt_value(value: Any, unit: str) -> str:
    if value is None:
        return ""
    v = int(value) if float(value).is_integer() else value
    return f"{v} {unit}".strip() if unit else f"{v} (unit not reported)"


def _candidate_line(c: Dict[str, Any]) -> str:
    parts = [p for p in (c.get("department"), ", ".join(c.get("expected_units") or [])) if p]
    name = c.get("name") or c.get("label") or c.get("uri", "?")
    return f"{name} ({'; '.join(parts)})" if parts else name


def build_clarification(
    status: str,
    message: str = "",
    candidates: Optional[List[Dict[str, Any]]] = None,
    details: Optional[Dict[str, Any]] = None,
    registry: Any = None,
) -> str:
    """Return one clinician-facing clarification for a non-RESOLVED gate result."""
    candidates = candidates or []
    details = details or {}
    if registry is None:
        from ontogate.config import get_default_registry
        registry = get_default_registry()
    missing: List[str] = list(details.get("missing") or [])

    if status == "RANGE_COLLISION":
        readings = details.get("readings") or {}
        shown = ", ".join(f"{k} → {v}" for k, v in readings.items())
        value = _fmt_value(details.get("value"), details.get("unit") or "")
        lines = [f"Range collision detected: value {value} is classified differently across look-alike tests: {shown}."]
        lines += _facet_questions(missing, registry)
        if "unit" in missing:
            lines.append(f"Also report the unit ({_units_of(candidates)}).")
        return " ".join(lines)

    if status == "MISSING_QUALIFIER":
        q = details.get("question")
        values = details.get("available_qualifiers") or []
        if not q and details.get("facet") in getattr(registry, "population_facets", {}):
            q = f"Which {details['facet'].replace('_', ' ')} applies?"
        q = q or "Which qualifier applies?"
        extra = ""
        if details.get("population_readings"):
            extra = " Readings by population: " + ", ".join(
                f"{k} → {v}" for k, v in details["population_readings"].items()) + "."
        return f"{q} Provide one of: {', '.join(values)}.{extra}"

    if status == "AMBIGUOUS" and details.get("contradiction"):
        return f"{details['contradiction']} Please send a consistent test name and qualifier."

    if status == "AMBIGUOUS":
        lines = ["Ambiguity detected: this term matches more than one test: "
                 + "; ".join(_candidate_line(c) for c in candidates) + "."]
        q = _facet_questions(missing, registry)
        lines += q or ["Which test was ordered?"]
        if "unit" in missing:
            lines.append("Report the unit — it identifies the test here.")
        return " ".join(lines)

    if status == "UNIT_MISMATCH":
        if details.get("reported_unit"):
            return (f"The unit '{details['reported_unit']}' is not valid for this test. "
                    f"Valid units: {_units_of(candidates)}.")
        return "A numeric value was sent without a unit. Report the unit so the correct scale is used."

    if status == "NOT_FOUND":
        return message or "No matching test was found. Please check the test name or department."

    return message or "Clarification required before this result can be interpreted."


def _units_of(candidates: List[Dict[str, Any]]) -> str:
    units: List[str] = []
    for c in candidates:
        for u in c.get("expected_units") or []:
            if u not in units:
                units.append(u)
    return ", ".join(units) or "see the test definition"


def _facet_questions(missing: List[str], registry: Any) -> List[str]:
    out = []
    for fid in missing:
        facet = registry.facets.get(fid) if registry is not None else None
        if facet is not None:
            out.append(f"{facet.question or facet.label} Provide one of: {', '.join(facet.values)}.")
    return out
