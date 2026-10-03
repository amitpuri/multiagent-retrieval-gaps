"""
src/core/__init__.py — central shim that wires agent-framework to the
shared ADK core (models, config, detectors) using importlib.util.

Strategy: load each ADK file directly and register them in sys.modules
under their canonical 'src.core.*' names BEFORE any cross-imports run.
This avoids the 'src' namespace collision between agent-framework and
google-adk-agents (both use 'src.*' as their package root).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent.parent  # repo root
_adk_src   = _repo_root / "google-adk-agents" / "src"

if not _adk_src.exists():
    raise RuntimeError(
        f"google-adk-agents/src not found at: {_adk_src}. "
        "Clone the full multiagent-retrieval-gaps repository."
    )


def _load_and_register(logical_name: str, file_path: Path):
    """Load a module from file_path and register it in sys.modules as logical_name."""
    if logical_name in sys.modules:
        return sys.modules[logical_name]
    spec = importlib.util.spec_from_file_location(logical_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[logical_name] = mod          # register BEFORE exec to handle circular refs
    spec.loader.exec_module(mod)
    return mod


# ── Load in dependency order ────────────────────────────────────────────────
# 1. models (no internal deps)
_models = _load_and_register(
    "src.core.models",
    _adk_src / "core" / "models.py",
)

# 2. config (depends on src.core.models)
_config = _load_and_register(
    "src.core.config",
    _adk_src / "core" / "config.py",
)

# 3. detectors sub-package
_det_init = _load_and_register(
    "src.core.detectors",
    _adk_src / "core" / "detectors" / "__init__.py",
)
for _det_file in (_adk_src / "core" / "detectors").glob("*.py"):
    if _det_file.name == "__init__.py":
        continue
    _stem = _det_file.stem
    _load_and_register(f"src.core.detectors.{_stem}", _det_file)

# ── Public re-exports ────────────────────────────────────────────────────────
from src.core.models import (  # noqa: F401, E402
    ResolutionStatus,
    EvaluationContext,
    GapEvaluationResult,
    ConceptDefinition,
    CollisionFamily,
    NumericAssay,
    PanelDefinition,
    ProtocolDefinition,
    SpecimenTubeRule,
)

from src.core.config import (  # noqa: F401, E402
    get_default_registry,
    load_scenario_extension,
    OntologyRegistry,
)

# Alias used in some tools
EvaluationResult = GapEvaluationResult
