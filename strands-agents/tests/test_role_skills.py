"""
Runtime skills on Strands: each role agent carries exactly its role's skills
as an AgentSkills plugin built from local, hash-verified Skill instances.
"""
import pytest
from strands.vended_plugins.skills import AgentSkills

from ontogate.skills import skills_for_role
from src.agents.clarification_agent import create_clarification_agent
from src.agents.ontology_agent import create_ontology_agent
from src.agents.protocol_agent import create_protocol_agent
from src.agents.synthesis_agent import create_synthesis_agent
from src.agents.triage_agent import create_triage_orchestrator
from src.models.provider import MockBedrockModel
from src.skills_loader import agent_skills_for

FACTORIES = {
    "ontology_resolver": create_ontology_agent,
    "protocol_retriever": create_protocol_agent,
    "clinical_synthesizer": create_synthesis_agent,
    "clarification_coordinator": create_clarification_agent,
    "triage_orchestrator": create_triage_orchestrator,
}


def test_code_node_has_no_skills_plugin():
    assert agent_skills_for("safety_guard") is None


@pytest.mark.parametrize("role", sorted(FACTORIES))
def test_plugin_holds_exactly_the_role_skills(role):
    plugin = agent_skills_for(role)
    assert isinstance(plugin, AgentSkills)
    assert [s.name for s in plugin.get_available_skills()] == [p.name for p in skills_for_role(role)]
    assert all(str(s.path).startswith(str(p)) for s, p in zip(plugin.get_available_skills(), skills_for_role(role)))


@pytest.mark.parametrize("role", sorted(FACTORIES))
def test_agent_is_built_with_its_skills(role):
    agent = FACTORIES[role](model=MockBedrockModel())
    names = set(agent.tool_names)
    assert "skills" in names, f"{role}: AgentSkills tool not registered ({sorted(names)})"
