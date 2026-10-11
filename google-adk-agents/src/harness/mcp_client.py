"""
MCP Client and Tool Dispatcher Bridge for Google ADK Agent Harness.
Bridges Gemini function declarations with FastMCP tool execution, intercepting
requests, executing tools, and returning structured MCP outputs.
"""
from __future__ import annotations

import inspect
import math
import typing
from typing import Any, Callable, Dict, List, Optional
from google.genai import types

from src.harness.mcp_server import CLINICAL_MCP_TOOLS, get_mcp_server


def _schema_type(annotation: Any) -> "types.Type":
    """Map a Python annotation to a Gemini schema type."""
    origin_args = typing.get_args(annotation) or (annotation,)
    for a in origin_args:
        if a in (float, int):
            return types.Type.NUMBER
        if a is bool:
            return types.Type.BOOLEAN
        if a in (list, List) or typing.get_origin(a) is list:
            return types.Type.ARRAY
        if a in (dict, Dict) or typing.get_origin(a) is dict:
            return types.Type.OBJECT
    return types.Type.STRING


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
        Generate google.genai FunctionDeclarations from the canonical tool
        signatures (one source of truth for names, parameters and descriptions).
        """
        declarations: List[types.FunctionDeclaration] = []
        for name, func in self.tools.items():
            hints = typing.get_type_hints(func)
            sig = inspect.signature(func)
            props: Dict[str, types.Schema] = {}
            required: List[str] = []
            for pname, param in sig.parameters.items():
                props[pname] = types.Schema(type=_schema_type(hints.get(pname, str)), description=pname.replace("_", " "))
                if param.default is inspect.Parameter.empty:
                    required.append(pname)
            declarations.append(types.FunctionDeclaration(
                name=name,
                description=(func.__doc__ or name).strip().splitlines()[0],
                parameters=types.Schema(type=types.Type.OBJECT, properties=props, required=required or None),
            ))
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
            hints = typing.get_type_hints(func)
            valid_args = {}
            for k, v in args.items():
                if k in sig.parameters:
                    # Cast float if required (annotations may be postponed strings)
                    if hints.get(k) in (float, Optional[float]) and v is not None:
                        try:
                            v = float(v)
                            # reject non-finite values produced by model output
                            # before they reach EvaluationContext or any detector.
                            if not math.isfinite(v):
                                return {
                                    "error": (
                                        f"Non-finite value {v!r} rejected for parameter '{k}'. "
                                        "NaN and infinite values are not valid clinical measurements."
                                    ),
                                    "status": "EXECUTION_ERROR",
                                    "tool_name": tool_name,
                                }
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
