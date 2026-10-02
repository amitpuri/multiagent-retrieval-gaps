"""
ADK 2.0 Deterministic Workflow Graph for Laboratory Medicine.
Closes Gap 9 (Safety rule lives in prompt) by moving routing policy
out of prompt text into code-enforced graph orchestration with
deterministic gating and Human-In-The-Loop pauses (RequestInput).
"""

import re
from typing import Any, Callable, Dict, Generator, Optional, Union
from google.adk import Agent, Event, Workflow
from google.adk.events import RequestInput
from src.agents import MODEL, create_synthesize_agent
from src.tools import fetch_grounded_protocol, resolve_lab_term


def route_for(status: str) -> str:
    """Pure routing function, easy to unit test.
    
    Fails closed on unknown statuses: only 'RESOLVED' proceeds to clinical protocol fetch;
    everything else ('AMBIGUOUS', 'UNIT_MISMATCH', 'NOT_FOUND', 'RANGE_COLLISION', 'UNKNOWN')
    routes to 'CLARIFY'.
    """
    return "PROCEED" if status == "RESOLVED" else "CLARIFY"


def parse(node_input: Any) -> Event:
    """Parser node: extracts test term, optional value, and reported unit from clinician input.
    
    Supports formats:
      - 'Hb'
      - 'Hb | g/dL'
      - 'Hb 13.5 | g/dL'
      - 'Hb | mg/dL'
    """
    if hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text
    elif isinstance(node_input, dict) and "text" in node_input:
        text = node_input["text"]
    else:
        text = str(node_input)

    left, _, unit = text.partition("|")
    left_str = left.strip()
    unit_str = unit.strip()

    # Extract numeric value if present (e.g. 13.5)
    val_match = re.search(r"\b(\d+(?:\.\d+)?)\b", left_str)
    patient_value = float(val_match.group(1)) if val_match else None
    
    # Strip numeric value from term if present
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


def resolve_node(node_input: Dict[str, Any]) -> Event:
    """Ontology resolution node: maps term and unit to canonical LOINC concepts."""
    term = node_input.get("term", "")
    unit = node_input.get("unit", "")
    resolution = resolve_lab_term(term, unit)
    
    # Carry forward patient value
    resolution["patient_value"] = node_input.get("patient_value")
    return Event(output=resolution)


def gate(node_input: Dict[str, Any]) -> Event:
    """Deterministic routing node. No LLM invocation here.
    
    Inspects resolution status and assigns graph branch:
    - 'PROCEED' if RESOLVED
    - 'CLARIFY' if AMBIGUOUS, UNIT_MISMATCH, NOT_FOUND, etc.
    """
    status = node_input.get("status", "")
    return Event(output=node_input, route=route_for(status))


def clarify(node_input: Dict[str, Any]) -> Generator[RequestInput, None, None]:
    """Human-in-the-loop pause node. No LLM invocation here.
    
    Yields RequestInput to pause the workflow until clinician provides missing unit or test.
    """
    status = node_input.get("status", "UNKNOWN")
    candidates = node_input.get("candidates", [])
    labels = ", ".join(c.get("label", "") for c in candidates) or "none"
    message = f"Status {status}. Candidates: {labels}. Which test and unit?"
    yield RequestInput(message=message)


def fetch_node(node_input: Dict[str, Any]) -> Event:
    """Protocol retrieval node: grounded strictly on resolved canonical URI."""
    candidates = node_input.get("candidates", [])
    if candidates and "uri" in candidates[0]:
        uri = candidates[0]["uri"]
        protocol_data = fetch_grounded_protocol(uri)
        result = {
            "resolved_uri": uri,
            "concept": candidates[0],
            "protocol": protocol_data,
            "patient_value": node_input.get("patient_value"),
            "reported_unit": candidates[0]["expected_units"][0],
        }
        return Event(output=result)
    return Event(output={"status": "NO_RESOLVED_CANDIDATE"})


def build_lab_workflow(
    name: str = "lab_gate",
    synthesize_target: Union[Agent, Callable[[Any], Event], None] = None,
) -> Workflow:
    """Build and return an ADK Workflow graph with deterministic gating.
    
    Graph Topology:
        START -> parse -> resolve_node -> gate
        gate --PROCEED--> fetch_node -> synthesize_target
        gate --CLARIFY--> clarify (Human-in-the-loop pause)
    """
    if synthesize_target is None:
        synthesize_target = create_synthesize_agent()

    return Workflow(
        name=name,
        edges=[
            ("START", parse, resolve_node, gate),
            (gate, {"PROCEED": fetch_node, "CLARIFY": clarify}),
            (fetch_node, synthesize_target),
        ],
    )


# Default workflow using the single-turn synthesize agent
root_agent = build_lab_workflow()

# Re-export multi-agent orchestrator workflow
from src.orchestration.a2a_orchestrator import (
    build_multiagent_workflow,
    parse_clinician_input,
)
