"""
P8.4 on ADK: every model-backed agent is built from its role spec. The
instruction is the shared ``instruction_for`` text, the tools are exactly the
granted canonical tools plus one AgentTool per delegate, and every tool
declaration builds (model-facing signatures only).
"""
import pytest
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool

from ontogate.roles import load_all_role_specs, instruction_for
from src.agents.roles import build_role_agent

MODEL_ROLES = sorted(r for r, s in load_all_role_specs().items() if s.uses_model)


@pytest.mark.parametrize("role", MODEL_ROLES)
def test_agent_matches_its_role_spec(role):
    spec = load_all_role_specs()[role]
    agent = build_role_agent(role)
    assert agent.name == role
    assert agent.instruction == instruction_for(spec)
    functions = [t for t in agent.tools if callable(t) and not isinstance(t, AgentTool)]
    assert [f.__name__ for f in functions] == spec.tools
    assert [t.agent.name for t in agent.tools if isinstance(t, AgentTool)] == spec.delegates
    for fn in functions:
        assert FunctionTool(fn)._get_declaration() is not None


def test_code_node_has_no_agent():
    with pytest.raises(ValueError, match="code node"):
        build_role_agent("safety_guard")


def test_runtime_context_is_appended_not_substituted():
    from src.agents.synthesis_agent import create_synthesize_agent
    agent = create_synthesize_agent(trust_tier="human-reviewed")
    assert agent.instruction.startswith(instruction_for("clinical_synthesizer"))
    assert "human-reviewed" in agent.instruction
