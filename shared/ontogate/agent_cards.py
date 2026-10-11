"""
A2A AgentCards generated from role specs (plan P8.6).

An AgentCard ``skills[]`` entry is an *A2A capability* — what a deployed agent
can do — not a runtime skill package (glossary, plan §8.1). Each capability is
derived from a role spec: its description, its canonical tools and the roles it
hands off to. The card for an entrypoint role advertises its own capability and
those of every role reachable through its hand-offs, so a client sees the whole
fleet behind one URL. Every framework serves the same card at
``/.well-known/agent-card.json``; only ``url`` and the framework label differ.

``url`` is the A2A JSON-RPC binding every server mounts at ``/a2a``
(:mod:`ontogate.a2a`, ``message/send`` only, so ``streaming`` and
``pushNotifications`` are false). The repository's REST API
(``POST /api/v1/query``) answers the same questions and is documented at
``documentationUrl``; it is not an A2A transport, so the card does not list it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import yaml

from ontogate.a2a import A2A_PATH
from ontogate.config import get_default_registry
from ontogate.paths import scenarios_dir
from ontogate.roles import RoleSpec, get_role_spec, load_all_role_specs

A2A_PROTOCOL_VERSION = "0.3.0"
RELEASE_EXTENSION = "https://ontogate.ai/ext/knowledge-release"


def _reachable(role: str, specs: Dict[str, RoleSpec]) -> List[str]:
    """``role`` and every role reachable through hand-offs, in declaration order."""
    order: List[str] = []

    def visit(name: str) -> None:
        if name in order or name not in specs:
            return
        order.append(name)
        for target in specs[name].delegates:
            visit(target)

    visit(role)
    return order


def _examples(limit: int = 3) -> List[str]:
    out: List[str] = []
    for path in sorted(scenarios_dir().glob("*.yaml")):
        for tc in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("test_cases", []):
            if tc.get("input_text") and tc["input_text"] not in out:
                out.append(tc["input_text"])
                break
        if len(out) >= limit:
            break
    return out


def capability(spec: RoleSpec, examples: Optional[List[str]] = None) -> Dict[str, Any]:
    """The A2A capability (AgentCard skill entry) a role contributes."""
    entry: Dict[str, Any] = {
        "id": spec.role,
        "name": spec.role.replace("_", " ").title(),
        "description": spec.description,
        "tags": ["clinical-decision-support", "laboratory-medicine", *spec.tools],
        "inputModes": ["text/plain"],
        "outputModes": ["application/json"],
    }
    if examples:
        entry["examples"] = examples
    return entry


def agent_card(role: str, url: str, *, framework: str = "", release: Optional[Dict[str, Any]] = None,
               bearer_auth: bool = False) -> Dict[str, Any]:
    """The AgentCard for a model-backed role served at ``url`` (the service base URL).

    ``bearer_auth`` declares that the server itself requires a Bearer token
    (ADK with ``HARNESS_API_TOKENS``); platform-level auth (AgentCore, Container
    Apps, Cloud Run IAM) is not the agent's to declare.
    """
    from ontogate import __version__
    from ontogate.release import current_release

    specs = load_all_role_specs()
    spec = get_role_spec(role)
    if not spec.uses_model:
        raise ValueError(f"'{role}' is a code node and is not served as an agent")
    release = release or current_release()
    base = url.rstrip("/")
    card: Dict[str, Any] = {
        "protocolVersion": A2A_PROTOCOL_VERSION,
        "name": role,
        "description": spec.description,
        "url": base + A2A_PATH,
        "preferredTransport": "JSONRPC",
        "additionalInterfaces": [{"url": base + A2A_PATH, "transport": "JSONRPC"}],
        "version": __version__,
        "documentationUrl": base + "/docs",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extensions": [{
                "uri": RELEASE_EXTENSION,
                "description": "The knowledge release this agent serves (ontology bundle and skills lock).",
                "required": False,
                "params": {
                    "bundle_sha256": release.get("bundle_sha256"),
                    "skills_lock_sha256": release.get("skills_lock_sha256"),
                    "domains": sorted(get_default_registry().domains),
                    "framework": framework,
                },
            }],
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["application/json"],
        "skills": [capability(specs[name], _examples() if name == role else None)
                   for name in _reachable(role, specs)],
    }
    if bearer_auth:
        card["securitySchemes"] = {"bearer": {"type": "http", "scheme": "bearer"}}
        card["security"] = [{"bearer": []}]
    return card


def entrypoint_role() -> str:
    """The role a deployment exposes (the one no other role hands off to)."""
    specs = load_all_role_specs()
    targets = {t for s in specs.values() for t in s.delegates}
    roots = [r for r, s in sorted(specs.items()) if s.uses_model and s.delegates and r not in targets]
    if len(roots) != 1:
        raise ValueError(f"expected exactly one entrypoint role, found {roots}")
    return roots[0]
