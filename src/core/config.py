"""
Declarative configuration loader and registries.
Reads domain YAML configurations for concepts, protocols, ranges, and specimen rules.
Enables dynamic registration of new domains and scenarios without modifying source code.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from src.core.models import (
    CollisionFamily,
    ConceptDefinition,
    NumericAssay,
    PanelDefinition,
    ProtocolDefinition,
    SpecimenTubeRule,
)


class OntologyRegistry:
    """Central in-memory registry holding domain concepts and protocols."""

    def __init__(self):
        self.concepts: Dict[str, ConceptDefinition] = {}
        self.protocols: Dict[str, ProtocolDefinition] = {}
        self.assays: Dict[str, NumericAssay] = {}
        self.collision_families: Dict[str, CollisionFamily] = {}
        self.panels: Dict[str, PanelDefinition] = {}

    def register_concept(self, concept: ConceptDefinition):
        self.concepts[concept.uri] = concept

    def register_protocol(self, uri: str, protocol: ProtocolDefinition):
        self.protocols[uri] = protocol

    def register_assay(self, assay_id: str, assay: NumericAssay):
        self.assays[assay_id] = assay

    def register_collision_family(self, family_id: str, family: CollisionFamily):
        self.collision_families[family_id] = family

    def register_panel(self, panel_id: str, panel: PanelDefinition):
        self.panels[panel_id] = panel

    def find_concepts(self, term: str) -> List[ConceptDefinition]:
        """Find all concepts matching a lexical term or alternate label."""
        return [c for c in self.concepts.values() if c.matches(term)]

    def get_protocol(self, uri: str) -> Optional[ProtocolDefinition]:
        return self.protocols.get(uri)

    def get_panel(self, panel_id: str) -> Optional[PanelDefinition]:
        return self.panels.get(panel_id)


def load_domain_config(domain_dir: Path) -> OntologyRegistry:
    """Load all YAML files from a domain configuration directory into an OntologyRegistry."""
    registry = OntologyRegistry()

    # 1. Load concepts
    concepts_file = domain_dir / "concepts.yaml"
    if concepts_file.exists():
        with open(concepts_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            for uri, c_data in data.get("concepts", {}).items():
                concept = ConceptDefinition(
                    uri=uri,
                    label=c_data.get("label", ""),
                    alt_labels=c_data.get("alt_labels", []),
                    department=c_data.get("department", ""),
                    units=c_data.get("units", []),
                    specimen=c_data.get("specimen"),
                    attributes=c_data.get("attributes", {}),
                )
                registry.register_concept(concept)

    # 2. Load protocols
    protocols_file = domain_dir / "protocols.yaml"
    if protocols_file.exists():
        with open(protocols_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            for uri, p_data in data.get("protocols", {}).items():
                protocol = ProtocolDefinition(
                    reference_range=p_data.get("reference_range", ""),
                    panic_limits=p_data.get("panic_limits", ""),
                    clinical_guideline=p_data.get("clinical_guideline"),
                )
                registry.register_protocol(uri, protocol)

    # 3. Load ranges and collision families
    ranges_file = domain_dir / "ranges.yaml"
    if ranges_file.exists():
        with open(ranges_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            for assay_id, a_data in data.get("assays", {}).items():
                assay = NumericAssay(
                    uri=a_data.get("uri", ""),
                    name=a_data.get("name", ""),
                    qualifiers=a_data.get("qualifiers", []),
                    unit=a_data.get("unit", ""),
                    ref_low=float(a_data.get("ref_low", 0.0)),
                    ref_high=float(a_data.get("ref_high", 0.0)),
                    crit_low=float(a_data.get("crit_low", 0.0)),
                    crit_high=float(a_data.get("crit_high", 0.0)),
                )
                registry.register_assay(assay_id, assay)

            for fam_id, f_data in data.get("collision_families", {}).items():
                family = CollisionFamily(
                    family_name=f_data.get("family_name", fam_id),
                    assays=f_data.get("assays", []),
                    trigger_unit=f_data.get("trigger_unit", ""),
                    default_qualifier_required=f_data.get("default_qualifier_required", True),
                )
                registry.register_collision_family(fam_id, family)

    # 4. Load specimen rules
    specimen_file = domain_dir / "specimen_rules.yaml"
    if specimen_file.exists():
        with open(specimen_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            for panel_id, p_data in data.get("panels", {}).items():
                tube_rules = []
                for tr in p_data.get("tube_rules", []):
                    tube_rules.append(
                        SpecimenTubeRule(
                            tube=tr.get("tube", 1),
                            department=tr.get("department", ""),
                            description=tr.get("description"),
                            tests=tr.get("tests", []),
                        )
                    )
                panel = PanelDefinition(
                    name=p_data.get("name", panel_id),
                    specimen=p_data.get("specimen", ""),
                    tube_rules=tube_rules,
                )
                registry.register_panel(panel_id, panel)

    return registry


def load_scenario_extension(scenario_path: Path, registry: OntologyRegistry):
    """Dynamically register extensions declared in a scenario YAML into an existing registry."""
    if not scenario_path.exists():
        return
    with open(scenario_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    for uri, c_data in data.get("extension_concepts", {}).items():
        concept = ConceptDefinition(
            uri=uri,
            label=c_data.get("label", ""),
            alt_labels=c_data.get("alt_labels", []),
            department=c_data.get("department", ""),
            units=c_data.get("units", []),
            specimen=c_data.get("specimen"),
            attributes=c_data.get("attributes", {}),
        )
        registry.register_concept(concept)

    for uri, p_data in data.get("extension_protocols", {}).items():
        protocol = ProtocolDefinition(
            reference_range=p_data.get("reference_range", ""),
            panic_limits=p_data.get("panic_limits", ""),
            clinical_guideline=p_data.get("clinical_guideline"),
        )
        registry.register_protocol(uri, protocol)


_DEFAULT_REGISTRY: Optional[OntologyRegistry] = None


# Find root config directory
def get_default_registry(reload: bool = False) -> OntologyRegistry:
    """Return cached default registry loaded from standard config directory."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None or reload:
        project_root = Path(__file__).resolve().parent.parent.parent
        domain_path = project_root / "config" / "domains" / "laboratory_medicine"
        if not domain_path.exists():
            # Fallback to local config relative to current working directory
            domain_path = Path.cwd() / "config" / "domains" / "laboratory_medicine"
        _DEFAULT_REGISTRY = load_domain_config(domain_path)
    return _DEFAULT_REGISTRY
