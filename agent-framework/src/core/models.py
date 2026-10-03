"""
src/core/models.py shim for agent-framework.
Loads all core model classes directly from google-adk-agents/src/core/models.py
via importlib.util, bypassing the 'src' namespace collision.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_adk_models = (
    Path(__file__).resolve().parent.parent.parent.parent  # repo root
    / "google-adk-agents" / "src" / "core" / "models.py"
)

if not _adk_models.exists():
    raise RuntimeError(f"ADK models.py not found at: {_adk_models}")

_spec = importlib.util.spec_from_file_location("_adk_core_models", _adk_models)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Re-export all public symbols from the ADK models module
ResolutionStatus     = _mod.ResolutionStatus
EvaluationContext    = _mod.EvaluationContext
GapEvaluationResult  = _mod.GapEvaluationResult
ConceptDefinition    = _mod.ConceptDefinition
CollisionFamily      = _mod.CollisionFamily
NumericAssay         = _mod.NumericAssay
PanelDefinition      = _mod.PanelDefinition
ProtocolDefinition   = _mod.ProtocolDefinition
SpecimenTubeRule     = _mod.SpecimenTubeRule

# Alias for backward compat with Strands-style imports
EvaluationResult = GapEvaluationResult

__all__ = [
    "ResolutionStatus", "EvaluationContext", "GapEvaluationResult",
    "EvaluationResult", "ConceptDefinition", "CollisionFamily",
    "NumericAssay", "PanelDefinition", "ProtocolDefinition", "SpecimenTubeRule",
]
