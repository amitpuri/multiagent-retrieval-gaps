"""
Second-domain reuse proof (plan P13.8): the cardiology pack runs through the
unchanged gate, resolver, validator and skills with no edit to shared code or
role specs — only YAML under ontology/domains/cardiology and its domain skill.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import ontogate
from ontogate.config import get_default_registry, load_domain_config
from ontogate.detectors.engine import SafetyGateEngine
from ontogate.models import ResolutionStatus
from ontogate.paths import domain_dir
from ontogate.tools import evaluate_safety_gate, resolve_lab_term
from ontogate.validate import ERROR, check_registry

TNI, TNT = "loinc:10839-9", "loinc:6598-7"


@pytest.fixture(scope="module")
def cardio():
    return load_domain_config(domain_dir("cardiology"))


def test_pack_validates_cleanly(cardio):
    assert [str(i) for i in check_registry(cardio) if i.level == ERROR] == []


def test_packs_do_not_leak_into_each_other(cardio):
    lab = get_default_registry()
    assert TNI not in lab.concepts and "loinc:718-7" not in cardio.concepts


@pytest.mark.parametrize("term", ["cTn", "Troponin"])
def test_unqualified_troponin_is_ambiguous(cardio, term):
    result = resolve_lab_term(term, registry=cardio)
    assert result["status"] == ResolutionStatus.AMBIGUOUS.value
    assert {c["uri"] for c in result["candidates"]} == {TNI, TNT}


@pytest.mark.parametrize("term,uri", [("cTnI", TNI), ("Troponin I", TNI), ("cTnT", TNT), ("Troponin T", TNT)])
def test_qualified_troponin_resolves(cardio, term, uri):
    result = resolve_lab_term(term, registry=cardio)
    assert result["status"] == ResolutionStatus.RESOLVED.value
    assert [c["uri"] for c in result["candidates"]] == [uri]


def test_lookalike_relation_is_symmetric(cardio):
    assert TNT in cardio.concepts[TNI].confusable_with
    assert TNI in cardio.concepts[TNT].confusable_with


@pytest.mark.parametrize("term,unit,value,route", [
    ("cTnI", "ng/L", 12.0, "PROCEED"),
    ("cTnT", "ng/L", 30.0, "PROCEED"),
    ("cTn", "ng/L", 12.0, "CLARIFY"),
    ("cTn", "", None, "CLARIFY"),
    ("NT-proBNP", "ng/L", 300.0, "CLARIFY"),
])
def test_gate_routes_cardiology_queries(cardio, term, unit, value, route):
    status = resolve_lab_term(term, unit=unit, registry=cardio)["status"]
    gate = evaluate_safety_gate(term=term, unit=unit, patient_value=value, status=status, registry=cardio)
    assert gate["route"] == route


def test_fail_closed_routing_holds_for_every_status(cardio):
    engine = SafetyGateEngine(cardio)
    for status in ResolutionStatus:
        assert engine.route_for(status) == ("PROCEED" if status == ResolutionStatus.RESOLVED else "CLARIFY")


def test_shared_code_never_names_a_domain_pack():
    """Domain packs are configuration: no shared module may mention one."""
    root = Path(ontogate.__file__).parent
    offenders = [p.name for p in root.rglob("*.py") if "cardiology" in p.read_text(encoding="utf-8")]
    assert offenders == []
