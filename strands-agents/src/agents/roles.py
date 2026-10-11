"""
Role spec → Strands ``Agent`` (plan P8.4: one instruction source and one tool grant per role).

Every model-backed Strands agent is built from ``agents/<role>.yaml``: the shared
instruction text (``ontogate.roles.instruction_for``), exactly the granted
canonical ``@tool`` wrappers, one hand-off tool per role it may delegate to
(the delegate agent built from its own spec — agents-as-tools), and its
runtime skills as an ``AgentSkills`` plugin.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, List, Optional

from strands import Agent, tool
from strands.models.model import Model

from ontogate.roles import get_role_spec, instruction_for
from src.skills_loader import skill_plugins_for


def run_in_clean_thread(func: Callable[[], Any]) -> Any:
    """Run a callable in an isolated OS thread (avoids ContextVar / OpenTelemetry token collisions)."""
    result: List[Any] = []
    error: List[BaseException] = []

    def target() -> None:
        try:
            result.append(func())
        except BaseException as exc:  # re-raised in the caller's thread
            error.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


def role_tools(role: str) -> List[Any]:
    """The canonical ``@tool`` wrappers a role is granted."""
    import src.tools as canonical
    return [getattr(canonical, name) for name in get_role_spec(role).tools]


def handoff_tool(target: str, model_factory: Callable[[], Optional[Model]]) -> Any:
    """A tool named after ``target`` that runs that role's agent on a request."""
    spec = get_role_spec(target)

    @tool(name=target, description=f"Hand off to {target}: {spec.description}")
    def handoff(request: str) -> str:
        """Send the request, with the facts it needs, to the delegate role and return its answer.

        Args:
            request: What the delegate must do, including the resolved URI, gate result or
                panel it applies to.
        """
        def _run() -> str:
            agent = build_role_agent(target, model=model_factory())
            agent.callback_handler = lambda **_: None
            return str(agent(request))

        return str(run_in_clean_thread(_run))

    return handoff


def build_role_agent(role: str, model: Optional[Model] = None, context: str = "", **agent_kwargs: Any) -> Agent:
    """Build the Strands agent for a model-backed role from its role spec."""
    spec = get_role_spec(role)
    if not spec.uses_model:
        raise ValueError(f"'{role}' is a code node: call its tool, it has no model agent")

    def model_factory() -> Optional[Model]:
        if model is not None:
            return model
        from src.models.provider import get_strands_model
        return get_strands_model()

    tools = role_tools(role) + [handoff_tool(target, model_factory) for target in spec.delegates]
    return Agent(
        model=model,
        name=role,
        description=spec.description,
        system_prompt=instruction_for(spec, context),
        tools=tools,
        plugins=skill_plugins_for(role),
        **agent_kwargs,
    )
