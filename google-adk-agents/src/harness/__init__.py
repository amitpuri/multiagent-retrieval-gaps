"""
Google ADK Agent Harness Package.
Implements the 4-step Agent Harness architecture:
Step 1: Continuous reasoning loop (ClinicalADKHarness)
Step 2: MCP Tool Integration (FastMCP server & MCPToolBridge)
Step 3: Context Window & Token Management (ContextWindowManager & HarnessSession)
Step 4: Continuous Deployment (FastAPI ASGI application & Interactive CLI)
"""
from src.harness.agent import (
    ClinicalADKHarness,
    HarnessResponse,
    create_clinical_harness,
)
from src.harness.context import ContextWindowManager
from src.harness.mcp_client import MCPToolBridge
from src.harness.mcp_server import (
    CLINICAL_MCP_TOOLS,
    get_mcp_server,
)
from src.harness.server import app
from src.harness.session import (
    HarnessSession,
    SessionMessage,
    ToolInvocationRecord,
)

__all__ = [
    "ClinicalADKHarness",
    "HarnessResponse",
    "create_clinical_harness",
    "ContextWindowManager",
    "MCPToolBridge",
    "CLINICAL_MCP_TOOLS",
    "get_mcp_server",
    "app",
    "HarnessSession",
    "SessionMessage",
    "ToolInvocationRecord",
]
