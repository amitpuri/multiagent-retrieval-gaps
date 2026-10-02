"""
Ontology definitions and semantic knowledge bases for laboratory medicine retrieval.
Covers controlled vocabularies, thesaurus alternate labels, LOINC concept mappings,
reference protocols, and CSF tube sequencing as described in:
'Information Retrieval, Part III: When the Retriever Has to Decide'

Dynamically populated from declarative YAML configurations (config/domains/laboratory_medicine/).
"""

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
CONCEPTS: Dict[str, Dict[str, Any]] = {
    uri: {
        "label": c.label,
        "alt_labels": c.alt_labels,
        "department": c.department,
        "units": c.units,
    }
    for uri, c in _registry.concepts.items()
}

# -------------------------------------------------------------------------
# Scenario A: Grounded Protocols Keyed by Canonical Concept URI
# -------------------------------------------------------------------------
PROTOCOLS: Dict[str, Dict[str, str]] = {
    uri: {
        "reference_range": p.reference_range,
        "panic_limits": p.panic_limits,
    }
    for uri, p in _registry.protocols.items()
}

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
# -------------------------------------------------------------------------
RANGES: Dict[str, Dict[str, Any]] = {
    assay.uri: {
        "name": assay.name,
        "ref": (assay.ref_low, assay.ref_high),
        "crit_low": assay.crit_low,
        "crit_high": assay.crit_high,
        "unit": assay.unit,
    }
    for assay in _registry.assays.values()
}
