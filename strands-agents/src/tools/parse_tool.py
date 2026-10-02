"""
Clinician Input Parser Tool using Strands Agents SDK.
Parses raw clinician input and emits structured parameters with an A2A message.
"""
import re
from typing import Any, Dict, Optional
from strands import tool
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole


@tool
def parse_clinician_input(raw_text: str) -> Dict[str, Any]:
    """Parse a clinician's raw query into structured fields.

    Supports: 'Hb', 'Hb | g/dL', 'Hb 13.5 | g/dL', 'Calcium 4.8 | total'.

    Args:
        raw_text: Raw clinician query string.

    Returns:
        dict with keys: term, unit, qualifier, patient_value, raw_text, a2a_triage_message.
    """
    left, _, right = raw_text.partition("|")
    left_str, right_str = left.strip(), right.strip()

    qualifier, unit = "", ""
    if right_str.lower() in ("total", "tca", "ionized", "ica", "free", "i", "t"):
        qualifier = right_str.lower()
    else:
        unit = right_str

    val_match = re.search(r"\b(\d+(?:\.\d+)?)\b", left_str)
    patient_value = float(val_match.group(1)) if val_match else None
    term = re.sub(r"\b\d+(?:\.\d+)?\b", "", left_str).strip() or left_str

    a2a_msg = A2AMessage(
        sender=AgentRole.TRIAGE,
        recipient=AgentRole.ONTOLOGY_RESOLVER,
        action=A2AAction.PARSE_REQUEST,
        payload={
            "raw_text": raw_text,
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
        "raw_text": raw_text,
        "a2a_triage_message": a2a_msg.model_dump(mode="json"),
    }
