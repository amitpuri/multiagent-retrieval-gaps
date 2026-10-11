"""
Model catalog access — resolves the model a role must use on a cloud from
``config/models.yaml``. No model ID is hard-coded anywhere else.

    >>> from ontogate.catalog import model_for
    >>> model_for("aws", "clinical_synthesizer")["bedrock_id"]
    'global.anthropic.claude-opus-5-5'
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ontogate.paths import config_file

CLOUDS = ("gcp", "aws", "azure")
RETIREMENT_WARNING_DAYS = 30


@lru_cache(maxsize=4)
def load_catalog(path: Optional[str] = None) -> Dict[str, Any]:
    p = Path(path) if path else config_file("models.yaml")
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def model_ids(path: Optional[str] = None) -> List[str]:
    """Every provider-facing model ID string declared in the catalog."""
    cat = load_catalog(path)
    ids: List[str] = []
    for key, entry in (cat.get("catalog") or {}).items():
        ids.append(key)
        for field in ("anthropic_id", "bedrock_id"):
            if entry.get(field):
                ids.append(entry[field])
    for cloud in (cat.get("deployments") or {}).values():
        if cloud.get("deployment_name"):
            ids.append(cloud["deployment_name"])
    return sorted(set(ids))


def model_for(cloud: str, role: str = "", path: Optional[str] = None) -> Dict[str, Any]:
    """Resolve ``{id, ...provider fields, effort/reasoning_effort}`` for a role on a cloud."""
    if cloud not in CLOUDS:
        raise ValueError(f"Unknown cloud '{cloud}' (expected one of {CLOUDS})")
    cat = load_catalog(path)
    dep = (cat.get("deployments") or {}).get(cloud) or {}
    model_key = (dep.get("roles") or {}).get(role) or dep.get("default")
    entry = dict((cat.get("catalog") or {}).get(model_key) or {})
    if not entry:
        raise ValueError(f"Model '{model_key}' for {cloud}/{role} is not in the catalog")
    if entry.get("provider") != cloud:
        raise ValueError(f"Model '{model_key}' belongs to {entry.get('provider')}, not {cloud}")
    out: Dict[str, Any] = {"id": model_key, **entry, "framework": dep.get("framework")}
    if cloud == "aws":
        out["effort"] = (dep.get("role_effort") or {}).get(role, dep.get("effort", "high"))
    if cloud == "azure":
        out["deployment_name"] = dep.get("deployment_name", model_key)
        out["reasoning_effort"] = (dep.get("role_reasoning_effort") or {}).get(role, dep.get("reasoning_effort"))
    return out


def retirement_warnings(now: Optional[datetime] = None, path: Optional[str] = None) -> List[str]:
    """Models pinned by a deployment that retire within the warning window (or already have)."""
    now = now or datetime.now(timezone.utc)
    cat = load_catalog(path)
    pinned = set()
    for dep in (cat.get("deployments") or {}).values():
        pinned.add(dep.get("default"))
        pinned.update((dep.get("roles") or {}).values())
    warnings: List[str] = []
    for key in sorted(k for k in pinned if k):
        retire = ((cat.get("catalog") or {}).get(key) or {}).get("retire_after")
        if not retire:
            continue
        day = retire if isinstance(retire, date) else date.fromisoformat(str(retire))
        if now.date() >= day - timedelta(days=RETIREMENT_WARNING_DAYS):
            warnings.append(f"{key} retires on {day.isoformat()}")
    return warnings


#: Stop / finish reasons after which model output must not be shown (fail closed).
UNUSABLE_STOP_REASONS = frozenset({
    "refusal", "content_filtered", "guardrail_intervened", "safety", "blocked", "prohibited_content",
    "max_tokens", "length", "recitation", "spii", "malformed_function_call",
})


def is_unusable_stop(reason: Optional[str]) -> bool:
    """True when a model turn ended in a way that must route to CLARIFY (MODEL_UNAVAILABLE)."""
    if not reason:
        return False
    return str(reason).strip().lower().split(".")[-1] in UNUSABLE_STOP_REASONS
