"""
Clinical laboratory tools for the ADK agents.

``search_lab_kb`` is the deliberately naive keyword-retrieval baseline from
'Information Retrieval, Part III: When the Retriever Has to Decide' (Gaps 2 & 8).
Every ontology-grounded tool is the shared canonical implementation in
``ontogate.tools`` — one semantics across ADK, Strands and MAF.
"""
from __future__ import annotations

from ontogate.tools import (  # noqa: F401  (canonical tools, re-exported)
    attest_computation,
    build_clarification_prompt,
    classify_lookalikes,
    evaluate_safety_gate,
    fetch_grounded_protocol,
    panel_workup,
    parse_clinician_input,
    resolve_lab_term,
)
from src.naive_kb import LAB_KB


def search_lab_kb(query: str) -> str:
    """Search laboratory reference notes by keyword (naive baseline).

    Demonstrates Gap 2 (semantic blurring) and Gap 8 (silent confidence):
    searching 'Hb 13.5' matches both Hematology and Endocrinology notes.
    """
    terms = [t.lower() for t in query.split()]
    hits = [d["text"] for d in LAB_KB if any(t in d["text"].lower() for t in terms)]
    return "\n---\n".join(hits) or "No matching notes."
