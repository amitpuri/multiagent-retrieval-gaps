"""
Ontology definitions and semantic knowledge bases for laboratory medicine retrieval.
Covers controlled vocabularies, thesaurus alternate labels, LOINC concept mappings,
reference protocols, and CSF tube sequencing as described in:
'Information Retrieval, Part III: When the Retriever Has to Decide'
"""

from typing import Any, Dict, List

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
# Jessica Talisman's Ontology Pipeline:
# Controlled Vocabulary -> Metadata -> Taxonomy -> Thesaurus -> Ontology
CONCEPTS: Dict[str, Dict[str, Any]] = {
    "loinc:718-7": {
        "label": "Hemoglobin [Mass/volume] in Blood",
        "alt_labels": [
            "hb",
            "hgb",
            "hemoglobin",
            "total hemoglobin",
            "cbc hemoglobin",
        ],
        "department": "Hematology",
        "units": ["g/dL", "g/L"],
    },
    "loinc:4548-4": {
        "label": "Hemoglobin A1c/Hemoglobin.total in Blood",
        "alt_labels": [
            "hb",
            "hemoglobin",
            "hba1c",
            "hb a1c",
            "a1c",
            "glycated hemoglobin",
        ],
        "department": "Clinical Biochemistry",
        "units": ["%"],  # IFCC results in mmol/mol belong to LOINC 59261-8
    },
}

# -------------------------------------------------------------------------
# Scenario A: Grounded Protocols Keyed by Canonical Concept URI
# -------------------------------------------------------------------------
PROTOCOLS: Dict[str, Dict[str, str]] = {
    "loinc:718-7": {
        "reference_range": "Adult male 13.8-17.2 g/dL; adult female 12.1-15.1 g/dL",
        "panic_limits": "Low < 7.0 g/dL; high > 20.0 g/dL",
    },
    "loinc:4548-4": {
        "reference_range": "Normal < 5.7%; prediabetes 5.7-6.4%; diabetes >= 6.5%",
        "panic_limits": "Values far above target need urgent review of glycemic control",
    },
}

# -------------------------------------------------------------------------
# Scenario B (Gap 11): CSF Emergency Panel Taxonomy & Department Ownership
# -------------------------------------------------------------------------
# Single Lumbar Puncture specimen distributed across three departments:
# Tube 1: Biochemistry (Protein, Glucose)
# Tube 2: Microbiology (Gram stain, Culture)
# Tube 3: Hematology (Cell count: Leukocytes, Neutrophils)
CSF_TESTS: Dict[str, Dict[str, Any]] = {
    "loinc:2880-3": {
        "test": "Protein [Mass/volume] in CSF",
        "department": "Clinical Biochemistry",
        "tube": 1,
    },
    "loinc:2342-4": {
        "test": "Glucose [Mass/volume] in CSF",
        "department": "Clinical Biochemistry",
        "tube": 1,
    },
    "loinc:14357-8": {
        "test": "Microscopic observation [Identifier] in CSF by Gram stain",
        "department": "Microbiology",
        "tube": 2,
    },
    "loinc:606-4": {
        "test": "Bacteria identified in CSF by culture",
        "department": "Microbiology",
        "tube": 2,
    },
    "loinc:26465-5": {
        "test": "Leukocytes [#/volume] in CSF",
        "department": "Hematology",
        "tube": 3,
    },
    "loinc:26512-4": {
        "test": "Neutrophils/Leukocytes in CSF",
        "department": "Hematology",
        "tube": 3,
    },
}

# -------------------------------------------------------------------------
# Scenario C (Look-Alike Tests & Range Collisions): Total vs Ionized Calcium
# -------------------------------------------------------------------------
RANGES: Dict[str, Dict[str, Any]] = {
    "loinc:17861-6": {
        "name": "Total calcium",
        "ref": (8.5, 10.5),
        "crit_low": 6.0,
        "crit_high": 13.0,
        "unit": "mg/dL",
    },
    "loinc:17864-0": {
        "name": "Ionized calcium",
        "ref": (4.5, 5.6),
        "crit_low": 3.0,
        "crit_high": 6.5,
        "unit": "mg/dL",
    },
}
