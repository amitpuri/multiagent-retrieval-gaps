"""
Strands Agents adapter for runtime Agent Skills.

Builds a role-scoped ``AgentSkills`` plugin from the hash-verified skill
directories ``ontogate.skills.skills_for_role`` resolves. Skills are parsed
eagerly (``strict=True``) so a malformed skill fails at startup, and only
local ``Skill`` instances are passed — never an ``https://`` source.
"""
from __future__ import annotations

from typing import List, Optional

from strands.vended_plugins.skills import AgentSkills, Skill

from ontogate.skills import skills_for_role


def agent_skills_for(role: str) -> Optional[AgentSkills]:
    """The role's skills as a native AgentSkills plugin, or None for a role without skills."""
    paths = skills_for_role(role)
    if not paths:
        return None
    return AgentSkills(skills=[Skill.from_file(p, strict=True) for p in paths], strict=True)


def skill_plugins_for(role: str) -> List[AgentSkills]:
    """``Agent(plugins=[...])`` entries for a role (empty when it loads no skills)."""
    plugin = agent_skills_for(role)
    return [plugin] if plugin else []
