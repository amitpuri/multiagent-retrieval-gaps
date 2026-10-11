"""
Agent role specifications (``agents/<role>.yaml``).

A role spec is the single, framework-neutral declaration of an agent: whether
it calls a model, which canonical tools it is granted, which runtime skills it
loads and its base instruction. ADK, Strands and MAF adapters build their
agents from it; the skills build checks it against every skill's declared roles
and tools (RoleSkillShape).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from ontogate.paths import repo_root

ROLE_KEYS = {"role", "description", "uses_model", "model_tier", "tools", "skills",
             "domain_skills", "delegates", "output_schema", "base_instruction"}
MODEL_TIERS = {"reasoning", "flash", "none"}


@dataclass(frozen=True)
class RoleSpec:
    """One declared agent role."""
    role: str
    description: str
    uses_model: bool
    model_tier: str
    tools: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    # Load the domain skill of every loaded domain pack (domain-<pack id>), so a
    # new pack adds its guidance without editing any role spec.
    domain_skills: bool = False
    # Roles this role may hand off to (agents-as-tools on Strands and ADK, workflow
    # edges on MAF). The gate decides *whether* to hand off; this only grants *to whom*.
    delegates: List[str] = field(default_factory=list)
    output_schema: str = "A2AMessage"
    base_instruction: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def agents_dir() -> Path:
    return repo_root() / "agents"


def load_role_spec(file_path: Path) -> RoleSpec:
    """Load and check one role spec (unknown keys and tiers are errors)."""
    file_path = Path(file_path)
    data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    unknown = set(data) - ROLE_KEYS
    if unknown:
        raise ValueError(f"{file_path.name}: unknown role spec key(s): {', '.join(sorted(unknown))}")
    if data.get("role") != file_path.stem:
        raise ValueError(f"{file_path.name}: role '{data.get('role')}' must match the file name")
    tier = data.get("model_tier", "flash")
    if tier not in MODEL_TIERS:
        raise ValueError(f"{file_path.name}: model_tier must be one of {sorted(MODEL_TIERS)}")
    uses_model = bool(data.get("uses_model", True))
    if not uses_model and tier != "none":
        raise ValueError(f"{file_path.name}: a code node (uses_model: false) must have model_tier: none")
    return RoleSpec(
        role=data["role"],
        description=" ".join(str(data.get("description", "")).split()),
        uses_model=uses_model,
        model_tier=tier,
        tools=list(data.get("tools") or []),
        skills=list(data.get("skills") or []),
        domain_skills=bool(data.get("domain_skills", False)),
        delegates=list(data.get("delegates") or []),
        output_schema=data.get("output_schema", "A2AMessage"),
        base_instruction=str(data.get("base_instruction", "")).strip(),
    )


def load_all_role_specs(root: Optional[Path] = None) -> Dict[str, RoleSpec]:
    """Load every ``agents/*.yaml`` role spec, keyed by role name."""
    root = Path(root) if root else agents_dir()
    if not root.is_dir():
        return {}
    return {spec.role: spec for spec in (load_role_spec(p) for p in sorted(root.glob("*.yaml")))}


def get_role_spec(role: str) -> RoleSpec:
    path = agents_dir() / f"{role}.yaml"
    if not path.is_file():
        raise KeyError(f"No role spec for '{role}' at {path}")
    return load_role_spec(path)


def check_role_specs(specs: Dict[str, RoleSpec]) -> List[Tuple[str, str, str]]:
    """Delegation rules: (role, rule, message) for each violation."""
    errors: List[Tuple[str, str, str]] = []
    for role, spec in sorted(specs.items()):
        if spec.delegates and not spec.uses_model:
            errors.append((role, "CODE_NODE_DELEGATES", "a code node does not hand off to agents"))
        for target in spec.delegates:
            if target == role:
                errors.append((role, "SELF_DELEGATION", "a role cannot delegate to itself"))
            elif target not in specs:
                errors.append((role, "UNKNOWN_DELEGATE", f"delegates to unknown role '{target}'"))
            elif not specs[target].uses_model:
                errors.append((role, "DELEGATE_TO_CODE_NODE",
                               f"'{target}' is a code node; call its tool instead of delegating"))
    # Hand-offs must not loop back (a delegate chain is a tree, not a cycle).
    def reaches(start: str, goal: str, seen: frozenset = frozenset()) -> bool:
        for nxt in specs.get(start, RoleSpec(start, "", True, "flash")).delegates:
            if nxt == goal or (nxt not in seen and reaches(nxt, goal, seen | {nxt})):
                return True
        return False
    for role in sorted(specs):
        if any(reaches(d, role) for d in specs[role].delegates if d != role and d in specs):
            errors.append((role, "DELEGATION_CYCLE", "hand-offs lead back to this role"))
    return errors


def instruction_for(role: "RoleSpec | str", context: str = "",
                    specs: Optional[Dict[str, RoleSpec]] = None) -> str:
    """The one instruction text for a role, identical on every framework.

    Base instruction from the role spec, the tools it is granted, the roles it
    may hand off to, then any runtime ``context`` (e.g. the trust posture of the
    concept being interpreted).
    """
    spec = role if isinstance(role, RoleSpec) else get_role_spec(role)
    parts = [spec.base_instruction]
    if spec.tools:
        parts.append("Tools you may call: " + ", ".join(spec.tools) + ".")
    if spec.delegates:
        specs = specs or load_all_role_specs()
        parts.append("Roles you may hand off to:\n" + "\n".join(
            f"- {d}: {specs[d].description}" for d in spec.delegates))
    if context.strip():
        parts.append(context.strip())
    return "\n\n".join(parts)
