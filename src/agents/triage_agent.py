"""
Triage Orchestrator Agent: Entrypoint for the multi-agent retrieval-gap pipeline.
Ingests raw clinician queries, coordinates specialist subagent delegation
via A2A structured envelopes, and manages session state across conversation turns.
"""

from typing import Any, Optional
from google.adk import Agent

from src.a2a.contracts import A2AAction, A2AMessage, AgentRole

DEFAULT_MODEL = "gemini-3.5-flash"


def create_triage_agent(model: Optional[str] = None) -> Agent:
    """Create the Triage Orchestrator ADK Agent.
    
    This agent serves as the primary entrypoint that:
    1. Accepts raw clinician queries and parsed intent.
    2. Delegates to OntologyResolverAgent, SafetyGuardAgent, ProtocolRetrieverAgent,
       ClinicalSynthesizerAgent, and ClarificationCoordinatorAgent via A2A.
    3. Enforces strict fail-closed session state management.
    """
    chosen_model = model or DEFAULT_MODEL
    return Agent(
        name="triage_orchestrator",
        model=chosen_model,
        instruction=(
            "You are the Triage Orchestrator for a clinical laboratory decision-support system.\n"
            "Your responsibilities:\n"
            "1. Accept a clinician's raw query (e.g. 'Hb 13.5 | g/dL') and extract: term, unit, value, qualifier.\n"
            "2. Delegate ontology resolution to the OntologyResolverAgent.\n"
            "3. Delegate safety validation to the SafetyGuardAgent (deterministic, fail-closed).\n"
            "4. If safety gate passes, delegate to ProtocolRetrieverAgent then ClinicalSynthesizerAgent.\n"
            "5. If safety gate fails (AMBIGUOUS, UNIT_MISMATCH, RANGE_COLLISION), "
            "delegate to ClarificationCoordinatorAgent and await clinician response.\n"
            "Never speculate. Never proceed if status is not RESOLVED. Always cite which agent produced each finding."
        ),
    )


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
