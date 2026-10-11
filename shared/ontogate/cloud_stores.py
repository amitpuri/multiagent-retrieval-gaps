"""
Skill stores per cloud, behind :class:`~ontogate.ports.SkillStorePort`.

Skill archives are content-addressed: ``<prefix>/<name>/<archive_sha256>.zip``.
A published archive is therefore immutable and every release pins exactly the
archives its ``skills.lock.json`` names. Materialising a lock fails closed
twice over — the archive hash must match before extraction, and the extracted
tree hash must match after — so a runtime only ever loads the skills that
were linted and locked in CI.

    ontogate skills publish gs://bucket/skills            # Google Cloud Storage
    ontogate skills publish s3://bucket/skills            # Amazon S3
    ontogate skills publish azblob://account/container/skills   # Azure Blob Storage
    ontogate skills publish /path/to/dir                  # local / image-baked

A runtime sets ``ONTOGATE_SKILL_STORE`` to one of those URLs to load skills
from the store at startup; without it, skills load from the image tree.
Cloud SDKs are imported only by the store that needs them.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from ontogate.ports import sha256_file, sha256_tree


class SkillStoreError(RuntimeError):
    """A locked skill could not be fetched or did not match its hash (fail closed)."""


def archive_key(prefix: str, name: str, archive_sha256: str) -> str:
    return str(PurePosixPath(prefix.strip("/")) / name / f"{archive_sha256}.zip") if prefix.strip("/") \
        else f"{name}/{archive_sha256}.zip"


def _safe_extract(archive: Path, target: Path) -> None:
    """Extract a skill archive, refusing absolute paths and parent traversal."""
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            parts = PurePosixPath(member).parts
            if member.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
                raise SkillStoreError(f"{archive.name}: unsafe member path '{member}'")
        zf.extractall(target)


class ArchiveSkillStore:
    """Materialises locked skills from content-addressed archives (subclasses fetch them)."""

    scheme = "file"

    def __init__(self, prefix: str = "", cache_dir: Optional[Path] = None) -> None:
        self.prefix = prefix
        self.cache_dir = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "ontogate-skill-cache"

    # Subclasses implement transport only.
    def _download(self, key: str, dest: Path) -> None:
        raise NotImplementedError

    def _upload(self, key: str, source: Path) -> None:
        raise NotImplementedError

    def _exists(self, key: str) -> bool:
        raise NotImplementedError

    def materialise(self, lock: Dict[str, Any], dest: Path) -> List[Path]:
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        paths: List[Path] = []
        for name, meta in sorted(lock.get("skills", {}).items()):
            digest = meta.get("archive_sha256")
            if not digest:
                raise SkillStoreError(f"Lock entry '{name}' has no archive_sha256")
            cached = self.cache_dir / f"{name}-{digest}.zip"
            if not cached.exists():
                partial = cached.with_suffix(".part")
                try:
                    self._download(archive_key(self.prefix, name, digest), partial)
                except SkillStoreError:
                    raise
                except Exception as exc:
                    raise SkillStoreError(f"Could not fetch skill '{name}' from {self.describe()}: {exc}") from exc
                partial.replace(cached)
            actual = sha256_file(cached)
            if actual != digest:
                cached.unlink(missing_ok=True)
                raise SkillStoreError(f"Skill '{name}' archive hash mismatch: locked {digest}, fetched {actual}")
            target = dest / name
            if target.exists():
                shutil.rmtree(target)
            _safe_extract(cached, target)
            tree = sha256_tree(target)
            if tree != meta.get("sha256"):
                shutil.rmtree(target, ignore_errors=True)
                raise SkillStoreError(f"Skill '{name}' content hash mismatch after extraction")
            paths.append(target)
        return paths

    def publish(self, lock: Dict[str, Any], archives_dir: Path) -> List[str]:
        """Upload each locked archive that is not already in the store. Returns uploaded keys."""
        uploaded = []
        for name, meta in sorted(lock.get("skills", {}).items()):
            source = Path(archives_dir) / f"{name}.zip"
            if not source.is_file() or sha256_file(source) != meta["archive_sha256"]:
                raise SkillStoreError(f"{source} is missing or does not match the lock (run `ontogate skills build`)")
            key = archive_key(self.prefix, name, meta["archive_sha256"])
            if not self._exists(key):
                self._upload(key, source)
                uploaded.append(key)
        return uploaded

    def describe(self) -> str:
        return f"{self.scheme}://{self.prefix}"


class DirectorySkillStore(ArchiveSkillStore):
    """A local directory (a mounted volume, or archives baked into the image)."""

    def __init__(self, root: Path, prefix: str = "", cache_dir: Optional[Path] = None) -> None:
        super().__init__(prefix, cache_dir)
        self.root = Path(root)

    def _download(self, key: str, dest: Path) -> None:
        shutil.copyfile(self.root / key, dest)

    def _upload(self, key: str, source: Path) -> None:
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def _exists(self, key: str) -> bool:
        return (self.root / key).is_file()

    def describe(self) -> str:
        return str(self.root / self.prefix)


class GcsSkillStore(ArchiveSkillStore):
    """Google Cloud Storage (``gs://bucket/prefix``); the runtime service account needs read access only."""

    scheme = "gs"

    def __init__(self, bucket: str, prefix: str = "skills", cache_dir: Optional[Path] = None, client: Any = None):
        super().__init__(prefix, cache_dir)
        self.bucket_name = bucket
        self._client = client

    def _bucket(self):
        if self._client is None:
            from google.cloud import storage  # google-cloud-storage
            self._client = storage.Client()
        return self._client.bucket(self.bucket_name)

    def _download(self, key: str, dest: Path) -> None:
        self._bucket().blob(key).download_to_filename(str(dest))

    def _upload(self, key: str, source: Path) -> None:
        self._bucket().blob(key).upload_from_filename(str(source), if_generation_match=0)

    def _exists(self, key: str) -> bool:
        return self._bucket().blob(key).exists()

    def describe(self) -> str:
        return f"gs://{self.bucket_name}/{self.prefix}"


class S3SkillStore(ArchiveSkillStore):
    """Amazon S3 (``s3://bucket/prefix``); the AgentCore execution role needs s3:GetObject only."""

    scheme = "s3"

    def __init__(self, bucket: str, prefix: str = "skills", cache_dir: Optional[Path] = None, client: Any = None):
        super().__init__(prefix, cache_dir)
        self.bucket = bucket
        self._client = client

    def _s3(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("s3")
        return self._client

    def _download(self, key: str, dest: Path) -> None:
        self._s3().download_file(self.bucket, key, str(dest))

    def _upload(self, key: str, source: Path) -> None:
        self._s3().upload_file(str(source), self.bucket, key)

    def _exists(self, key: str) -> bool:
        try:
            self._s3().head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def describe(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"


class AzureBlobSkillStore(ArchiveSkillStore):
    """Azure Blob Storage (``azblob://account/container/prefix``), Entra ID auth via DefaultAzureCredential."""

    scheme = "azblob"

    def __init__(self, account: str, container: str, prefix: str = "skills",
                 cache_dir: Optional[Path] = None, client: Any = None):
        super().__init__(prefix, cache_dir)
        self.account, self.container = account, container
        self._client = client

    def _container(self):
        if self._client is None:
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import BlobServiceClient
            service = BlobServiceClient(f"https://{self.account}.blob.core.windows.net",
                                        credential=DefaultAzureCredential())
            self._client = service.get_container_client(self.container)
        return self._client

    def _download(self, key: str, dest: Path) -> None:
        with open(dest, "wb") as fh:
            self._container().download_blob(key).readinto(fh)

    def _upload(self, key: str, source: Path) -> None:
        with open(source, "rb") as fh:
            self._container().upload_blob(key, fh, overwrite=False)

    def _exists(self, key: str) -> bool:
        return self._container().get_blob_client(key).exists()

    def describe(self) -> str:
        return f"azblob://{self.account}/{self.container}/{self.prefix}"


def store_from_url(url: str, cache_dir: Optional[Path] = None) -> ArchiveSkillStore:
    """Build a store from ``gs://``, ``s3://``, ``azblob://`` or a local path."""
    for scheme, cls in (("gs://", GcsSkillStore), ("s3://", S3SkillStore)):
        if url.startswith(scheme):
            bucket, _, prefix = url[len(scheme):].partition("/")
            return cls(bucket, prefix, cache_dir)
    if url.startswith("azblob://"):
        parts = url[len("azblob://"):].split("/", 2)
        if len(parts) < 2:
            raise ValueError("azblob URL must be azblob://<account>/<container>[/<prefix>]")
        return AzureBlobSkillStore(parts[0], parts[1], parts[2] if len(parts) > 2 else "", cache_dir)
    if "://" in url:
        raise ValueError(f"Unsupported skill store URL '{url}'")
    return DirectorySkillStore(Path(url), cache_dir=cache_dir)


@lru_cache(maxsize=1)
def materialised_base() -> Optional[Path]:
    """Materialise the locked skills from ``ONTOGATE_SKILL_STORE`` once per process.

    Returns the directory holding ``<name>/SKILL.md`` for every locked skill, or
    None when no store is configured (skills then load from the image tree).
    """
    url = os.environ.get("ONTOGATE_SKILL_STORE")
    if not url:
        return None
    from ontogate.skills import load_lock
    dest = Path(os.environ.get("ONTOGATE_SKILLS_DIR") or Path(tempfile.gettempdir()) / "ontogate-skills")
    store_from_url(url).materialise(load_lock(), dest)
    return dest
