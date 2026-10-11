"""
Each integrity rule has a negative fixture proving it fires, and the shipped
pack + scenario overlays validate with zero errors.
"""
from __future__ import annotations

import copy
from typing import Any, Dict

import pytest

from ontogate.config import OntologyRegistry, apply_core, apply_pack, find_core_file, get_default_registry, read_core
from ontogate.paths import domain_dir, scenarios_dir
from ontogate.validate import ERROR, check_registry, validate_pack


def _base() -> Dict[str, Any]:
    return {
        "departments": {"dept:a": {"label": "A"}, "dept:b": {"label": "B"}},
        "analytes": {"x": {"label": "X"}},
        "facets": {"form": {"values": ["p", "q"]}},
        "observables": {
            "t:1": {"label": "One", "department": "dept:a", "measures": "x", "units": ["mg/dL"],
                    "axes": {"property": "MCnc", "scale": "Qn"}, "axes_verified": True,
                    "intervals_not_applicable": "fixture"},
            "t:2": {"label": "Two", "department": "dept:a", "measures": "x", "units": ["mg/dL"],
                    "axes": {"property": "MCnc", "scale": "Qn"}, "axes_verified": True,
                    "intervals_not_applicable": "fixture"},
        },
    }


def _codes(pack: Dict[str, Any]) -> set:
    reg = OntologyRegistry()
    apply_core(reg, read_core(find_core_file(None)))
    apply_pack(reg, pack)
    return {i.code for i in check_registry(reg) if i.level == ERROR}


def test_clean_fixture_has_no_errors():
    """The minimal fixture itself is valid (so each mutation isolates one rule)."""
    assert _codes(_base()) == set()


MUTATIONS = {
    "DANGLING_GOVERNED_BY": lambda p: p["observables"]["t:1"].update(governed_by="protocol:none"),
    "DANGLING_LINK": lambda p: p["observables"]["t:1"].update(links=[{"target_uri": "t:9", "kind": "see_also"}]),
    "UNKNOWN_ANALYTE": lambda p: p["observables"]["t:1"].update(measures="nope"),
    "UNKNOWN_FACET_VALUE": lambda p: p["observables"]["t:1"].update(facets={"form": "z"}),
    "UNKNOWN_UNIT": lambda p: p["observables"]["t:1"].update(units=["furlongs/fortnight"]),
    "UNIT_PROPERTY_CONFLICT": lambda p: p["observables"]["t:1"].update(units=["mg/dL", "mmol/L"]),
    "QN_WITHOUT_INTERVALS": lambda p: p["observables"]["t:1"].pop("intervals_not_applicable"),
    "UNCONTROLLED_DEPARTMENT": lambda p: p["observables"]["t:1"].update(department="Somewhere"),
    "SILENT_SYNONYMY": lambda p: p.update(designations={"amb": {"denotes": ["t:1", "t:2"], "kind": "synonym"}}),
    "FALSE_AMBIGUITY": lambda p: p.update(designations={"one": {"denotes": ["t:1"], "kind": "ambiguous"}}),
    "DESIGNATION_DANGLING": lambda p: p.update(designations={"ghost": {"denotes": ["t:9"], "kind": "synonym"}}),
    "INTERVAL_ORDER": lambda p: p.update(reference_intervals=[{
        "id": "i:1", "observable": "t:1", "unit": "mg/dL", "normal": [5, 4], "critical": [1, 9]}]),
    "INTERVAL_UNIT": lambda p: p.update(reference_intervals=[{
        "id": "i:1", "observable": "t:1", "unit": "g/L", "normal": [1, 2], "critical": [0.5, 3]}]),
    "PROVENANCE_CONTRADICTION": lambda p: p.update(reference_intervals=[{
        "id": "i:1", "observable": "t:1", "unit": "mg/dL", "normal": [1, 2], "critical": [0.5, 3],
        "verified_by": "human:reviewer", "clinically_unvalidated": True}]),
    "STEP_DEPARTMENT": lambda p: p.update(panels={"pn": {"name": "P", "steps": [
        {"id": "s:1", "tube": 1, "department": "dept:b", "includes": ["t:1"]}]}}),
    "PRECEDES_CYCLE": lambda p: p.update(panels={"pn": {"name": "P", "steps": [
        {"id": "s:1", "tube": 1, "department": "dept:a", "includes": ["t:1"], "precedes": "s:2"},
        {"id": "s:2", "tube": 2, "department": "dept:a", "includes": ["t:2"], "precedes": "s:1"}]}}),
}


@pytest.mark.parametrize("code", sorted(MUTATIONS))
def test_rule_fires_on_its_negative_fixture(code):
    """Each integrity rule detects the defect it exists for."""
    pack = copy.deepcopy(_base())
    MUTATIONS[code](pack)
    assert code in _codes(pack)


def test_symmetric_confusable_is_materialised():
    """confusable_with declared on one side is materialised on the other (no asymmetric error)."""
    pack = copy.deepcopy(_base())
    pack["observables"]["t:1"]["confusable_with"] = ["t:2"]
    reg = OntologyRegistry()
    apply_pack(reg, pack)
    assert "t:1" in reg.concepts["t:2"].confusable_with


def test_shipped_pack_and_scenarios_validate():
    """The released laboratory_medicine pack and every scenario overlay have zero integrity errors."""
    issues = validate_pack(domain_dir(), sorted(scenarios_dir().glob("*.yaml")))
    errors = [str(i) for i in issues if i.level == ERROR]
    assert errors == []


def test_designations_are_reflected_in_alt_labels():
    """Every designation appears as an alt_label on each observable it denotes."""
    reg = get_default_registry()
    assert "calcium" in reg.concepts["loinc:17861-6"].alt_labels
    assert "calcium" in reg.concepts["loinc:17864-0"].alt_labels
    assert "ica" in reg.concepts["loinc:17864-0"].alt_labels
    assert "ica" not in reg.concepts["loinc:17861-6"].alt_labels
