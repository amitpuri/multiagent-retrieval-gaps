"""
The Agent Runtime package is self-contained: staged without the repository,
the ADK workflow imports, the skills lock verifies and the bundle hash matches.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_agent_runtime_dry_run_stages_an_importable_agent():
    proc = subprocess.run([sys.executable, str(REPO / "deployment" / "gcloud-scripts" / "agent_runtime.py"),
                           "--dry-run"], capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "Staged agent imports cleanly" in proc.stdout
