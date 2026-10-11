"""
Knowledge release identity: which ontology bundle, skills lock and
model catalog a runtime is serving, and fail-closed verification of them.

A built release lives in ``dist/release/manifest.json`` (``ontogate build``).
Without one (development checkout), the identity is computed from the source
trees so audit records still name an exact knowledge version.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from ontogate.paths import config_file, ontology_dir, repo_root
from ontogate.ports import sha256_content, sha256_file, sha256_tree


class ReleaseVerificationError(RuntimeError):
    """Raised when the served knowledge does not match the pinned release (fail closed)."""


def release_dir() -> Path:
    env = os.environ.get("ONTOGATE_RELEASE_DIR")
    return Path(env) if env else repo_root() / "dist" / "release"


def load_manifest(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = path or (release_dir() / "manifest.json")
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def current_release() -> Dict[str, Any]:
    """Identity of the knowledge being served (built manifest, else computed from sources)."""
    manifest = load_manifest()
    if manifest:
        return {
            "version": manifest.get("version"),
            "bundle_sha256": manifest.get("bundle_sha256"),
            "skills_lock_sha256": manifest.get("skills_lock_sha256"),
            "models_sha256": manifest.get("models_sha256"),
            "source": "manifest",
        }
    lock = repo_root() / "skills" / "skills.lock.json"
    models = config_file("models.yaml")
    return {
        "version": "dev",
        "bundle_sha256": sha256_tree(ontology_dir()) if ontology_dir().exists() else None,
        "skills_lock_sha256": sha256_content(lock) if lock.exists() else None,
        "models_sha256": sha256_content(models) if models.exists() else None,
        "source": "computed",
    }


def verify_release(expected_bundle_sha256: Optional[str] = None) -> Dict[str, Any]:
    """Verify the served release against a pin (``ONTOGATE_BUNDLE_SHA256``) and its own manifest.

    Raises :class:`ReleaseVerificationError` on any mismatch — runtimes call this
    at startup and refuse to serve on failure.
    """
    current_release.cache_clear()
    rel = current_release()
    pin = expected_bundle_sha256 or os.environ.get("ONTOGATE_BUNDLE_SHA256")
    if pin and rel.get("bundle_sha256") != pin:
        raise ReleaseVerificationError(
            f"Ontology bundle hash {rel.get('bundle_sha256')} does not match pinned {pin}")
    manifest = load_manifest()
    if manifest:
        root = release_dir()
        for rel_path, digest in (manifest.get("files") or {}).items():
            actual = sha256_file(root / rel_path) if (root / rel_path).exists() else None
            if actual != digest:
                raise ReleaseVerificationError(f"Release file {rel_path} hash mismatch")
    return rel


def build_release(dest: Optional[Path] = None, *, owl_rl: bool = True) -> Dict[str, Any]:
    """``ontogate build``: the knowledge release every runtime is pinned to.

    1. Integrity rules over the pack and every scenario overlay.
    2. ``ontogate skills build`` (render references, lint, role checks, lock, archives).
    3. RDF export of the ontology + agent meta-graph, SHACL validation, OWL 2 RL.
    4. ``dist/release/manifest.json`` naming the bundle, skills lock and model catalog,
       with a hash for every file copied into the release.
    """
    import shutil
    from ontogate.config import get_default_registry
    from ontogate.paths import domain_dir, scenarios_dir
    from ontogate.rdf_export import build_ontology_bundle
    from ontogate.roles import load_all_role_specs
    from ontogate.skills import build_skills, dist_skills_dir, load_skills, lock_path
    from ontogate.validate import ERROR, validate_pack

    errors = [i for i in validate_pack(domain_dir(), sorted(scenarios_dir().glob("*.yaml"))) if i.level == ERROR]
    if errors:
        raise ReleaseVerificationError("Integrity errors:\n" + "\n".join(str(i) for i in errors))
    lock = build_skills()
    root = Path(dest) if dest else release_dir()
    if root.exists():
        shutil.rmtree(root)
    bundle = build_ontology_bundle(get_default_registry(), root / "bundle", owl_rl=owl_rl,
                                   roles=load_all_role_specs(), skills=load_skills(), lock=lock)
    shutil.copytree(dist_skills_dir(), root / "skills")
    shutil.copy2(lock_path(), root / "skills.lock.json")
    shutil.copy2(config_file("models.yaml"), root / "models.yaml")
    files = {p.relative_to(root).as_posix(): sha256_file(p)
             for p in sorted(root.rglob("*")) if p.is_file()}
    manifest = {
        "version": __import__("ontogate").__version__,
        "bundle_sha256": bundle["bundle_sha256"],
        "skills_lock_sha256": sha256_content(lock_path()),
        "models_sha256": sha256_content(config_file("models.yaml")),
        "domains": bundle["domains"],
        "files": files,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    current_release.cache_clear()
    return manifest
