"""
Tests for role specifications, Agent Skills building, clinical linting, and locking.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ontogate.paths import repo_root
from ontogate.roles import load_all_role_specs, load_role_spec
from ontogate.skills import (
    CANONICAL_MCP_TOOLS,
    build_and_lock_skills,
    lint_skill_package,
    verify_skills_lock,
)


def test_role_specifications_completeness():
    """Verify all 7 agent role specifications exist and adhere to contracts."""
    specs = load_all_role_specs()
    expected_roles = {
        "triage_orchestrator",
        "ontology_resolver",
        "safety_guard",
        "protocol_retriever",
        "clinical_synthesizer",
        "clarification_coordinator",
        "panel_coordinator",
    }
    assert set(specs.keys()) == expected_roles

    # Invariant 1: Safety Guard is a pure code node
    sg = specs["safety_guard"]
    assert sg.uses_model is False
    assert sg.skills == []
    assert sg.tools == ["evaluate_safety_gate"]

    # All tools must be in canonical MCP tools
    for role_name, spec in specs.items():
        for t in spec.tools:
            assert t in CANONICAL_MCP_TOOLS, f"Role {role_name} uses non-canonical tool: {t}"


def test_skills_lock_and_verification():
    """Verify skills locking and on-disk directory hashing."""
    lock = build_and_lock_skills()
    assert len(lock["skills"]) >= 7
    assert "domain-laboratory-medicine" in lock["skills"]
    assert verify_skills_lock() is True


def test_clinical_lint_blocks_numbers_and_scripts(tmp_path: Path):
    """Verify clinical lint blocks hardcoded clinical values and scripts in clinical skills."""
    bad_skill = tmp_path / "bad-skill"
    bad_skill.mkdir()
    (bad_skill / "SKILL.md").write_text(
        "---\nname: bad-skill\ndescription: A bad clinical skill\nmetadata:\n  risk_class: clinical\n---\n"
        "# Bad\nAssume normal Hb is 13.5 g/dL and proceed.",
        encoding="utf-8",
    )

    errors = lint_skill_package(bad_skill)
    assert any(e.rule == "NO_CLINICAL_NUMBERS" for e in errors)

    # Adding scripts/ directory must also be rejected
    (bad_skill / "scripts").mkdir()
    errors = lint_skill_package(bad_skill)
    assert any(e.rule == "NO_SCRIPTS_ALLOWED" for e in errors)
