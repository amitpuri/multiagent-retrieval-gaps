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
    
    Delegates to the shared ontology-aware parser (``ontogate.parsing``), so the
    workflow parser, this intake node and every framework extract identical fields.
    """
    if hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text
    elif isinstance(node_input, dict) and "text" in node_input:
        text = node_input["text"]
    else:
        text = str(node_input)

    from ontogate.parsing import parse_clinician_text

    parsed = parse_clinician_text(text)
    term = parsed["term"]
    unit = parsed["unit"]
    qualifier = parsed["qualifier"]
    patient_value = parsed["patient_value"]
    ambiguous_thousands = parsed["ambiguous_thousands"]

    # OKF: Progressive disclosure pre-scoping via concept index
    department_scope = None
    index_match_count = 0
    try:
        from ontogate.config import get_default_registry
        from ontogate.okf_index import build_index, inspect_index_scope
        reg = get_default_registry()
        idx = build_index(reg)
        scope = inspect_index_scope(idx, term)
        department_scope = scope.get("department_scope")
        index_match_count = scope.get("match_count", 0)
    except Exception:
        pass

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
            "department_scope": department_scope,
            "index_match_count": index_match_count,
            "ambiguous_thousands": ambiguous_thousands,
        },
    )

    return Event(
        output={
            "term": term,
            "unit": unit,
            "qualifier": qualifier,
            "patient_value": patient_value,
            "raw_text": text,
            "department_scope": department_scope,
            "index_match_count": index_match_count,
            "ambiguous_thousands": ambiguous_thousands,
            "ambiguous_value": parsed["ambiguous_value"],
            "population": parsed["population"],
            "department": parsed["department"],
            "panel_id": parsed["panel_id"],
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
