"""
Workflow routing and parsing compatibility helpers.
Provides route_for and parse for pure-code deterministic evaluation.
"""
import re
from typing import Any, Dict


class Event:
    """Lightweight event container for test assertions."""
    def __init__(self, output: Dict[str, Any]):
        self.output = output


def route_for(status: str) -> str:
    """Pure routing function, fail-closed on anything other than RESOLVED."""
    return "PROCEED" if status == "RESOLVED" else "CLARIFY"


def parse(node_input: Any) -> Event:
    """Parser node: extracts test term, optional value, and reported unit."""
    if hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text
    elif isinstance(node_input, dict) and "text" in node_input:
        text = node_input["text"]
    else:
        text = str(node_input)

    left, _, unit = text.partition("|")
    left_str = left.strip()
    unit_str = unit.strip()

    val_match = re.search(r"\b(\d+(?:\.\d+)?)\b", left_str)
    patient_value = float(val_match.group(1)) if val_match else None

    cleaned_term = re.sub(r"\b\d+(?:\.\d+)?\b", "", left_str).strip()
    term = cleaned_term if cleaned_term else left_str

    return Event(
        output={
            "term": term,
            "unit": unit_str,
            "patient_value": patient_value,
            "raw_text": text,
        }
    )
