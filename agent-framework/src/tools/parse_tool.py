"""
Clinician Input Parser — plain Python function for MAF binding.
Thin wrapper over the shared ontology-aware parser with an A2A message.
No framework decorator — bound to agents via YAML 'bindings: {function: parse_clinician_input}'.
"""
from __future__ import annotations

from typing import Any, Dict
from ontogate.parsing import parse_clinician_text
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole


def parse_clinician_input(
    raw_text: str = "",
    text: str = "",
    query: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Parse a clinician's raw query into structured fields.

    Pipe segments are classified by vocabulary (unit, facet qualifier,
    population, department): 'Hb', 'Hb 13.5', 'Hb 13.5 | g/dL',
    'Calcium 4.8 | total | mg/dL'.

    Args:
        raw_text: Raw clinician query string.
        text: Alternative input key (A2A / ADK convention).
        query: Alternative input key (MCP convention).

    Returns:
        dict with term, unit, qualifier, patient_value, population, department,
        panel_id, raw_text and a2a_triage_message.
    """
    raw = raw_text or text or query or kwargs.get("input", "") or ""
    parsed = parse_clinician_text(raw)
    a2a_msg = A2AMessage(
        sender=AgentRole.TRIAGE,
        recipient=AgentRole.ONTOLOGY_RESOLVER,
        action=A2AAction.PARSE_REQUEST,
        payload={k: parsed[k] for k in ("raw_text", "term", "unit", "qualifier", "patient_value")},
    )
    return {**parsed, "status": "PARSED", "a2a_triage_message": a2a_msg.model_dump(mode="json")}
