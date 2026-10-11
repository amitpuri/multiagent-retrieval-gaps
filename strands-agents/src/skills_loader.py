"""
Skill loader for AWS Strands Agents SDK.

Loads role-scoped AgentSkills plugin with local directory paths only (no https/remote).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ontogate.paths import repo_root
from ontogate.roles import load_role_spec
from ontogate.skills import verify_skills_lock


def get_skills_for_role(role_name: str) -> List[Path]:
    """Resolve local directory paths for skills granted to a given role."""
    spec_path = repo_root() / "agents" / f"{role_name}.yaml"
    if not spec_path.is_file():
        return []

    spec = load_role_spec(spec_path)
    if not spec.skills:
        return []

    lock_file = repo_root() / "skills" / "skills.lock.json"
    if not lock_file.is_file():
        raise FileNotFoundError(f"Missing {lock_file}. Run build_and_lock_skills() first.")

    lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
    skills_map = lock_data.get("skills", {})

    paths: List[Path] = []
    for s_name in spec.skills:
        if s_name in skills_map:
            paths.append(repo_root() / skills_map[s_name]["path"])
        else:
            raise KeyError(f"Role '{role_name}' requests skill '{s_name}' which is not in skills.lock.json")
    return paths


def load_strands_agent_skills(role_name: str) -> Optional[Any]:
    """Load native Strands AgentSkills plugin with strictly local paths."""
    skill_paths = get_skills_for_role(role_name)
    if not skill_paths:
        return None

    # Verify lock before loading
    verify_skills_lock()

    try:
        from strands.vended_plugins.skills import AgentSkills  # type: ignore
        return AgentSkills(skills=[str(p) for p in skill_paths])
    except ImportError:
        return {
            "role": role_name,
            "skills": [p.name for p in skill_paths],
            "paths": [str(p) for p in skill_paths],
        }
