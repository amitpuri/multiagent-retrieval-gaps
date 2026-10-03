"""
Interactive CLI Console for Google ADK Clinical Agent Harness.
Demonstrates continuous reasoning loop, MCP tool call visibility,
and multi-turn context retention.
"""
from __future__ import annotations

import asyncio
import sys
from typing import Optional

from src.harness.agent import ClinicalADKHarness, create_clinical_harness


async def run_interactive_console(offline: Optional[bool] = None) -> None:
    """Run an interactive terminal session with the agent harness."""
    harness = create_clinical_harness(offline=offline)
    session = harness.create_session()

    mode_str = "Offline Deterministic" if harness.offline else f"Live Gemini ({harness.model_name})"
    print("=" * 80)
    print("  GOOGLE ADK CLINICAL AGENT HARNESS CONSOLE")
    print(f"  Mode: {mode_str} | Session ID: {session.session_id}")
    print("  Type 'exit', 'quit', or 'q' to end the session.")
    print("=" * 80)

    while True:
        try:
            prompt = input("\n[Clinician Prompt] > ").strip()
            if not prompt:
                continue
            if prompt.lower() in ("exit", "quit", "q"):
                print("Exiting harness console.")
                break

            print(f"\n[*] Dispatching to Agent Harness (Turn {len(session.messages) // 2 + 1})...")
            response = await harness.run(prompt=prompt, session=session)

            print(f"\n[Safety Gate Route]: {response.route} | [Status]: {response.status}")
            if response.attested:
                print("  --> [Attested \u2713] Numeric boundaries verified against canonical ontology.")

            if response.tool_calls:
                print(f"\n[*] MCP Tools Intercepted & Executed ({len(response.tool_calls)}):")
                for tc in response.tool_calls:
                    print(f"    - {tc.tool_name}({tc.args})")

            print("\n[Harness Output]:")
            for line in response.text.splitlines():
                print(f"  {line}")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting harness console.")
            break
        except Exception as e:
            print(f"\n[Error]: {e}", file=sys.stderr)


if __name__ == "__main__":
    offline_flag = "--offline" in sys.argv
    asyncio.run(run_interactive_console(offline=offline_flag))
