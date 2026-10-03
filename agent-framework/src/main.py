"""
Main CLI entry point for the Microsoft Agent Framework (MAF) laboratory decision support demo.
Runs clinical decision scenarios A through D.

Usage:
    python src/main.py                        # Live (auto-detect credentials from src/.env)
    python src/main.py --offline              # Offline deterministic mode (no API calls)
    python src/main.py --scenario A           # Single scenario via workflow runner
    python src/main.py --harness              # Launch interactive MAF Harness console
    python src/main.py --harness-scenario A   # Run a scenario through the MAF Harness

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


async def _run_harness(scenario: str | None = None):
    """Launch the MAF Harness runtime (interactive or single scenario)."""
    from src.harness.agent import create_clinical_harness_agent
    from src.harness.console import run_harness_console, run_scenario_through_harness

    agent = create_clinical_harness_agent()

    if scenario:
        for scen in (["A", "B", "C", "D"] if scenario == "all" else [scenario]):
            await run_scenario_through_harness(agent, scen)
    else:
        await run_harness_console(agent=agent)


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
        help="Which scenario to run via WorkflowFactory runner (default: all)",
    )
    parser.add_argument(
        "--harness",
        action="store_true",
        help="Launch the interactive Microsoft Agent Framework Harness console",
    )
    parser.add_argument(
        "--harness-scenario",
        dest="harness_scenario",
        choices=["all", "A", "B", "C", "D"],
        default=None,
        help="Run a specific scenario through the MAF Harness runtime (non-interactive)",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("   Information Retrieval, Part III: When the Retriever Has to Decide")
    print("   Microsoft Agent Framework (MAF) — Declarative Agents Implementation")
    mode = "Offline / Deterministic" if args.offline or not is_live_mode() else "Live (OpenAI gpt-5)"
    print(f"   Mode: {mode}")
    print("=" * 80 + "\n")

    if args.harness or args.harness_scenario:
        asyncio.run(_run_harness(scenario=args.harness_scenario))
    else:
        asyncio.run(_run(args.scenario))


if __name__ == "__main__":
    main()
