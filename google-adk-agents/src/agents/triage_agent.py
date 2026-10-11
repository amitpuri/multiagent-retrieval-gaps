"""
Triage Orchestrator Agent: Entrypoint for the multi-agent retrieval-gap pipeline.
Ingests raw clinician queries, coordinates specialist subagent delegation
via A2A structured envelopes, and manages session state across conversation turns.
"""

from typing import Any, Optional
from google.adk import Agent

from src.a2a.contracts import A2AAction, A2AMessage, AgentRole

from ontogate.catalog import model_for
from src.skills_loader import skill_tools_for

DEFAULT_MODEL = model_for("gcp")["id"]  # config/models.yaml


def create_triage_agent(model: Optional[str] = None) -> Agent:
    """The triage_orchestrator agent, built from agents/triage_orchestrator.yaml.

    It is granted parse / resolve / gate and hands off to the roles it delegates
    to (each an ``AgentTool`` built from its own role spec). The deterministic
    gate, not the model, decides which hand-off happens.
    """
    from src.agents.roles import build_role_agent
    return build_role_agent("triage_orchestrator", model=model or DEFAULT_MODEL)


def make_triage_envelope(
    raw_text: str,
    term: str,
    unit: str = "",
    qualifier: str = "",
    patient_value: Any = None,
) -> A2AMessage:
    """Construct the initial A2A envelope dispatched by the Triage Orchestrator."""
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
