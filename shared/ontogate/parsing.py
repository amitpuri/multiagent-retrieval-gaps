"""
Ontology-aware clinician input parser — the single parser every
framework delegates to.

Input shape: ``<term> [value] | <segment> | <segment> ...``. The left part
yields the term and an optional numeric value. Each pipe segment is classified
by vocabulary lookup, not by position:

=====================  =========================================  ==============
Segment                Lookup                                     Field
=====================  =========================================  ==============
``g/dL``, ``mmol/L``   core unit catalogue (or unit-shaped token) ``unit``
``total``, ``ica``     domain facet values / synonyms             ``qualifier``
``female``, ``adult``  population facets                          ``population``
``hemat``              Department entity (id/label/synonym)       ``department``
anything else          kept as a free qualifier (``I``, ``T``…)    ``qualifier``
=====================  =========================================  ==============

A term that names a panel (``CSF Emergency Panel``) sets ``panel_id``.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_VALUE = r"(?:^|(?<=\s))(-?\d+(?:\.\d+)?)(?![\w-])"
_UNIT_SHAPED = re.compile(r"^[^\s]*[/%][^\s]*$|^%$")


def _split_value(left: str) -> Dict[str, Any]:
    ambiguous_thousands = bool(re.search(r"\b\d+,\d{3}\b", left))
    patient_value: Optional[float] = None
    ambiguous_value = False
    normalised = left
    if not ambiguous_thousands:
        normalised = re.sub(r"(\d),(\d)", r"\1.\2", left)
        values = re.findall(_VALUE, normalised)
        if len(values) > 1:
            ambiguous_value = True
        elif values:
            patient_value = float(values[0])
    cleaned = re.sub(_VALUE, "", normalised).strip()
    return {
        "term": cleaned or left.strip(),
        "patient_value": patient_value,
        "ambiguous_thousands": ambiguous_thousands,
        "ambiguous_value": ambiguous_value,
    }


def parse_clinician_text(text: str, registry: Any = None) -> Dict[str, Any]:
    """Parse raw clinician text into structured, ontology-classified fields."""
    if registry is None:
        from ontogate.config import get_default_registry
        registry = get_default_registry()

    raw = text or ""
    left, *segments = [p.strip() for p in raw.split("|")]
    out = _split_value(left)
    out.update({"unit": "", "qualifier": "", "department": "", "panel_id": None,
                "population": {}, "unclassified": [], "raw_text": raw})

    free: List[str] = []
    for seg in segments:
        if not seg:
            continue
        if registry.unit(seg) is not None or (_UNIT_SHAPED.match(seg) and not out["unit"]):
            if not out["unit"]:
                out["unit"] = seg
                continue
        pop = registry.population_value(seg)
        if pop is not None:
            out["population"][pop[0]] = pop[1]
            if not out["qualifier"]:
                out["qualifier"] = seg.lower()
            continue
        if registry.facet_value(seg) is not None:
            if not out["qualifier"] or registry.population_value(out["qualifier"]) is not None:
                out["qualifier"] = seg.lower()
            continue
        if registry.department(seg) is not None:
            out["department"] = seg
            continue
        free.append(seg)

    # Inline unit: "Calcium 4.8 mg/dL" — a trailing catalogue unit in the term.
    if not out["unit"] and out["patient_value"] is not None:
        tokens = out["term"].split()
        if len(tokens) > 1 and registry.unit(tokens[-1]) is not None:
            out["unit"] = tokens[-1]
            out["term"] = " ".join(tokens[:-1])

    found = registry.find_panel(out["term"]) if out["term"] else None
    if found:
        out["panel_id"] = found[0]
        # "CSF Panel | hemat": the segment after a panel is a
        # department filter. A unit there is not a department: it fails closed
        # as an unknown department (NOT_FOUND) instead of being silently dropped.
        if not out["department"] and free:
            out["department"] = free.pop(0)
        elif not out["department"] and out["unit"]:
            out["department"], out["unit"] = out["unit"], ""

    # Remaining free segments: the first becomes the qualifier ("Troponin 15 | I");
    # without a unit, a lone free segment is still a qualifier, never a silent unit.
    for seg in free:
        if not out["qualifier"]:
            out["qualifier"] = seg.lower() if len(seg) > 1 else seg
        else:
            out["unclassified"].append(seg)
    return out
