"""
Role specifications and loading from agents/<role>.yaml.

Defines role metadata, tool grants, model tiers, and loaded Agent Skills.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ontogate.paths import repo_root


@dataclass(frozen=True)
class RoleSpec:
    """One declared agent role specification."""
    role: str
    description: str
    uses_model: bool
    model_tier: str
    tools: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    output_schema: str = "A2AMessage"
    base_instruction: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "description": self.description,
            "uses_model": self.uses_model,
            "model_tier": self.model_tier,
            "tools": list(self.tools),
            "skills": list(self.skills),
            "output_schema": self.output_schema,
            "base_instruction": self.base_instruction,
        }


def load_role_spec(file_path: Path) -> RoleSpec:
    """Load a single role specification YAML file."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return RoleSpec(
        role=data["role"],
        description=data.get("description", ""),
        uses_model=bool(data.get("uses_model", True)),
        model_tier=data.get("model_tier", "flash"),
        tools=list(data.get("tools", [])),
        skills=list(data.get("skills", [])),
        output_schema=data.get("output_schema", "A2AMessage"),
        base_instruction=data.get("base_instruction", "").strip(),
    )


def load_all_role_specs(agents_dir: Optional[Path] = None) -> Dict[str, RoleSpec]:
    """Load all role specifications from agents/*.yaml."""
    root = agents_dir or (repo_root() / "agents")
    if not root.is_dir():
        return {}

    specs: Dict[str, RoleSpec] = {}
    for p in sorted(root.glob("*.yaml")):
        spec = load_role_spec(p)
        specs[spec.role] = spec
    return specs
