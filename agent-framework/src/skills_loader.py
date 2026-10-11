"""
Microsoft Agent Framework adapter for runtime Agent Skills.

Builds a role-scoped ``SkillsProvider`` (a context provider) from the
hash-verified skill directories ``ontogate.skills.skills_for_role`` resolves.
Script discovery is disabled (no script extensions, no runner) and only
Markdown resources are exposed.
"""
from __future__ import annotations

from typing import Any, List, Optional

from agent_framework import SkillsProvider

from ontogate.skills import skills_for_role


def skills_provider_for(role: str) -> Optional[SkillsProvider]:
    """The role's skills as a native SkillsProvider, or None for a role without skills."""
    paths = skills_for_role(role)
    if not paths:
        return None
    return SkillsProvider.from_paths(
        skill_paths=[str(p) for p in paths],
        script_extensions=(),
        resource_extensions=(".md",),
        source_id=f"ontogate:{role}",
    )


def attach_skills(agent: Any, role: str) -> Any:
    """Append the role's SkillsProvider to an agent built from declarative YAML."""
    provider = skills_provider_for(role)
    if provider is not None:
        providers: List[Any] = getattr(agent, "context_providers", None)
        if providers is None:
            raise TypeError(f"{type(agent).__name__} has no context_providers to attach skills to")
        providers.append(provider)
    return agent
