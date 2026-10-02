"""
Google ADK agent definitions for laboratory medicine.
Includes:
1. Naive agent (pure keyword retrieval, demonstrating Gap 2 & Gap 8)
2. Grounded agent v1 (tool-equipped with resolver, demonstrating Gap 9)
3. Synthesis agent (single-turn agent used within the deterministic graph)
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
# Where it still fails (Gap 9): Instructions are probabilistic.
# The model might guess, skip the resolver, or interpret ambiguous results anyway.
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
# Agent 3: Single-Turn Synthesis Agent (Used in ADK Workflow Graph)
# -------------------------------------------------------------------------
def create_synthesize_agent(model: str = MODEL) -> Agent:
    """Create a single-turn agent for synthesizing interpretations from grounded protocols."""
    return Agent(
        name="synthesize",
        model=model,
        mode="single_turn",
        instruction=(
            "You are a clinical laboratory specialist. Interpret the patient's value "
            "using ONLY the protocol data provided in the input. Name the resolved LOINC "
            "concept, cite the reference range and panic limits, and provide a calibrated, "
            "cautious interpretation. Never speculate beyond the provided protocol."
        ),
    )


synthesize = create_synthesize_agent()
