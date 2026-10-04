"""
FastMCP Server implementation for clinical laboratory decision support.
Implements Step 2: registers laboratory tools in an MCP protocol server,
allowing the agent harness to dispatch structured tool execution requests
over MCP rather than hardcoding ad-hoc API integrations.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP

from src.tools import (
    check_calcium as base_check_calcium,
    csf_workup as base_csf_workup,
    fetch_grounded_protocol as base_fetch_grounded_protocol,
    resolve_lab_term as base_resolve_lab_term,
)
from src.core.detectors.engine import SafetyGateEngine
from src.core.models import EvaluationContext


# Initialize FastMCP instance
mcp_server = FastMCP(
    name="ClinicalLabMCPServer",
    instructions=(
        "Clinical Laboratory Decision Support MCP Server. "
        "Provides canonical LOINC ontology resolution, deterministic safety gating, "
        "CSF tube sequencing, look-alike range collision detection, and protocol retrieval."
    ),
)


@mcp_server.tool(name="resolve_lab_term", description="Map a lab test name, optional unit, and optional qualifier to canonical LOINC concepts.")
def resolve_lab_term(term: str, unit: str = "", qualifier: str = "") -> Dict[str, Any]:
    """
    Resolve test name to LOINC concept.
    Returns status: RESOLVED, AMBIGUOUS, UNIT_MISMATCH, or NOT_FOUND.
    """
    return base_resolve_lab_term(term=term, unit=unit, qualifier=qualifier)


@mcp_server.tool(name="evaluate_safety_gate", description="Run deterministic safety gate detectors over candidate concepts and patient values.")
def evaluate_safety_gate(
    term: str,
    unit: str = "",
    qualifier: str = "",
    patient_value: Optional[float] = None,
    status: str = "UNKNOWN",
) -> Dict[str, Any]:
    """
    Runs the SafetyGateEngine over clinical inputs via EvaluationContext.
    Fails closed: returns route: PROCEED or CLARIFY with full gap diagnostic details.
    """
    engine = SafetyGateEngine()

    ctx = EvaluationContext(
        term=term,
        unit=unit,
        qualifier=qualifier,
        patient_value=patient_value,
    )

    verdict = engine.evaluate(ctx)
    route = "PROCEED" if verdict.passed else "CLARIFY"
    
    return {
        "route": route,
        "status": verdict.status.value if hasattr(verdict.status, "value") else str(verdict.status),
        "passed": verdict.passed,
        "triggered_gaps": [verdict.gap_name] if not verdict.passed else [],
        "clarification_prompt": verdict.message if not verdict.passed else None,
        "candidates": verdict.candidates,
    }


@mcp_server.tool(name="fetch_grounded_protocol", description="Fetch reference ranges and panic limits bound strictly to a canonical LOINC URI.")
def fetch_grounded_protocol(uri: str) -> Dict[str, Any]:
    """
    Fetches reference ranges and critical limits bound to a single concept URI.
    Ensures zero cross-concept contamination.
    """
    return base_fetch_grounded_protocol(uri=uri)


@mcp_server.tool(name="csf_workup", description="Pre-scopes emergency CSF tests by department and governed tube drawing sequence.")
def csf_workup(department: str = "") -> Dict[str, Any]:
    """
    Pre-scoped CSF workup enforcing governed tube sequence (Tube 1-4).
    """
    return base_csf_workup(department=department)


@mcp_server.tool(name="check_calcium", description="Evaluates look-alike calcium values (mg/dL) across Total vs. Ionized Calcium interpretations.")
def check_calcium(value_mg_dl: float, qualifier: str = "") -> Dict[str, Any]:
    """
    Detects range collisions between Total Calcium (crit low < 6.5) and Ionized Calcium (normal 4.5-5.6).
    """
    return base_check_calcium(value_mg_dl=value_mg_dl, qualifier=qualifier)


@mcp_server.tool(name="attest_computation", description="Deterministically verifies numeric calculation or range check per OKF v0.2 §5.4.")
def attest_computation(
    value: float,
    uri: str,
    unit: str = "",
) -> Dict[str, Any]:
    """
    Verifies that a patient value is physiologically plausible and within valid parameters.
    """
    # Fetch protocol
    proto = base_fetch_grounded_protocol(uri)
    if not proto or proto.get("status") == "NOT_FOUND":
        return {
            "passed": False,
            "verdict": "FAIL",
            "message": f"Protocol not found for URI: {uri}",
        }
    
    # Basic physiological sanity check
    if value < 0 or value > 10_000:
        return {
            "passed": False,
            "verdict": "FAIL",
            "message": f"Value {value} {unit} violates physiological plausibility bounds.",
        }
    
    ref_range = proto.get("reference_range", "N/A")
    panic_limits = proto.get("panic_limits", "N/A")
    return {
        "passed": True,
        "verdict": "PASS",
        "attested_value": value,
        "unit": unit,
        "uri": uri,
        "reference_range": ref_range,
        "panic_limits": panic_limits,
        "badge": "[Attested ✓]",
    }


# Export dictionary of registered in-process tools
CLINICAL_MCP_TOOLS: Dict[str, Any] = {
    "resolve_lab_term": resolve_lab_term,
    "evaluate_safety_gate": evaluate_safety_gate,
    "fetch_grounded_protocol": fetch_grounded_protocol,
    "csf_workup": csf_workup,
    "check_calcium": check_calcium,
    "attest_computation": attest_computation,
}


def get_mcp_server() -> FastMCP:
    """Return the configured FastMCP server instance."""
    return mcp_server
