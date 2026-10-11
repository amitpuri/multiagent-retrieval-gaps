"""
Ports: the narrow interfaces between the cloud-agnostic core and each
runtime. The core depends only on these Protocols; framework (L2) and cloud
(L3) adapters implement them.

Local adapters here run in development, CI and offline mode. Cloud adapters for
artifact stores are in :mod:`ontogate.adapters` and import their SDKs lazily.

Data protection: ``AuditPort`` events never contain raw patient values unless
``ONTOGATE_AUDIT_INCLUDE_VALUES=1`` is set explicitly.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

log = logging.getLogger("ontogate.audit")


# ---------------------------------------------------------------------------
# Port definitions
# ---------------------------------------------------------------------------

@runtime_checkable
class BundleStorePort(Protocol):
    """Fetches a released ontology/skills bundle by version and returns a local directory."""

    def fetch(self, release: str, dest: Path) -> Path: ...


@runtime_checkable
class SkillStorePort(Protocol):
    """Resolves locked skills to local directories for framework loaders."""

    def materialise(self, lock: Dict[str, Any], dest: Path) -> List[Path]: ...


@runtime_checkable
class AuditPort(Protocol):
    """Records gate decisions and attestations (ABox events — never the knowledge corpus)."""

    def record(self, event: str, payload: Dict[str, Any]) -> None: ...


@runtime_checkable
class TelemetryPort(Protocol):
    """Attaches GenAI / gate attributes to the current trace span."""

    def annotate(self, attributes: Dict[str, Any]) -> None: ...


@runtime_checkable
class ModelPort(Protocol):
    """Resolves the model a role must use on the current cloud (from config/models.yaml)."""

    def model_for(self, role: str) -> Dict[str, Any]: ...


@runtime_checkable
class PolicyPort(Protocol):
    """Answers which canonical tools a role may call (additive to the gate, never a substitute)."""

    def allowed_tools(self, role: str) -> List[str]: ...


@runtime_checkable
class MemoryPort(Protocol):
    """Session / long-term memory. Must never store raw patient values."""

    def append(self, session_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None: ...

    def history(self, session_id: str) -> List[Dict[str, Any]]: ...


@runtime_checkable
class IdentityPort(Protocol):
    """Identifies the calling workload (for audit attribution)."""

    def principal(self) -> str: ...


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_VALUE_KEYS = {"patient_value", "value", "attested_value", "raw_text", "text", "prompt"}


def redact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop patient-identifying values unless explicitly allowed."""
    if os.environ.get("ONTOGATE_AUDIT_INCLUDE_VALUES") == "1":
        return dict(payload)
    out: Dict[str, Any] = {}
    for k, v in payload.items():
        if k in _VALUE_KEYS:
            out[k] = "<redacted>" if v not in (None, "") else v
        elif isinstance(v, dict):
            out[k] = redact(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Local adapters
# ---------------------------------------------------------------------------

class LoggingAudit:
    """Default audit sink: structured log lines, plus JSONL when ``ONTOGATE_AUDIT_PATH`` is set."""

    def __init__(self, path: Optional[Path] = None) -> None:
        env = os.environ.get("ONTOGATE_AUDIT_PATH")
        self.path = path or (Path(env) if env else None)

    def record(self, event: str, payload: Dict[str, Any]) -> None:
        entry = {"ts": time.time(), "event": event, **redact(payload)}
        try:
            from ontogate.release import current_release
            entry.setdefault("bundle_sha256", current_release().get("bundle_sha256"))
            entry.setdefault("skills_lock_sha256", current_release().get("skills_lock_sha256"))
        except Exception:
            pass
        log.info("%s %s", event, json.dumps(entry, default=str, sort_keys=True))
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str, sort_keys=True) + "\n")


@dataclass
class MemoryAudit:
    """In-memory audit sink for tests."""
    events: List[Dict[str, Any]] = field(default_factory=list)

    def record(self, event: str, payload: Dict[str, Any]) -> None:
        self.events.append({"event": event, **redact(payload)})


class NoopTelemetry:
    """Telemetry adapter that tries OpenTelemetry and otherwise does nothing."""

    def annotate(self, attributes: Dict[str, Any]) -> None:
        try:
            from opentelemetry import trace  # type: ignore
            span = trace.get_current_span()
            for k, v in attributes.items():
                if isinstance(v, (str, bool, int, float)):
                    span.set_attribute(k, v)
        except Exception:
            return


class LocalBundleStore:
    """Bundles already present on disk (checkout, CI, or baked into an image)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def fetch(self, release: str, dest: Path) -> Path:
        candidate = self.root / release
        return candidate if candidate.exists() else self.root


class LocalSkillStore:
    """Skills built into ``dist/skills`` (or baked into the image at the lock path)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def materialise(self, lock: Dict[str, Any], dest: Path) -> List[Path]:
        return [self.root / name for name in lock.get("skills", {})]


class InMemoryMemory:
    """Session memory for offline mode and tests (no PHI persisted)."""

    def __init__(self) -> None:
        self._turns: Dict[str, List[Dict[str, Any]]] = {}

    def append(self, session_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self._turns.setdefault(session_id, []).append({"role": role, "content": content,
                                                        "metadata": redact(metadata or {})})

    def history(self, session_id: str) -> List[Dict[str, Any]]:
        return list(self._turns.get(session_id, []))


class EnvIdentity:
    """Workload principal from the environment (set by each cloud's runtime)."""

    def principal(self) -> str:
        for key in ("ONTOGATE_PRINCIPAL", "K_SERVICE", "AWS_EXECUTION_ENV", "CONTAINER_APP_NAME", "USERNAME", "USER"):
            if os.environ.get(key):
                return f"{key.lower()}:{os.environ[key]}"
        return "unknown"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_tree(root: Path) -> str:
    """Deterministic hash of a directory tree (relative paths + contents)."""
    h = hashlib.sha256()
    for p in sorted(x for x in Path(root).rglob("*") if x.is_file()):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(sha256_file(p).encode())
    return h.hexdigest()


_AUDIT: Optional[AuditPort] = None


def get_audit() -> AuditPort:
    """Process-wide audit port (LoggingAudit unless replaced with :func:`set_audit`)."""
    global _AUDIT
    if _AUDIT is None:
        _AUDIT = LoggingAudit()
    return _AUDIT


def set_audit(audit: AuditPort) -> None:
    global _AUDIT
    _AUDIT = audit
