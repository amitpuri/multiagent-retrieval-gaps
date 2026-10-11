"""
Runtime skills on ADK: every model-backed agent carries exactly its role's
skills as a native SkillToolset, and script execution is never exposed.
"""
import asyncio

import pytest
from google.adk.tools.skill_toolset import SkillToolset

from ontogate.skills import skills_for_role
from src.agents.ontology_agent import create_ontology_agent
from src.agents.synthesis_agent import create_synthesize_agent
from src.agents.triage_agent import create_triage_agent
from src.skills_loader import SKILL_TOOLS, skill_toolset_for

FACTORIES = {
    "ontology_resolver": create_ontology_agent,
    "clinical_synthesizer": create_synthesize_agent,
    "triage_orchestrator": create_triage_agent,
}


def _toolsets(agent):
    return [t for t in agent.tools if isinstance(t, SkillToolset)]


def test_code_node_has_no_skill_toolset():
    assert skill_toolset_for("safety_guard") is None


@pytest.mark.parametrize("role", sorted(FACTORIES))
def test_agent_carries_its_role_skills(role):
    toolsets = _toolsets(FACTORIES[role]())
    assert len(toolsets) == 1
    assert [s.name for s in toolsets[0].skills] == [p.name for p in skills_for_role(role)]
    tools = asyncio.run(toolsets[0].get_tools())
    assert sorted(t.name for t in tools) == sorted(SKILL_TOOLS)
    assert "run_skill_script" not in {t.name for t in tools}
