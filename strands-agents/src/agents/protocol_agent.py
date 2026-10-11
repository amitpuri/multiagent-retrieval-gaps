"""
Protocol Retrieval agent (Strands Agents SDK), built from ``agents/protocol_retriever.yaml``.
Instruction, tool grants, hand-offs and skills come from the role spec (``src.agents.roles``).
"""
from typing import Optional

from strands import Agent
from strands.models.model import Model

from src.agents.roles import build_role_agent


def create_protocol_agent(model: Optional[Model] = None) -> Agent:
    """The protocol_retriever agent, built from its role spec."""
    return build_role_agent("protocol_retriever", model=model)
