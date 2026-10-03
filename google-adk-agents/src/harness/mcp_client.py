"""
MCP Client and Tool Dispatcher Bridge for Google ADK Agent Harness.
Bridges Gemini function declarations with FastMCP tool execution, intercepting
requests, executing tools, and returning structured MCP outputs.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional
from google.genai import types

from src.harness.mcp_server import CLINICAL_MCP_TOOLS, get_mcp_server


class MCPToolBridge:
    """
    Manages MCP tool discovery, Gemini function declaration generation,
    and runtime dispatching of tool execution requests.
    """

    def __init__(self, tools: Optional[Dict[str, Callable]] = None):
        self.tools: Dict[str, Callable] = tools or dict(CLINICAL_MCP_TOOLS)
        self.mcp_server = get_mcp_server()

    def get_tool_declarations_for_gemini(self) -> List[types.FunctionDeclaration]:
        """
        Generates google.genai.types.FunctionDeclaration definitions
        for all registered clinical MCP tools.
        """
        declarations = [
            types.FunctionDeclaration(
                name="resolve_lab_term",
                description="Map a lab test name and optional unit to canonical LOINC concepts. Returns status: RESOLVED, AMBIGUOUS, UNIT_MISMATCH, or NOT_FOUND.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "term": types.Schema(type=types.Type.STRING, description="Laboratory test name or abbreviation (e.g. 'Hb', 'Troponin')"),
                        "unit": types.Schema(type=types.Type.STRING, description="Reported unit of measure (e.g. 'g/dL', 'ng/L')"),
                    },
                    required=["term"],
                ),
            ),
            types.FunctionDeclaration(
                name="evaluate_safety_gate",
                description="Evaluate clinical input against deterministic safety gate detectors. Fails closed: returns route PROCEED or CLARIFY.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "term": types.Schema(type=types.Type.STRING, description="Laboratory test name"),
                        "unit": types.Schema(type=types.Type.STRING, description="Reported unit"),
                        "qualifier": types.Schema(type=types.Type.STRING, description="Qualifier such as total or ionized"),
                        "patient_value": types.Schema(type=types.Type.NUMBER, description="Numeric patient measurement"),
                        "status": types.Schema(type=types.Type.STRING, description="Resolution status from resolve_lab_term"),
                    },
                    required=["term"],
                ),
            ),
            types.FunctionDeclaration(
                name="fetch_grounded_protocol",
                description="Fetch reference ranges and panic limits bound strictly to a canonical LOINC URI.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "uri": types.Schema(type=types.Type.STRING, description="Canonical concept identifier (e.g. 'loinc:718-7')"),
                    },
                    required=["uri"],
                ),
            ),
            types.FunctionDeclaration(
                name="csf_workup",
                description="Pre-scopes emergency CSF diagnostic panel by department and governed tube sequence (Tubes 1-4).",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "department": types.Schema(type=types.Type.STRING, description="Optional department filter (e.g. 'hemat', 'biochem')"),
                    },
                ),
            ),
            types.FunctionDeclaration(
                name="check_calcium",
                description="Evaluates look-alike calcium values (mg/dL) across Total vs. Ionized Calcium interpretations to detect collisions.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "value_mg_dl": types.Schema(type=types.Type.NUMBER, description="Calcium level in mg/dL"),
                        "qualifier": types.Schema(type=types.Type.STRING, description="Qualifier: 'total', 'ionized', or empty"),
                    },
                    required=["value_mg_dl"],
                ),
            ),
            types.FunctionDeclaration(
                name="attest_computation",
                description="Deterministically verifies numeric calculation or range check per OKF v0.2 §5.4. Emits [Attested ✓].",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "value": types.Schema(type=types.Type.NUMBER, description="Patient numeric value"),
                        "uri": types.Schema(type=types.Type.STRING, description="Canonical LOINC URI"),
                        "unit": types.Schema(type=types.Type.STRING, description="Measurement unit"),
                    },
                    required=["value", "uri"],
                ),
            ),
        ]
        return declarations

    def get_gemini_tools(self) -> List[types.Tool]:
        """Returns the google.genai.types.Tool wrapper containing all declarations."""
        return [types.Tool(function_declarations=self.get_tool_declarations_for_gemini())]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Intercepts and executes a tool call through the MCP registry.
        Enforces argument sanitation and fail-closed safety handling.
        """
        if tool_name not in self.tools:
            return {
                "error": f"Tool '{tool_name}' not found in MCP registry.",
                "status": "NOT_FOUND",
            }

        func = self.tools[tool_name]
        try:
            # Bind arguments cleanly to avoid unexpected kwarg errors
            sig = inspect.signature(func)
            valid_args = {}
            for k, v in args.items():
                if k in sig.parameters:
                    # Cast float if required
                    param = sig.parameters[k]
                    if param.annotation in (float, Optional[float]) and v is not None:
                        try:
                            v = float(v)
                        except (ValueError, TypeError):
                            pass
                    valid_args[k] = v
            
            result = func(**valid_args)
            return result if isinstance(result, dict) else {"result": result}
        except Exception as e:
            return {
                "error": str(e),
                "status": "EXECUTION_ERROR",
                "tool_name": tool_name,
            }
