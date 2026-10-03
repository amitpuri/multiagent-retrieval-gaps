"""
MAF Harness Terminal UX Console.
Provides an interactive command interface conforming to the Microsoft Agent Framework
Harness console specification:
- Real-time command execution and clinical query submission
- /todos command to inspect workflow steps
- /mode command to inspect and toggle Plan vs. Execute modes
- /scenario command to execute MARS benchmark scenarios A-D
- /status and /clear session controls
"""
from __future__ import annotations

import asyncio
import sys
from typing import Optional

from src.harness.agent import ClinicalHarnessAgent, create_clinical_harness_agent
from src.harness.providers import AgentMode
from src.harness.session import HarnessSession
from src.tools import csf_workup


BANNER = """
================================================================================
  Microsoft Agent Framework (MAF) — Clinical Laboratory Decision Harness Console
  Architecture: Chat Client + Context Providers + Safety Gate + Interactive UX
================================================================================
  Commands:
    /todos           Show diagnostic workflow todos and progress
    /mode [p|e]      View or toggle mode ('plan' or 'execute')
    /scenario <A-D>  Execute clinical benchmark scenario (A, B, C, or D)
    /status          Display session ID, active mode, and registered tools
    /clear           Reset conversation session and memory
    /help            Display this help menu
    /exit            Exit the harness console
================================================================================
"""


async def run_scenario_through_harness(agent: ClinicalHarnessAgent, scenario: str) -> None:
    """Run a MARS benchmark scenario through the harness runtime."""
    scenario = scenario.upper()
    print(f"\n[*] Executing Scenario {scenario} via MAF Harness Runtime...")

    if scenario == "A":
        turns = [
            ("Turn 1: Ambiguous — Missing Unit", "Hb 13.5"),
            ("Turn 2: Valid Unit — Resolves", "Hb 13.5 | g/dL"),
            ("Turn 3: Invalid Unit — Mismatch", "Hb 13.5 | mg/dL"),
        ]
        for label, query in turns:
            print(f"\n--- {label} ---")
            print(f"Query: \"{query}\"")
            res = await agent.run(query)
            _render_response(res)

    elif scenario == "B":
        print("\n--- Scenario B: CSF Emergency Workup (Governed Tube Ordering - Gap 11) ---")
        workup = csf_workup()
        print("Pre-scoped Emergency CSF Tube Workup:")
        for dept, tests in workup.items():
            print(f"  Department [{dept}]:")
            for t in tests:
                print(f"    - Tube {t['tube']}: {t['test']} [{t['uri']}]")

    elif scenario == "C":
        turns = [
            ("Unqualified Calcium (Collision Expected)", "Calcium 4.8 | mg/dL"),
            ("Qualified Total Calcium", "Calcium 4.8 | mg/dL | total"),
            ("Qualified Ionized Calcium", "Calcium 4.8 | mg/dL | ionized"),
        ]
        for label, query in turns:
            print(f"\n--- {label} ---")
            print(f"Query: \"{query}\"")
            res = await agent.run(query)
            _render_response(res)

    elif scenario == "D":
        turns = [
            ("Turn 1: Ambiguous Troponin", "Troponin 15"),
            ("Turn 2: Valid ng/L Unit", "Troponin 15 | ng/L"),
            ("Turn 3: Unit Mismatch mg/dL", "Troponin 15 | mg/dL"),
        ]
        for label, query in turns:
            print(f"\n--- {label} ---")
            print(f"Query: \"{query}\"")
            res = await agent.run(query)
            _render_response(res)
    else:
        print(f"[!] Unknown scenario '{scenario}'. Choose from A, B, C, or D.")


def _render_response(res) -> None:
    """Pretty-print harness response with tool details and route verdicts."""
    route_badge = f"[{res.route}]"
    print(f"  Verdict: {route_badge} | Status: {res.status} | Mode: {res.mode.value.upper()}")

    # Render tool trace
    if res.tool_calls:
        print("  Tools executed:")
        for call in res.tool_calls:
            approval_mark = "[Auto-Approved]" if call.approved else "[Requires HITL]"
            print(f"    -> {call.tool_name}() {approval_mark}")

    print("\n  Agent Output:")
    for line in res.text.strip().split("\n"):
        print(f"    {line}")
    print()


async def run_harness_console(
    agent: Optional[ClinicalHarnessAgent] = None,
    session: Optional[HarnessSession] = None,
) -> None:
    """Run the interactive MAF terminal console."""
    if agent is None:
        agent = create_clinical_harness_agent()
    if session is None:
        session = agent.create_session()

    print(BANNER)
    print(f"Active Session: {session.session_id}")
    print(f"Operating Mode: {agent.mode_provider.mode.value.upper()}\n")

    while True:
        try:
            prompt = input("clinician> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting harness console.")
            break

        if not prompt:
            continue

        cmd = prompt.lower()
        if cmd in ("/exit", "/quit"):
            print("Session ended. Goodbye.")
            break

        elif cmd == "/todos":
            print("\n" + agent.todo_provider.format_todos() + "\n")

        elif cmd.startswith("/mode"):
            parts = prompt.split()
            if len(parts) == 1:
                print(f"Current mode: {agent.mode_provider.mode.value.upper()}")
            else:
                target = parts[1].lower()
                if target in ("plan", "p"):
                    agent.mode_provider.set_mode(AgentMode.PLAN)
                    print("Mode updated to PLAN. Queries will analyze gaps without executing protocols.")
                elif target in ("execute", "e", "exec"):
                    agent.mode_provider.set_mode(AgentMode.EXECUTE)
                    print("Mode updated to EXECUTE. Queries will fetch protocols or trigger clarifications.")
                else:
                    print("Invalid mode. Use '/mode plan' or '/mode execute'.")

        elif cmd.startswith("/scenario"):
            parts = prompt.split()
            if len(parts) < 2:
                print("Usage: /scenario <A|B|C|D>")
            else:
                await run_scenario_through_harness(agent, parts[1])

        elif cmd == "/status":
            print(f"\n--- Harness Status ---")
            print(f"Agent Name:    {agent.name}")
            print(f"Session ID:    {session.session_id}")
            print(f"History Turns: {len(session.history)}")
            print(f"Active Mode:   {agent.mode_provider.mode.value.upper()}")
            print(f"Tools ({len(agent.tools)}):  {', '.join(agent.tools.keys())}")
            print(f"Client:        {type(agent.client).__name__ if agent.client else 'Deterministic Offline'}\n")

        elif cmd == "/clear":
            session.clear()
            agent.todo_provider.reset()
            print("Session history and memory cleared.")

        elif cmd in ("/help", "/?"):
            print(BANNER)

        else:
            # Process normal clinical query
            res = await agent.run(prompt, session=session)
            _render_response(res)


if __name__ == "__main__":
    asyncio.run(run_harness_console())
