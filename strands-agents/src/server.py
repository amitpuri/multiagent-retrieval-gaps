"""
Production Deployment Server for AWS Strands Agents SDK & Amazon Bedrock AgentCore.
Runs continuous FastAPI REST service on port 8000.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.orchestration.strands_orchestrator import (
    StrandsDecisionSupportOrchestrator,
    build_strands_orchestrator,
)

log = logging.getLogger(__name__)

app = FastAPI(
    title="AWS Strands Clinical Decision Support Server",
    description="Continuous production runtime for AWS Strands Agents SDK & Bedrock AgentCore with deterministic safety gating.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

_ORCHESTRATOR: Optional[StrandsDecisionSupportOrchestrator] = None


def get_orchestrator() -> StrandsDecisionSupportOrchestrator:
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        offline = os.environ.get("STRANDS_OFFLINE_MODE", "").lower() in ("true", "1", "yes")
        _ORCHESTRATOR = build_strands_orchestrator(offline=offline)
    return _ORCHESTRATOR


class QueryRequest(BaseModel):
    prompt: str = Field(..., description="Clinician inquiry, e.g. 'Hb 13.5 | g/dL'")
    session_id: Optional[str] = Field(None, description="Optional conversation session ID")
    user_id: Optional[str] = Field("clinician_user", description="Identifier of the ordering clinician")


class QueryResponse(BaseModel):
    session_id: str
    text: str
    route: str
    status: str
    attested: bool = False
    clarification: Optional[str] = None


@app.get("/healthz", status_code=status.HTTP_200_OK, tags=["Monitoring"])
def healthz() -> Dict[str, str]:
    return {"status": "healthy", "service": "aws-strands-agents"}


@app.get("/readyz", status_code=status.HTTP_200_OK, tags=["Monitoring"])
def readyz() -> Dict[str, Any]:
    orch = get_orchestrator()
    return {
        "status": "ready",
        "service": "aws-strands-agents",
        "offline_mode": bool(orch.offline),
        "model": "us.anthropic.claude-sonnet-4-5:0 (Bedrock)",
    }


@app.post("/api/v1/sessions", status_code=status.HTTP_201_CREATED, tags=["Sessions"])
def create_session() -> Dict[str, Any]:
    sess_id = str(uuid.uuid4())
    return {"session_id": sess_id, "message": "Strands AgentCore session initialized."}


@app.post("/api/v1/query", response_model=QueryResponse, tags=["Query"])
def query_strands(req: QueryRequest) -> QueryResponse:
    orch = get_orchestrator()
    sess_id = req.session_id or str(uuid.uuid4())

    # Deterministic evaluation with safety gate
    result = orch.process_query_direct(req.prompt)
    route = result.get("route", "CLARIFY")
    res_status = result.get("status", "UNKNOWN")
    clarification = result.get("clarification")

    if route == "PROCEED":
        concept = result.get("concept", {})
        protocol = result.get("protocol", {}).get("protocol", {})
        text = f"[Attested ✓] Resolved LOINC: {concept.get('label')} ({concept.get('uri')}). Ref range: {protocol.get('reference_range')}."
    else:
        text = clarification or f"Safety gate flagged {res_status}. Clinician clarification required."

    return QueryResponse(
        session_id=sess_id,
        text=text,
        route=route,
        status=res_status,
        attested=(route == "PROCEED"),
        clarification=clarification,
    )
