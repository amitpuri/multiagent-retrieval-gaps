"""
Clarification Coordinator Agent: Human-In-The-Loop (HITL) pause via RequestInput.
Constructs targeted clinical clarification prompts when safety invariants fail closed.
"""

from typing import Any, Dict, Generator
from google.adk.events import RequestInput


def create_clarification_node() -> Any:
    """Generate the clarification generator node for ADK workflows."""
    def clarify_node(node_input: Dict[str, Any]) -> Generator[RequestInput, None, None]:
        status = node_input.get("status", "UNKNOWN")
        candidates = node_input.get("candidates", [])
        term = node_input.get("term", "")
        reported_unit = node_input.get("reported_unit") or node_input.get("unit")
        collision_details = node_input.get("collision_details", {})

        labels = ", ".join(c.get("label", "") for c in candidates) or "none"
        message = f"Status {status}. Candidates: {labels}. Which test and unit?"
        yield RequestInput(message=message)

    return clarify_node
