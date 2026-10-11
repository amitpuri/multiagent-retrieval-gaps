"""
Clinical Protocol Retrieval Agent using Strands Agents SDK.
Fetches reference intervals, panic limits, and clinical guidelines.
"""
from typing import Optional
from strands import Agent
from strands.models.model import Model
from src.tools.protocol_tool import fetch_grounded_protocol


def create_protocol_agent(model: Optional[Model] = None) -> Agent:
    """Create a Protocol Retrieval Agent."""
    return Agent(
        model=model,
        system_prompt=(
            "You are a Clinical Protocol Retrieval Specialist.\n"
            "Use the fetch_grounded_protocol tool to retrieve reference ranges and panic thresholds "
            "for verified canonical LOINC URIs. Never fabricate or interpolate ranges."
        ),
        tools=[fetch_grounded_protocol],
    )
