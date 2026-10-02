"""
Amazon Bedrock AgentCore Session & Memory Integration.
Provides managed AgentCore memory in cloud mode and LocalMemorySessionManager in offline mode.
"""
import os
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone


class LocalMemorySessionManager:
    """In-memory session manager for deterministic offline testing and local execution."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or f"local-session-{uuid.uuid4().hex[:8]}"
        self.turns: List[Dict[str, Any]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def add_turn(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        turn = {
            "turn_id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.turns.append(turn)
        return turn

    def get_last_k_turns(self, k: int = 10) -> List[Dict[str, Any]]:
        return self.turns[-k:]

    def clear(self) -> None:
        self.turns.clear()


def get_agentcore_session_manager(
    memory_id: Optional[str] = None,
    session_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    region_name: Optional[str] = None,
    offline: Optional[bool] = None,
) -> Any:
    """Get Amazon Bedrock AgentCore MemorySessionManager or LocalMemorySessionManager fallback."""
    if offline is None:
        offline = (
            os.environ.get("STRANDS_OFFLINE_MODE", "").lower() in ("true", "1", "yes")
            or not bool(os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))
        )

    resolved_memory_id = memory_id or os.environ.get("AGENTCORE_MEMORY_ID")
    if offline or not resolved_memory_id:
        return LocalMemorySessionManager(session_id=session_id)

    try:
        from bedrock_agentcore.memory.session import MemorySessionManager
        region = region_name or os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        return MemorySessionManager(memory_id=resolved_memory_id, region_name=region)
    except Exception:
        # Graceful fallback to local in-memory manager
        return LocalMemorySessionManager(session_id=session_id)
