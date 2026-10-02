"""
Compatibility module redirecting a2a_orchestrator to strands_orchestrator.
"""
from src.orchestration.strands_orchestrator import (
    StrandsDecisionSupportOrchestrator,
    build_strands_orchestrator,
    parse_clinician_input_direct,
    parse_clinician_input,
    ParsedEvent,
)

__all__ = [
    "StrandsDecisionSupportOrchestrator",
    "build_strands_orchestrator",
    "parse_clinician_input_direct",
    "parse_clinician_input",
    "ParsedEvent",
]
