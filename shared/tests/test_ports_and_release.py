"""
Runtime ports, TBox/ABox separation (audit vs knowledge log), and knowledge-release identity.
"""
from __future__ import annotations

import pytest

from ontogate.ports import (
    AuditPort,
    InMemoryMemory,
    MemoryAudit,
    get_audit,
    redact,
    set_audit,
    sha256_tree,
)
from ontogate.release import ReleaseVerificationError, current_release, verify_release


def test_audit_redacts_patient_values_by_default(monkeypatch):
    """F1: audit events carry no raw patient values unless explicitly enabled."""
    monkeypatch.delenv("ONTOGATE_AUDIT_INCLUDE_VALUES", raising=False)
    assert redact({"patient_value": 4.8, "uri": "loinc:17861-6"}) == {"patient_value": "<redacted>",
                                                                       "uri": "loinc:17861-6"}
    monkeypatch.setenv("ONTOGATE_AUDIT_INCLUDE_VALUES", "1")
    assert redact({"patient_value": 4.8})["patient_value"] == 4.8


def test_memory_audit_satisfies_port():
    audit = MemoryAudit()
    assert isinstance(audit, AuditPort)
    audit.record("gate", {"status": "RESOLVED", "patient_value": 1.0})
    assert audit.events[0]["patient_value"] == "<redacted>"


def test_in_memory_session_memory_redacts_metadata():
    mem = InMemoryMemory()
    mem.append("s1", "user", "Hb", {"patient_value": 13.5})
    assert mem.history("s1")[0]["metadata"]["patient_value"] == "<redacted>"


def test_set_audit_replaces_process_sink():
    previous = get_audit()
    sink = MemoryAudit()
    set_audit(sink)
    try:
        get_audit().record("x", {})
        assert sink.events
    finally:
        set_audit(previous)


def test_release_identity_is_computed_without_a_build(tmp_path, monkeypatch):
    """Without dist/release the bundle hash is computed from ontology/ sources."""
    monkeypatch.setenv("ONTOGATE_RELEASE_DIR", str(tmp_path / "none"))
    current_release.cache_clear()
    rel = current_release()
    assert rel["source"] == "computed" and len(rel["bundle_sha256"]) == 64


def test_release_pin_mismatch_fails_closed(tmp_path, monkeypatch):
    """A runtime pinned to a different bundle refuses to start."""
    monkeypatch.setenv("ONTOGATE_RELEASE_DIR", str(tmp_path / "none"))
    with pytest.raises(ReleaseVerificationError):
        verify_release(expected_bundle_sha256="0" * 64)
    current_release.cache_clear()


def test_tree_hash_is_deterministic(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "c.txt").write_text("2")
    assert sha256_tree(tmp_path) == sha256_tree(tmp_path)
