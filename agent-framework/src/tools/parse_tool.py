"""
Clinician Input Parser — plain Python function for MAF binding.
Parses raw clinician input and returns structured fields with an A2A message.
No framework decorator — bound to agents via YAML 'bindings: {function: parse_clinician_input}'.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole


def parse_clinician_input(
    raw_text: str = "",
    text: str = "",
    query: str = "",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Parse a clinician's raw query into structured fields.

    Supports formats: 'Hb', 'Hb 13.5', 'Hb 13.5 | g/dL', 'Calcium 4.8 | total'.

    Args:
        raw_text: Raw clinician query string.
        text: Alternative input key (A2A / ADK convention).
        query: Alternative input key (MCP convention).

    Returns:
        dict with keys: term, unit, qualifier, patient_value, raw_text, a2a_triage_message.
    """
    # Resolve the actual raw string from whichever key was populated.
    raw = raw_text or text or query or kwargs.get("input", "") or ""
    parts = [p.strip() for p in raw.split("|") if p.strip()]
    left_str = parts[0] if parts else ""

    qualifier, unit = "", ""
    for part in parts[1:]:
        if part.lower() in ("total", "tca", "ionized", "ica", "free", "i", "t"):
            qualifier = part.lower()
        else:
            unit = part

    # Support negative values: a '-' immediately preceded by whitespace (or start)
    # is treated as a sign, not a separator.
    val_match = re.search(r"(?:^|(?<=\s))(-?\d+(?:\.\d+)?)(?![\w-])", left_str)
    patient_value = float(val_match.group(1)) if val_match else None
    term = re.sub(r"(?:^|(?<=\s))-?\d+(?:\.\d+)?(?![\w-])", "", left_str).strip() or left_str

    a2a_msg = A2AMessage(
        sender=AgentRole.TRIAGE,
        recipient=AgentRole.ONTOLOGY_RESOLVER,
        action=A2AAction.PARSE_REQUEST,
        payload={
            # Bug fix: use `raw` (the resolved value) not `raw_text` (the parameter,
            # which is empty when input arrives via text= or query=).
            "raw_text": raw,
            "term": term,
            "unit": unit,
            "qualifier": qualifier,
            "patient_value": patient_value,
        },
    )

    return {
        "term": term,
        "unit": unit,
        "qualifier": qualifier,
        "patient_value": patient_value,
        "raw_text": raw,  # Bug fix: was `raw_text` (empty when using text= / query=)
        "a2a_triage_message": a2a_msg.model_dump(mode="json"),
    }
