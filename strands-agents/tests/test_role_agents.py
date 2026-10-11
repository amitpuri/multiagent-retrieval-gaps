"""
P8.4 on Strands: every model-backed agent is built from its role spec. The
system prompt is the shared ``instruction_for`` text and the tools are exactly
the granted canonical tools, one hand-off tool per delegate, and the skills tool.
"""
import pytest

from ontogate.roles import instruction_for, load_all_role_specs
from src.agents.roles import build_role_agent
from src.models.provider import MockBedrockModel

SPECS = load_all_role_specs()
MODEL_ROLES = sorted(r for r, s in SPECS.items() if s.uses_model)


@pytest.mark.parametrize("role", MODEL_ROLES)
def test_agent_matches_its_role_spec(role):
    spec = SPECS[role]
    agent = build_role_agent(role, model=MockBedrockModel())
    assert agent.system_prompt == instruction_for(spec)
    expected = set(spec.tools) | set(spec.delegates) | ({"skills"} if spec.skills or spec.domain_skills else set())
    assert set(agent.tool_names) == expected


def test_code_node_has_no_agent():
    with pytest.raises(ValueError, match="code node"):
        build_role_agent("safety_guard", model=MockBedrockModel())
