"""
A2A AgentCards are generated from role specs (P8.6): one capability per role
reachable from the entrypoint, the served knowledge release as an extension,
and a ``url`` that speaks the A2A JSON-RPC binding (``/a2a``).
"""
import pytest

from ontogate.agent_cards import A2A_PROTOCOL_VERSION, RELEASE_EXTENSION, agent_card, capability, entrypoint_role
from ontogate.release import current_release
from ontogate.roles import load_all_role_specs


@pytest.fixture(scope="module")
def card():
    return agent_card(entrypoint_role(), "https://agents.example.test/", framework="test")


def test_entrypoint_is_the_triage_orchestrator():
    assert entrypoint_role() == "triage_orchestrator"


def test_card_points_at_the_a2a_jsonrpc_binding(card):
    assert card["protocolVersion"] == A2A_PROTOCOL_VERSION
    assert card["url"] == "https://agents.example.test/a2a"
    assert card["preferredTransport"] == "JSONRPC"
    assert card["additionalInterfaces"] == [{"url": card["url"], "transport": "JSONRPC"}]
    assert card["capabilities"]["streaming"] is False
    assert card["capabilities"]["pushNotifications"] is False


def test_bearer_auth_is_declared_only_when_the_server_requires_it(card):
    assert "securitySchemes" not in card and "security" not in card
    secured = agent_card(entrypoint_role(), "https://agents.example.test/", bearer_auth=True)
    assert secured["securitySchemes"] == {"bearer": {"type": "http", "scheme": "bearer"}}
    assert secured["security"] == [{"bearer": []}]


def test_capabilities_cover_the_entrypoint_and_its_hand_offs(card):
    specs = load_all_role_specs()
    assert [s["id"] for s in card["skills"]] == ["triage_orchestrator", *specs["triage_orchestrator"].delegates]
    for entry in card["skills"]:
        spec = specs[entry["id"]]
        assert entry["description"] == spec.description
        assert set(spec.tools) <= set(entry["tags"])
    assert "safety_guard" not in {s["id"] for s in card["skills"]}


def test_examples_are_competency_question_inputs(card):
    assert card["skills"][0]["examples"] and all(isinstance(e, str) for e in card["skills"][0]["examples"])


def test_release_extension_names_the_served_knowledge(card):
    ext = card["capabilities"]["extensions"][0]
    assert ext["uri"] == RELEASE_EXTENSION
    assert ext["params"]["bundle_sha256"] == current_release()["bundle_sha256"]
    assert ext["params"]["domains"] == ["laboratory_medicine"]


def test_code_node_is_not_served_as_an_agent():
    with pytest.raises(ValueError, match="code node"):
        agent_card("safety_guard", "https://x")


def test_capability_is_derived_from_the_spec():
    spec = load_all_role_specs()["panel_coordinator"]
    entry = capability(spec)
    assert entry["id"] == "panel_coordinator" and "panel_workup" in entry["tags"]
