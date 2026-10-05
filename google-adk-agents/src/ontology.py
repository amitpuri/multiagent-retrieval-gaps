"""
Ontology definitions and semantic knowledge bases for laboratory medicine retrieval.
Covers controlled vocabularies, thesaurus alternate labels, LOINC concept mappings,
reference protocols, and CSF tube sequencing as described in:
'Information Retrieval, Part III: When the Retriever Has to Decide'

Dynamically populated from declarative YAML configurations (config/domains/laboratory_medicine/).
"""
from __future__ import annotations

from typing import Any, Dict, List
from src.core.config import get_default_registry

# Initialize registry from YAML configs
_registry = get_default_registry()

# -------------------------------------------------------------------------
# Scenario A (Gap 2 & Gap 8): Unstructured Mock Notes (Naive KB)
# -------------------------------------------------------------------------
LAB_KB: List[Dict[str, str]] = [
    {
        "id": "KB-1",
        "text": (
            "Hb above 10% means poorly controlled diabetes. "
            "Hb above 13% is critical: escalate to endocrinology."
        ),
    },
    {
        "id": "KB-2",
        "text": (
            "Adult male Hb reference range is 13.8 to 17.2 g/dL. "
            "Below 12.0 g/dL suggests anemia."
        ),
    },
]

# -------------------------------------------------------------------------
# Scenario A (Gap 2 & Gap 8): Controlled Vocabulary & Thesaurus (CONCEPTS)
# -------------------------------------------------------------------------
class _DynamicConcepts(dict):
    """Dynamically delegates to live registry so scenario extensions are visible."""

    def __getitem__(self, uri: str) -> Dict[str, Any]:
        reg = get_default_registry()
        if uri in reg.concepts:
            c = reg.concepts[uri]
            return {
                "label": c.label,
                "alt_labels": c.alt_labels,
                "department": c.department,
                "units": c.units,
            }
        return super().__getitem__(uri)

    def __contains__(self, uri: object) -> bool:
        return uri in get_default_registry().concepts or super().__contains__(uri)

    def items(self):
        reg = get_default_registry()
        seen = set()
        for uri, c in reg.concepts.items():
            seen.add(uri)
            yield uri, {
                "label": c.label,
                "alt_labels": c.alt_labels,
                "department": c.department,
                "units": c.units,
            }
        for k, v in super().items():
            if k not in seen:
                yield k, v

    def values(self):
        for _, v in self.items():
            yield v

    def keys(self):
        reg = get_default_registry()
        k_list = list(reg.concepts.keys())
        for k in super().keys():
            if k not in reg.concepts:
                k_list.append(k)
        return k_list

    def get(self, uri: str, default: Any = None) -> Any:
        try:
            return self[uri]
        except KeyError:
            return default

    def __len__(self) -> int:
        return len(list(self.keys()))

    def __iter__(self):
        return iter(self.keys())


CONCEPTS: Dict[str, Dict[str, Any]] = _DynamicConcepts()

# -------------------------------------------------------------------------
# Scenario A: Grounded Protocols Keyed by Canonical Concept URI
# -------------------------------------------------------------------------
class _DynamicProtocols(dict):
    """Dynamically delegates to live registry so scenario extensions are visible."""

    def __getitem__(self, uri: str) -> Dict[str, str]:
        reg = get_default_registry()
        if uri in reg.protocols:
            p = reg.protocols[uri]
            return {
                "reference_range": p.reference_range,
                "panic_limits": p.panic_limits,
            }
        return super().__getitem__(uri)

    def __contains__(self, uri: object) -> bool:
        return uri in get_default_registry().protocols or super().__contains__(uri)

    def items(self):
        reg = get_default_registry()
        seen = set()
        for uri, p in reg.protocols.items():
            seen.add(uri)
            yield uri, {
                "reference_range": p.reference_range,
                "panic_limits": p.panic_limits,
            }
        for k, v in super().items():
            if k not in seen:
                yield k, v

    def values(self):
        for _, v in self.items():
            yield v

    def keys(self):
        reg = get_default_registry()
        k_list = list(reg.protocols.keys())
        for k in super().keys():
            if k not in reg.protocols:
                k_list.append(k)
        return k_list

    def get(self, uri: str, default: Any = None) -> Any:
        try:
            return self[uri]
        except KeyError:
            return default

    def __len__(self) -> int:
        return len(list(self.keys()))

    def __iter__(self):
        return iter(self.keys())


PROTOCOLS: Dict[str, Dict[str, str]] = _DynamicProtocols()

# -------------------------------------------------------------------------
# Scenario B (Gap 11): CSF Emergency Panel Taxonomy & Department Ownership
# -------------------------------------------------------------------------
CSF_TESTS: Dict[str, Dict[str, Any]] = {}
_csf_panel = _registry.get_panel("csf_emergency_panel")
if _csf_panel:
    for _rule in _csf_panel.tube_rules:
        for _test in _rule.tests:
            CSF_TESTS[_test["uri"]] = {
                "test": _test["test_name"],
                "department": _rule.department,
                "tube": _rule.tube,
            }

# -------------------------------------------------------------------------
# Scenario C (Look-Alike Tests & Range Collisions): Total vs Ionized Calcium
# Keyed by assay registry ID (e.g. 'total_calcium', 'total_calcium_mmol') so
# that mmol/L and mg/dL variants sharing the same LOINC URI do not overwrite
# each other.  check_calcium() only uses mg/dL assays (filter by unit == mg/dL).
# -------------------------------------------------------------------------
RANGES: Dict[str, Dict[str, Any]] = {
    assay_id: {
        "name": assay.name,
        "ref": (assay.ref_low, assay.ref_high),
        "crit_low": assay.crit_low,
        "crit_high": assay.crit_high,
        "unit": assay.unit,
        "uri": assay.uri,
    }
    for assay_id, assay in _registry.assays.items()
}
