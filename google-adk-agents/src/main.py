"""
Main CLI entry point for executing the ADK laboratory decision support demo.
Runs the pure code test assertions first, followed by the scenario workflows.
"""

import asyncio
from pathlib import Path
import sys

# Configure UTF-8 encoding for standard streams (Windows compatibility)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure google-adk-agents root and repo root are in sys.path
_adk_dir = Path(__file__).resolve().parent.parent
_repo_root = _adk_dir.parent
for p in (str(_repo_root), str(_adk_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.runner import main as run_scenarios


def main():
    print("=" * 80)
    print("   Information Retrieval, Part III: When the Retriever Has to Decide")
    print("   Generic & Reusable Multi-Agent Architecture with Google ADK 2.0 & A2A")
    print("=" * 80 + "\n")
    asyncio.run(run_scenarios())


if __name__ == "__main__":
    main()
