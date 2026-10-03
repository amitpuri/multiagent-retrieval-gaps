"""
Session and conversation state management for the Google ADK Agent Harness.
Maintains turn-by-turn history, tool invocations, and Gemini Content representations.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ToolInvocationRecord(BaseModel):
    """Record of a tool call requested by the model and executed by the harness."""
    tool_name: str
    args: Dict[str, Any]
    result: Optional[Any] = None
    call_id: Optional[str] = None
    approved: bool = True
    executed_at: float = Field(default_factory=time.time)


class SessionMessage(BaseModel):
    """A single turn in the harness conversation history."""
    role: str  # "user", "model", "system", "tool"
    content: str = ""
    tool_calls: List[ToolInvocationRecord] = Field(default_factory=list)
    tool_responses: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class HarnessSession(BaseModel):
    """
    Session container isolating conversation history, safety state,
    and attestation records for a clinical interaction.
    """
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = "clinician_user"
    messages: List[SessionMessage] = Field(default_factory=list)
    state: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def add_user_message(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> SessionMessage:
        msg = SessionMessage(role="user", content=content, metadata=metadata or {})
        self.messages.append(msg)
        self.updated_at = time.time()
        return msg

    def add_model_message(
        self,
        content: str = "",
        tool_calls: Optional[List[ToolInvocationRecord]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionMessage:
        msg = SessionMessage(
            role="model",
            content=content,
            tool_calls=tool_calls or [],
            metadata=metadata or {},
        )
        self.messages.append(msg)
        self.updated_at = time.time()
        return msg

    def add_tool_response(
        self,
        tool_name: str,
        result: Any,
        call_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionMessage:
        msg = SessionMessage(
            role="tool",
            content=str(result),
            tool_responses=[{"tool_name": tool_name, "call_id": call_id, "result": result}],
            metadata=metadata or {},
        )
        self.messages.append(msg)
        self.updated_at = time.time()
        return msg

    def get_recent_messages(self, limit: Optional[int] = None) -> List[SessionMessage]:
        if limit is None or limit <= 0:
            return list(self.messages)
        return self.messages[-limit:]

    def clear(self) -> None:
        self.messages.clear()
        self.state.clear()
        self.updated_at = time.time()
