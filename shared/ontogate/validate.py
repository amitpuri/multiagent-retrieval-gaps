"""
Ontology integrity validation — the rules a domain pack must satisfy before
it can be released. Structural typing is enforced by the strict models at load
time; this module checks cross-entity integrity. The same rules are expressed as
SHACL shapes in ``ontology/core/shapes.ttl`` for external validators.

Run::

    python -m ontogate validate                 # default pack + all scenario overlays
    python -m ontogate validate path/to/pack    # one pack
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import yaml

from ontogate.config import OntologyRegistry, load_domain_config, load_scenario_extension

ERROR = "error"
WARNING = "warning"
SUPPORTED_MAJOR = "1"


@dataclass(frozen=True)
class Issue:
    """One integrity finding."""
    level: str
    code: str
    subject: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.code} {self.subject}: {self.message}"


def _err(code: str, subject: str, message: str) -> Issue:
    return Issue(ERROR, code, subject, message)


def _warn(code: str, subject: str, message: str) -> Issue:
    return Issue(WARNING, code, subject, message)


def check_registry(reg: OntologyRegistry) -> List[Issue]:
    """Run every integrity rule over a loaded registry."""
    issues: List[Issue] = []
    concepts = reg.concepts
    known_targets = set(concepts) | set(reg.protocol_nodes)

    for uri, c in concepts.items():
        # References
        if c.governed_by and c.governed_by not in reg.protocol_nodes:
            issues.append(_err("DANGLING_GOVERNED_BY", uri, f"governed_by '{c.governed_by}' is not a protocol node"))
        for other in c.confusable_with:
            if other not in concepts:
                issues.append(_err("DANGLING_CONFUSABLE", uri, f"confusable_with '{other}' is not an observable"))
            elif uri not in concepts[other].confusable_with:
                issues.append(_err("ASYMMETRIC_CONFUSABLE", uri,
                                   f"confusable_with '{other}' is not declared on '{other}' (symmetric relation)"))
        for link in c.links:
            if link.target_uri not in known_targets:
                issues.append(_err("DANGLING_LINK", uri, f"{link.kind.value} → '{link.target_uri}' does not exist"))
        if c.superseded_by and c.superseded_by not in concepts:
            issues.append(_err("DANGLING_SUPERSEDED_BY", uri, f"superseded_by '{c.superseded_by}' does not exist"))
        if c.status == "deprecated" and not c.superseded_by:
            issues.append(_warn("DEPRECATED_WITHOUT_SUCCESSOR", uri, "deprecated observable has no superseded_by"))

        # Controlled vocabularies
        if c.department_id is None and reg.departments:
            issues.append(_err("UNCONTROLLED_DEPARTMENT", uri, f"department '{c.department}' is not a Department entity"))
        if c.measures and c.measures not in reg.analytes:
            issues.append(_err("UNKNOWN_ANALYTE", uri, f"measures '{c.measures}' is not an Analyte"))
        for fid, value in c.facets.items():
            facet = reg.facets.get(fid)
            if facet is None:
                issues.append(_err("UNKNOWN_FACET", uri, f"facet '{fid}' is not declared"))
            elif value not in facet.values:
                issues.append(_err("UNKNOWN_FACET_VALUE", uri, f"{fid}='{value}' is not one of {facet.values}"))

        # Units vs LOINC property axis
        prop = c.axes.get("property")
        prop_dim = reg.property_dimensions.get(prop) if prop else None
        for unit in c.units:
            ud = reg.unit(unit)
            if ud is None:
                issues.append(_err("UNKNOWN_UNIT", uri, f"unit '{unit}' is not in the core unit catalogue"))
                continue
            if prop_dim and prop_dim != "none" and ud.dimension != prop_dim:
                alt = [p for p, d in reg.property_dimensions.items() if d == ud.dimension]
                coded = [p for p in alt if p in c.property_codings]
                if not coded:
                    issues.append(_err("UNIT_PROPERTY_CONFLICT", uri,
                                       f"unit '{unit}' ({ud.dimension}) conflicts with LOINC property {prop} "
                                       f"({prop_dim}) and no property_codings entry covers it"))
                elif all(c.property_codings.get(p) is None for p in coded):
                    issues.append(_warn("UNIT_PROPERTY_CODING_PENDING", uri,
                                        f"unit '{unit}' needs a {'/'.join(coded)} coding — pending verification"))

        # Quantitative observables need intervals (or a declared reason)
        if c.axes.get("scale") == "Qn" and c.is_usable() and not reg.intervals_for(uri) \
                and not c.intervals_not_applicable:
            issues.append(_err("QN_WITHOUT_INTERVALS", uri,
                               "quantitative observable has no reference interval and no intervals_not_applicable"))
        if not c.axes:
            issues.append(_warn("NO_LOINC_AXES", uri, "LOINC axes not declared"))
        elif not c.axes_verified:
            issues.append(_warn("AXES_UNVERIFIED", uri, "LOINC axes derived from label; verify against release"))

    for node_id, p in reg.protocol_nodes.items():
        if not p.governs or p.governs not in concepts:
            issues.append(_err("PROTOCOL_GOVERNS_UNKNOWN", node_id, f"governs '{p.governs}' is not an observable"))

    for interval in reg.intervals:
        concept = concepts.get(interval.observable)
        if concept is None:
            issues.append(_err("INTERVAL_UNKNOWN_OBSERVABLE", interval.id, f"observable '{interval.observable}'"))
            continue
        if not concept.supports_unit(interval.unit):
            issues.append(_err("INTERVAL_UNIT", interval.id, f"unit '{interval.unit}' not admitted by {concept.uri}"))
        bounds = [interval.critical[0], interval.normal[0], interval.normal[1], interval.critical[1]]
        present = [b for b in bounds if b is not None]
        if present != sorted(present) or len(set(present)) != len(present):
            issues.append(_err("INTERVAL_ORDER", interval.id,
                               f"bounds must satisfy critLow < normLow < normHigh < critHigh, got {bounds}"))
        if interval.verified_by and interval.verified_by.startswith("human:") and interval.clinically_unvalidated:
            issues.append(_err("PROVENANCE_CONTRADICTION", interval.id,
                               "human-verified interval cannot also be flagged clinically_unvalidated"))
        for key, value in interval.population.items():
            facet = reg.population_facets.get(key)
            if value != "any" and facet is not None and value not in facet.values:
                issues.append(_err("UNKNOWN_POPULATION_VALUE", interval.id, f"{key}='{value}'"))

    for text, d in reg.designations.items():
        for uri in d.denotes:
            if uri not in concepts:
                issues.append(_err("DESIGNATION_DANGLING", text, f"denotes unknown '{uri}'"))
        if d.is_ambiguous and d.kind != "ambiguous":
            issues.append(_err("SILENT_SYNONYMY", text,
                               f"denotes {len(d.denotes)} observables but kind is '{d.kind}' (must be 'ambiguous')"))
        if d.kind == "ambiguous" and not d.is_ambiguous:
            issues.append(_err("FALSE_AMBIGUITY", text, "kind 'ambiguous' but denotes a single observable"))

    for pid, panel in reg.panels.items():
        ids = {r.id for r in panel.tube_rules if r.id}
        seen_dept = set()
        for rule in panel.tube_rules:
            seen_dept.add(rule.department)
            if rule.precedes and rule.precedes not in ids:
                issues.append(_err("DANGLING_PRECEDES", f"{pid}/{rule.id}", f"precedes '{rule.precedes}'"))
            for uri in rule.includes:
                c = concepts.get(uri)
                if c is None:
                    issues.append(_err("STEP_UNKNOWN_OBSERVABLE", f"{pid}/{rule.id}", uri))
                elif rule.department_id and c.department_id and c.department_id != rule.department_id:
                    issues.append(_err("STEP_DEPARTMENT", f"{pid}/{rule.id}",
                                       f"{uri} belongs to {c.department}, step is routed to {rule.department}"))
        if _has_cycle({r.id: r.precedes for r in panel.tube_rules if r.id}):
            issues.append(_err("PRECEDES_CYCLE", pid, "collection steps form a cycle"))
    return issues


def _has_cycle(edges: Dict[str, Optional[str]]) -> bool:
    for start in edges:
        seen, cur = set(), start
        while cur is not None:
            if cur in seen:
                return True
            seen.add(cur)
            cur = edges.get(cur)
    return False


def check_schema_versions(paths: Iterable[Path]) -> List[Issue]:
    """All files of a release must share the supported schema major version."""
    issues: List[Issue] = []
    for path in paths:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        version = str(data.get("schema_version", ""))
        if version and version.split(".")[0] != SUPPORTED_MAJOR:
            issues.append(_err("SCHEMA_VERSION", path.name, f"schema_version {version} (supported: {SUPPORTED_MAJOR}.x)"))
    return issues


def validate_pack(domain_dir: Path, scenarios: Iterable[Path] = ()) -> List[Issue]:
    """Validate a pack and each scenario overlay applied on top of it."""
    domain_dir = Path(domain_dir)
    issues = check_schema_versions(sorted(domain_dir.glob("*.yaml")))
    base = load_domain_config(domain_dir)
    issues += check_registry(base)
    import copy
    for scenario in scenarios:
        reg = load_scenario_extension(scenario, copy.deepcopy(base))
        for issue in check_registry(reg):
            if issue not in issues:
                issues.append(Issue(issue.level, issue.code, f"{scenario.stem}:{issue.subject}", issue.message))
    return issues


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    from ontogate.paths import domain_dir, scenarios_dir

    parser = argparse.ArgumentParser(prog="ontogate validate")
    parser.add_argument("pack", nargs="?", default=None)
    parser.add_argument("--no-scenarios", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors.")
    args = parser.parse_args(argv)
    pack = Path(args.pack) if args.pack else domain_dir()
    scenarios = [] if args.no_scenarios else sorted(scenarios_dir().glob("*.yaml"))
    issues = validate_pack(pack, scenarios)
    for issue in issues:
        print(issue)
    errors = [i for i in issues if i.level == ERROR or (args.strict and i.level == WARNING)]
    print(f"{len(errors)} error(s), {len(issues) - len(errors)} warning(s)")
    return 1 if errors else 0
