"""
Clarification Coordinator Agent using Strands Agents SDK.
Builds human-in-the-loop clarification questions when ambiguous tests or range collisions occur.
"""
from typing import Optional
from strands import Agent
from strands.models.model import Model
from src.tools.clarification_tool import build_clarification_prompt


def create_clarification_agent(model: Optional[Model] = None) -> Agent:
    """Create a Clarification Coordinator Agent."""
    return Agent(
        model=model,
        system_prompt=(
            "You are a Clinical Clarification Coordinator.\n"
            "When a query fails the deterministic safety gate (due to ambiguity, unit mismatch, "
            "or range collision), use build_clarification_prompt to format a precise, unambiguous "
            "question for the ordering clinician."
        ),
        tools=[build_clarification_prompt],
    )
