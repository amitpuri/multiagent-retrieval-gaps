"""
Semantic-web layer: both packs conform to the SHACL shapes, every shape has a
failing fixture, OWL 2 RL materialises the declared characteristics, SPARQL
answers competency questions, and the bundle is hashed and fail-closed.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("rdflib")
pytest.importorskip("pyshacl")
pytest.importorskip("owlrl")

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF

from ontogate import rdf_export as rx
from ontogate.config import get_default_registry, load_domain_config
from ontogate.paths import domain_dir
from ontogate.roles import load_all_role_specs
from ontogate.skills import load_lock, load_skills

AG = rx.Namespace(rx.AG_NS)
KB = rx.Namespace(rx.KB_NS)
LOINC = rx.Namespace(rx.LOINC_NS)
HB, HBA1C, TCA, ICA = LOINC["718-7"], LOINC["4548-4"], LOINC["17861-6"], LOINC["17864-0"]


def _graph(reg=None, agents=True) -> Graph:
    reg = reg or get_default_registry()
    g = rx.build_ontology_graph(reg)
    if agents:
        rx.add_agent_graph(g, load_all_role_specs(), load_skills(), load_lock(), domains=reg.domains)
    return g


@pytest.fixture(scope="module")
def lab_graph() -> Graph:
    return _graph()


@pytest.fixture
def g(lab_graph) -> Graph:
    copy = Graph()
    for prefix, ns in lab_graph.namespaces():
        copy.bind(prefix, ns)
    for t in lab_graph:
        copy.add(t)
    return copy


def _messages(graph: Graph):
    return [v["message"] for v in rx.validate_shacl(graph)["violations"]]


# --------------------------------------------------------------------------- conformance
def test_lab_medicine_with_agents_conforms(lab_graph):
    result = rx.validate_shacl(lab_graph)
    assert result["violations"] == [] and result["conforms"]


def test_cardiology_pack_conforms():
    result = rx.validate_shacl(_graph(load_domain_config(domain_dir("cardiology"))))
    assert result["violations"] == []


def test_tbox_follows_the_core_relation_catalogue(lab_graph):
    assert (AG.confusableWith, RDF.type, OWL.SymmetricProperty) in lab_graph
    assert (AG.confusableWith, RDF.type, OWL.IrreflexiveProperty) in lab_graph
    assert (AG.governedBy, RDF.type, OWL.FunctionalProperty) in lab_graph
    assert (AG.precedes, RDF.type, OWL.TransitiveProperty) in lab_graph
    # OWL 2 DL: no asymmetry on a transitive property (acyclicity is a SHACL rule instead).
    assert (AG.precedes, RDF.type, OWL.AsymmetricProperty) not in lab_graph
    assert (AG.intervalOf, OWL.inverseOf, AG.hasInterval) in lab_graph


# --------------------------------------------------------------------------- one failing fixture per shape
def _interval(g: Graph) -> URIRef:
    return next(s for s in g.subjects(AG.intervalOf, HB))


def test_interval_bounds_order(g):
    iv = _interval(g)
    g.set((iv, AG.normalLow, Literal(99.0)))
    assert any("criticalLow < normalLow" in m for m in _messages(g))


def test_interval_unit_must_be_admitted(g):
    g.set((_interval(g), AG.unit, KB["unit/mmol%2FL"]))
    assert any("not admitted" in m for m in _messages(g))


def test_provenance_contradiction(g):
    iv = _interval(g)
    g.add((iv, rx.PROV.wasAttributedTo, Literal("human:dr.lab")))
    g.set((iv, AG.clinicallyUnvalidated, Literal(True)))
    assert any("ProvenanceShape" in m for m in _messages(g))


def test_confusable_irreflexive(g):
    g.add((HB, AG.confusableWith, HB))
    assert any("irreflexive" in m for m in _messages(g))


def test_confusable_symmetric(g):
    g.add((TCA, AG.confusableWith, HB))
    assert any("symmetric" in m for m in _messages(g))


def test_quantitative_observable_needs_intervals(g):
    for iv in list(g.subjects(AG.intervalOf, HB)):
        g.remove((iv, None, None))
    assert any("Qn" in m for m in _messages(g))


def test_silent_synonymy(g):
    hb = KB["designation/hb"]
    g.set((hb, AG.kind, Literal("synonym")))
    assert any("Silent synonymy" in m for m in _messages(g))


def test_false_ambiguity(g):
    hb = KB["designation/hb"]
    g.remove((hb, AG.denotes, HBA1C))
    assert any("False ambiguity" in m for m in _messages(g))


def test_precedes_acyclic(g):
    first = KB["step/step_csf-tube-1"]
    last = KB["step/step_csf-tube-3"]
    g.add((last, AG.precedes, first))
    assert any("acyclic" in m for m in _messages(g))


def test_step_department_consistency(g):
    g.set((KB["step/step_csf-tube-1"], AG.inDepartment, KB["department/dept_hematology"]))
    assert any("different department" in m for m in _messages(g))


def test_protocol_governs_one_observable(g):
    protocol = next(g.objects(HB, AG.governedBy))
    g.add((HBA1C, AG.governedBy, protocol))
    assert any("governs a different observable" in m or "at most one" in m for m in _messages(g))


def test_dangling_reference_is_caught_by_sh_class(g):
    g.add((HB, AG.confusableWith, LOINC["0000-0"]))
    g.add((LOINC["0000-0"], AG.confusableWith, HB))
    assert any("existing observable" in m for m in _messages(g))


def test_header_needs_bundle_hash(g):
    ont = next(g.subjects(RDF.type, OWL.Ontology))
    g.set((ont, AG.bundleSha256, Literal("unset")))
    assert any("bundleSha256" in m for m in _messages(g))


def test_role_skill_tool_grant(g):
    g.remove((KB["role/ontology_resolver"], AG.grantedTool, KB["tool/resolve_lab_term"]))
    assert any("not granted" in m for m in _messages(g))


def test_code_node_uses_no_skills(g):
    g.add((KB["role/safety_guard"], AG.usesSkill, KB["skill/clinical-triage"]))
    assert any("code node" in m for m in _messages(g))


def test_non_canonical_tool(g):
    g.add((KB["role/triage_orchestrator"], AG.grantedTool, KB["tool/shell_exec"]))
    assert any("ToolShape" in m for m in _messages(g))


def test_clinical_skill_without_scripts(g):
    g.set((KB["skill/clinical-triage"], AG.hasScripts, Literal(True)))
    assert any("scripts" in m for m in _messages(g))


def test_skill_locked_against_another_bundle(g):
    g.set((KB["skill/clinical-triage"], AG.derivedFromBundle, Literal("f" * 64)))
    assert any("locked against bundle" in m for m in _messages(g))


# --------------------------------------------------------------------------- OWL 2 RL
def test_owl_rl_materialises_symmetry_and_inverses(g):
    g.remove((ICA, AG.confusableWith, TCA))
    iv = _interval(g)
    assert (HB, AG.hasInterval, iv) not in g
    rx.apply_owl_reasoning(g)
    assert (ICA, AG.confusableWith, TCA) in g
    assert (HB, AG.hasInterval, iv) in g


# --------------------------------------------------------------------------- SPARQL competency questions
def test_cq_ambiguous_designations(lab_graph):
    rows = rx.query(lab_graph, """
        SELECT DISTINCT ?text WHERE {
            ?d a ag:Designation ; skosxl:literalForm ?text ; ag:denotes ?a , ?b . FILTER (?a != ?b)
        }""")
    expected = {d.text for d in get_default_registry().designations.values() if d.is_ambiguous}
    assert {r["text"] for r in rows} == expected


def test_cq_lookalikes_of_hemoglobin(lab_graph):
    rows = rx.query(lab_graph, """
        SELECT ?other WHERE { <https://loinc.org/718-7> ag:confusableWith ?other }""")
    assert {r["other"] for r in rows} == {str(HBA1C)}


def test_cq_role_skills(lab_graph):
    rows = rx.query(lab_graph, """
        SELECT ?skill WHERE { kb:role/ontology_resolver ag:usesSkill ?s . ?s ag:skillName ?skill }""".replace(
        "kb:role/ontology_resolver", f"<{KB['role/ontology_resolver']}>"))
    assert {r["skill"] for r in rows} == {"lab-term-resolution", "domain-laboratory-medicine"}


# --------------------------------------------------------------------------- bundle
def test_bundle_is_hashed_and_round_trips(tmp_path):
    reg = get_default_registry()
    manifest = rx.build_ontology_bundle(reg, tmp_path, owl_rl=False, roles=load_all_role_specs(),
                                        skills=load_skills(), lock=load_lock())
    assert manifest["bundle_sha256"] == rx.source_bundle_sha256()
    on_disk = json.loads((tmp_path / "bundle.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    for name, digest in manifest["files"].items():
        assert rx.hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest
    reparsed = Graph().parse(tmp_path / "ontology.ttl", format="turtle")
    assert len(reparsed) == manifest["triples"]


def test_bundle_fails_closed_on_shacl_violation(tmp_path, monkeypatch):
    original = rx.build_ontology_graph

    def broken(reg, **kwargs):
        graph = original(reg, **kwargs)
        graph.add((HB, AG.confusableWith, HB))
        return graph

    monkeypatch.setattr(rx, "build_ontology_graph", broken)
    with pytest.raises(ValueError, match="SHACL"):
        rx.build_ontology_bundle(get_default_registry(), tmp_path)
    assert not (tmp_path / "bundle.json").exists()
