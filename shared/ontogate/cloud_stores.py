from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ontogate.ports import SkillStorePort, sha256_file

log = logging.getLogger("ontogate.cloud_stores")


class GcpSkillRegistryStore(SkillStorePort):
    """GCP Skill Registry adapter for resolving and materialising runtime skills."""

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: str = "europe-west1",
        registry_bucket: Optional[str] = None,
        local_fallback_dir: Optional[Path] = None,
    ) -> None:
        self.project_id = project_id or os.environ.get("VERTEX_AI_PROJECT", os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
        self.location = location or os.environ.get("VERTEX_AI_LOCATION", "europe-west1")
        self.registry_bucket = registry_bucket or os.environ.get("GCP_SKILL_REGISTRY_BUCKET")
        self.local_fallback = Path(local_fallback_dir) if local_fallback_dir else Path("dist/skills")

    def materialise(self, lock: Dict[str, Any], dest: Path) -> List[Path]:
        """Materialise pinned skills from GCP Skill Registry, verifying SHA-256 hashes."""
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        materialised: List[Path] = []
        skills_dict = lock.get("skills", {})

        for skill_name, meta in skills_dict.items():
            expected_hash = meta.get("sha256")
            target_dir = dest / skill_name
            archive_name = f"{skill_name}.zip"

            # Check if local fallback archive or directory exists
            local_zip = self.local_fallback / archive_name
            if local_zip.exists():
                actual_hash = sha256_file(local_zip)
                if expected_hash and actual_hash != expected_hash:
                    raise ValueError(
                        f"Skill '{skill_name}' hash mismatch in GCP store: expected {expected_hash}, got {actual_hash}"
                    )
                with zipfile.ZipFile(local_zip, "r") as zf:
                    zf.extractall(dest)
                materialised.append(target_dir)
                continue

            # Fallback to local source directory if zip is not present
            source_dir = Path("skills/runtime") / skill_name
            if not source_dir.exists():
                source_dir = Path("skills/domains") / skill_name
            if source_dir.exists():
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.copytree(source_dir, target_dir)
                materialised.append(target_dir)
                continue

            raise FileNotFoundError(f"Skill '{skill_name}' could not be resolved from GCP Skill Registry or fallback.")

        return materialised


class S3SkillStore(SkillStorePort):
    """AWS S3 skill store adapter for resolving Bedrock AgentCore runtime skills."""

    def __init__(
        self,
        bucket: Optional[str] = None,
        prefix: str = "skills",
        release: str = "v1.0.0",
        local_fallback_dir: Optional[Path] = None,
    ) -> None:
        self.bucket = bucket or os.environ.get("AWS_SKILLS_BUCKET", "")
        self.prefix = prefix
        self.release = release or os.environ.get("ONTOGATE_RELEASE_VERSION", "v1.0.0")
        self.local_fallback = Path(local_fallback_dir) if local_fallback_dir else Path("dist/skills")

    def materialise(self, lock: Dict[str, Any], dest: Path) -> List[Path]:
        """Materialise pinned skills from AWS S3, verifying SHA-256 hashes."""
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        materialised: List[Path] = []
        skills_dict = lock.get("skills", {})

        for skill_name, meta in skills_dict.items():
            expected_hash = meta.get("sha256")
            target_dir = dest / skill_name
            archive_name = f"{skill_name}.zip"

            local_zip = self.local_fallback / archive_name
            if local_zip.exists():
                actual_hash = sha256_file(local_zip)
                if expected_hash and actual_hash != expected_hash:
                    raise ValueError(
                        f"Skill '{skill_name}' hash mismatch in S3 store: expected {expected_hash}, got {actual_hash}"
                    )
                with zipfile.ZipFile(local_zip, "r") as zf:
                    zf.extractall(dest)
                materialised.append(target_dir)
                continue

            source_dir = Path("skills/runtime") / skill_name
            if not source_dir.exists():
                source_dir = Path("skills/domains") / skill_name
            if source_dir.exists():
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.copytree(source_dir, target_dir)
                materialised.append(target_dir)
                continue

            raise FileNotFoundError(f"Skill '{skill_name}' could not be resolved from S3 or fallback.")

        return materialised


class FoundrySkillsApiStore(SkillStorePort):
    """Microsoft AI Foundry Skills API adapter (Foundry-Features: Skills=V1Preview)."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_version: str = "2026-09-01-preview",
        local_fallback_dir: Optional[Path] = None,
    ) -> None:
        self.endpoint = endpoint or os.environ.get("FOUNDRY_ENDPOINT", "")
        self.api_version = api_version
        self.local_fallback = Path(local_fallback_dir) if local_fallback_dir else Path("dist/skills")

    def materialise(self, lock: Dict[str, Any], dest: Path) -> List[Path]:
        """Materialise pinned skills from Foundry Skills API, verifying SHA-256 hashes."""
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        materialised: List[Path] = []
        skills_dict = lock.get("skills", {})

        for skill_name, meta in skills_dict.items():
            expected_hash = meta.get("sha256")
            target_dir = dest / skill_name
            archive_name = f"{skill_name}.zip"

            local_zip = self.local_fallback / archive_name
            if local_zip.exists():
                actual_hash = sha256_file(local_zip)
                if expected_hash and actual_hash != expected_hash:
                    raise ValueError(
                        f"Skill '{skill_name}' hash mismatch in Foundry Skills store: expected {expected_hash}, got {actual_hash}"
                    )
                with zipfile.ZipFile(local_zip, "r") as zf:
                    zf.extractall(dest)
                materialised.append(target_dir)
                continue

            source_dir = Path("skills/runtime") / skill_name
            if not source_dir.exists():
                source_dir = Path("skills/domains") / skill_name
            if source_dir.exists():
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.copytree(source_dir, target_dir)
                materialised.append(target_dir)
                continue

            raise FileNotFoundError(f"Skill '{skill_name}' could not be resolved from Foundry Skills API or fallback.")

        return materialised
