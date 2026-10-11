"""
Ontology Specialist Agent using Strands Agents SDK.
Maps clinician queries to canonical LOINC identifiers.
"""
from typing import Optional
from strands import Agent
from strands.models.model import Model
from src.tools.ontology_tool import resolve_lab_term


def create_ontology_agent(model: Optional[Model] = None) -> Agent:
    """Create an Ontology Specialist Agent."""
    return Agent(
        model=model,
        system_prompt=(
            "You are an Ontology Resolution Specialist for Laboratory Medicine.\n"
            "Your sole responsibility is to map incoming lab test terms and units to canonical "
            "LOINC identifiers using the resolve_lab_term tool.\n"
            "Never guess or assume unverified concepts. Always return the structured resolution result verbatim."
        ),
        tools=[resolve_lab_term],
    )
