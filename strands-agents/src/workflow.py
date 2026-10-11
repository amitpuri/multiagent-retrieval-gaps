"""
Workflow routing and parsing helpers (shared parser, fail-closed routing).
Provides route_for and parse for pure-code deterministic evaluation.
"""
from typing import Any, Dict


class Event:
    """Lightweight event container for test assertions."""
    def __init__(self, output: Dict[str, Any]):
        self.output = output


def route_for(status: str) -> str:
    """Pure routing function, fail-closed on anything other than RESOLVED."""
    return "PROCEED" if status == "RESOLVED" else "CLARIFY"


def parse(node_input: Any) -> Event:
    """Parser node: shared ontology-aware parse (``ontogate.parsing``)."""
    if hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text
    elif isinstance(node_input, dict) and "text" in node_input:
        text = node_input["text"]
    else:
        text = str(node_input)

    from ontogate.parsing import parse_clinician_text

    return Event(output=parse_clinician_text(text))
