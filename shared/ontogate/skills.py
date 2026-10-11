"""
Agent Skills management, validation, clinical linting, and locking.

Implements build, lint, and lock per Open Knowledge & Agent Skills specifications.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from ontogate.paths import repo_root

CANONICAL_MCP_TOOLS = {
    "parse_clinician_input",
    "resolve_lab_term",
    "evaluate_safety_gate",
    "fetch_grounded_protocol",
    "attest_computation",
    "build_clarification_prompt",
    "panel_workup",
    "classify_lookalikes",
}

# Regex to detect clinical number + unit in procedural skill text (prohibited for risk_class: clinical)
CLINICAL_VALUE_PATTERN = re.compile(
    r"\b\d+(\.\d+)?\s*(mg/dL|mmol/L|g/dL|ng/L|ng/mL|%)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SkillLintError:
    skill_name: str
    rule: str
    message: str


@dataclass(frozen=True)
class SkillPackage:
    name: str
    description: str
    path: Path
    risk_class: str = "general"
    roles: List[str] = field(default_factory=list)
    version: str = "1.0.0"
    bundle_sha256: Optional[str] = None


def parse_skill_md(skill_file: Path) -> Tuple[Dict[str, Any], str]:
    """Parse frontmatter and markdown body from SKILL.md."""
    content = skill_file.read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise ValueError(f"{skill_file}: Missing YAML frontmatter marker '---'")

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{skill_file}: Malformed YAML frontmatter")

    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()
    return frontmatter, body


def lint_skill_package(skill_dir: Path) -> List[SkillLintError]:
    """Validate a skill directory against agentskills.io and clinical lint rules."""
    errors: List[SkillLintError] = []
    skill_file = skill_dir / "SKILL.md"
    name = skill_dir.name

    if not skill_file.is_file():
        return [SkillLintError(name, "MISSING_SKILL_MD", "SKILL.md not found at root of skill directory")]

    try:
        fm, body = parse_skill_md(skill_file)
    except Exception as e:
        return [SkillLintError(name, "MALFORMED_FRONTMATTER", str(e))]

    skill_name = fm.get("name", "")
    if not skill_name:
        errors.append(SkillLintError(name, "EMPTY_NAME", "Frontmatter 'name' is required"))
    elif len(skill_name) > 64:
        errors.append(SkillLintError(name, "NAME_TOO_LONG", "Name exceeds 64 characters"))
    elif not re.match(r"^[a-z0-9_-]+$", skill_name):
        errors.append(SkillLintError(name, "INVALID_NAME_CHARS", "Name must be lowercase alphanumeric with hyphens/underscores"))

    desc = fm.get("description", "")
    if not desc:
        errors.append(SkillLintError(name, "EMPTY_DESCRIPTION", "Frontmatter 'description' is required"))
    elif len(desc) > 1024:
        errors.append(SkillLintError(name, "DESC_TOO_LONG", "Description exceeds 1024 characters"))

    metadata = fm.get("metadata", {})
    risk_class = metadata.get("risk_class", "general")

    # Clinical lint rules
    if risk_class == "clinical":
        # 1. No scripts directory
        if (skill_dir / "scripts").is_dir():
            errors.append(SkillLintError(name, "NO_SCRIPTS_ALLOWED", "Clinical skills must not contain a scripts/ directory"))

        # 2. No clinical numbers + unit patterns in procedural instructions
        match = CLINICAL_VALUE_PATTERN.search(body)
        if match:
            errors.append(SkillLintError(
                name,
                "NO_CLINICAL_NUMBERS",
                f"Clinical skill body contains hardcoded clinical value '{match.group(0)}'. Procedural skills must be value-free.",
            ))

    return errors


def compute_directory_sha256(dir_path: Path) -> str:
    """Compute deterministic SHA-256 over all files in a directory."""
    hasher = hashlib.sha256()
    for p in sorted(dir_path.rglob("*")):
        if p.is_file() and not p.name.endswith(".pyc") and "__pycache__" not in p.parts:
            rel = p.relative_to(dir_path).as_posix()
            hasher.update(rel.encode("utf-8"))
            hasher.update(p.read_bytes())
    return hasher.hexdigest()


def discover_skills(skills_root: Optional[Path] = None) -> List[Path]:
    """Find all skill directories containing SKILL.md under skills/."""
    root = skills_root or (repo_root() / "skills")
    if not root.is_dir():
        return []

    found: List[Path] = []
    for skill_file in sorted(root.rglob("SKILL.md")):
        # Skip templates or documentation files
        if "references" not in skill_file.parts:
            found.append(skill_file.parent)
    return found


def build_and_lock_skills(
    skills_root: Optional[Path] = None,
    dist_dir: Optional[Path] = None,
    bundle_sha256: str = "core-bundle-v1",
) -> Dict[str, Any]:
    """Lint all skills, package into dist/skills/*.zip, and write skills/skills.lock.json."""
    root = skills_root or (repo_root() / "skills")
    dist = dist_dir or (repo_root() / "dist" / "skills")
    dist.mkdir(parents=True, exist_ok=True)

    skill_dirs = discover_skills(root)
    lock_entries: Dict[str, Any] = {}
    all_errors: List[SkillLintError] = []

    for s_dir in skill_dirs:
        errors = lint_skill_package(s_dir)
        if errors:
            all_errors.extend(errors)
            continue

        fm, _ = parse_skill_md(s_dir / "SKILL.md")
        skill_name = fm["name"]
        sha256 = compute_directory_sha256(s_dir)

        # Create zip package for cloud store upload (GCP Skill Registry, Foundry, S3)
        zip_path = dist / f"{skill_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(s_dir.rglob("*")):
                if p.is_file() and not p.name.endswith(".pyc"):
                    zf.write(p, p.relative_to(s_dir).as_posix())

        lock_entries[skill_name] = {
            "name": skill_name,
            "version": fm.get("metadata", {}).get("version", "1.0.0"),
            "risk_class": fm.get("metadata", {}).get("risk_class", "general"),
            "path": s_dir.relative_to(repo_root()).as_posix(),
            "sha256": sha256,
            "bundle_sha256": bundle_sha256,
        }

    if all_errors:
        err_msg = "\n".join(f"[{e.rule}] {e.skill_name}: {e.message}" for e in all_errors)
        raise ValueError(f"Skill lint failed with {len(all_errors)} errors:\n{err_msg}")

    lock_data = {
        "version": "1.0.0",
        "bundle_sha256": bundle_sha256,
        "skills": lock_entries,
    }

    lock_file = root / "skills.lock.json"
    lock_file.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")
    return lock_data


def verify_skills_lock(skills_root: Optional[Path] = None) -> bool:
    """Verify that on-disk skill directories match the hashes recorded in skills.lock.json."""
    root = skills_root or (repo_root() / "skills")
    lock_file = root / "skills.lock.json"
    if not lock_file.is_file():
        raise FileNotFoundError(f"Missing {lock_file}")

    lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
    for skill_name, meta in lock_data.get("skills", {}).items():
        s_dir = repo_root() / meta["path"]
        if not s_dir.is_dir():
            raise FileNotFoundError(f"Skill directory not found for {skill_name}: {s_dir}")
        curr_hash = compute_directory_sha256(s_dir)
        if curr_hash != meta["sha256"]:
            raise ValueError(f"Skill '{skill_name}' hash mismatch: expected {meta['sha256']}, got {curr_hash}")

    return True
