"""
Main CLI entry point for the Microsoft Agent Framework (MAF) laboratory decision support demo.
Runs clinical decision scenarios A through D.

Usage:
    python src/main.py                 # Live (auto-detect credentials from src/.env)
    python src/main.py --offline       # Offline deterministic mode (no API calls)
    python src/main.py --scenario A    # Single scenario

The src/.env file is loaded automatically. Set OPENAI_API_KEY for local testing.
"""
import argparse
import asyncio
import sys
from pathlib import Path

# Configure UTF-8 encoding for standard streams (Windows compatibility)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure agent-framework root and repo root are on sys.path
_agent_framework_dir = Path(__file__).resolve().parent.parent
_repo_root = _agent_framework_dir.parent

for p in (str(_repo_root), str(_agent_framework_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

from src.runner import (
    run_scenario_a,
    run_scenario_b,
    run_scenario_c,
    run_scenario_d,
    is_live_mode,
)


async def _run(scenario: str):
    if scenario == "all":
        await run_scenario_a()
        run_scenario_b()
        await run_scenario_c()
        await run_scenario_d()
    elif scenario == "A":
        await run_scenario_a()
    elif scenario == "B":
        run_scenario_b()
    elif scenario == "C":
        await run_scenario_c()
    elif scenario == "D":
        await run_scenario_d()


def main():
    parser = argparse.ArgumentParser(
        description="MAF Clinical Decision Support — Scenarios A–D"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run without any API calls (deterministic mock for CI/testing)",
    )
    parser.add_argument(
        "--scenario",
        default="all",
        choices=["all", "A", "B", "C", "D"],
        help="Which scenario to run (default: all)",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("   Information Retrieval, Part III: When the Retriever Has to Decide")
    print("   Microsoft Agent Framework (MAF) — Declarative Agents Implementation")
    mode = "Offline / Deterministic" if args.offline or not is_live_mode() else "Live (OpenAI gpt-5)"
    print(f"   Mode: {mode}")
    print("=" * 80 + "\n")

    asyncio.run(_run(args.scenario))


if __name__ == "__main__":
    main()
