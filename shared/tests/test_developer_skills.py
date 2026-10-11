"""
Developer skills (.agents/) must match the code they teach: every Python
snippet compiles, and every ``ontogate`` import it shows resolves.
"""
import ast
import importlib
import re

import pytest

from ontogate.paths import repo_root

FENCE = re.compile(r"```python\n(.*?)```", re.DOTALL)


def _snippets():
    out = []
    for path in sorted((repo_root() / ".agents").rglob("*.md")):
        for i, code in enumerate(FENCE.findall(path.read_text(encoding="utf-8"))):
            out.append(pytest.param(code, id=f"{path.relative_to(repo_root()).as_posix()}#{i}"))
    return out


@pytest.mark.parametrize("code", _snippets())
def test_snippet_compiles_and_imports_resolve(code):
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Fragments shown inside a function body: compile them indented in one.
        tree = ast.parse("async def _snippet():\n" + "\n".join("    " + l for l in code.splitlines()))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "ontogate":
            module = importlib.import_module(node.module)
            for alias in node.names:
                assert hasattr(module, alias.name), f"{node.module} has no '{alias.name}'"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "ontogate":
                    importlib.import_module(alias.name)


def test_developer_skills_meet_the_skill_format():
    """Same agentskills.io format rules as runtime skills (they are not role-scoped)."""
    from ontogate.skills import DEVELOPER_SKILL_RULES_SKIPPED, lint_skill_package
    errors = []
    for skill_dir in sorted((repo_root() / ".agents" / "skills").iterdir()):
        errors += [str(e) for e in lint_skill_package(skill_dir) if e.rule not in DEVELOPER_SKILL_RULES_SKIPPED]
    assert errors == []


def test_claude_mirror_is_in_sync():
    """`.claude/skills` mirrors `.agents/skills` (run `python -m ontogate skills mirror`)."""
    from ontogate.skills import mirror_developer_skills
    assert mirror_developer_skills(check=True) == []
