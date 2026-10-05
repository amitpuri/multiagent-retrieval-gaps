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

    parts = [p.strip() for p in text.split("|")]
    left_str = parts[0]
    unit = ""
    qualifier = ""

    KNOWN_QUALIFIERS = {"total", "tca", "ionized", "ica", "free", "i", "t"}
    KNOWN_UNITS = {"g/dl", "g/l", "%", "mg/dl", "mmol/l", "ng/l", "/ul", "ng/ml"}

    for part in parts[1:]:
        p_lower = part.lower()
        if p_lower in KNOWN_QUALIFIERS and not qualifier:
            qualifier = p_lower
        elif (p_lower in KNOWN_UNITS or not unit) and not unit:
            unit = part

    # Ambiguous thousands-separator guard (e.g. "Troponin 1,250 | ng/L")
    ambiguous_thousands = bool(re.search(r"\b\d+,\d{3}\b", left_str))

    # Normalise comma-decimal notation (e.g. "4,8" -> "4.8") only when NOT thousands
    left_normalised = left_str
    patient_value: Optional[float] = None
    if not ambiguous_thousands:
        left_normalised = re.sub(r"(\d),(\d)", r"\1.\2", left_str)
        val_match = re.search(r"(?:^|(?<=\s))(-?\d+(?:\.\d+)?)(?![\w-])", left_normalised)
        patient_value = float(val_match.group(1)) if val_match else None

    # Strip matched number from term
    cleaned_term = re.sub(r"(?:^|(?<=\s))-?\d+(?:\.\d+)?(?![\w-])", "", left_normalised).strip()
    term = cleaned_term if cleaned_term else left_str.strip()

    # OKF Phase 5: Progressive disclosure pre-scoping via concept index
    department_scope = None
    index_match_count = 0
    try:
        from src.core.config import get_default_registry
        from src.core.okf_index import build_index, inspect_index_scope
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
