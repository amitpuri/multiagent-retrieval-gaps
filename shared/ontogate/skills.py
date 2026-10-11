"""
Runtime Agent Skills: render, lint, lock, package and resolve per role.

Skills are first-party, hash-locked procedural knowledge (agentskills.io format)
under ``skills/runtime/<name>/`` and ``skills/domains/<name>/``. They never
carry clinical numbers and never decide routing — the gate does.

``ontogate skills build``:

1. **Render** each skill's generated references from the ontology bundle
   (``metadata.references``; see :mod:`ontogate.skill_refs`).
2. **Lint** every skill against the agentskills.io format, the cloud-store
   constraints and the clinical rules (no ``scripts/``, no number+unit, no
   routing verbs, tool names within the canonical MCP contract).
3. **Check** roles against skills (RoleSkillShape): a role loads a skill only if
   the skill declares that role, and a skill names only tools its roles are granted.
4. **Lock** ``skills/skills.lock.json`` (content hash per skill, the bundle hash
   it was rendered from) and write deterministic archives to ``dist/skills/``.

``ontogate skills check`` runs 1–4 without writing and fails on any drift.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from ontogate.paths import domain_dir, ontology_dir, repo_root
from ontogate.ports import TEXT_SUFFIXES, sha256_tree
from ontogate.roles import RoleSpec, check_role_specs, load_all_role_specs

from ontogate.mcp_server import CLINICAL_MCP_TOOLS

# The model-facing tool contract: exactly the tools the ontogate MCP server serves.
CANONICAL_MCP_TOOLS = frozenset(CLINICAL_MCP_TOOLS)

LOCK_SCHEMA_VERSION = "1.0.0"
NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_BODY_CHARS = 20_000           # ~5k tokens (L2 budget)
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
RISK_CLASSES = {"clinical", "general"}

# A number followed by a clinical unit — reference values live in the ontology only.
CLINICAL_VALUE_PATTERN = re.compile(
    r"(?<![\w.])\d+(?:[.,]\d+)?\s*"
    r"(?:mg/dL|mg/L|g/dL|g/L|mmol/L|umol/L|µmol/L|nmol/L|ng/L|ng/mL|pg/mL|mEq/L|U/L|IU/L|%)"
    r"(?![\w/])",
    re.IGNORECASE,
)
# Routing / defaulting language — whether to proceed is the gate's decision.
ROUTING_PATTERN = re.compile(
    r"\b(proceed if|continue if|assume (?:the|a|an|that)\b|default to|most likely (?:means|is)|probably means)",
    re.IGNORECASE,
)
# A prohibition ("never assume the unit", "do not proceed if") names the forbidden act.
_NEGATION = re.compile(r"\b(?:never|not|don't|do not|must not)\s+(?:\w+\s+){0,2}$", re.IGNORECASE)
TOOL_MENTION = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`")
_QUOTED_FIELD = re.compile(r"^(name|description):\s*[\"']", re.MULTILINE)


class SkillBuildError(ValueError):
    """Raised when lint, role/skill consistency or drift checks fail."""

    def __init__(self, errors: Sequence["SkillLintError"]):
        self.errors = list(errors)
        super().__init__(f"{len(self.errors)} skill error(s):\n" + "\n".join(str(e) for e in self.errors))


@dataclass(frozen=True)
class SkillLintError:
    skill_name: str
    rule: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.skill_name}: {self.message}"


@dataclass(frozen=True)
class SkillPackage:
    """A parsed skill directory."""
    name: str
    description: str
    path: Path
    body: str
    risk_class: str = "general"
    version: str = "1.0.0"
    roles: Tuple[str, ...] = ()
    allowed_tools: Tuple[str, ...] = ()
    domain: Optional[str] = None
    references: Tuple[str, ...] = ()
    raw_frontmatter: str = field(default="", repr=False)

    @property
    def is_domain_skill(self) -> bool:
        return self.domain is not None


# --------------------------------------------------------------------------- paths
def skills_dir() -> Path:
    return repo_root() / "skills"


def dist_skills_dir() -> Path:
    return repo_root() / "dist" / "skills"


def lock_path(root: Optional[Path] = None) -> Path:
    return (Path(root) if root else skills_dir()) / "skills.lock.json"


def domain_skill_name(domain_id: str) -> str:
    """Name of the domain skill for a pack id (``laboratory_medicine`` → ``domain-laboratory-medicine``)."""
    return "domain-" + domain_id.replace("_", "-")


# --------------------------------------------------------------------------- parse
def _split_list(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = re.split(r"[,\s]+", str(value))
    return tuple(i.strip() for i in items if str(i).strip())


def parse_skill_md(skill_file: Path) -> Tuple[Dict[str, Any], str, str]:
    """Return (frontmatter, body, raw frontmatter text) of a SKILL.md."""
    content = Path(skill_file).read_text(encoding="utf-8").replace("\r\n", "\n")
    if not content.startswith("---\n"):
        raise ValueError("missing YAML frontmatter ('---' on the first line)")
    end = content.find("\n---", 4)
    if end < 0:
        raise ValueError("unterminated YAML frontmatter")
    raw = content[4:end]
    frontmatter = yaml.safe_load(raw) or {}
    if not isinstance(frontmatter, dict):
        raise ValueError("frontmatter must be a mapping")
    body = content[end + 4:].lstrip("\n")
    return frontmatter, body, raw


def load_skill(skill_dir: Path) -> SkillPackage:
    skill_dir = Path(skill_dir)
    fm, body, raw = parse_skill_md(skill_dir / "SKILL.md")
    meta = fm.get("metadata") or {}
    return SkillPackage(
        name=str(fm.get("name", "")),
        description=str(fm.get("description", "")),
        path=skill_dir,
        body=body,
        risk_class=str(meta.get("risk_class", "general")),
        version=str(meta.get("version", "1.0.0")),
        roles=_split_list(meta.get("roles")),
        allowed_tools=_split_list(fm.get("allowed-tools")),
        domain=meta.get("domain"),
        references=_split_list(meta.get("references")),
        raw_frontmatter=raw,
    )


def discover_skills(root: Optional[Path] = None) -> List[Path]:
    """Skill directories (holding SKILL.md) under ``skills/runtime`` and ``skills/domains``."""
    root = Path(root) if root else skills_dir()
    found: List[Path] = []
    for group in ("runtime", "domains"):
        base = root / group
        if base.is_dir():
            found += sorted(p for p in base.iterdir() if (p / "SKILL.md").is_file())
    return found


def load_skills(root: Optional[Path] = None) -> Dict[str, SkillPackage]:
    return {s.name: s for s in (load_skill(p) for p in discover_skills(root))}


# --------------------------------------------------------------------------- lint
def _text_files(skill_dir: Path) -> Iterable[Path]:
    for p in sorted(skill_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
            yield p


def _routing_hits(text: str) -> List[str]:
    hits = []
    for m in ROUTING_PATTERN.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        if not _NEGATION.search(text[line_start:m.start()]):
            hits.append(m.group(0))
    return hits


def lint_skill_package(skill_dir: Path) -> List[SkillLintError]:
    """Lint one skill directory (format, store constraints, clinical rules)."""
    skill_dir = Path(skill_dir)
    label = skill_dir.name
    if not (skill_dir / "SKILL.md").is_file():
        return [SkillLintError(label, "MISSING_SKILL_MD", "SKILL.md not found at the skill root")]
    try:
        skill = load_skill(skill_dir)
    except Exception as exc:  # malformed YAML or frontmatter
        return [SkillLintError(label, "MALFORMED_FRONTMATTER", str(exc))]

    errors: List[SkillLintError] = []

    def err(rule: str, message: str) -> None:
        errors.append(SkillLintError(skill.name or label, rule, message))

    if not skill.name:
        err("EMPTY_NAME", "frontmatter 'name' is required")
    elif len(skill.name) > MAX_NAME:
        err("NAME_TOO_LONG", f"name exceeds {MAX_NAME} characters")
    elif not NAME_PATTERN.match(skill.name):
        err("INVALID_NAME", "name must match ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
    elif skill.name != skill_dir.name:
        err("NAME_DIR_MISMATCH", f"name '{skill.name}' must equal its directory name '{skill_dir.name}'")
    if not skill.description.strip():
        err("EMPTY_DESCRIPTION", "frontmatter 'description' is required")
    elif len(skill.description) > MAX_DESCRIPTION:
        err("DESC_TOO_LONG", f"description exceeds {MAX_DESCRIPTION} characters")
    if _QUOTED_FIELD.search(skill.raw_frontmatter):
        err("QUOTED_FIELD", "name and description must be unquoted (Foundry Skills API)")
    if len(skill.body) > MAX_BODY_CHARS:
        err("BODY_TOO_LONG", f"SKILL.md body exceeds {MAX_BODY_CHARS} characters (~5k tokens)")
    if skill.risk_class not in RISK_CLASSES:
        err("INVALID_RISK_CLASS", f"metadata.risk_class must be one of {sorted(RISK_CLASSES)}")
    if not skill.roles:
        err("NO_ROLES", "metadata.roles must name the role(s) that load this skill")
    if skill.domain and skill.name != domain_skill_name(skill.domain):
        err("DOMAIN_SKILL_NAME", f"domain skill for '{skill.domain}' must be named '{domain_skill_name(skill.domain)}'")

    for tool in skill.allowed_tools:
        if tool not in CANONICAL_MCP_TOOLS:
            err("UNKNOWN_TOOL", f"allowed-tools names '{tool}', which is not in the canonical MCP contract")
    for p in _text_files(skill_dir):
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(skill_dir).as_posix()
        if "�" in text or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
            err("CONTROL_CHARACTERS", f"{rel} contains control or undecodable characters")
        if "https://" in text or "http://" in text:
            err("REMOTE_REFERENCE", f"{rel} references a remote URL; skills are first-party and offline")
        for tool in set(TOOL_MENTION.findall(text)):
            if tool in CANONICAL_MCP_TOOLS and tool not in skill.allowed_tools:
                err("UNDECLARED_TOOL", f"{rel} names tool '{tool}' that is not in allowed-tools")
        if skill.risk_class == "clinical":
            m = CLINICAL_VALUE_PATTERN.search(text)
            if m:
                err("NO_CLINICAL_NUMBERS", f"{rel} contains the clinical value '{m.group(0)}'; values live in the ontology")
            for hit in _routing_hits(text):
                err("NO_ROUTING_VERBS", f"{rel} contains routing language '{hit}'; routing is the gate's decision")
    for name in skill.references:
        if not (skill_dir / "references" / f"{name}.md").is_file():
            err("MISSING_REFERENCE", f"generated reference references/{name}.md is missing (run `ontogate skills build`)")

    if skill.risk_class == "clinical" and (skill_dir / "scripts").exists():
        err("NO_SCRIPTS_ALLOWED", "clinical skills must not contain a scripts/ directory")
    size = sum(p.stat().st_size for p in skill_dir.rglob("*") if p.is_file())
    if size > MAX_ARCHIVE_BYTES:
        err("ARCHIVE_TOO_LARGE", f"skill is {size} bytes; the store limit is {MAX_ARCHIVE_BYTES}")
    return errors


def check_roles_and_skills(roles: Dict[str, RoleSpec], skills: Dict[str, SkillPackage]) -> List[SkillLintError]:
    """RoleSkillShape / ToolShape: roles, skills and tool grants agree in both directions."""
    errors: List[SkillLintError] = [SkillLintError(*e) for e in check_role_specs(roles)]
    domain_roles = {r for r, spec in roles.items() if spec.domain_skills}
    for role, spec in sorted(roles.items()):
        for tool in spec.tools:
            if tool not in CANONICAL_MCP_TOOLS:
                errors.append(SkillLintError(role, "UNKNOWN_TOOL", f"role grants non-canonical tool '{tool}'"))
        if not spec.uses_model and (spec.skills or spec.domain_skills):
            errors.append(SkillLintError(role, "CODE_NODE_WITH_SKILLS", "a code node (uses_model: false) loads no skills"))
        for name in spec.skills:
            skill = skills.get(name)
            if skill is None:
                errors.append(SkillLintError(role, "ROLE_UNKNOWN_SKILL", f"loads skill '{name}', which does not exist"))
            elif skill.is_domain_skill:
                errors.append(SkillLintError(role, "DOMAIN_SKILL_LISTED",
                                             f"loads domain skill '{name}' by name; use domain_skills: true"))
    for name, skill in sorted(skills.items()):
        for role in skill.roles:
            if role not in roles:
                errors.append(SkillLintError(name, "SKILL_UNKNOWN_ROLE", f"declares unknown role '{role}'"))
                continue
            loads = role in domain_roles if skill.is_domain_skill else name in roles[role].skills
            if not loads:
                errors.append(SkillLintError(name, "SKILL_ROLE_MISMATCH", f"declares role '{role}', which does not load it"))
                continue
            missing = [t for t in skill.allowed_tools if t not in roles[role].tools]
            if missing:
                errors.append(SkillLintError(name, "TOOL_NOT_GRANTED",
                                             f"needs tool(s) {', '.join(missing)} not granted to role '{role}'"))
        loaded_by = {r for r, spec in roles.items() if name in spec.skills}
        if skill.is_domain_skill:
            loaded_by |= domain_roles
        undeclared = loaded_by - set(skill.roles)
        if undeclared:
            errors.append(SkillLintError(name, "ROLE_SKILL_NOT_DECLARED",
                                         f"loaded by role(s) {', '.join(sorted(undeclared))} that it does not declare"))
    return errors


# --------------------------------------------------------------------------- render
def _registry_for(skill: SkillPackage):
    from ontogate.config import get_default_registry, load_domain_config
    if skill.domain:
        return load_domain_config(domain_dir(skill.domain))
    return get_default_registry()


def render_skill_references(skill: SkillPackage) -> Dict[Path, str]:
    """Rendered content for each generated reference of a skill."""
    from ontogate.skill_refs import render_reference
    if not skill.references:
        return {}
    reg = _registry_for(skill)
    return {skill.path / "references" / f"{name}.md": render_reference(name, reg) for name in skill.references}


def _read_normalised(path: Path) -> Optional[str]:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.is_file() else None


# --------------------------------------------------------------------------- package
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def package_skill(skill_dir: Path) -> bytes:
    """Deterministic zip of a skill (SKILL.md at the archive root, LF line endings)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(x for x in Path(skill_dir).rglob("*") if x.is_file() and "__pycache__" not in x.parts):
            data = p.read_bytes()
            if p.suffix.lower() in TEXT_SUFFIXES:
                data = data.replace(b"\r\n", b"\n")
            info = zipfile.ZipInfo(p.relative_to(skill_dir).as_posix(), date_time=_ZIP_EPOCH)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return buf.getvalue()


def _sha256_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def compute_lock(root: Optional[Path] = None, skills: Optional[Dict[str, SkillPackage]] = None) -> Dict[str, Any]:
    """Lock content for the skills on disk (no writes)."""
    root = Path(root) if root else skills_dir()
    skills = skills if skills is not None else load_skills(root)
    entries = {}
    for name, skill in sorted(skills.items()):
        entries[name] = {
            "version": skill.version,
            "risk_class": skill.risk_class,
            "path": skill.path.relative_to(root).as_posix(),
            "roles": list(skill.roles),
            "allowed_tools": list(skill.allowed_tools),
            "domain": skill.domain,
            "sha256": sha256_tree(skill.path),
            "archive_sha256": _sha256_bytes(package_skill(skill.path)),
        }
    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "bundle_sha256": sha256_tree(ontology_dir()),
        "skills": entries,
    }


# --------------------------------------------------------------------------- build / check
def _collect_errors(root: Path, roles: Dict[str, RoleSpec]) -> Tuple[Dict[str, SkillPackage], List[SkillLintError]]:
    errors: List[SkillLintError] = []
    for skill_dir in discover_skills(root):
        errors += lint_skill_package(skill_dir)
    skills = {}
    for skill_dir in discover_skills(root):
        try:
            skill = load_skill(skill_dir)
        except Exception:
            continue
        if skill.name in skills:
            errors.append(SkillLintError(skill.name, "DUPLICATE_NAME", f"defined in {skills[skill.name].path} and {skill_dir}"))
        skills[skill.name] = skill
    errors += check_roles_and_skills(roles, skills)
    return skills, errors


def build_skills(root: Optional[Path] = None, dist_dir: Optional[Path] = None,
                 roles: Optional[Dict[str, RoleSpec]] = None) -> Dict[str, Any]:
    """Render references, lint, check roles, write the lock and the archives."""
    root = Path(root) if root else skills_dir()
    dist = Path(dist_dir) if dist_dir else dist_skills_dir()
    roles = roles if roles is not None else load_all_role_specs()
    render_errors: List[SkillLintError] = []
    for skill_dir in discover_skills(root):
        try:
            skill = load_skill(skill_dir)
        except Exception:
            continue  # malformed frontmatter is reported by lint below
        try:
            rendered = render_skill_references(skill)
        except Exception as exc:
            render_errors.append(SkillLintError(skill.name, "RENDER_FAILED", f"{type(exc).__name__}: {exc}"))
            continue
        for path, content in rendered.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if _read_normalised(path) != content:
                path.write_text(content, encoding="utf-8", newline="\n")
    skills, errors = _collect_errors(root, roles)
    errors = render_errors + errors
    if errors:
        raise SkillBuildError(errors)
    lock = compute_lock(root, skills)
    lock_path(root).write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n")
    dist.mkdir(parents=True, exist_ok=True)
    for name, skill in skills.items():
        (dist / f"{name}.zip").write_bytes(package_skill(skill.path))
    return lock


def check_skills(root: Optional[Path] = None, roles: Optional[Dict[str, RoleSpec]] = None) -> List[SkillLintError]:
    """Everything ``build`` checks, plus drift of references and lock — without writing."""
    root = Path(root) if root else skills_dir()
    roles = roles if roles is not None else load_all_role_specs()
    skills, errors = _collect_errors(root, roles)
    for name, skill in skills.items():
        for path, content in render_skill_references(skill).items():
            if _read_normalised(path) != content:
                errors.append(SkillLintError(name, "REFERENCE_DRIFT",
                                             f"{path.relative_to(skill.path).as_posix()} differs from the ontology "
                                             "(run `ontogate skills build`)"))
    committed = json.loads(lock_path(root).read_text(encoding="utf-8")) if lock_path(root).is_file() else None
    if committed is None:
        errors.append(SkillLintError("skills.lock.json", "MISSING_LOCK", "run `ontogate skills build`"))
    elif committed != compute_lock(root, skills):
        errors.append(SkillLintError("skills.lock.json", "LOCK_DRIFT",
                                     "skills or the ontology changed since the lock was written (run `ontogate skills build`)"))
    return errors


def load_lock(root: Optional[Path] = None) -> Dict[str, Any]:
    path = lock_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"Missing {path} (run `ontogate skills build`)")
    return json.loads(path.read_text(encoding="utf-8"))


def verify_skills_lock(root: Optional[Path] = None, *, base: Optional[Path] = None) -> bool:
    """Fail closed unless every locked skill directory matches its recorded hash.

    ``base`` is where the skill directories live (default: the skills root);
    a skill store passes its materialisation directory.
    """
    root = Path(root) if root else skills_dir()
    lock = load_lock(root)
    for name, meta in lock.get("skills", {}).items():
        skill_dir = (Path(base) / name) if base else root / meta["path"]
        if not skill_dir.is_dir():
            raise FileNotFoundError(f"Locked skill '{name}' not found at {skill_dir}")
        actual = sha256_tree(skill_dir)
        if actual != meta["sha256"]:
            raise ValueError(f"Skill '{name}' hash mismatch: locked {meta['sha256']}, found {actual}")
    return True


# --------------------------------------------------------------------------- per role
def skill_names_for_role(role: RoleSpec, domains: Optional[Iterable[str]] = None) -> List[str]:
    """Skills a role loads: its declared skills plus the domain skill of each loaded pack."""
    names = list(role.skills)
    if role.domain_skills:
        if domains is None:
            from ontogate.config import get_default_registry
            domains = get_default_registry().domains.keys()
        names += [domain_skill_name(d) for d in sorted(domains)]
    return names


def skills_for_role(role: str, *, domains: Optional[Iterable[str]] = None,
                    root: Optional[Path] = None, base: Optional[Path] = None) -> List[Path]:
    """Hash-verified local skill directories for a role (fails closed).

    ``base`` is a materialised skills directory (``<base>/<name>/``) from a
    :class:`~ontogate.ports.SkillStorePort`; by default skills load from the
    repository / image tree at their locked paths.
    """
    from ontogate.roles import get_role_spec
    spec = get_role_spec(role)
    names = skill_names_for_role(spec, domains)
    if not names:
        return []
    root = Path(root) if root else skills_dir()
    if base is None:
        from ontogate.cloud_stores import materialised_base
        base = materialised_base()
    lock = load_lock(root)
    verify_skills_lock(root, base=base)
    paths = []
    for name in names:
        meta = lock["skills"].get(name)
        if meta is None:
            raise KeyError(f"Role '{role}' loads skill '{name}', which is not in skills.lock.json")
        paths.append((Path(base) / name) if base else root / meta["path"])
    return paths


# --------------------------------------------------------------------------- developer skills
DEVELOPER_SKILL_RULES_SKIPPED = {"NO_ROLES", "UNDECLARED_TOOL"}  # not role-scoped; they teach the tools


def mirror_developer_skills(check: bool = False) -> List[str]:
    """Mirror ``.agents/skills`` (source of truth) into ``.claude/skills`` for discovery.

    Returns the relative paths that differ; with ``check`` nothing is written.
    """
    import shutil
    source, target = repo_root() / ".agents" / "skills", repo_root() / ".claude" / "skills"
    wanted = {p.relative_to(source).as_posix(): p for p in source.rglob("*") if p.is_file()}
    present = {p.relative_to(target).as_posix(): p for p in target.rglob("*") if p.is_file()} if target.exists() else {}
    drift = sorted(rel for rel in wanted.keys() | present.keys()
                   if rel not in wanted or rel not in present
                   or _read_normalised(wanted[rel]) != _read_normalised(present[rel]))
    if not check and drift:
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
    return drift


# --------------------------------------------------------------------------- CLI
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="ontogate skills", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="render references, lint, check roles, write lock and dist/skills archives")
    sub.add_parser("check", help="lint and fail on reference or lock drift (no writes)")
    sub.add_parser("verify", help="verify skill directories against skills.lock.json")
    role_p = sub.add_parser("role", help="print the skill directories a role loads")
    role_p.add_argument("role")
    pub_p = sub.add_parser("publish", help="upload locked archives to a store (gs://, s3://, azblob://, path)")
    pub_p.add_argument("store")
    mir_p = sub.add_parser("mirror", help="copy developer skills .agents/skills into .claude/skills")
    mir_p.add_argument("--check", action="store_true", help="fail if the mirror differs (no writes)")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "build":
            lock = build_skills()
            print(f"Locked {len(lock['skills'])} skill(s); archives in {dist_skills_dir()}")
        elif args.cmd == "check":
            errors = check_skills()
            for e in errors:
                print(e)
            print(f"{len(errors)} error(s)")
            return 1 if errors else 0
        elif args.cmd == "verify":
            verify_skills_lock()
            print("skills.lock.json verified")
        elif args.cmd == "role":
            for p in skills_for_role(args.role):
                print(p)
        elif args.cmd == "mirror":
            drift = mirror_developer_skills(check=args.check)
            for path in drift:
                print(f"drift: {path}")
            if args.check:
                return 1 if drift else 0
            print(f"Mirrored developer skills into {repo_root() / '.claude' / 'skills'}")
        elif args.cmd == "publish":
            from ontogate.cloud_stores import store_from_url
            store = store_from_url(args.store)
            uploaded = store.publish(load_lock(), dist_skills_dir())
            print(f"{len(uploaded)} archive(s) uploaded to {store.describe()}; "
                  f"{len(load_lock()['skills']) - len(uploaded)} already present")
    except (SkillBuildError, ValueError, KeyError, FileNotFoundError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
