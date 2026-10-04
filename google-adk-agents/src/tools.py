"""
Clinical laboratory retrieval and resolution tools.
Implements the naive retrieval baseline and the ontology-grounded tools
from 'Information Retrieval, Part III: When the Retriever Has to Decide'.
"""

from typing import Any, Dict, List, Optional
from src.ontology import CONCEPTS, CSF_TESTS, LAB_KB, PROTOCOLS, RANGES


# -------------------------------------------------------------------------
# Step 1: Naive Agent Retrieval Tool (Gap 2: Semantic Blurring & Gap 8)
# -------------------------------------------------------------------------
def search_lab_kb(query: str) -> str:
    """Search laboratory reference notes by keyword.
    
    Demonstrates Gap 2 (semantic blurring) and Gap 8 (silent confidence)
    where searching 'Hb 13.5' matches both Hematology and Endocrinology notes.
    """
    terms = [t.lower() for t in query.split()]
    hits = [d["text"] for d in LAB_KB if any(t in d["text"].lower() for t in terms)]
    return "\n---\n".join(hits) or "No matching notes."


# -------------------------------------------------------------------------
# Step 4: The Ontology Resolver (Gap 8: Ambiguity becomes an explicit output)
# -------------------------------------------------------------------------
def _view(uri: str) -> Dict[str, Any]:
    """Helper to project a concept view for agent consumption."""
    c = CONCEPTS[uri]
    return {
        "uri": uri,
        "label": c["label"],
        "department": c["department"],
        "expected_units": c["units"],
    }


def resolve_lab_term(term: str, unit: str = "") -> Dict[str, Any]:
    """Map a lab test name (and optional unit) to canonical LOINC concepts.
    
    Never guesses: returns AMBIGUOUS when several concepts match.
    Returns:
        - RESOLVED: exactly one concept matched.
        - AMBIGUOUS: multiple concepts matched the term (e.g. 'Hb' matches both LOINC 718-7 and 4548-4).
        - UNIT_MISMATCH: the provided unit does not belong to any matching concept.
        - NOT_FOUND: no concept matched the search term.
    """
    t = term.strip().lower()
    candidates = [
        u
        for u, c in CONCEPTS.items()
        if t == c["label"].lower() or t in [alt.lower() for alt in c["alt_labels"]]
    ]
    if not candidates:
        return {"status": "NOT_FOUND", "candidates": []}

    if unit:  # ontology constraint: the unit must be valid for the concept
        u = unit.strip().lower()
        matched = [
            c
            for c in candidates
            if u in [x.lower() for x in CONCEPTS[c]["units"]]
        ]
        if not matched:
            return {
                "status": "UNIT_MISMATCH",
                "reported_unit": unit,
                "candidates": [_view(c) for c in candidates],
            }
        candidates = matched

    status = "RESOLVED" if len(candidates) == 1 else "AMBIGUOUS"
    return {"status": status, "candidates": [_view(c) for c in candidates]}


# -------------------------------------------------------------------------
# Step 5: Grounded Protocol Retrieval by Canonical URI
# -------------------------------------------------------------------------
def fetch_grounded_protocol(uri: str) -> Dict[str, Any]:
    """Fetch clinical reference data bound to one canonical concept URI.
    
    Ensures knowledge attaches to a unique concept identifier,
    preventing cross-concept contamination.
    """
    return PROTOCOLS.get(uri, {"status": "NOT_FOUND"})


# -------------------------------------------------------------------------
# Scenario B: CSF Emergency Panel Workup (Closing Gap 11: Scope Retrieval)
# -------------------------------------------------------------------------
def csf_workup(department: str = "") -> Dict[str, Any]:
    """Return CSF tests grouped by owning department, with tube assignments.
    
    Pre-scopes results by department ownership and governed tube sequence:
    Tube 1: Clinical Biochemistry (Protein, Glucose)
    Tube 2: Microbiology (Gram stain, Culture)
    Tube 3: Hematology (Leukocytes, Neutrophils)
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for uri, t in CSF_TESTS.items():
        if department and department.lower() not in t["department"].lower():
            continue
        grouped.setdefault(t["department"], []).append(
            {"uri": uri, "test": t["test"], "tube": t["tube"]}
        )
    return grouped or {"status": "NOT_FOUND"}


# -------------------------------------------------------------------------
# Scenario C: Look-Alike Tests & Range Collisions (Total vs Ionized Calcium)
# -------------------------------------------------------------------------
def classify(value: float, r: Dict[str, Any]) -> str:
    """Classify a numeric value against clinical reference and critical ranges."""
    if value < r["crit_low"]:
        return "CRITICAL_LOW"
    if value > r["crit_high"]:
        return "CRITICAL_HIGH"
    if value < r["ref"][0]:
        return "LOW"
    if value > r["ref"][1]:
        return "HIGH"
    return "NORMAL"


def check_calcium(value_mg_dl: float, qualifier: str = "") -> Dict[str, Any]:
    """Classify a calcium value (mg/dL) under plausible concepts.

    Flags RANGE_COLLISION if candidate interpretations conflict.
    For example: 4.8 mg/dL is CRITICAL_LOW for Total Calcium (ref 8.5-10.5)
    but NORMAL for Ionized Calcium (ref 4.5-5.6).

    Only mg/dL assay entries are evaluated (value_mg_dl parameter);
    mmol/L variants in RANGES are excluded to prevent wrong-unit classification.
    """
    q = qualifier.strip().lower()
    # Filter to mg/dL assay entries only (RANGES now also contains mmol/L variants)
    mgdl_ranges = {k: v for k, v in RANGES.items() if v.get("unit", "mg/dL") == "mg/dL"}

    if q in ("total", "tca"):
        uris = [k for k, v in mgdl_ranges.items() if "total" in v["name"].lower()]
    elif q in ("ionized", "ica", "free"):
        uris = [k for k, v in mgdl_ranges.items() if "ionized" in v["name"].lower()]
    else:
        uris = list(mgdl_ranges)

    readings = {mgdl_ranges[u]["name"]: classify(value_mg_dl, mgdl_ranges[u]) for u in uris}
    status = "RANGE_COLLISION" if len(set(readings.values())) > 1 else "RESOLVED"
    return {"status": status, "value_mg_dl": value_mg_dl, "readings": readings}
