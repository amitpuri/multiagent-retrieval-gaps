"""
Clinician Input Parser Tool using Strands Agents SDK.
Thin ``@tool`` wrapper over the shared ontology-aware parser with an A2A message.
"""
from __future__ import annotations

from typing import Any, Dict
from strands import tool
from ontogate.parsing import parse_clinician_text
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole


@tool
def parse_clinician_input(raw_text: str) -> Dict[str, Any]:
    """Parse a clinician's raw query into structured fields.

    Pipe segments are classified by vocabulary (unit, facet qualifier,
    population, department): 'Hb', 'Hb | g/dL', 'Hb 13.5 | g/dL',
    'Calcium 4.8 | total | mg/dL', 'Hb 13.5 | female | g/dL'.

    Args:
        raw_text: Raw clinician query string.

    Returns:
        dict with term, unit, qualifier, patient_value, population, department,
        panel_id, raw_text and a2a_triage_message.
    """
    parsed = parse_clinician_text(raw_text)
    a2a_msg = A2AMessage(
        sender=AgentRole.TRIAGE,
        recipient=AgentRole.ONTOLOGY_RESOLVER,
        action=A2AAction.PARSE_REQUEST,
        payload={k: parsed[k] for k in ("raw_text", "term", "unit", "qualifier", "patient_value")},
    )
    return {**parsed, "status": "PARSED", "a2a_triage_message": a2a_msg.model_dump(mode="json")}
