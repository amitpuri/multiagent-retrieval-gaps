"""
Ontology loading and the in-memory ``OntologyRegistry``.

A domain pack (``ontology/domains/<id>/``) is assembled from the files listed in
its ``domain.yaml`` plus the imported core ontology (``ontology/core/core.yaml``),
validated against the strict models, and registered. Scenario overlays
(``config/scenarios/*.yaml``, key ``overlay:``) add entities on top of a pack.

``ConceptDefinition.alt_labels`` is a derived view of the designations that
denote each observable; the term mapping itself lives in ``designations``.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from ontogate.models import (
    Analyte,
    AttestedComputation,
    ConceptDefinition,
    ConceptLink,
    ConceptSource,
    Department,
    Designation,
    Facet,
    PanelDefinition,
    ProtocolDefinition,
    ReferenceInterval,
    RelationshipKind,
    Specimen,
    SpecimenTubeRule,
    UnitDef,
)


def slug(text: str) -> str:
    """Identifier fragment (``Clinical Biochemistry`` → ``clinical_biochemistry``)."""
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


class OntologyRegistry:
    """Central in-memory registry holding one or more loaded domain packs."""

    def __init__(self) -> None:
        # Observables and protocols (protocols keyed by the observable they govern)
        self.concepts: Dict[str, ConceptDefinition] = {}
        self.protocols: Dict[str, ProtocolDefinition] = {}
        self.protocol_nodes: Dict[str, ProtocolDefinition] = {}
        self.designations: Dict[str, Designation] = {}
        self.facets: Dict[str, Facet] = {}
        self.population_facets: Dict[str, Facet] = {}
        self.analytes: Dict[str, Analyte] = {}
        self.units: Dict[str, UnitDef] = {}
        self.departments: Dict[str, Department] = {}
        self.specimens: Dict[str, Specimen] = {}
        self.intervals: List[ReferenceInterval] = []
        self.panels: Dict[str, PanelDefinition] = {}
        self.property_dimensions: Dict[str, str] = {}
        self.relations: Dict[str, Dict[str, Any]] = {}
        self.gate_policy: Dict[str, Any] = {"population_required_when": "critical_divergence"}
        self.trust_policy: Dict[str, Any] = {}
        self.domains: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ register
    def register_concept(self, concept: ConceptDefinition) -> None:
        self.concepts[concept.uri] = concept

    def register_protocol(self, uri: str, protocol: ProtocolDefinition) -> None:
        self.protocols[uri] = protocol
        if protocol.id:
            self.protocol_nodes[protocol.id] = protocol

    def register_panel(self, panel_id: str, panel: PanelDefinition) -> None:
        self.panels[panel_id] = panel

    def register_designation(self, designation: Designation) -> None:
        self.designations[designation.text.strip().lower()] = designation

    def register_interval(self, interval: ReferenceInterval) -> None:
        self.intervals = [i for i in self.intervals if i.id != interval.id]
        self.intervals.append(interval)

    # ------------------------------------------------------------------- lookup
    def find_concepts(self, term: str) -> List[ConceptDefinition]:
        """Find all concepts matching a lexical term (label or alternate label)."""
        return [c for c in self.concepts.values() if c.matches(term)]

    def find_designation(self, term: str) -> Optional[Designation]:
        return self.designations.get(term.strip().lower())

    def get_protocol(self, uri: str) -> Optional[ProtocolDefinition]:
        """Protocol governing an observable URI (or a protocol node by its own id)."""
        return self.protocols.get(uri) or self.protocol_nodes.get(uri)

    def get_panel(self, panel_id: str) -> Optional[PanelDefinition]:
        return self.panels.get(panel_id)

    def find_panel(self, text: str) -> Optional[Tuple[str, PanelDefinition]]:
        """Resolve a panel by id, name or declared designation (exact, case-insensitive)."""
        t = text.strip().lower()
        for pid, panel in self.panels.items():
            names = {pid.lower(), panel.name.lower(), *(d.lower() for d in panel.designations)}
            if t in names:
                return pid, panel
        return None

    def intervals_for(self, uri: str) -> List[ReferenceInterval]:
        return [i for i in self.intervals if i.observable == uri]

    def unit(self, code: str) -> Optional[UnitDef]:
        if not code:
            return None
        exact = self.units.get(code)
        if exact:
            return exact
        lowered = code.strip().lower()
        for k, v in self.units.items():
            if k.lower() == lowered:
                return v
        return None

    def department(self, text: str) -> Optional[Department]:
        if not text:
            return None
        if text in self.departments:
            return self.departments[text]
        for d in self.departments.values():
            if d.matches(text):
                return d
        return None

    def facet_value(self, qualifier: str) -> Optional[Tuple[str, str]]:
        """Map a qualifier to ``(facet_id, value)`` among domain facets."""
        if not qualifier:
            return None
        for fid, facet in self.facets.items():
            v = facet.normalize(qualifier)
            if v is not None:
                return fid, v
        return None

    def population_value(self, qualifier: str) -> Optional[Tuple[str, str]]:
        """Map a qualifier to ``(population_facet, value)`` (e.g. ``female`` → ``("sex", "female")``)."""
        if not qualifier:
            return None
        for fid, facet in self.population_facets.items():
            v = facet.normalize(qualifier)
            if v is not None:
                return fid, v
        return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_links(raw_links: List[Dict[str, Any]]) -> List[ConceptLink]:
    """Parse a YAML ``links:`` list. An unknown relation kind is an error."""
    result = []
    for entry in raw_links or []:
        kind_raw = entry.get("kind", "see_also")
        try:
            kind = RelationshipKind(kind_raw)
        except ValueError:
            allowed = ", ".join(k.value for k in RelationshipKind)
            raise ValueError(f"Unknown link kind '{kind_raw}' (allowed: {allowed})") from None
        result.append(ConceptLink(target_uri=entry.get("target_uri", ""), kind=kind,
                                  description=entry.get("description")))
    return result


def _parse_sources(raw_sources: List[Dict[str, Any]]) -> List[ConceptSource]:
    return [ConceptSource.model_validate(s) for s in raw_sources or []]


def _parse_attested_computation(raw: Optional[Dict[str, Any]]) -> Optional[AttestedComputation]:
    return AttestedComputation.model_validate(raw) if raw else None


# ---------------------------------------------------------------------------
# Pack assembly
# ---------------------------------------------------------------------------

def _read_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # Top-level keys starting with "_" hold YAML anchors only.
    return {k: v for k, v in data.items() if not str(k).startswith("_")}


def find_core_file(domain_dir: Optional[Path] = None) -> Optional[Path]:
    """Locate ``core/core.yaml`` relative to a pack, else via repository discovery."""
    from ontogate.paths import ontology_dir
    candidates = []
    if domain_dir is not None:
        candidates.append(Path(domain_dir).parent.parent / "core" / "core.yaml")
    candidates.append(ontology_dir() / "core" / "core.yaml")
    for c in candidates:
        if c.exists():
            return c
    return None


def read_core(core_file: Optional[Path]) -> Dict[str, Any]:
    return _read_yaml(core_file) if core_file and core_file.exists() else {}


def read_pack(domain_dir: Path) -> Dict[str, Any]:
    """Assemble a pack dict from ``domain.yaml`` and the files it lists."""
    manifest = _read_yaml(domain_dir / "domain.yaml")
    pack: Dict[str, Any] = {"manifest": manifest}
    for name in manifest.get("files", []):
        part = _read_yaml(domain_dir / name)
        for key, value in part.items():
            if key == "schema_version":
                continue
            if isinstance(value, dict):
                pack.setdefault(key, {}).update(value)
            elif isinstance(value, list):
                pack.setdefault(key, []).extend(value)
            else:
                pack[key] = value
    return pack


def apply_core(registry: OntologyRegistry, core: Dict[str, Any]) -> None:
    for code, u in (core.get("units") or {}).items():
        registry.units[code] = UnitDef(code=code, **u)
    for fid, f in (core.get("population_facets") or {}).items():
        registry.population_facets[fid] = Facet(id=fid, **f)
    registry.property_dimensions.update(core.get("property_dimensions") or {})
    registry.relations.update(core.get("relations") or {})
    registry.gate_policy.update(core.get("gate_policy") or {})
    registry.trust_policy.update(core.get("trust_policy") or {})


def _check_overlay_conflict(kind: str, key: str, existing: Any, new: Any, overrides: Iterable[str]) -> None:
    if existing is None or existing == new or key in overrides:
        return
    raise ValueError(
        f"Overlay redefines existing {kind} '{key}' without declaring it under 'overrides:'."
    )


def apply_pack(registry: OntologyRegistry, pack: Dict[str, Any], *, overlay: bool = False) -> OntologyRegistry:
    """Validate and register every entity of a pack (or overlay) into ``registry``."""
    overrides = set(pack.get("overrides", []) or [])
    manifest = pack.get("manifest") or {}
    if manifest.get("id"):
        registry.domains[manifest["id"]] = manifest

    for did, d in (pack.get("departments") or {}).items():
        registry.departments[did] = Department(id=did, **d)
    for sid, s in (pack.get("specimens") or {}).items():
        registry.specimens[sid] = Specimen(id=sid, **s)
    for aid, a in (pack.get("analytes") or {}).items():
        registry.analytes[aid] = Analyte(id=aid, **a)
    for fid, f in (pack.get("facets") or {}).items():
        registry.facets[fid] = Facet(id=fid, **f)

    protocol_by_node = {node_id: ProtocolDefinition(id=node_id, **dict(p or {}))
                        for node_id, p in (pack.get("protocols") or {}).items()}

    for uri, raw in (pack.get("observables") or {}).items():
        body = dict(raw or {})
        dept_ref = body.pop("department", "") or ""
        dept = registry.departments.get(dept_ref)
        spec_ref = body.pop("specimen", None)
        spec = registry.specimens.get(spec_ref) if spec_ref else None
        concept = ConceptDefinition(
            uri=uri,
            department=dept.label if dept else dept_ref,
            department_id=dept.id if dept else None,
            specimen=spec.label if spec else spec_ref,
            specimen_id=spec.id if spec else None,
            sources=_parse_sources(body.pop("sources", [])),
            links=_parse_links(body.pop("links", [])),
            **body,
        )
        if overlay:
            _check_overlay_conflict("observable", uri, registry.concepts.get(uri), concept, overrides)
        # Mirror governed_by as a typed link so graph traversal reaches protocol nodes.
        if concept.governed_by and not any(
            lk.kind == RelationshipKind.GOVERNED_BY and lk.target_uri == concept.governed_by for lk in concept.links
        ):
            concept.links.append(ConceptLink(target_uri=concept.governed_by, kind=RelationshipKind.GOVERNED_BY,
                                             description="Governing protocol node"))
        registry.register_concept(concept)

    # Additive facet values for existing observables (overlays never redefine them).
    for uri, values in (pack.get("facet_assignments") or {}).items():
        concept = registry.concepts.get(uri)
        if concept is None:
            raise ValueError(f"facet_assignments references unknown observable '{uri}'")
        for fid, value in values.items():
            current = concept.facets.get(fid)
            if current is not None and current != value and uri not in overrides:
                raise ValueError(f"facet_assignments changes {uri}.{fid} from '{current}' to '{value}' "
                                 "without declaring it under 'overrides:'.")
            concept.facets[fid] = value

    for node_id, protocol in protocol_by_node.items():
        governed = protocol.governs or ""
        if overlay:
            _check_overlay_conflict("protocol", governed, registry.protocols.get(governed), protocol, overrides)
        registry.register_protocol(governed, protocol)

    for text, d in (pack.get("designations") or {}).items():
        registry.register_designation(Designation(text=str(text).strip().lower(), **d))

    for raw in pack.get("reference_intervals") or []:
        registry.register_interval(ReferenceInterval(**raw))

    for pid, p in (pack.get("panels") or {}).items():
        registry.register_panel(pid, _build_panel(registry, pid, p))

    _materialise_symmetric(registry)
    _project_designations(registry)
    return registry


def _build_panel(registry: OntologyRegistry, panel_id: str, p: Dict[str, Any]) -> PanelDefinition:
    spec_ref = p.get("specimen")
    spec = registry.specimens.get(spec_ref) if spec_ref else None
    specimen_label = spec.label if spec else (spec_ref or "")
    if p.get("collection_method") and spec:
        specimen_label = f"{spec.label} ({p['collection_method']})"
    rules: List[SpecimenTubeRule] = []
    for step in p.get("steps", []) or []:
        dept = registry.departments.get(step.get("department", ""))
        tests = []
        for uri in step.get("includes", []) or []:
            concept = registry.concepts.get(uri)
            tests.append({"uri": uri, "test_name": concept.label if concept else uri})
        rules.append(SpecimenTubeRule(
            tube=step.get("tube", len(rules) + 1),
            department=dept.label if dept else step.get("department", ""),
            department_id=dept.id if dept else None,
            description=step.get("description"),
            tests=tests,
            id=step.get("id"),
            includes=list(step.get("includes", []) or []),
            precedes=step.get("precedes"),
        ))
    rules.sort(key=lambda r: r.tube)
    return PanelDefinition(
        name=p.get("name", panel_id),
        specimen=specimen_label,
        tube_rules=rules,
        specimen_id=spec.id if spec else None,
        collection_method=p.get("collection_method"),
        designations=list(p.get("designations", []) or []),
    )


def _materialise_symmetric(registry: OntologyRegistry) -> None:
    """``confusable_with`` is symmetric: add the inverse edge wherever only one side is declared."""
    for uri, concept in registry.concepts.items():
        for other in concept.confusable_with:
            target = registry.concepts.get(other)
            if target is not None and uri not in target.confusable_with and other != uri:
                target.confusable_with.append(uri)


def _project_designations(registry: OntologyRegistry) -> None:
    """Project designations into ``alt_labels`` (union; never removes existing labels)."""
    for designation in registry.designations.values():
        for uri in designation.denotes:
            concept = registry.concepts.get(uri)
            if concept is None or designation.text.lower() == concept.label.lower():
                continue
            if all(designation.text != a.lower() for a in concept.alt_labels):
                concept.alt_labels.append(designation.text)


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_domain_config(domain_dir: Path) -> OntologyRegistry:
    """Load a domain pack (``domain.yaml`` + its files) together with the core ontology."""
    domain_dir = Path(domain_dir)
    if not (domain_dir / "domain.yaml").exists():
        raise FileNotFoundError(f"No domain.yaml in {domain_dir}")
    registry = OntologyRegistry()
    apply_core(registry, read_core(find_core_file(domain_dir)))
    return apply_pack(registry, read_pack(domain_dir))


def load_scenario_extension(
    scenario_path: Path,
    registry: Optional[OntologyRegistry] = None,
) -> OntologyRegistry:
    """Apply a scenario's ``overlay:`` to a registry.

    Without ``registry`` the default registry is deep-copied first, so the global
    singleton is never mutated.
    """
    if registry is None:
        registry = copy.deepcopy(get_default_registry())
    scenario_path = Path(scenario_path)
    if not scenario_path.exists():
        return registry
    overlay = _read_yaml(scenario_path).get("overlay")
    if not overlay:
        return registry
    return apply_pack(registry, overlay, overlay=True)


_DEFAULT_REGISTRY: Optional[OntologyRegistry] = None


def get_default_registry(reload: bool = False) -> OntologyRegistry:
    """Return the cached default registry (laboratory_medicine pack)."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None or reload:
        from ontogate.paths import domain_dir
        _DEFAULT_REGISTRY = load_domain_config(domain_dir())
    return _DEFAULT_REGISTRY
