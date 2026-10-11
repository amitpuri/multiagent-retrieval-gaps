"""
Every runtime image ships the knowledge release it serves: the shared core,
the ontology, the model catalog, the hash-locked skills and the role specs.
"""
import re

import pytest

from ontogate.paths import repo_root

DOCKERFILES = ["google-adk-agents/Dockerfile", "strands-agents/Dockerfile", "agent-framework/Dockerfile"]
REQUIRED = ["shared/", "ontology/", "config/", "skills/", "agents/"]


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_image_ships_the_knowledge_release(dockerfile):
    text = (repo_root() / dockerfile).read_text(encoding="utf-8")
    copied = set(re.findall(r"^COPY\s+(\S+)", text, flags=re.MULTILINE))
    assert set(REQUIRED) <= copied, sorted(set(REQUIRED) - copied)
    assert "ENV ONTOGATE_REPO_ROOT=/app" in text


def test_dockerignore_does_not_exclude_the_release():
    path = repo_root() / ".dockerignore"
    if not path.exists():
        return
    ignored = {line.strip().rstrip("/") for line in path.read_text(encoding="utf-8").splitlines()
               if line.strip() and not line.startswith("#")}
    assert not ignored & {r.rstrip("/") for r in REQUIRED}
