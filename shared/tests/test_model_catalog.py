"""
Model catalog: one source of truth for model IDs, per-role resolution, and a
repository-wide guard against model IDs that are not in the catalog.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone

import pytest

from ontogate.catalog import is_unusable_stop, model_for, model_ids, retirement_warnings
from ontogate.paths import repo_root

MODEL_ID = re.compile(
    r"(?<![\w/.])(?:global\.|us\.|eu\.)?(?:anthropic\.)?"
    r"(gemini-[0-9][\w.-]*|claude-(?:opus|sonnet|haiku|fable)[\w.:-]*|gpt-[0-9][\w.-]*)"
)
# Provenance strings name the model that generated a knowledge artifact (historical fact).
PROVENANCE = re.compile(r"reference_agent/gemini-[\w.-]+")
SKIP_PREFIXES = ("docs/", "config/models.yaml")
SCANNED_SUFFIXES = (".py", ".sh", ".ps1", ".yaml", ".yml", ".toml", ".example", ".env", "Dockerfile")


def _tracked_files():
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=repo_root(),
                         capture_output=True, text=True, check=True).stdout.splitlines()
    return [f for f in out if f.endswith(SCANNED_SUFFIXES) and not f.startswith(SKIP_PREFIXES)
            and (repo_root() / f).is_file()]


def test_every_model_id_in_the_repository_is_in_the_catalog():
    """Code, scripts, templates and agent YAML may only name catalog model IDs."""
    allowed = set(model_ids())
    stray = []
    for rel in _tracked_files():
        text = PROVENANCE.sub("", (repo_root() / rel).read_text(encoding="utf-8", errors="ignore"))
        for m in MODEL_ID.finditer(text):
            full = m.group(0)
            if full not in allowed and m.group(1) not in allowed:
                stray.append(f"{rel}: {full}")
    assert stray == []


@pytest.mark.parametrize("cloud,family", [("gcp", "gemini"), ("aws", "claude"), ("azure", "openai")])
def test_each_cloud_uses_its_first_party_family(cloud, family):
    assert model_for(cloud)["family"] == family


def test_role_specific_settings():
    """Claude effort and OpenAI reasoning effort are explicit per role."""
    assert model_for("aws", "clinical_synthesizer")["effort"] == "high"
    assert model_for("aws", "clarification_coordinator")["effort"] == "low"
    assert model_for("aws")["bedrock_id"] == "global.anthropic.claude-opus-5-5"
    assert model_for("azure", "clinical_synthesizer")["reasoning_effort"] == "high"
    assert model_for("azure")["deployment_name"] == "gpt-6.1-sol"
    assert model_for("gcp")["id"] == "gemini-3.8-flash"


def test_unknown_cloud_is_rejected():
    with pytest.raises(ValueError):
        model_for("oracle")


def test_no_pinned_model_is_near_retirement():
    """CI warns before a pinned model retires (catalog retire_after)."""
    assert retirement_warnings(datetime.now(timezone.utc)) == []


@pytest.mark.parametrize("reason,unusable", [
    ("end_turn", False), ("tool_use", False), ("refusal", True), ("max_tokens", True),
    ("FinishReason.SAFETY", True), ("content_filtered", True), (None, False),
])
def test_unusable_stop_reasons_fail_closed(reason, unusable):
    """A refusal / safety block / truncation routes to CLARIFY (MODEL_UNAVAILABLE)."""
    assert is_unusable_stop(reason) is unusable
