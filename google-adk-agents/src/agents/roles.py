"""
Role spec → ADK ``Agent`` (plan P8.4: one instruction source and one tool grant per role).

Every model-backed ADK agent is built from ``agents/<role>.yaml``: the shared
instruction text (``ontogate.roles.instruction_for``), exactly the granted
canonical tools (the model-facing MCP contract), one ``AgentTool`` per role it
may hand off to, and its runtime skills. Runtime context — such as the trust
posture of the concept being interpreted — is appended, never substituted.
"""
from __future__ import annotations

from typing import Any, List, Optional

from google.adk import Agent
from google.adk.tools.agent_tool import AgentTool

from ontogate.catalog import model_for
from ontogate.mcp_server import CLINICAL_MCP_TOOLS
from ontogate.roles import get_role_spec, instruction_for
from src.skills_loader import skill_tools_for


def role_tools(role: str) -> List[Any]:
    """The canonical tools a role is granted, as model-facing functions ADK can declare."""
    return [CLINICAL_MCP_TOOLS[name] for name in get_role_spec(role).tools]


def build_role_agent(role: str, *, model: Optional[str] = None, context: str = "", **agent_kwargs: Any) -> Agent:
    """Build the ADK agent for a model-backed role from its role spec."""
    spec = get_role_spec(role)
    if not spec.uses_model:
        raise ValueError(f"'{role}' is a code node: call its tool, it has no model agent")
    tools: List[Any] = role_tools(role)
    tools += [AgentTool(build_role_agent(target, model=model)) for target in spec.delegates]
    tools += skill_tools_for(role)
    return Agent(
        name=role,
        model=model or model_for("gcp", role)["id"],
        description=spec.description,
        instruction=instruction_for(spec, context),
        tools=tools,
        **agent_kwargs,
    )
