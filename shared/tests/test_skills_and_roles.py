"""
Role specs and runtime Agent Skills: committed state, one failing fixture per
lint / consistency rule, lock integrity and per-role resolution.

No test writes into the repository: builds run against a copy in tmp_path.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, Optional

import pytest

from ontogate.config import get_default_registry
from ontogate.paths import repo_root
from ontogate.ports import sha256_tree
from ontogate.roles import RoleSpec, load_all_role_specs, load_role_spec
from ontogate.skill_refs import render_reference
from ontogate.skills import (
    CANONICAL_MCP_TOOLS,
    build_skills,
    check_roles_and_skills,
    check_skills,
    compute_lock,
    lint_skill_package,
    load_lock,
    load_skill,
    load_skills,
    package_skill,
    skills_for_role,
    verify_skills_lock,
)

EXPECTED_ROLES = {
    "triage_orchestrator", "ontology_resolver", "safety_guard", "protocol_retriever",
    "clinical_synthesizer", "clarification_coordinator", "panel_coordinator",
}


# --------------------------------------------------------------------------- committed state
def test_role_specs_are_complete_and_canonical():
    specs = load_all_role_specs()
    assert set(specs) == EXPECTED_ROLES
    guard = specs["safety_guard"]
    assert (guard.uses_model, guard.model_tier, guard.skills, guard.domain_skills) == (False, "none", [], False)
    assert guard.tools == ["evaluate_safety_gate"]
    for role, spec in specs.items():
        assert set(spec.tools) <= CANONICAL_MCP_TOOLS, role
        assert spec.base_instruction, role


def test_committed_skills_lint_clean_and_match_lock_and_ontology():
    """References render identically from the ontology, lint passes, and the lock is current."""
    assert [str(e) for e in check_skills()] == []


def test_committed_lock_verifies():
    assert verify_skills_lock() is True
    lock = load_lock()
    assert lock["schema_version"] == "1.0.0"
    assert set(lock["skills"]) == set(load_skills())


def test_archives_are_deterministic():
    skill_dir = repo_root() / "skills" / "runtime" / "clinical-triage"
    assert package_skill(skill_dir) == package_skill(skill_dir)


def test_tree_hash_ignores_line_endings(tmp_path):
    (tmp_path / "lf").mkdir()
    (tmp_path / "crlf").mkdir()
    (tmp_path / "lf" / "SKILL.md").write_bytes(b"---\nname: x\n---\nbody\n")
    (tmp_path / "crlf" / "SKILL.md").write_bytes(b"---\r\nname: x\r\n---\r\nbody\r\n")
    assert sha256_tree(tmp_path / "lf") == sha256_tree(tmp_path / "crlf")


def test_designation_index_lists_every_ambiguous_designation():
    reg = get_default_registry()
    text = render_reference("designation-index", reg)
    ambiguous = [d.text for d in reg.designations.values() if d.is_ambiguous]
    assert ambiguous
    for designation in ambiguous:
        assert f"## `{designation}`" in text


def test_trust_caveats_follow_the_core_ontology():
    reg = get_default_registry()
    text = render_reference("trust-caveats", reg)
    for tier, wording in reg.trust_policy["caveats"].items():
        assert wording in text, tier


# --------------------------------------------------------------------------- per-role resolution
def test_code_node_loads_no_skills():
    assert skills_for_role("safety_guard") == []


def test_roles_load_their_declared_skills_and_the_domain_skill():
    assert [p.name for p in skills_for_role("ontology_resolver")] == ["lab-term-resolution",
                                                                     "domain-laboratory-medicine"]
    assert [p.name for p in skills_for_role("clinical_synthesizer")] == ["grounded-synthesis",
                                                                        "domain-laboratory-medicine"]
    assert [p.name for p in skills_for_role("triage_orchestrator")] == ["clinical-triage"]


def test_second_domain_needs_no_role_change():
    """Serving the cardiology pack swaps the domain skill; no role spec is edited."""
    assert [p.name for p in skills_for_role("ontology_resolver", domains=["cardiology"])] == [
        "lab-term-resolution", "domain-cardiology"]


def test_resolution_fails_closed_on_tampered_skill(tmp_path):
    root = tmp_path / "skills"
    shutil.copytree(repo_root() / "skills", root)
    (root / "runtime" / "clinical-triage" / "SKILL.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        skills_for_role("triage_orchestrator", root=root)


# --------------------------------------------------------------------------- build on a copy
@pytest.fixture
def skills_copy(tmp_path) -> Path:
    root = tmp_path / "skills"
    shutil.copytree(repo_root() / "skills", root)
    return root


def test_build_reproduces_the_committed_lock(skills_copy, tmp_path):
    lock = build_skills(skills_copy, dist_dir=tmp_path / "dist")
    assert lock == load_lock()
    assert sorted(p.stem for p in (tmp_path / "dist").glob("*.zip")) == sorted(lock["skills"])


def test_reference_drift_is_reported(skills_copy):
    ref = skills_copy / "runtime" / "grounded-synthesis" / "references" / "trust-caveats.md"
    ref.write_text(ref.read_text(encoding="utf-8") + "\nHand edit.\n", encoding="utf-8")
    rules = {e.rule for e in check_skills(skills_copy)}
    assert {"REFERENCE_DRIFT", "LOCK_DRIFT"} <= rules


# --------------------------------------------------------------------------- lint fixtures
def _skill(tmp_path: Path, name: str = "demo-skill", *, body: str = "# Demo\n\nUse `resolve_lab_term`.\n",
           frontmatter: Optional[str] = None, files: Optional[Dict[str, str]] = None, dirname: Optional[str] = None,
           risk: str = "clinical") -> Path:
    d = tmp_path / (dirname or name)
    d.mkdir(parents=True)
    fm = frontmatter if frontmatter is not None else (
        f"name: {name}\ndescription: A demo skill.\nallowed-tools: resolve_lab_term\n"
        f"metadata:\n  roles: ontology_resolver\n  risk_class: {risk}\n")
    (d / "SKILL.md").write_text(f"---\n{fm}---\n\n{body}", encoding="utf-8")
    for rel, content in (files or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(content, encoding="utf-8")
    return d


def _rules(skill_dir: Path):
    return {e.rule for e in lint_skill_package(skill_dir)}


def test_clean_fixture_passes(tmp_path):
    assert _rules(_skill(tmp_path)) == set()


@pytest.mark.parametrize("kwargs,rule", [
    ({"name": "Bad_Name"}, "INVALID_NAME"),
    ({"dirname": "other-dir"}, "NAME_DIR_MISMATCH"),
    ({"frontmatter": "name: \"demo-skill\"\ndescription: Quoted.\nmetadata:\n  roles: x\n"}, "QUOTED_FIELD"),
    ({"frontmatter": "name: demo-skill\ndescription: ''\nmetadata:\n  roles: x\n"}, "EMPTY_DESCRIPTION"),
    ({"frontmatter": "name: demo-skill\ndescription: No roles.\n"}, "NO_ROLES"),
    ({"body": "Normal Hb is 13.5 g/dL.\n"}, "NO_CLINICAL_NUMBERS"),
    ({"body": "HbA1c above 6.5 % is diagnostic.\n"}, "NO_CLINICAL_NUMBERS"),
    ({"files": {"references/notes.md": "Upper limit 14 ng/L.\n"}}, "NO_CLINICAL_NUMBERS"),
    ({"body": "Proceed if the unit looks right.\n"}, "NO_ROUTING_VERBS"),
    ({"body": "If no unit is given, assume the unit is g/dL.\n"}, "NO_ROUTING_VERBS"),
    ({"frontmatter": "name: demo-skill\ndescription: d\nallowed-tools: rm_rf_tool\nmetadata:\n  roles: x\n"},
     "UNKNOWN_TOOL"),
    ({"body": "Call `evaluate_safety_gate` yourself.\n"}, "UNDECLARED_TOOL"),
    ({"files": {"scripts/run.py": "print('x')\n"}}, "NO_SCRIPTS_ALLOWED"),
    ({"body": "Call \x0baluate_safety_gate.\n"}, "CONTROL_CHARACTERS"),
    ({"body": "See https://example.org/skill.\n"}, "REMOTE_REFERENCE"),
    ({"frontmatter": "name: demo-skill\ndescription: d\nmetadata:\n  roles: x\n  references: panels\n"},
     "MISSING_REFERENCE"),
    ({"frontmatter": "name: demo-skill\ndescription: d\nmetadata:\n  roles: x\n  risk_class: secret\n"},
     "INVALID_RISK_CLASS"),
])
def test_lint_rule_fires(tmp_path, kwargs, rule):
    assert rule in _rules(_skill(tmp_path, **kwargs))


def test_negated_routing_language_is_allowed(tmp_path):
    assert _rules(_skill(tmp_path, body="Never assume the unit; never proceed if unsure.\n")) == set()


def test_general_skills_may_carry_numbers(tmp_path):
    assert "NO_CLINICAL_NUMBERS" not in _rules(_skill(tmp_path, body="Keep files under 10 %.\n", risk="general"))


def test_malformed_frontmatter(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / "SKILL.md").write_text("no frontmatter", encoding="utf-8")
    assert _rules(d) == {"MALFORMED_FRONTMATTER"}


# --------------------------------------------------------------------------- role/skill consistency
def _role(role: str, *, tools=("resolve_lab_term",), skills=(), uses_model=True, domain_skills=False) -> RoleSpec:
    return RoleSpec(role=role, description="d", uses_model=uses_model, model_tier="flash" if uses_model else "none",
                    tools=list(tools), skills=list(skills), domain_skills=domain_skills, base_instruction="x")


def _consistency(tmp_path, roles, **skill_kwargs):
    skill = load_skill(_skill(tmp_path, **skill_kwargs))
    return {e.rule for e in check_roles_and_skills(roles, {skill.name: skill})}


def test_consistent_role_and_skill(tmp_path):
    assert _consistency(tmp_path, {"ontology_resolver": _role("ontology_resolver", skills=["demo-skill"])}) == set()


@pytest.mark.parametrize("roles,rule", [
    ({"ontology_resolver": _role("ontology_resolver", tools=["panel_workup"], skills=["demo-skill"])},
     "TOOL_NOT_GRANTED"),
    ({"ontology_resolver": _role("ontology_resolver")}, "SKILL_ROLE_MISMATCH"),
    ({"ontology_resolver": _role("ontology_resolver", skills=["demo-skill", "ghost-skill"])}, "ROLE_UNKNOWN_SKILL"),
    ({"ontology_resolver": _role("ontology_resolver", skills=["demo-skill"]),
      "other": _role("other", skills=["demo-skill"])}, "ROLE_SKILL_NOT_DECLARED"),
    ({"ontology_resolver": _role("ontology_resolver", skills=["demo-skill"], uses_model=False)},
     "CODE_NODE_WITH_SKILLS"),
    ({"ontology_resolver": _role("ontology_resolver", tools=["shell"], skills=["demo-skill"])}, "UNKNOWN_TOOL"),
])
def test_consistency_rule_fires(tmp_path, roles, rule):
    assert rule in _consistency(tmp_path, roles)


def test_skill_declaring_unknown_role(tmp_path):
    assert "SKILL_UNKNOWN_ROLE" in _consistency(tmp_path, {})


# --------------------------------------------------------------------------- role spec loader
@pytest.mark.parametrize("content,match", [
    ("role: demo\nuses_model: true\nmodel_tier: flash\nsurprise: 1\n", "unknown role spec key"),
    ("role: other\nuses_model: true\n", "must match the file name"),
    ("role: demo\nuses_model: false\nmodel_tier: flash\n", "code node"),
    ("role: demo\nmodel_tier: huge\n", "model_tier"),
])
def test_role_spec_loader_rejects(tmp_path, content, match):
    path = tmp_path / "demo.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_role_spec(path)


def test_lock_is_computed_from_disk_without_writing(tmp_path):
    before = (repo_root() / "skills" / "skills.lock.json").read_bytes()
    assert compute_lock() == load_lock()
    assert (repo_root() / "skills" / "skills.lock.json").read_bytes() == before


# --------------------------------------------------------------------------- delegation (P8.4)
def _deleg(role, delegates=(), uses_model=True):
    return RoleSpec(role=role, description=f"{role} role", uses_model=uses_model,
                    model_tier="flash" if uses_model else "none", delegates=list(delegates), base_instruction="x")


@pytest.mark.parametrize("specs,rule", [
    ({"a": _deleg("a", ["ghost"])}, "UNKNOWN_DELEGATE"),
    ({"a": _deleg("a", ["a"])}, "SELF_DELEGATION"),
    ({"a": _deleg("a", ["gate"]), "gate": _deleg("gate", uses_model=False)}, "DELEGATE_TO_CODE_NODE"),
    ({"a": _deleg("a", ["b"]), "b": _deleg("b", ["a"])}, "DELEGATION_CYCLE"),
    ({"gate": _deleg("gate", ["b"], uses_model=False), "b": _deleg("b")}, "CODE_NODE_DELEGATES"),
])
def test_delegation_rule_fires(specs, rule):
    from ontogate.roles import check_role_specs
    assert rule in {r for _, r, _ in check_role_specs(specs)}


def test_committed_role_specs_delegate_cleanly():
    from ontogate.roles import check_role_specs
    assert check_role_specs(load_all_role_specs()) == []


def test_instruction_text_is_shared_and_complete():
    from ontogate.roles import instruction_for
    specs = load_all_role_specs()
    text = instruction_for("triage_orchestrator", "Runtime note.")
    assert text.startswith(specs["triage_orchestrator"].base_instruction)
    assert "Tools you may call: parse_clinician_input, resolve_lab_term, evaluate_safety_gate." in text
    for target in specs["triage_orchestrator"].delegates:
        assert f"- {target}: {specs[target].description}" in text
    assert text.endswith("Runtime note.")
