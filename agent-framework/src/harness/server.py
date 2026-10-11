"""
Production Deployment Server for Microsoft Agent Framework (MAF).
Runs continuous FastAPI REST service on port 8000.
"""
from __future__ import annotations

from ontogate.catalog import model_for as _model_for

import logging
import os
import uuid
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.harness.agent import ClinicalHarnessAgent, create_clinical_harness_agent
from src.harness.session import HarnessSession

log = logging.getLogger(__name__)

app = FastAPI(
    title="Microsoft Agent Framework (MAF) Clinical Decision Server",
    description="Continuous production runtime for MAF Declarative Agents with deterministic safety gating.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

_HARNESS_AGENT: Optional[ClinicalHarnessAgent] = None
_SESSIONS: Dict[str, HarnessSession] = {}


def get_agent() -> ClinicalHarnessAgent:
    global _HARNESS_AGENT
    if _HARNESS_AGENT is None:
        _HARNESS_AGENT = create_clinical_harness_agent()
    return _HARNESS_AGENT


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
    return {"status": "healthy", "service": "azure-agent-framework"}


@app.get("/readyz", status_code=status.HTTP_200_OK, tags=["Monitoring"])
def readyz() -> Dict[str, Any]:
    agent = get_agent()
    return {
        "status": "ready",
        "service": "azure-agent-framework",
        "model": f"{_model_for('azure')['id']} via Microsoft Foundry (Responses API)",
        "tools": list(agent.tools.keys()),
    }


@app.post("/api/v1/sessions", status_code=status.HTTP_201_CREATED, tags=["Sessions"])
def create_session() -> Dict[str, Any]:
    agent = get_agent()
    sess = agent.create_session()
    _SESSIONS[sess.session_id] = sess
    return {"session_id": sess.session_id, "message": "MAF Harness session initialized."}


@app.post("/api/v1/query", response_model=QueryResponse, tags=["Query"])
async def query_maf(req: QueryRequest) -> QueryResponse:
    agent = get_agent()
    sess_id = req.session_id or str(uuid.uuid4())
    session = _SESSIONS.get(sess_id) or agent.create_session(session_id=sess_id)
    _SESSIONS[sess_id] = session

    resp = await agent.run(prompt=req.prompt, session=session)

    return QueryResponse(
        session_id=resp.session_id,
        text=resp.text,
        route=resp.route,
        status=resp.status,
        attested=(resp.route == "PROCEED"),
        clarification=resp.clarification,
    )
