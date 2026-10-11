"""
Skill stores: content-addressed publish / materialise, fail-closed hash checks,
and the GCS / S3 / Azure Blob transports (exercised with in-memory fakes).
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from ontogate import cloud_stores
from ontogate.cloud_stores import (
    AzureBlobSkillStore,
    DirectorySkillStore,
    GcsSkillStore,
    S3SkillStore,
    SkillStoreError,
    archive_key,
    store_from_url,
)
from ontogate.paths import repo_root
from ontogate.skills import build_skills, load_lock, package_skill, skills_for_role


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Archives built from the committed skills into a temporary dist directory."""
    import shutil
    tmp = tmp_path_factory.mktemp("skills-build")
    shutil.copytree(repo_root() / "skills", tmp / "skills")
    lock = build_skills(tmp / "skills", dist_dir=tmp / "dist")
    return lock, tmp / "dist"


def test_archive_keys_are_content_addressed():
    assert archive_key("skills", "clinical-triage", "ab" * 32) == f"skills/clinical-triage/{'ab' * 32}.zip"
    assert archive_key("", "x", "cd") == "x/cd.zip"


def test_publish_is_idempotent_and_materialise_verifies(built, tmp_path):
    lock, dist = built
    store = DirectorySkillStore(tmp_path / "store", prefix="skills", cache_dir=tmp_path / "cache")
    assert len(store.publish(lock, dist)) == len(lock["skills"])
    assert store.publish(lock, dist) == []
    paths = store.materialise(lock, tmp_path / "out")
    assert sorted(p.name for p in paths) == sorted(lock["skills"])
    assert (tmp_path / "out" / "clinical-triage" / "SKILL.md").is_file()


def test_tampered_archive_fails_closed(built, tmp_path):
    lock, dist = built
    store = DirectorySkillStore(tmp_path / "store", cache_dir=tmp_path / "cache")
    store.publish(lock, dist)
    digest = lock["skills"]["clinical-triage"]["archive_sha256"]
    target = tmp_path / "store" / archive_key("", "clinical-triage", digest)
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises(SkillStoreError, match="archive hash mismatch"):
        store.materialise(lock, tmp_path / "out")


def test_content_hash_is_checked_after_extraction(built, tmp_path):
    lock, dist = built
    store = DirectorySkillStore(tmp_path / "store", cache_dir=tmp_path / "cache")
    store.publish(lock, dist)
    bad = json.loads(json.dumps(lock))
    bad["skills"]["clinical-triage"]["sha256"] = "0" * 64
    with pytest.raises(SkillStoreError, match="content hash mismatch"):
        store.materialise(bad, tmp_path / "out")


def test_missing_archive_fails_closed(built, tmp_path):
    lock, _ = built
    with pytest.raises(SkillStoreError, match="Could not fetch"):
        DirectorySkillStore(tmp_path / "empty", cache_dir=tmp_path / "cache").materialise(lock, tmp_path / "out")


def test_unsafe_archive_paths_are_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.md", "x")
    archive = tmp_path / "evil.zip"
    archive.write_bytes(buf.getvalue())
    with pytest.raises(SkillStoreError, match="unsafe member"):
        cloud_stores._safe_extract(archive, tmp_path / "out")


def test_publish_refuses_archives_that_do_not_match_the_lock(built, tmp_path):
    lock, dist = built
    stale = tmp_path / "dist"
    stale.mkdir()
    for p in dist.glob("*.zip"):
        (stale / p.name).write_bytes(p.read_bytes() + b"x")
    with pytest.raises(SkillStoreError, match="does not match the lock"):
        DirectorySkillStore(tmp_path / "store").publish(lock, stale)


@pytest.mark.parametrize("url,cls,attrs", [
    ("gs://bucket/skills", GcsSkillStore, {"bucket_name": "bucket", "prefix": "skills"}),
    ("s3://bucket/a/b", S3SkillStore, {"bucket": "bucket", "prefix": "a/b"}),
    ("azblob://acct/cont/skills", AzureBlobSkillStore, {"account": "acct", "container": "cont", "prefix": "skills"}),
])
def test_store_from_url(url, cls, attrs):
    store = store_from_url(url)
    assert isinstance(store, cls)
    for k, v in attrs.items():
        assert getattr(store, k) == v


def test_store_from_url_rejects_unknown_scheme():
    with pytest.raises(ValueError):
        store_from_url("ftp://host/skills")


# --------------------------------------------------------------------------- fake cloud clients
class _Blob:
    def __init__(self, data, key):
        self.data, self.key = data, key

    def download_to_filename(self, path):
        Path(path).write_bytes(self.data[self.key])

    def upload_from_filename(self, path, if_generation_match=None):
        assert if_generation_match == 0 and self.key not in self.data
        self.data[self.key] = Path(path).read_bytes()

    def exists(self):
        return self.key in self.data


class FakeGcs:
    def __init__(self):
        self.data = {}

    def bucket(self, name):
        return self

    def blob(self, key):
        return _Blob(self.data, key)


class FakeS3:
    def __init__(self):
        self.data = {}

    def download_file(self, bucket, key, path):
        Path(path).write_bytes(self.data[(bucket, key)])

    def upload_file(self, path, bucket, key):
        self.data[(bucket, key)] = Path(path).read_bytes()

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.data:
            raise KeyError(Key)


class FakeContainer:
    def __init__(self):
        self.data = {}

    def download_blob(self, key):
        data = self.data[key]

        class _Stream:
            def readinto(self, fh):
                fh.write(data)
        return _Stream()

    def upload_blob(self, key, fh, overwrite=False):
        assert not overwrite and key not in self.data
        self.data[key] = fh.read()

    def get_blob_client(self, key):
        return type("C", (), {"exists": lambda _self: key in self.data})()


@pytest.mark.parametrize("make", [
    lambda tmp: GcsSkillStore("b", "skills", tmp / "cache", client=FakeGcs()),
    lambda tmp: S3SkillStore("b", "skills", tmp / "cache", client=FakeS3()),
    lambda tmp: AzureBlobSkillStore("a", "c", "skills", tmp / "cache", client=FakeContainer()),
])
def test_cloud_transports_roundtrip(built, tmp_path, make):
    lock, dist = built
    store = make(tmp_path)
    assert len(store.publish(lock, dist)) == len(lock["skills"])
    assert store.publish(lock, dist) == []
    assert len(store.materialise(lock, tmp_path / "out")) == len(lock["skills"])


def test_runtime_loads_role_skills_from_the_configured_store(built, tmp_path, monkeypatch):
    """ONTOGATE_SKILL_STORE: skills_for_role resolves to verified, materialised directories."""
    lock, dist = built
    DirectorySkillStore(tmp_path / "store", prefix="skills").publish(load_lock(), dist)
    monkeypatch.setenv("ONTOGATE_SKILL_STORE", str(tmp_path / "store" / "skills"))
    monkeypatch.setenv("ONTOGATE_SKILLS_DIR", str(tmp_path / "materialised"))
    cloud_stores.materialised_base.cache_clear()
    try:
        paths = skills_for_role("triage_orchestrator")
    finally:
        cloud_stores.materialised_base.cache_clear()
    assert paths == [tmp_path / "materialised" / "clinical-triage"]
    assert package_skill(paths[0]) == package_skill(repo_root() / "skills" / "runtime" / "clinical-triage")
