"""
Google ADK adapter for runtime Agent Skills.

Builds a role-scoped native ``SkillToolset`` from the hash-verified skill
directories ``ontogate.skills.skills_for_role`` resolves (from the image tree,
or from the cloud skill store when ``ONTOGATE_SKILL_STORE`` is set).
Script execution is not exposed: no code executor, and ``run_skill_script`` is
filtered out of the toolset.
"""
from __future__ import annotations

from typing import List, Optional

from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset

from ontogate.skills import skills_for_role

# Progressive-disclosure tools only (L1 list, L2 load, L3 resource).
SKILL_TOOLS = ["list_skills", "load_skill", "load_skill_resource"]


def skill_toolset_for(role: str) -> Optional[SkillToolset]:
    """The role's skills as a native SkillToolset, or None for a role without skills."""
    paths = skills_for_role(role)
    if not paths:
        return None
    return SkillToolset(
        skills=[load_skill_from_dir(p) for p in paths],
        code_executor=None,
        tool_filter=list(SKILL_TOOLS),
    )


def skill_tools_for(role: str) -> List[SkillToolset]:
    """``Agent(tools=[...])`` entries for a role (empty when it loads no skills)."""
    toolset = skill_toolset_for(role)
    return [toolset] if toolset else []
