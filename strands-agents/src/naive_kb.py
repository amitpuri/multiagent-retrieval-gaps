"""
Unstructured reference notes for the naive keyword-retrieval baseline.

These notes intentionally mix Hematology and Endocrinology statements about
"Hb" so ``search_lab_kb`` can demonstrate semantic blurring (Gap 2) and silent
confidence (Gap 8). Ontology-grounded tools never read this corpus.
"""
from typing import Dict, List

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
