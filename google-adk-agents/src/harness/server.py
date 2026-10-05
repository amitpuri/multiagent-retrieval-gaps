"""
Production Deployment Server for Google ADK Agent Harness.
Implements Step 4: Moves the agentic harness to a production environment
where it can run continuously, serving REST endpoints and MCP discovery.

Security fixes (Fix 11)
-----------------------
* Session IDs are ALWAYS server-generated UUIDs.  Any client-supplied
  session_id in POST /api/v1/query is ignored for new sessions — only
  existing sessions can be resumed by ID.  This prevents session fixation.
* GET /api/v1/sessions/{id} requires a Bearer token (require_auth).
* Session count is capped at MAX_SESSIONS (default 1000, env-configurable).
* Prompt length is capped at 2000 characters.

Monitoring fix (Fix 6)
----------------------
* /readyz returns status="degraded" when offline_mode is True so
  load-balancers and dashboards can alert on stub-mode operation.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from src.harness.agent import ClinicalADKHarness, HarnessResponse, create_clinical_harness
from src.harness.mcp_server import CLINICAL_MCP_TOOLS
from src.harness.session import HarnessSession

log = logging.getLogger(__name__)

app = FastAPI(
    title="Google ADK Clinical Agent Harness",
    description="Continuous production runtime for ADK clinical decision support with MCP tool protocol and deterministic safety gating.",
    version="1.0.0",
)

# CORS: default to no cross-origin access; override via ALLOWED_ORIGINS env var.
# Example: ALLOWED_ORIGINS=https://lis.hospital.internal,https://portal.hospital.internal
# WARNING: Never use "*" with allow_credentials=True — browsers will reject it
# and it exposes credentials to any origin in non-browser clients.
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "")
_allowed_origins: List[str] = [
    o.strip() for o in _raw_origins.split(",") if o.strip()
]
_allow_credentials = bool(_allowed_origins)  # credentials only valid with explicit origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# In-memory session store (pluggable with Redis / Firestore in production)
_SESSIONS: Dict[str, HarnessSession] = {}
_HARNESS: Optional[ClinicalADKHarness] = None

# Fix 11: configurable session cap to prevent unbounded memory growth
MAX_SESSIONS: int = int(os.environ.get("MAX_SESSIONS", "1000"))

# Fix 11: configurable prompt length cap
MAX_PROMPT_LENGTH: int = int(os.environ.get("MAX_PROMPT_LENGTH", "2000"))

# Fix 11: static auth token list (replace with real IdP / OAuth2 in production)
# Format: comma-separated Bearer tokens stored in the HARNESS_API_TOKENS env var.
# Example: HARNESS_API_TOKENS=token-abc123,token-def456
_RAW_TOKENS = os.environ.get("HARNESS_API_TOKENS", "")
_VALID_TOKENS: frozenset = frozenset(
    t.strip() for t in _RAW_TOKENS.split(",") if t.strip()
)

if not _VALID_TOKENS:
    log.warning(
        "SECURITY WARNING: HARNESS_API_TOKENS is not set. "
        "All /api/v1 endpoints are open to unauthenticated access. "
        "Set HARNESS_API_TOKENS in the environment before production deployment."
    )


def get_harness() -> ClinicalADKHarness:
    """Singleton harness instance for the application."""
    global _HARNESS
    if _HARNESS is None:
        _HARNESS = create_clinical_harness()
    return _HARNESS


def _evict_oldest_sessions() -> None:
    """Evict the oldest session when the cap is exceeded."""
    while len(_SESSIONS) >= MAX_SESSIONS:
        oldest_key = next(iter(_SESSIONS))
        del _SESSIONS[oldest_key]


def require_auth(authorization: Optional[str] = Header(None)) -> str:
    """
    Fix 11: Bearer-token authentication stub.

    Validates the Authorization header against HARNESS_API_TOKENS.
    Returns the token on success; raises HTTP 401 on failure.

    IMPORTANT: This is a static-token stub. Replace with a real IdP
    (Google IAM, OAuth2 introspection, etc.) before production deployment.
    If HARNESS_API_TOKENS is not set, auth is disabled (dev-mode only).
    """
    if not _VALID_TOKENS:
        # Auth not configured — allow all requests (dev mode).
        return "unauthenticated"
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header with Bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ").strip()
    if token not in _VALID_TOKENS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


class QueryRequest(BaseModel):
    prompt: str = Field(
        ...,
        description="Clinician inquiry or laboratory order",
        json_schema_extra={"example": "Hb 13.5 | g/dL"},
    )
    session_id: Optional[str] = Field(
        None,
        description=(
            "Resume an existing session by server-issued ID. "
            "Omit (or pass null) to start a new session. "
            "Note: client-supplied IDs that do not match an existing session are IGNORED — "
            "the server always generates new session IDs."
        ),
    )
    user_id: Optional[str] = Field("clinician_user", description="Identifier of the ordering clinician")

    @field_validator("prompt")
    @classmethod
    def check_prompt_length(cls, v: str) -> str:
        """Fix 11: reject prompts exceeding the configured length cap."""
        if len(v) > MAX_PROMPT_LENGTH:
            raise ValueError(
                f"Prompt length {len(v)} exceeds maximum allowed length of {MAX_PROMPT_LENGTH} characters."
            )
        return v


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
    """
    Readiness probe.

    Fix 6: returns status="degraded" when offline_mode=True so load-balancers
    and dashboards can alert.  HTTP 200 is still returned (the process is alive),
    but the status field distinguishes live from stub mode.
    """
    harness = get_harness()
    ready_status = "degraded" if harness.offline else "ready"
    return {
        "status": ready_status,
        "offline_mode": harness.offline,
        "model": harness.model_name,
        "mcp_tools": list(CLINICAL_MCP_TOOLS.keys()),
    }


@app.post(
    "/api/v1/sessions",
    response_model=SessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Sessions"],
)
def create_session(
    _token: str = Depends(require_auth),  # Fix 11: auth required on all /api/v1 routes
) -> SessionCreateResponse:
    """Create a new isolated clinician conversation session."""
    harness = get_harness()
    _evict_oldest_sessions()
    # Fix 11: always server-generated UUID — never accept client IDs here.
    session = harness.create_session()
    _SESSIONS[session.session_id] = session
    return SessionCreateResponse(
        session_id=session.session_id,
        created_at=session.created_at,
        message="Session successfully initialized.",
    )


@app.get("/api/v1/sessions/{session_id}", tags=["Sessions"])
def get_session(
    session_id: str,
    _token: str = Depends(require_auth),  # Fix 11: auth required
) -> Dict[str, Any]:
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
async def query_harness(
    req: QueryRequest,
    _token: str = Depends(require_auth),  # Fix 11: auth required on all /api/v1 routes
) -> QueryResponse:
    """
    Execute a turn against the continuous agent harness.
    Manages inputs, MCP tool execution, context window updates, and safety gating.

    Fix 11: client-supplied session_id is only honoured if it matches an
    EXISTING server-known session.  Unknown IDs are silently ignored and a new
    server-generated session is started.  This prevents session fixation.
    """
    harness = get_harness()

    # Fix 11: session fixation prevention
    if req.session_id and req.session_id in _SESSIONS:
        # Resume known existing session
        session = _SESSIONS[req.session_id]
    else:
        # New session — always server-generated ID, ignore any client-supplied ID
        _evict_oldest_sessions()
        session = harness.create_session()
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
def list_mcp_tools(
    _token: str = Depends(require_auth),  # Fix 11: auth required on all /api/v1 routes
) -> Dict[str, Any]:
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
