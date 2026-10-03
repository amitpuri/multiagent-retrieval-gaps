"""
Agent-to-Agent (A2A) message schemas, task envelopes, and role definitions.
Standardizes communication between specialized agents in the ADK ecosystem.

OKF Enhancement (Phase 1/3):
A2ATaskState now carries OKF trust signals (trust_tier, concept_status,
stale_signals, deprecated_dropped) propagated from the ontology resolver
so every downstream agent can calibrate safely without re-deriving them.
"""

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.core.models import ResolutionStatus


class AgentRole(str, Enum):
    """Defined agent roles in the multi-agent retrieval-gap architecture."""
    TRIAGE = "triage_orchestrator"
    ONTOLOGY_RESOLVER = "ontology_resolver_agent"
    SAFETY_GUARD = "safety_guard_agent"
    PROTOCOL_RETRIEVER = "protocol_retriever_agent"
    CLINICAL_SYNTHESIZER = "clinical_synthesizer_agent"
    CLARIFICATION_COORDINATOR = "clarification_coordinator_agent"


class A2AAction(str, Enum):
    """Standardized action verbs for inter-agent delegation."""
    PARSE_REQUEST = "PARSE_REQUEST"
    RESOLVE_CONCEPT = "RESOLVE_CONCEPT"
    VALIDATE_SAFETY = "VALIDATE_SAFETY"
    FETCH_PROTOCOL = "FETCH_PROTOCOL"
    SYNTHESIZE_INTERPRETATION = "SYNTHESIZE_INTERPRETATION"
    REQUEST_CLARIFICATION = "REQUEST_CLARIFICATION"


class A2AMessage(BaseModel):
    """Envelope for messages exchanged between agents."""
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender: AgentRole
    recipient: AgentRole
    action: A2AAction
    timestamp: float = Field(default_factory=time.time)
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: Optional[ResolutionStatus] = None
    error: Optional[str] = None


class A2ATaskState(BaseModel):
    """Shared task state passed across multi-agent execution turns.

    OKF fields (trust_tier, concept_status, stale_signals, deprecated_dropped)
    are propagated from the ontology resolver so every downstream agent can
    calibrate its behaviour without re-deriving trust signals.
    """
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    raw_query: str = ""
    parsed_term: str = ""
    reported_unit: str = ""
    patient_value: Optional[float] = None
    qualifier: str = ""
    resolution_status: ResolutionStatus = ResolutionStatus.UNKNOWN
    candidates: List[Dict[str, Any]] = Field(default_factory=list)
    resolved_uri: Optional[str] = None
    protocol_data: Dict[str, Any] = Field(default_factory=dict)
    safety_findings: List[str] = Field(default_factory=list)
    clarification_prompt: Optional[str] = None
    synthesized_output: Optional[str] = None
    history: List[A2AMessage] = Field(default_factory=list)

    # OKF: Trust & lifecycle signals propagated from OntologyResolver (Phase 3)
    trust_tier: Optional[str] = None            # "human-reviewed" | "machine-confirmed" | "unverified"
    concept_status: Optional[str] = None        # "draft" | "stable" | "deprecated"
    stale_signals: List[str] = Field(default_factory=list)      # URIs dropped as stale
    deprecated_dropped: List[str] = Field(default_factory=list) # URIs dropped as deprecated

    def log_message(self, msg: A2AMessage):
        self.history.append(msg)
