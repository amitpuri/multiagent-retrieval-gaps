"""
Naive keyword-retrieval baseline (Gaps 2 & 8) — deliberately ungrounded, used
only to demonstrate semantic blurring next to the ontology-grounded tools.
"""
from src.naive_kb import LAB_KB


def search_lab_kb(query: str) -> str:
    """Search laboratory reference notes by keyword (naive baseline)."""
    terms = [t.lower() for t in query.split()]
    hits = [d["text"] for d in LAB_KB if any(t in d["text"].lower() for t in terms)]
    return "\n---\n".join(hits) or "No matching notes."
