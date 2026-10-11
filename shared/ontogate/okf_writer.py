"""
Open Knowledge Format (OKF) Knowledge Writeback and Audit Logger.
Maintains chronological writeback history in knowledge/log.md for agent-maintained
corpora, enabling human verification via git diff review.
Per OKF v0.2 §5.2 and §7.5.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_default_log_path() -> Path:
    """Return the default path to knowledge/log.md in the repository root."""
    env_path = os.environ.get("OKF_LOG_PATH")
    if env_path:
        return Path(env_path)
    from ontogate.paths import repo_root
    return repo_root() / "knowledge" / "log.md"


def format_log_entry(
    uri: str,
    change: str,
    agent_id: str,
    timestamp: Optional[datetime] = None,
    details: Optional[Dict[str, Any]] = None,
) -> str:
    """Format an ISO-timestamped markdown bullet entry for log.md."""
    # Sanitise parameters against newline/carriage-return injection
    uri_clean = str(uri).replace("\r", " ").replace("\n", " ").strip()
    change_clean = str(change).replace("\r", " ").replace("\n", " ").strip()
    agent_id_clean = str(agent_id).replace("\r", " ").replace("\n", " ").strip()
    ts = timestamp or datetime.now(timezone.utc)
    ts_str = ts.isoformat()
    if details:
        clean_details = {
            str(k).replace("\r", " ").replace("\n", " "): str(v).replace("\r", " ").replace("\n", " ")
            for k, v in details.items()
        }
        detail_str = f" | {clean_details}"
    else:
        detail_str = ""
    return f"- {ts_str} | `{uri_clean}` | {change_clean} | generated_by={agent_id_clean}{detail_str}\n"


def record_concept_update(
    uri: str,
    change: str,
    agent_id: str,
    log_path: Optional[Path] = None,
    details: Optional[Dict[str, Any]] = None,
    timestamp: Optional[datetime] = None,
) -> str:
    """Append a concept update or newly synthesized variant to the OKF log.md file.
    
    OKF §7.5 and §5.2: log.md chronological update history.
    
    Args:
        uri: The concept or protocol URI being created or updated.
        change: Concise description of the change (e.g. 'added alt_label', 'adjusted reference_range').
        agent_id: Identifier of the agent originating the update (e.g. 'synthesis_agent/gemini-2.5-pro').
        log_path: Custom destination Path; defaults to repo's knowledge/log.md.
        details: Optional dictionary of additional metadata.
        timestamp: Optional explicit datetime (defaults to current UTC time).
        
    Returns:
        The formatted log entry string appended to the file.
    """
    path = log_path or get_default_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        with open(path, "w", encoding="utf-8") as f:
            f.write("# OKF Knowledge Update Log\n\nChronological audit trail of agent-generated updates.\n\n")

    entry = format_log_entry(
        uri=uri,
        change=change,
        agent_id=agent_id,
        timestamp=timestamp,
        details=details,
    )

    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)

    return entry


def read_update_log(
    log_path: Optional[Path] = None,
    limit: Optional[int] = None,
) -> List[str]:
    """Read entries from the log.md file, returning list of stripped entry lines."""
    path = log_path or get_default_log_path()
    if not path.exists():
        return []

    entries: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("- "):
                entries.append(stripped)

    if limit is not None and limit > 0:
        return entries[-limit:]
    return entries
