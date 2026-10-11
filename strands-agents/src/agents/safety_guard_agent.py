"""
Deterministic Safety Guard Agent.
CRITICAL: Pure-code agent wrapper. NEVER calls an LLM.
Directly invokes evaluate_safety_gate to enforce fail-closed deterministic safety routing (Gap 9).
"""
from typing import Any, Dict
from src.tools.safety_gate_tool import evaluate_safety_gate


def invoke_safety_guard(context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the deterministic safety gate on the provided resolution context."""
    return evaluate_safety_gate(
        term=context.get("term", ""),
        unit=context.get("unit", ""),
        qualifier=context.get("qualifier", ""),
        patient_value=context.get("patient_value"),
        status=context.get("status", "UNKNOWN"),
    )
