"""
Multi-Agent A2A Orchestrator for Laboratory Medicine Decision Support.
Constructs an ADK 2.0 Workflow graph coordinating specialized subagents via
Agent-to-Agent (A2A) structured contracts, deterministic safety gating, and HITL pauses.
"""

import re
from typing import Any, Callable, Dict, Optional, Union
from google.adk import Agent, Event, Workflow
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole
from src.agents.clarification_agent import create_clarification_node
from src.agents.ontology_agent import ontology_resolver_node
from src.agents.protocol_agent import protocol_retriever_node
from src.agents.safety_guard_agent import safety_guard_node
from src.agents.synthesis_agent import create_synthesize_agent


def parse_clinician_input(node_input: Any) -> Event:
    """Parser / Intake Node: Extracts test name, optional unit, numeric value, and qualifier.
    
    Supports formats:
      - 'Hb'
      - 'Hb | g/dL'
      - 'Hb 13.5 | g/dL'
      - 'Calcium 4.8'
      - 'Calcium 4.8 | total'
      - 'Troponin 15 | ng/L'
    """
    if hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text
    elif isinstance(node_input, dict) and "text" in node_input:
        text = node_input["text"]
    else:
        text = str(node_input)

    left, _, right = text.partition("|")
    left_str = left.strip()
    right_str = right.strip()

    # Determine if right part is a unit or a qualifier
    qualifier = ""
    unit = ""
    if right_str.lower() in ("total", "tca", "ionized", "ica", "free", "i", "t"):
        qualifier = right_str.lower()
    else:
        unit = right_str

    # Extract numeric value if present
    val_match = re.search(r"\b(\d+(?:\.\d+)?)\b", left_str)
    patient_value = float(val_match.group(1)) if val_match else None

    # Strip numeric value from term
    cleaned_term = re.sub(r"\b\d+(?:\.\d+)?\b", "", left_str).strip()
    term = cleaned_term if cleaned_term else left_str

    a2a_msg = A2AMessage(
        sender=AgentRole.TRIAGE,
        recipient=AgentRole.ONTOLOGY_RESOLVER,
        action=A2AAction.PARSE_REQUEST,
        payload={
            "raw_text": text,
            "term": term,
            "unit": unit,
            "qualifier": qualifier,
            "patient_value": patient_value,
        },
    )

    return Event(
        output={
            "term": term,
            "unit": unit,
            "qualifier": qualifier,
            "patient_value": patient_value,
            "raw_text": text,
            "a2a_triage_message": a2a_msg.model_dump(mode="json"),
        }
    )


def build_multiagent_workflow(
    name: str = "multiagent_lab_workflow",
    synthesize_target: Union[Agent, Callable[[Any], Event], None] = None,
) -> Workflow:
    """Construct an ADK Workflow coordinating the specialized agents.
    
    Graph Topology:
        START -> parse_clinician_input -> ontology_resolver_node -> safety_guard_node
        safety_guard_node --PROCEED--> protocol_retriever_node -> synthesize_target
        safety_guard_node --CLARIFY--> clarification_node (HITL pause)
    """
    if synthesize_target is None:
        synthesize_target = create_synthesize_agent()

    clarify_node = create_clarification_node()

    return Workflow(
        name=name,
        edges=[
            ("START", parse_clinician_input, ontology_resolver_node, safety_guard_node),
            (safety_guard_node, {"PROCEED": protocol_retriever_node, "CLARIFY": clarify_node}),
            (protocol_retriever_node, synthesize_target),
        ],
    )
