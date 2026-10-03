"""
MAF Harness Session Management.
Maintains session state, conversation history, and per-service-call persistence
aligned with Microsoft Agent Framework session concepts.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SessionMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: str  # "user", "assistant", "system", "tool"
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class HarnessSession:
    """Manages conversation state and history for a harnessed agent."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id: str = session_id or f"session_{uuid.uuid4().hex[:8]}"
        self.history: List[SessionMessage] = []
        self.state: Dict[str, Any] = {}
        self.created_at: float = time.time()
        self.updated_at: float = time.time()

    def add_message(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionMessage:
        """Append a message to the session history."""
        msg = SessionMessage(
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self.history.append(msg)
        self.updated_at = time.time()
        return msg

    def get_history(self) -> List[Dict[str, Any]]:
        """Return history as list of dicts."""
        return [msg.model_dump() for msg in self.history]

    def set_state(self, key: str, value: Any) -> None:
        """Store session-scoped context data."""
        self.state[key] = value
        self.updated_at = time.time()

    def get_state(self, key: str, default: Any = None) -> Any:
        """Retrieve session-scoped context data."""
        return self.state.get(key, default)

    def clear(self) -> None:
        """Clear conversation history and state."""
        self.history.clear()
        self.state.clear()
        self.updated_at = time.time()

    def __repr__(self) -> str:
        return f"<HarnessSession id={self.session_id} turns={len(self.history)}>"
