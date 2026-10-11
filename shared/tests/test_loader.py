"""
Pack loading: strict schema, relation kinds, overlays and lifecycle.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from ontogate.config import OntologyRegistry, apply_pack, get_default_registry, load_domain_config
from ontogate.resolver import resolve
from ontogate.tools import resolve_lab_term


def _write_pack(tmp_path, observables):
    (tmp_path / "domain.yaml").write_text(yaml.safe_dump({"id": "t", "files": ["observables.yaml"]}))
    (tmp_path / "observables.yaml").write_text(yaml.safe_dump({"observables": observables}))
    return tmp_path


def test_unknown_field_is_rejected(tmp_path):
    """A typo in a domain pack fails the load instead of silently becoming empty."""
    _write_pack(tmp_path, {"t:1": {"label": "X", "alt_lables": ["x"]}})
    with pytest.raises(Exception, match="alt_lables"):
        load_domain_config(tmp_path)


def test_unknown_link_kind_is_rejected(tmp_path):
    """An unknown relation kind is an error, never coerced to a different relation."""
    _write_pack(tmp_path, {"t:1": {"label": "X", "links": [{"target_uri": "t:2", "kind": "looks_like"}]}})
    with pytest.raises(ValueError, match="Unknown link kind 'looks_like'"):
        load_domain_config(tmp_path)


def test_directory_without_manifest_is_rejected(tmp_path):
    """A directory is a domain pack only if it has a domain.yaml manifest."""
    with pytest.raises(FileNotFoundError):
        load_domain_config(tmp_path)


def test_overlay_cannot_silently_redefine_base_observable():
    """An overlay that changes a base observable must declare `overrides:`."""
    reg = copy.deepcopy(get_default_registry())
    overlay = {"observables": {"loinc:718-7": {"label": "Something else", "department": "dept:hematology"}}}
    with pytest.raises(ValueError, match="without declaring it under 'overrides:'"):
        apply_pack(reg, overlay, overlay=True)
    overlay["overrides"] = ["loinc:718-7"]
    apply_pack(reg, overlay, overlay=True)
    assert reg.concepts["loinc:718-7"].label == "Something else"


def test_facet_assignment_is_additive_and_guarded():
    """facet_assignments may add a facet value but not silently change one."""
    reg = copy.deepcopy(get_default_registry())
    reg.facets["form"] = reg.facets["fraction"].model_copy(update={"id": "form", "values": ["a", "b"]})
    apply_pack(reg, {"facet_assignments": {"loinc:2880-3": {"form": "a"}}}, overlay=True)
    assert reg.concepts["loinc:2880-3"].facets["form"] == "a"
    with pytest.raises(ValueError, match="without declaring it under 'overrides:'"):
        apply_pack(reg, {"facet_assignments": {"loinc:2880-3": {"form": "b"}}}, overlay=True)


def test_deprecated_observable_redirects_to_successor():
    """A deprecated observable is never a candidate; superseded_by redirects with a notice."""
    reg = OntologyRegistry()
    apply_pack(reg, {
        "departments": {"dept:x": {"label": "X"}},
        "observables": {
            "t:old": {"label": "Old test", "department": "dept:x", "status": "deprecated", "superseded_by": "t:new"},
            "t:new": {"label": "New test", "department": "dept:x"},
        },
        "designations": {"former name": {"denotes": ["t:old"], "kind": "synonym"}},
    })
    res = resolve(reg, "former name")
    assert [c.uri for c in res.candidates] == ["t:new"]
    assert res.redirected_from == ["t:old"]
    out = resolve_lab_term("former name", registry=reg)
    assert out["status"] == "RESOLVED" and out["superseded"] == ["t:old"]


def test_intervals_carry_honest_provenance():
    """Machine-generated demonstration intervals are unverified and flagged clinically unvalidated."""
    for interval in get_default_registry().intervals:
        assert interval.verified_by is None
        assert interval.clinically_unvalidated is True
        assert interval.trust_tier.value == "unverified"


def test_protocols_are_graph_nodes():
    """Each protocol has its own id, governs exactly one observable, and is reached via governed_by."""
    reg = get_default_registry()
    for node_id, protocol in reg.protocol_nodes.items():
        assert node_id.startswith("protocol:")
        assert reg.concepts[protocol.governs].governed_by == node_id
