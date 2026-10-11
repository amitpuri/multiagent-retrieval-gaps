"""
Skill loader for Google ADK agents.

Resolves role-scoped skills from agents/<role>.yaml, verifies integrity
against skills.lock.json, and initializes the ADK SkillToolset.
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


def load_adk_skill_toolset(role_name: str) -> Optional[Any]:
    """Load native ADK SkillToolset for a role, asserting no script execution tools."""
    skill_paths = get_skills_for_role(role_name)
    if not skill_paths:
        return None

    # Verify lock before loading
    verify_skills_lock()

    try:
        from google.adk.skills import load_skill_from_dir  # type: ignore
        from google.adk.tools import skill_toolset  # type: ignore

        loaded_skills = [load_skill_from_dir(p) for p in skill_paths]
        toolset = skill_toolset.SkillToolset(skills=loaded_skills)

        # Invariant: clinical skills ship no scripts, ensure run_skill_script is not exposed
        for tool in getattr(toolset, "tools", []):
            tool_name = getattr(tool, "name", str(tool))
            if "script" in tool_name.lower():
                raise PermissionError(f"Script tool '{tool_name}' prohibited for clinical role '{role_name}'")
        return toolset
    except ImportError:
        # Fallback dictionary for environments without google-adk installed
        return {
            "role": role_name,
            "skills": [p.name for p in skill_paths],
            "paths": [str(p) for p in skill_paths],
        }
