"""
Google ADK agent definitions and multi-agent roles for laboratory medicine.
"""

from typing import Optional
from google.adk import Agent
from src.tools import fetch_grounded_protocol, resolve_lab_term, search_lab_kb

# Recommended Gemini model for ADK agents
MODEL = "gemini-3.5-flash"

# -------------------------------------------------------------------------
# Agent 1: The Naive RAG Agent (Pure Keyword Retrieval)
# -------------------------------------------------------------------------
naive_agent = Agent(
    name="naive_lab_agent",
    model=MODEL,
    instruction=(
        "You are a laboratory assistant. Use search_lab_kb to find "
        "reference notes, then interpret the result for the clinician."
    ),
    tools=[search_lab_kb],
)

# -------------------------------------------------------------------------
# Agent 2: Ontology-Grounded Agent v1 (Prompt-governed safety)
# -------------------------------------------------------------------------
grounded_agent_v1 = Agent(
    name="grounded_lab_agent_v1",
    model=MODEL,
    instruction="""You are a laboratory decision-support assistant.
1. Call resolve_lab_term with the test name and unit (empty if none reported).
2. If status is AMBIGUOUS, UNIT_MISMATCH or NOT_FOUND: do NOT interpret the value.
   List the candidates (label, department, expected units) and ask which was ordered.
3. If RESOLVED: call fetch_grounded_protocol with the uri and interpret using ONLY
   the returned data. Name the concept you resolved to.
4. Never fill gaps from general knowledge.""",
    tools=[resolve_lab_term, fetch_grounded_protocol],
)

# -------------------------------------------------------------------------
# Specialized Multi-Agent Factory Exports
# -------------------------------------------------------------------------
from src.agents.ontology_agent import create_ontology_agent, ontology_resolver_node
from src.agents.safety_guard_agent import create_safety_guard_agent, safety_guard_node
from src.agents.protocol_agent import create_protocol_agent, protocol_retriever_node
from src.agents.synthesis_agent import create_synthesize_agent
from src.agents.clarification_agent import create_clarification_node
from src.agents.triage_agent import create_triage_agent, make_triage_envelope

synthesize = create_synthesize_agent(MODEL)

__all__ = [
    "MODEL",
    "naive_agent",
    "grounded_agent_v1",
    "synthesize",
    "create_synthesize_agent",
    "create_triage_agent",
    "make_triage_envelope",
    "create_ontology_agent",
    "ontology_resolver_node",
    "create_safety_guard_agent",
    "safety_guard_node",
    "create_protocol_agent",
    "protocol_retriever_node",
    "create_clarification_node",
]
