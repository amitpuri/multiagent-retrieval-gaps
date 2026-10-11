"""
RDF/SKOS/OWL/SHACL export for the ontogate ontology.

Exports a loaded OntologyRegistry to:
- Turtle (.ttl)    — human-readable, VCS-friendly
- JSON-LD (.jsonld) — API/linked-data consumers
- RDF/XML (.rdf)   — OWL toolchain compatibility (Protege, ROBOT)

Also provides:
- validate_shacl     — runs the shapes graph against the exported data graph (pyshacl)
- apply_owl_reasoning — materialises OWL 2 RL entailments (owlrl)
- build_ontology_bundle — lints, exports, validates, hashes to dist/bundle/

Run:
    python -m ontogate rdf_export           # default pack, all formats
    python -m ontogate rdf_export --validate # also run SHACL + OWL RL

Dependencies: rdflib>=6.3, pyshacl>=0.25, owlrl>=6.0
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from rdflib import (
        Graph,
        Literal,
        Namespace,
        RDF,
        RDFS,
        OWL,
        URIRef,
        XSD,
    )
    from rdflib.namespace import SKOS
    _HAS_RDFLIB = True
except ImportError:
    _HAS_RDFLIB = False
    Graph = Any  # type: ignore
    Literal = Any  # type: ignore
    URIRef = Any  # type: ignore
    Namespace = None  # type: ignore
    RDF = RDFS = OWL = XSD = SKOS = None  # type: ignore

from ontogate.config import OntologyRegistry
from ontogate.models import RelationshipKind, TrustTier

# ---------------------------------------------------------------------------
# Namespace declarations
# ---------------------------------------------------------------------------

if _HAS_RDFLIB:
    AG    = Namespace("https://ontogate.ai/ns/core#")
    LOINC = Namespace("https://loinc.org/")
    UCUM  = Namespace("https://ucum.org/")
    PROV  = Namespace("http://www.w3.org/ns/prov#")

    _TRUST_TIER_IRI: Dict[str, URIRef] = {
        TrustTier.UNVERIFIED.value:        AG["TrustTier/unverified"],
        TrustTier.MACHINE_CONFIRMED.value: AG["TrustTier/machine-confirmed"],
        TrustTier.HUMAN_REVIEWED.value:    AG["TrustTier/human-reviewed"],
    }
else:
    AG = LOINC = UCUM = PROV = None  # type: ignore
    _TRUST_TIER_IRI = {}

_CHARACTERISTIC_MAP: Dict[str, Dict[str, bool]] = {
    RelationshipKind.CONFUSABLE_WITH.value: {"symmetric": True, "irreflexive": True},
    RelationshipKind.GOVERNED_BY.value:     {"functional": True},
    RelationshipKind.SUPERSEDED_BY.value:   {"functional": True},
    RelationshipKind.PRECEDES.value:        {"transitive": True, "asymmetric": True},
    RelationshipKind.MEMBER_OF.value:       {},
    RelationshipKind.SEE_ALSO.value:        {},
}


def _loinc_uri(uri: str) -> URIRef:
    if uri.startswith("loinc:"):
        return LOINC[uri[6:]]
    return URIRef(uri)


def _ucum_uri(code: str) -> URIRef:
    return UCUM[code.replace("/", "_per_")]


def _bind_prefixes(g: Graph) -> None:
    g.bind("ag",    AG)
    g.bind("loinc", LOINC)
    g.bind("ucum",  UCUM)
    g.bind("skos",  SKOS)
    g.bind("owl",   OWL)
    g.bind("rdfs",  RDFS)
    g.bind("xsd",   XSD)
    g.bind("prov",  PROV)


def build_ontology_graph(
    reg: OntologyRegistry,
    iri: str = "https://ontogate.ai/ontology/core",
) -> Graph:
    """Convert OntologyRegistry to an RDF graph (SKOS + OWL + AG namespace)."""
    if not _HAS_RDFLIB:
        raise ImportError(
            "rdflib is required for RDF export. Install with: pip install 'ontogate[rdf]' or pip install rdflib pyshacl owlrl"
        )
    g = Graph()
    _bind_prefixes(g)

    ont_iri = URIRef(iri)
    g.add((ont_iri, RDF.type,           OWL.Ontology))
    g.add((ont_iri, RDFS.label,         Literal("ontogate core ontology", lang="en")))
    g.add((ont_iri, OWL.versionInfo,    Literal("1.0.0")))
    g.add((ont_iri, AG["bundleSha256"], Literal(reg.bundle_sha256 or "unset")))

    scheme = AG["ConceptScheme/core"]
    g.add((scheme, RDF.type,       SKOS.ConceptScheme))
    g.add((scheme, SKOS.prefLabel, Literal("ontogate laboratory medicine", lang="en")))

    # OWL object properties with characteristics
    for rel_name, chars in _CHARACTERISTIC_MAP.items():
        prop = AG[f"property/{rel_name}"]
        g.add((prop, RDF.type,   OWL.ObjectProperty))
        g.add((prop, RDFS.label, Literal(rel_name, lang="en")))
        if chars.get("symmetric"):
            g.add((prop, RDF.type, OWL.SymmetricProperty))
        if chars.get("transitive"):
            g.add((prop, RDF.type, OWL.TransitiveProperty))
        if chars.get("functional"):
            g.add((prop, RDF.type, OWL.FunctionalProperty))
        if chars.get("asymmetric"):
            g.add((prop, RDF.type, OWL.AsymmetricProperty))
        if chars.get("irreflexive"):
            g.add((prop, RDF.type, OWL.IrreflexiveProperty))

    # Units
    for ucum_code, ud in reg.units.items():
        u_iri = _ucum_uri(ucum_code)
        g.add((u_iri, RDF.type,          AG["Unit"]))
        g.add((u_iri, SKOS.notation,     Literal(ucum_code, datatype=UCUM["code"])))
        g.add((u_iri, AG["dimension"],   Literal(ud.dimension)))
        g.add((u_iri, AG["scaleFactor"], Literal(ud.factor, datatype=XSD.double)))

    # Observables (SKOS Concepts)
    for uri, concept in reg.concepts.items():
        c_iri = _loinc_uri(uri)
        g.add((c_iri, RDF.type,       SKOS.Concept))
        g.add((c_iri, RDF.type,       AG["Observable"]))
        g.add((c_iri, SKOS.inScheme,  scheme))
        g.add((c_iri, SKOS.notation,  Literal(uri)))
        g.add((c_iri, SKOS.prefLabel, Literal(concept.label, lang="en")))

        if concept.status == "deprecated":
            g.add((c_iri, OWL.deprecated, Literal(True, datatype=XSD.boolean)))
        if concept.superseded_by:
            g.add((c_iri, AG[RelationshipKind.SUPERSEDED_BY.value], _loinc_uri(concept.superseded_by)))
        for cf_uri in concept.confusable_with:
            g.add((c_iri, AG[RelationshipKind.CONFUSABLE_WITH.value], _loinc_uri(cf_uri)))
        if concept.governed_by:
            g.add((c_iri, AG[RelationshipKind.GOVERNED_BY.value],
                   URIRef(f"{iri}/protocol/{concept.governed_by}")))
        for link in concept.links:
            g.add((c_iri, AG[link.kind.value], _loinc_uri(link.target_uri)))
        for ucum_code in concept.units:
            g.add((c_iri, AG["admitsUnit"], _ucum_uri(ucum_code)))
        if concept.department:
            g.add((c_iri, AG["department"], Literal(concept.department)))
        if concept.measures:
            g.add((c_iri, AG["measures"], Literal(concept.measures)))
        for axis, val in concept.axes.items():
            g.add((c_iri, AG[f"loinc_{axis}"], Literal(val)))

        tier_iri = _TRUST_TIER_IRI.get(concept.trust_tier.value)
        if tier_iri:
            g.add((c_iri, AG["trustTier"], tier_iri))
        if concept.stale_after:
            g.add((c_iri, AG["staleAfter"],
                   Literal(concept.stale_after.isoformat(), datatype=XSD.dateTime)))
        if concept.verified_by:
            g.add((c_iri, PROV.wasAttributedTo, Literal(concept.verified_by)))

    # Designations
    for text, desig in reg.designations.items():
        slug = hashlib.md5(text.encode()).hexdigest()[:12]
        d_iri = AG[f"Designation/{slug}"]
        g.add((d_iri, RDF.type,       AG["Designation"]))
        g.add((d_iri, SKOS.prefLabel, Literal(text, lang="en")))
        g.add((d_iri, AG["kind"],     Literal(desig.kind)))
        for obs_uri in desig.denotes:
            g.add((d_iri, AG["denotes"], _loinc_uri(obs_uri)))

    # Reference Intervals
    for interval in reg.intervals:
        iv_iri = AG[f"Interval/{interval.id}"]
        g.add((iv_iri, RDF.type,            AG["ReferenceInterval"]))
        g.add((iv_iri, AG["forObservable"], _loinc_uri(interval.observable)))
        g.add((iv_iri, AG["unit"],          _ucum_uri(interval.unit)))
        if interval.normal[0] is not None:
            g.add((iv_iri, AG["normalLow"],   Literal(interval.normal[0],   datatype=XSD.double)))
        if interval.normal[1] is not None:
            g.add((iv_iri, AG["normalHigh"],  Literal(interval.normal[1],   datatype=XSD.double)))
        if interval.critical[0] is not None:
            g.add((iv_iri, AG["criticalLow"], Literal(interval.critical[0], datatype=XSD.double)))
        if interval.critical[1] is not None:
            g.add((iv_iri, AG["criticalHigh"],Literal(interval.critical[1], datatype=XSD.double)))
        for key, val in interval.population.items():
            if val != "any":
                g.add((iv_iri, AG[f"population_{key}"], Literal(val)))
        t_iri = _TRUST_TIER_IRI.get(interval.trust_tier.value)
        if t_iri:
            g.add((iv_iri, AG["trustTier"], t_iri))
        if interval.verified_by:
            g.add((iv_iri, PROV.wasAttributedTo, Literal(interval.verified_by)))

    return g


def validate_shacl(
    data_graph: Graph,
    shapes_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate `data_graph` against SHACL shapes. Requires pyshacl."""
    import pyshacl  # type: ignore
    if shapes_path is None:
        from ontogate.paths import repo_root
        shapes_path = repo_root() / "ontology" / "core" / "shapes.ttl"
    shapes_graph = Graph().parse(str(shapes_path), format="turtle")
    conforms, _, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes_graph,
        ont_graph=None,
        inference="rdfs",
        abort_on_first=False,
        meta_shacl=False,
    )
    violations: List[str] = [l.strip() for l in results_text.splitlines() if l.strip()] if not conforms else []
    return {"conforms": conforms, "violations": violations}


def apply_owl_reasoning(g: Graph) -> Graph:
    """Materialise OWL 2 RL entailments in-place. Requires owlrl."""
    import owlrl  # type: ignore
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
    return g


def export_graph(
    g: Graph,
    dest_dir: Path,
    base_name: str = "ontology",
    formats: Optional[List[str]] = None,
) -> Dict[str, Path]:
    """Serialise graph to one or more RDF formats. Returns {format: path}."""
    if formats is None:
        formats = ["turtle", "json-ld", "xml"]
    _EXT = {"turtle": ".ttl", "json-ld": ".jsonld", "xml": ".rdf"}
    dest_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Path] = {}
    for fmt in formats:
        out = dest_dir / f"{base_name}{_EXT.get(fmt, f'.{fmt}')}"
        g.serialize(destination=str(out), format=fmt)
        written[fmt] = out
    return written


def build_ontology_bundle(
    reg: OntologyRegistry,
    dist_dir: Optional[Path] = None,
    run_shacl: bool = True,
    run_owl_rl: bool = False,
    formats: Optional[List[str]] = None,
    bundle_sha256: str = "core-bundle-v1",
) -> Dict[str, Any]:
    """Export, SHACL-validate, and hash the full ontology bundle.

    Writes files under `dist_dir/bundle/` and returns the manifest dict.
    """
    from ontogate.paths import repo_root
    from ontogate.validate import check_registry

    dist = dist_dir or (repo_root() / "dist" / "bundle")
    issues = check_registry(reg)
    errors = [i for i in issues if i.level == "error"]
    if errors:
        raise ValueError(
            f"Registry has {len(errors)} error(s) before RDF export:\n"
            + "\n".join(str(i) for i in errors)
        )

    g = build_ontology_graph(reg)
    if run_owl_rl:
        apply_owl_reasoning(g)

    written = export_graph(g, dist, formats=formats)

    shacl_result: Dict[str, Any] = {"skipped": True}
    if run_shacl:
        shacl_result = validate_shacl(g)
        if not shacl_result["conforms"]:
            raise ValueError(
                f"SHACL validation failed with {len(shacl_result['violations'])} violations:\n"
                + "\n".join(shacl_result["violations"][:20])
            )

    hasher = hashlib.sha256()
    file_hashes: Dict[str, str] = {}
    for fmt, path in sorted(written.items()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        file_hashes[fmt] = digest
        hasher.update(digest.encode())

    manifest: Dict[str, Any] = {
        "bundle_sha256":    bundle_sha256,
        "export_sha256":    hasher.hexdigest(),
        "files":            {fmt: str(p.relative_to(repo_root())) for fmt, p in written.items()},
        "file_hashes":      file_hashes,
        "shacl":            shacl_result,
        "concept_count":    len(reg.concepts),
        "interval_count":   len(reg.intervals),
        "designation_count":len(reg.designations),
    }
    manifest_path = dist / "bundle.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry-point: `python -m ontogate rdf_export`."""
    import argparse
    from ontogate.config import get_default_registry

    parser = argparse.ArgumentParser(prog="ontogate rdf_export")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--owl-rl",  action="store_true")
    parser.add_argument(
        "--formats", nargs="+",
        choices=["turtle", "json-ld", "xml"],
        default=["turtle", "json-ld", "xml"],
    )
    args = parser.parse_args(argv)
    reg = get_default_registry()
    manifest = build_ontology_bundle(
        reg, run_shacl=args.validate, run_owl_rl=args.owl_rl, formats=args.formats,
    )
    print(json.dumps(manifest, indent=2))
    return 1 if manifest.get("shacl", {}).get("violations") else 0
