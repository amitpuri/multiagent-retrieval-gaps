"""
Strands tools package for Laboratory Medicine Decision Support.
Exports both Strands @tool-decorated functions and legacy retrieval utilities.
"""
from src.tools.parse_tool import parse_clinician_input
from src.tools.ontology_tool import resolve_ontology
from src.tools.safety_gate_tool import run_safety_gate
from src.tools.protocol_tool import fetch_protocol
from src.tools.clarification_tool import build_clarification_prompt

# Re-export legacy clinical utilities for backwards compatibility
from src.tools_legacy import (
    search_lab_kb,
    resolve_lab_term,
    fetch_grounded_protocol,
    csf_workup,
    check_calcium,
    classify,
)

# Alias get_protocol to fetch_grounded_protocol
get_protocol = fetch_grounded_protocol

__all__ = [
    "parse_clinician_input",
    "resolve_ontology",
    "run_safety_gate",
    "fetch_protocol",
    "build_clarification_prompt",
    "search_lab_kb",
    "resolve_lab_term",
    "get_protocol",
    "fetch_grounded_protocol",
    "csf_workup",
    "check_calcium",
    "classify",
]
