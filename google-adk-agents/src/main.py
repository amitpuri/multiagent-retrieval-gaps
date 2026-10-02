"""
Main CLI entry point for executing the ADK laboratory decision support demo.
Runs the pure code test assertions first, followed by the scenario workflows.
"""

import asyncio
from pathlib import Path
import sys

# __file__ is google-adk-agents/src/main.py; repo root is 3 levels up
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.runner import main as run_scenarios


def main():
    print("=" * 80)
    print("   Information Retrieval, Part III: When the Retriever Has to Decide")
    print("   Generic & Reusable Multi-Agent Architecture with Google ADK 2.0 & A2A")
    print("=" * 80 + "\n")
    asyncio.run(run_scenarios())


if __name__ == "__main__":
    main()
