"""Pytest configuration and global fixtures for google-adk-agents."""
from __future__ import annotations

from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def redirect_okf_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect knowledge/log.md writes to a temporary directory during test execution."""
    temp_log = tmp_path / "test_knowledge_log.md"
    monkeypatch.setenv("OKF_LOG_PATH", str(temp_log))
