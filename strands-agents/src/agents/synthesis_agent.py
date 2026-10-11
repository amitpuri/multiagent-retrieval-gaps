"""
Clinical Synthesis agent (Strands Agents SDK), built from ``agents/clinical_synthesizer.yaml``.
Instruction, tool grants, hand-offs and skills come from the role spec (``src.agents.roles``).
"""
from typing import Optional

from strands import Agent
from strands.models.model import Model

from src.agents.roles import build_role_agent


def create_synthesis_agent(model: Optional[Model] = None) -> Agent:
    """The clinical_synthesizer agent, built from its role spec."""
    return build_role_agent("clinical_synthesizer", model=model)
