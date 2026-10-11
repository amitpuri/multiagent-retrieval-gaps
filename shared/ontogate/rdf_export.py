"""
Semantic-web layer: SKOS / SKOS-XL / OWL 2 / PROV-O export, SHACL validation,
OWL 2 RL materialisation and the ontology bundle.

The YAML packs stay the authoring format; this module is the formal view of
the same knowledge. The TBox (classes, object properties and their OWL
characteristics) is generated from the core ontology's relation catalogue;
the ABox holds the loaded domain instances. Agent roles, skills and tools can
be added as an ``ag:`` meta-graph so the RoleSkillShape is a SHACL check.

    ontogate rdf export [--owl-rl]       # dist/bundle/ontology.{ttl,jsonld,rdf} + bundle.json
    ontogate rdf validate                # SHACL over the loaded pack (+ roles and skills)

Requires the ``rdf`` extra: ``pip install 'ontogate[rdf]'`` (rdflib, pyshacl, owlrl).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import quote

from ontogate.config import OntologyRegistry
from ontogate.models import TrustTier
from ontogate.paths import ontology_dir, repo_root
from ontogate.ports import sha256_tree

try:
    from rdflib import Graph, Literal, Namespace, URIRef
    from rdflib.namespace import OWL, PROV, RDF, RDFS, SKOS, XSD
    HAS_RDFLIB = True
except ImportError:  # the [rdf] extra is optional for runtimes
    HAS_RDFLIB = False

AG_NS = "https://ontogate.ai/ns/core#"
KB_NS = "https://ontogate.ai/kb/"
LOINC_NS = "https://loinc.org/"
SKOSXL_NS = "http://www.w3.org/2008/05/skos-xl#"
FORMATS = {"turtle": ".ttl", "json-ld": ".jsonld", "xml": ".rdf"}

# Classes of the core ontology (relation domains/ranges refer to these names).
CORE_CLASSES = {
    "Observable": "A LOINC-coded observable (what is measured, in which system, on which scale).",
    "Designation": "A clinician term that denotes one or more observables.",
    "ReferenceInterval": "Normal and critical bounds for one observable, unit and population.",
    "Protocol": "A clinical protocol governing exactly one observable.",
    "Facet": "A differentiating dimension between sibling observables.",
    "Analyte": "The substance an observable measures.",
    "Unit": "A UCUM unit with its dimension and scale factor.",
    "Department": "The laboratory department an observable or collection step is routed to.",
    "Specimen": "A specimen type (LOINC System axis).",
    "Panel": "An ordered set of collection steps.",
    "CollectionStep": "One tube / aliquot of a panel.",
    "TrustTier": "OKF trust tier derived from verification provenance.",
    "Role": "An agent role declared in agents/<role>.yaml.",
    "SkillPackage": "A first-party, hash-locked runtime skill.",
    "Tool": "A deterministic function of the canonical MCP contract.",
}


def _require_rdflib() -> None:
    if not HAS_RDFLIB:
        raise ImportError("RDF export needs the rdf extra: pip install 'ontogate[rdf]' (rdflib, pyshacl, owlrl)")


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p.title() for p in rest)


class _Ns:
    """Namespaces, created lazily so importing this module never needs rdflib."""

    def __init__(self) -> None:
        _require_rdflib()
        self.AG = Namespace(AG_NS)
        self.KB = Namespace(KB_NS)
        self.LOINC = Namespace(LOINC_NS)
        self.SKOSXL = Namespace(SKOSXL_NS)

    def kb(self, kind: str, ident: str) -> URIRef:
        return self.KB[f"{kind}/{quote(str(ident).replace(':', '_'), safe='')}"]

    def observable(self, uri: str) -> URIRef:
        return self.LOINC[uri.split(":", 1)[1]] if uri.startswith("loinc:") else self.kb("observable", uri)

    def tier(self, tier: TrustTier) -> URIRef:
        return self.AG[f"tier-{tier.value}"]


def _bind(g: "Graph", ns: _Ns) -> None:
    for prefix, namespace in (("ag", ns.AG), ("kb", ns.KB), ("loinc", ns.LOINC), ("skos", SKOS),
                              ("skosxl", ns.SKOSXL), ("owl", OWL), ("prov", PROV), ("xsd", XSD)):
        g.bind(prefix, namespace)


def source_bundle_sha256() -> str:
    """Content hash of the ontology sources (the bundle identity)."""
    return sha256_tree(ontology_dir())


# --------------------------------------------------------------------------- TBox
def _add_tbox(g: "Graph", reg: OntologyRegistry, ns: _Ns) -> None:
    AG = ns.AG
    for name, comment in CORE_CLASSES.items():
        g.add((AG[name], RDF.type, OWL.Class))
        g.add((AG[name], RDFS.comment, Literal(comment, lang="en")))
    g.add((AG.Observable, RDFS.subClassOf, SKOS.Concept))
    g.add((AG.Designation, RDFS.subClassOf, ns.SKOSXL.Label))
    for tier in TrustTier:
        g.add((ns.tier(tier), RDF.type, AG.TrustTier))
        g.add((ns.tier(tier), RDFS.label, Literal(tier.value)))

    def cls(name: str) -> URIRef:
        return OWL.Thing if name == "Thing" else AG[name]

    for rel, spec in sorted(reg.relations.items()):
        prop = AG[_camel(rel)]
        g.add((prop, RDF.type, OWL.ObjectProperty))
        g.add((prop, RDFS.label, Literal(rel)))
        if spec.get("domain"):
            g.add((prop, RDFS.domain, cls(spec["domain"])))
        if spec.get("range"):
            g.add((prop, RDFS.range, cls(spec["range"])))
        for flag, owl_type in (("symmetric", OWL.SymmetricProperty), ("irreflexive", OWL.IrreflexiveProperty),
                               ("functional", OWL.FunctionalProperty), ("transitive", OWL.TransitiveProperty)):
            if spec.get(flag):
                g.add((prop, RDF.type, owl_type))
        # OWL 2 DL forbids asymmetry on a transitive (non-simple) property; the
        # SequenceShape enforces acyclicity of such relations instead.
        if spec.get("asymmetric") and not spec.get("transitive"):
            g.add((prop, RDF.type, OWL.AsymmetricProperty))
        if spec.get("inverse"):
            inverse = AG[_camel(spec["inverse"])]
            g.add((inverse, RDF.type, OWL.ObjectProperty))
            g.add((inverse, RDFS.label, Literal(spec["inverse"])))
            g.add((inverse, OWL.inverseOf, prop))
        if spec.get("informational"):
            g.add((prop, RDFS.subPropertyOf, RDFS.seeAlso))


# --------------------------------------------------------------------------- ABox
def _lit_double(value: Optional[float]):
    return None if value is None else Literal(float(value), datatype=XSD.double)


def _add_abox(g: "Graph", reg: OntologyRegistry, ns: _Ns, scheme: URIRef) -> None:
    AG, KB = ns.AG, ns.KB

    for code, unit in sorted(reg.units.items()):
        u = ns.kb("unit", code)
        g.add((u, RDF.type, AG.Unit))
        g.add((u, SKOS.notation, Literal(code)))
        g.add((u, AG.dimension, Literal(unit.dimension)))
        g.add((u, AG.scaleFactor, Literal(float(unit.factor), datatype=XSD.double)))
    for did, dept in sorted(reg.departments.items()):
        d = ns.kb("department", did)
        g.add((d, RDF.type, AG.Department))
        g.add((d, RDFS.label, Literal(dept.label, lang="en")))
    for sid, spec in sorted(reg.specimens.items()):
        s = ns.kb("specimen", sid)
        g.add((s, RDF.type, AG.Specimen))
        g.add((s, RDFS.label, Literal(spec.label, lang="en")))
    for aid, analyte in sorted(reg.analytes.items()):
        a = ns.kb("analyte", aid)
        g.add((a, RDF.type, AG.Analyte))
        g.add((a, RDFS.label, Literal(analyte.label, lang="en")))
    for fid, facet in sorted({**reg.facets, **reg.population_facets}.items()):
        f = ns.kb("facet", fid)
        g.add((f, RDF.type, AG.Facet))
        g.add((f, RDFS.label, Literal(facet.label or fid, lang="en")))
        for value in facet.values:
            g.add((f, AG.allowedValue, Literal(value)))

    for node_id, proto in sorted(reg.protocol_nodes.items()):
        p = ns.kb("protocol", node_id)
        g.add((p, RDF.type, AG.Protocol))
        g.add((p, RDFS.label, Literal(node_id)))
        g.add((p, AG.status, Literal(proto.status)))
        if proto.governs:
            g.add((p, AG.governs, ns.observable(proto.governs)))
        if proto.clinical_guideline:
            g.add((p, PROV.wasDerivedFrom, Literal(proto.clinical_guideline)))
        if proto.stale_after:
            g.add((p, AG.staleAfter, Literal(proto.stale_after.isoformat(), datatype=XSD.dateTime)))
        if proto.verified_by:
            g.add((p, PROV.wasAttributedTo, Literal(proto.verified_by)))

    for uri, c in sorted(reg.concepts.items()):
        o = ns.observable(uri)
        g.add((o, RDF.type, AG.Observable))
        g.add((o, SKOS.inScheme, scheme))
        g.add((o, SKOS.notation, Literal(uri)))
        g.add((o, SKOS.prefLabel, Literal(c.name, lang="en")))
        if c.label != c.name:
            g.add((o, SKOS.definition, Literal(c.label, lang="en")))
        g.add((o, AG.status, Literal(c.status)))
        if c.status == "deprecated":
            g.add((o, OWL.deprecated, Literal(True)))
        g.add((o, AG.trustTier, ns.tier(c.trust_tier)))
        for code in c.units:
            g.add((o, AG.admitsUnit, ns.kb("unit", code)))
        if c.department_id:
            g.add((o, AG.inDepartment, ns.kb("department", c.department_id)))
        if c.specimen_id:
            g.add((o, AG.onSpecimen, ns.kb("specimen", c.specimen_id)))
        if c.measures:
            g.add((o, AG.measures, ns.kb("analyte", c.measures)))
        if c.governed_by:
            g.add((o, AG.governedBy, ns.kb("protocol", c.governed_by)))
        if c.superseded_by:
            g.add((o, AG.supersededBy, ns.observable(c.superseded_by)))
        for other in c.confusable_with:
            g.add((o, AG.confusableWith, ns.observable(other)))
        for fid, value in sorted(c.facets.items()):
            g.add((o, AG.differentiatedBy, ns.kb("facet", fid)))
            g.add((o, AG.facetValue, Literal(f"{fid}={value}")))
        for axis, value in sorted(c.axes.items()):
            g.add((o, AG[f"loinc{axis.title()}"], Literal(value)))
        if c.intervals_not_applicable:
            g.add((o, AG.intervalsNotApplicable, Literal(c.intervals_not_applicable, lang="en")))
        for link in c.links:
            if link.kind.value == "see_also":
                g.add((o, AG.seeAlso, ns.observable(link.target_uri)))
        if c.stale_after:
            g.add((o, AG.staleAfter, Literal(c.stale_after.isoformat(), datatype=XSD.dateTime)))
        if c.generated_by:
            g.add((o, PROV.wasGeneratedBy, Literal(c.generated_by)))
        if c.verified_by:
            g.add((o, PROV.wasAttributedTo, Literal(c.verified_by)))

    for text, d in sorted(reg.designations.items()):
        n = ns.kb("designation", text)
        g.add((n, RDF.type, AG.Designation))
        g.add((n, ns.SKOSXL.literalForm, Literal(d.text, lang="en")))
        g.add((n, AG.kind, Literal(d.kind)))
        for uri in d.denotes:
            g.add((n, AG.denotes, ns.observable(uri)))
            if len(d.denotes) == 1:
                g.add((ns.observable(uri), SKOS.altLabel, Literal(d.text, lang="en")))

    for interval in sorted(reg.intervals, key=lambda i: i.id):
        i = ns.kb("interval", interval.id)
        g.add((i, RDF.type, AG.ReferenceInterval))
        g.add((i, AG.intervalOf, ns.observable(interval.observable)))
        g.add((i, AG.unit, ns.kb("unit", interval.unit)))
        for prop, value in (("normalLow", interval.normal[0]), ("normalHigh", interval.normal[1]),
                            ("criticalLow", interval.critical[0]), ("criticalHigh", interval.critical[1])):
            if value is not None:
                g.add((i, AG[prop], _lit_double(value)))
        for key, value in sorted(interval.population.items()):
            if value != "any":
                g.add((i, AG.population, Literal(f"{key}={value}")))
        g.add((i, AG.trustTier, ns.tier(interval.trust_tier)))
        g.add((i, AG.clinicallyUnvalidated, Literal(bool(interval.clinically_unvalidated))))
        if interval.verified_by:
            g.add((i, PROV.wasAttributedTo, Literal(interval.verified_by)))
        if interval.generated_by:
            g.add((i, PROV.wasGeneratedBy, Literal(interval.generated_by)))

    for pid, panel in sorted(reg.panels.items()):
        p = ns.kb("panel", pid)
        g.add((p, RDF.type, AG.Panel))
        g.add((p, SKOS.prefLabel, Literal(panel.name, lang="en")))
        for step in panel.tube_rules:
            s = ns.kb("step", step.id or f"{pid}-{step.tube}")
            g.add((s, RDF.type, AG.CollectionStep))
            g.add((p, AG.hasStep, s))
            g.add((s, AG.stepNumber, Literal(step.tube)))
            if step.department_id:
                g.add((s, AG.inDepartment, ns.kb("department", step.department_id)))
            for uri in step.includes:
                g.add((s, AG.includes, ns.observable(uri)))
            if step.precedes:
                g.add((s, AG.precedes, ns.kb("step", step.precedes)))


def add_agent_graph(g: "Graph", roles: Dict[str, Any], skills: Dict[str, Any],
                    lock: Optional[Dict[str, Any]] = None, domains: Optional[Iterable[str]] = None) -> "Graph":
    """Add the ``ag:`` meta-graph: roles, skills, tools and their grants (plan §8.6).

    ``domains`` are the packs being served (roles with ``domain_skills`` load
    their domain skills); default: the configured pack.
    """
    from ontogate.skills import CANONICAL_MCP_TOOLS, skill_names_for_role
    ns = _Ns()
    AG = ns.AG
    for tool in sorted(CANONICAL_MCP_TOOLS):
        t = ns.kb("tool", tool)
        g.add((t, RDF.type, AG.Tool))
        g.add((t, AG.deterministic, Literal(True)))
    lock_skills = (lock or {}).get("skills", {})
    for name, skill in sorted(skills.items()):
        s = ns.kb("skill", name)
        g.add((s, RDF.type, AG.SkillPackage))
        g.add((s, AG.skillName, Literal(name)))
        g.add((s, AG.riskClass, Literal(skill.risk_class)))
        g.add((s, AG.version, Literal(skill.version)))
        g.add((s, AG.hasScripts, Literal((skill.path / "scripts").exists())))
        for tool in skill.allowed_tools:
            g.add((s, AG.requiresTool, ns.kb("tool", tool)))
        if lock is not None:
            g.add((s, AG.derivedFromBundle, Literal(lock.get("bundle_sha256", ""))))
            if name not in lock_skills:
                g.add((s, AG.unlocked, Literal(True)))
    domains = list(domains) if domains is not None else None
    for role, spec in sorted(roles.items()):
        r = ns.kb("role", role)
        g.add((r, RDF.type, AG.Role))
        g.add((r, RDFS.label, Literal(role)))
        g.add((r, AG.usesModel, Literal(bool(spec.uses_model))))
        for tool in spec.tools:
            g.add((r, AG.grantedTool, ns.kb("tool", tool)))
        for target in spec.delegates:
            g.add((r, AG.delegatesTo, ns.kb("role", target)))
        for name in skill_names_for_role(spec, domains):
            g.add((r, AG.usesSkill, ns.kb("skill", name)))
    return g


def build_ontology_graph(reg: OntologyRegistry, *, bundle_sha256: Optional[str] = None,
                         version: str = "1.0.0", label: Optional[str] = None) -> "Graph":
    """The formal (RDF) view of a loaded registry: TBox + ABox + ontology header."""
    ns = _Ns()
    g = Graph()
    _bind(g, ns)
    domain_ids = sorted(reg.domains) or ["core"]
    ont = URIRef(f"https://ontogate.ai/ontology/{'+'.join(domain_ids)}")
    g.add((ont, RDF.type, OWL.Ontology))
    g.add((ont, OWL.versionInfo, Literal(version)))
    g.add((ont, RDFS.label, Literal(label or ", ".join(str(reg.domains.get(d, {}).get("label", d))
                                                       for d in domain_ids), lang="en")))
    g.add((ont, ns.AG.bundleSha256, Literal(bundle_sha256 or source_bundle_sha256())))
    scheme = ns.kb("scheme", "+".join(domain_ids))
    g.add((scheme, RDF.type, SKOS.ConceptScheme))
    g.add((scheme, SKOS.prefLabel, Literal(f"ontogate {'+'.join(domain_ids)}", lang="en")))
    _add_tbox(g, reg, ns)
    _add_abox(g, reg, ns, scheme)
    return g


# --------------------------------------------------------------------------- SHACL / OWL RL
def shapes_path() -> Path:
    return ontology_dir() / "core" / "shapes.ttl"


def validate_shacl(data_graph: "Graph", shapes: Optional[Path] = None) -> Dict[str, Any]:
    """Validate a graph against the core SHACL shapes. Returns conforms + violation messages."""
    _require_rdflib()
    import pyshacl
    shapes_graph = Graph().parse(str(shapes or shapes_path()), format="turtle")
    conforms, report, _ = pyshacl.validate(
        data_graph, shacl_graph=shapes_graph, inference="none",
        allow_warnings=True, abort_on_first=False, advanced=True,
    )
    SH = Namespace("http://www.w3.org/ns/shacl#")
    violations = []
    for result in report.subjects(RDF.type, SH.ValidationResult):
        severity = report.value(result, SH.resultSeverity)
        if severity != SH.Violation:
            continue
        focus = report.value(result, SH.focusNode)
        message = report.value(result, SH.resultMessage)
        source = report.value(result, SH.sourceShape)
        violations.append({"focus": str(focus), "message": str(message), "shape": str(source)})
    violations.sort(key=lambda v: (v["shape"], v["focus"], v["message"]))
    return {"conforms": bool(conforms) or not violations, "violations": violations}


def apply_owl_reasoning(g: "Graph") -> "Graph":
    """Materialise OWL 2 RL entailments in place (build time only, never at runtime)."""
    _require_rdflib()
    import owlrl
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics, rdfs_closure=False,
                           axiomatic_triples=False, datatype_axioms=False).expand(g)
    return g


# --------------------------------------------------------------------------- bundle
def export_graph(g: "Graph", dest_dir: Path, base_name: str = "ontology",
                 formats: Optional[Sequence[str]] = None) -> Dict[str, Path]:
    """Serialise a graph to Turtle / JSON-LD / RDF-XML. Returns {format: path}."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for fmt in formats or FORMATS:
        if fmt not in FORMATS:
            raise ValueError(f"Unknown RDF format '{fmt}'; use one of {sorted(FORMATS)}")
        out = dest_dir / f"{base_name}{FORMATS[fmt]}"
        out.write_text(g.serialize(format=fmt), encoding="utf-8", newline="\n")
        written[fmt] = out
    return written


def build_ontology_bundle(reg: OntologyRegistry, dist_dir: Optional[Path] = None, *,
                          owl_rl: bool = False, formats: Optional[Sequence[str]] = None,
                          roles: Optional[Dict[str, Any]] = None, skills: Optional[Dict[str, Any]] = None,
                          lock: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validate (integrity rules + SHACL), export and hash the ontology bundle.

    Fails closed: any integrity error or SHACL violation raises before files are written.
    """
    from ontogate.validate import ERROR, check_registry

    errors = [i for i in check_registry(reg) if i.level == ERROR]
    if errors:
        raise ValueError("Integrity errors:\n" + "\n".join(str(i) for i in errors))
    bundle_sha = source_bundle_sha256()
    g = build_ontology_graph(reg, bundle_sha256=bundle_sha)
    if roles is not None and skills is not None:
        add_agent_graph(g, roles, skills, lock, domains=reg.domains)
    shacl = validate_shacl(g)
    if not shacl["conforms"]:
        raise ValueError(f"SHACL: {len(shacl['violations'])} violation(s):\n"
                         + "\n".join(f"{v['focus']}: {v['message']}" for v in shacl["violations"][:25]))
    if owl_rl:
        apply_owl_reasoning(g)
    dist = Path(dist_dir) if dist_dir else repo_root() / "dist" / "bundle"
    written = export_graph(g, dist, formats=formats)
    manifest = {
        "bundle_sha256": bundle_sha,
        "domains": sorted(reg.domains),
        "owl_rl": owl_rl,
        "triples": len(g),
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in written.values()},
        "shacl": {"conforms": True, "shapes_sha256": hashlib.sha256(shapes_path().read_bytes()
                                                                     .replace(b"\r\n", b"\n")).hexdigest()},
        "counts": {"observables": len(reg.concepts), "designations": len(reg.designations),
                   "intervals": len(reg.intervals), "protocols": len(reg.protocol_nodes),
                   "panels": len(reg.panels)},
    }
    (dist / "bundle.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def query(g: "Graph", sparql: str) -> List[Dict[str, str]]:
    """Run a SPARQL SELECT (competency questions) and return rows as dicts of strings."""
    result = g.query(sparql, initNs={"ag": Namespace(AG_NS), "skos": SKOS, "kb": Namespace(KB_NS),
                                     "skosxl": Namespace(SKOSXL_NS)})
    return [{str(k): str(v) for k, v in row.asdict().items()} for row in result]
