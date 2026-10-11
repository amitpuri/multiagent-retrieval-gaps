"""
Clinical MCP server for the ADK harness — the shared canonical server
(``ontogate.mcp_server``), so ADK, Strands and MAF expose one tool contract.
"""
from __future__ import annotations

from ontogate.mcp_server import (  # noqa: F401
    CLINICAL_MCP_TOOLS,
    attest_computation,
    build_clarification_prompt,
    evaluate_safety_gate,
    fetch_grounded_protocol,
    get_mcp_server,
    panel_workup,
    parse_clinician_input,
    resolve_lab_term,
)
