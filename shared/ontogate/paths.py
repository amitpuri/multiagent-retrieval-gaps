"""
Filesystem discovery for the knowledge artifacts ontogate consumes.

Runtimes find the ontology, scenarios, skills and model catalog the same way
whether they run from a checkout, a test session, or a container image:

1. An explicit environment variable (``ONTOGATE_REPO_ROOT``).
2. The nearest ancestor of the current working directory that looks like a repo root.
3. The nearest ancestor of this package that looks like a repo root.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

# A directory is treated as the repo / app root when it holds any of these.
_ROOT_MARKERS = ("ontology", "config")


def _candidates() -> Iterable[Path]:
    env = os.environ.get("ONTOGATE_REPO_ROOT")
    if env:
        yield Path(env)
    cwd = Path.cwd().resolve()
    yield cwd
    yield from cwd.parents
    here = Path(__file__).resolve()
    yield from here.parents


def _looks_like_root(path: Path) -> bool:
    return any((path / marker).is_dir() for marker in _ROOT_MARKERS)


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Return the directory holding ``ontology/`` and/or ``config/``."""
    for cand in _candidates():
        if _looks_like_root(cand):
            return cand
    return Path.cwd().resolve()


def ontology_dir() -> Path:
    """Return the ``ontology/`` directory (core + domain packs)."""
    return repo_root() / "ontology"


def domain_dir(domain: str = "laboratory_medicine") -> Path:
    """Return a domain pack directory (``ontology/domains/<domain>``)."""
    env = os.environ.get("ONTOGATE_DOMAIN_DIR")
    if env:
        return Path(env)
    return ontology_dir() / "domains" / domain


def scenarios_dir() -> Path:
    """Return the scenario (competency question + overlay) directory."""
    return repo_root() / "config" / "scenarios"


def config_file(name: str) -> Path:
    """Return a file under ``config/`` (e.g. ``models.yaml``)."""
    return repo_root() / "config" / name


def first_existing(*paths: Optional[Path]) -> Optional[Path]:
    """Return the first path that exists, or None."""
    for p in paths:
        if p is not None and p.exists():
            return p
    return None
