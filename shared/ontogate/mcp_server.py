"""
Canonical clinical MCP server — the same tool contract on every framework and
every cloud (Agent Gateway, AgentCore Gateway, Foundry toolbox).

Run standalone::

    python -m ontogate.mcp_server            # stdio
    python -m ontogate.mcp_server --http 8080  # streamable HTTP

Each tool is a thin wrapper over :mod:`ontogate.tools` and returns a ``dict``
with a ``"status"`` key (agent invariant 3).
"""
from __future__ import annotations

import argparse
from typing import Any, Callable, Dict, Optional

from ontogate import tools as T

try:  # The MCP SDK is optional for library use; required to serve.
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore[assignment]

INSTRUCTIONS = (
    "Clinical laboratory decision-support tools. Resolve terms with resolve_lab_term, "
    "always call evaluate_safety_gate before interpreting a value, and fetch protocols "
    "or attest values only after the gate returns route=PROCEED."
)


def resolve_lab_term(term: str, unit: str = "", qualifier: str = "") -> Dict[str, Any]:
    """Map a lab test name, optional unit and qualifier to canonical LOINC observables."""
    return T.resolve_lab_term(term=term, unit=unit, qualifier=qualifier)


def evaluate_safety_gate(term: str, unit: str = "", qualifier: str = "",
                         patient_value: Optional[float] = None, status: str = "UNKNOWN",
                         sex: str = "", age_band: str = "", department: str = "",
                         panel_id: str = "") -> Dict[str, Any]:
    """Run the deterministic safety gate. Only route=PROCEED permits interpretation."""
    return T.evaluate_safety_gate(term=term, unit=unit, qualifier=qualifier, patient_value=patient_value,
                                  status=status, sex=sex, age_band=age_band, department=department,
                                  panel_id=panel_id)


def fetch_grounded_protocol(uri: str) -> Dict[str, Any]:
    """Fetch the protocol bound strictly to one canonical LOINC URI."""
    return T.fetch_grounded_protocol(uri=uri)


def attest_computation(value: float, uri: str, unit: str = "", sex: str = "",
                       age_band: str = "") -> Dict[str, Any]:
    """Deterministically attest a value against the protocol for a URI (OKF §5.4)."""
    return T.attest_computation(value=value, uri=uri, unit=unit, sex=sex, age_band=age_band)


def parse_clinician_input(raw_text: str) -> Dict[str, Any]:
    """Parse raw clinician text into term, value, unit, qualifier, population and panel."""
    return T.parse_clinician_input(raw_text=raw_text)


def build_clarification_prompt(status: str, candidates: Optional[list] = None,
                               details: Optional[dict] = None, message: str = "") -> Dict[str, Any]:
    """Deterministic clarification text for a non-RESOLVED gate status."""
    return T.build_clarification_prompt(status=status, candidates=candidates, details=details, message=message)


def panel_workup(panel: str = "csf_emergency_panel", department: str = "") -> Dict[str, Any]:
    """Ordered, department-scoped specimen collection steps for a panel."""
    return T.panel_workup(panel=panel, department=department)


#: Registered tools by name.
CLINICAL_MCP_TOOLS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "parse_clinician_input": parse_clinician_input,
    "resolve_lab_term": resolve_lab_term,
    "evaluate_safety_gate": evaluate_safety_gate,
    "fetch_grounded_protocol": fetch_grounded_protocol,
    "attest_computation": attest_computation,
    "build_clarification_prompt": build_clarification_prompt,
    "panel_workup": panel_workup,
}

_SERVER: Any = None


def get_mcp_server() -> Any:
    """Return the configured FastMCP server (built once)."""
    global _SERVER
    if _SERVER is None:
        if FastMCP is None:
            raise ImportError("Install the MCP SDK (`pip install ontogate[mcp]`) to serve tools.")
        server = FastMCP(name="ClinicalLabMCPServer", instructions=INSTRUCTIONS)
        for name, fn in CLINICAL_MCP_TOOLS.items():
            description = (fn.__doc__ or "").strip().splitlines()[0]
            server.tool(name=name, description=description)(fn)
        _SERVER = server
    return _SERVER


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the canonical clinical MCP tools.")
    parser.add_argument("--http", type=int, default=None, help="Serve streamable HTTP on this port.")
    args = parser.parse_args(argv)
    server = get_mcp_server()
    if args.http:
        server.settings.port = args.http
        server.settings.host = "0.0.0.0"
        server.run(transport="streamable-http")
    else:
        server.run()


if __name__ == "__main__":
    main()
