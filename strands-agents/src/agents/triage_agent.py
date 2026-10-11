"""
Triage Orchestrator (Strands Agents SDK), built from ``agents/triage_orchestrator.yaml``.

It is granted parse / resolve / gate and hands off to the roles it delegates to
(protocol retriever, clinical synthesizer, clarification coordinator, panel
coordinator), each a tool that runs that role's own agent. The deterministic
gate, not the model, decides which hand-off happens.
"""
from typing import Any, Optional

from strands import Agent
from strands.models.model import Model

from src.agents.roles import build_role_agent


def create_triage_orchestrator(model: Optional[Model] = None) -> Agent:
    """The triage_orchestrator agent, built from its role spec."""
    return build_role_agent("triage_orchestrator", model=model)


create_triage_agent = create_triage_orchestrator


def make_triage_envelope(
    raw_text: str,
    term: str,
    unit: str = "",
    qualifier: str = "",
    patient_value: Any = None,
):
    """Construct the initial A2A envelope dispatched by the Triage Orchestrator."""
    from src.a2a.contracts import A2AAction, A2AMessage, AgentRole

    return A2AMessage(
        sender=AgentRole.TRIAGE,
        recipient=AgentRole.ONTOLOGY_RESOLVER,
        action=A2AAction.PARSE_REQUEST,
        payload={
            "raw_text": raw_text,
            "term": term,
            "unit": unit,
            "qualifier": qualifier,
            "patient_value": patient_value,
        },
    )
