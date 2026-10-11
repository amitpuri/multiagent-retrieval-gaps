"""
MAF declarative agents generated from the framework-neutral role specs.

``agents/<role>.yaml`` is the single declaration of a role (instruction, tool
grants, skills). This module renders the Microsoft Agent Framework
``kind: Prompt`` YAML for every role that calls a model; the safety guard is a
code node and gets no prompt agent. Tool descriptions come from the canonical
tool contract (``ontogate.tools``).

    python -m src.declarative          # rewrite declarative-agents/*.yaml
    python -m src.declarative --check  # fail if any file drifted from its role spec
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Dict

import yaml

from ontogate import tools as canonical_tools
from ontogate.roles import RoleSpec, load_all_role_specs

AGENT_DIR = Path(__file__).resolve().parent.parent / "declarative-agents"
HEADER = "# Generated from agents/{role}.yaml by `python -m src.declarative`. Do not edit.\n"


class _Literal(str):
    """Render multi-line strings as YAML block literals."""


yaml.SafeDumper.add_representer(
    _Literal, lambda dumper, data: dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|"))


def _tool_description(name: str) -> str:
    doc = inspect.getdoc(getattr(canonical_tools, name)) or name
    return doc.splitlines()[0]


def render_agent(spec: RoleSpec) -> str:
    """The MAF declarative YAML for one model-backed role."""
    doc = {
        "kind": "Prompt",
        "name": spec.role,
        "description": spec.description,
        "model": {"options": {"allowMultipleToolCalls": False, "chatToolMode": "auto"}},
        "instructions": _Literal(spec.base_instruction.rstrip() + "\n"),
        "tools": [{
            "kind": "function",
            "name": tool,
            "description": _tool_description(tool),
            "bindings": {"function": tool},
        } for tool in spec.tools],
    }
    return HEADER.format(role=spec.role) + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)


def render_all() -> Dict[Path, str]:
    return {AGENT_DIR / f"{role}.yaml": render_agent(spec)
            for role, spec in sorted(load_all_role_specs().items()) if spec.uses_model}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    rendered = render_all()
    stale = sorted(set(AGENT_DIR.glob("*.yaml")) - set(rendered))
    drift = [p for p, text in rendered.items()
             if not p.is_file() or p.read_text(encoding="utf-8").replace("\r\n", "\n") != text]
    if "--check" in argv:
        for p in drift + stale:
            print(f"drift: {p.name}")
        return 1 if drift or stale else 0
    for p in stale:
        p.unlink()
    for p, text in rendered.items():
        p.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {len(rendered)} declarative agent(s); removed {len(stale)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
