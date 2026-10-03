"""
Production Deployment Server for Google ADK Agent Harness.
Implements Step 4: Moves the agentic harness to a production environment
where it can run continuously, serving REST endpoints and MCP discovery.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.harness.agent import ClinicalADKHarness, HarnessResponse, create_clinical_harness
from src.harness.mcp_server import CLINICAL_MCP_TOOLS
from src.harness.session import HarnessSession

app = FastAPI(
    title="Google ADK Clinical Agent Harness",
    description="Continuous production runtime for ADK clinical decision support with MCP tool protocol and deterministic safety gating.",
    version="1.0.0",
)

# Enable CORS for browser clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store (pluggable with Redis / Firestore in production)
_SESSIONS: Dict[str, HarnessSession] = {}
_HARNESS: Optional[ClinicalADKHarness] = None


def get_harness() -> ClinicalADKHarness:
    """Singleton harness instance for the application."""
    global _HARNESS
    if _HARNESS is None:
        _HARNESS = create_clinical_harness()
    return _HARNESS


class QueryRequest(BaseModel):
    prompt: str = Field(..., description="Clinician inquiry or laboratory order", json_schema_extra={"example": "Hb 13.5 | g/dL"})
    session_id: Optional[str] = Field(None, description="Active session ID or creates new if omitted")
    user_id: Optional[str] = Field("clinician_user", description="Identifier of the ordering clinician")


class QueryResponse(BaseModel):
    session_id: str
    text: str
    route: str
    status: str
    attested: bool
    is_hitl_paused: bool
    tool_calls_count: int
    clarification: Optional[str] = None


class SessionCreateResponse(BaseModel):
    session_id: str
    created_at: float
    message: str


@app.get("/healthz", status_code=status.HTTP_200_OK, tags=["Monitoring"])
def healthz() -> Dict[str, str]:
    """Liveness probe."""
    return {"status": "healthy", "service": "google-adk-harness"}


@app.get("/readyz", status_code=status.HTTP_200_OK, tags=["Monitoring"])
def readyz() -> Dict[str, Any]:
    """Readiness probe."""
    harness = get_harness()
    return {
        "status": "ready",
        "offline_mode": harness.offline,
        "model": harness.model_name,
        "mcp_tools": list(CLINICAL_MCP_TOOLS.keys()),
    }


@app.post("/api/v1/sessions", response_model=SessionCreateResponse, status_code=status.HTTP_201_CREATED, tags=["Sessions"])
def create_session() -> SessionCreateResponse:
    """Create a new isolated clinician conversation session."""
    harness = get_harness()
    session = harness.create_session()
    _SESSIONS[session.session_id] = session
    return SessionCreateResponse(
        session_id=session.session_id,
        created_at=session.created_at,
        message="Session successfully initialized.",
    )


@app.get("/api/v1/sessions/{session_id}", tags=["Sessions"])
def get_session(session_id: str) -> Dict[str, Any]:
    """Retrieve turn history and state for an active session."""
    if session_id not in _SESSIONS:
        raise HTTPException(status_code=404, detail="Session not found.")
    session = _SESSIONS[session_id]
    return {
        "session_id": session.session_id,
        "turn_count": len(session.messages),
        "messages": [msg.model_dump() for msg in session.messages],
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


@app.post("/api/v1/query", response_model=QueryResponse, tags=["Agent Harness"])
async def query_harness(req: QueryRequest) -> QueryResponse:
    """
    Execute a turn against the continuous agent harness.
    Manages inputs, MCP tool execution, context window updates, and safety gating.
    """
    harness = get_harness()
    
    if req.session_id and req.session_id in _SESSIONS:
        session = _SESSIONS[req.session_id]
    else:
        session = harness.create_session(session_id=req.session_id)
        _SESSIONS[session.session_id] = session

    res: HarnessResponse = await harness.run(prompt=req.prompt, session=session)

    return QueryResponse(
        session_id=res.session_id,
        text=res.text,
        route=res.route,
        status=res.status,
        attested=res.attested,
        is_hitl_paused=res.is_hitl_paused,
        tool_calls_count=len(res.tool_calls),
        clarification=res.clarification,
    )


@app.get("/api/v1/mcp/tools", tags=["MCP Tools"])
def list_mcp_tools() -> Dict[str, Any]:
    """Inspect all tools registered on the FastMCP server."""
    harness = get_harness()
    declarations = harness.mcp_bridge.get_tool_declarations_for_gemini()
    tools_summary = []
    for d in declarations:
        tools_summary.append({
            "name": d.name,
            "description": d.description,
            "required_parameters": getattr(d.parameters, "required", []),
        })
    return {
        "mcp_server": "ClinicalLabMCPServer",
        "tool_count": len(tools_summary),
        "tools": tools_summary,
    }
