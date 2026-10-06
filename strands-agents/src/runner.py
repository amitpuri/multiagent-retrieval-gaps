"""
Scenario Runner for Strands Agents SDK & Amazon Bedrock AgentCore.
Runs Scenarios A, B, C, and D matching the Google ADK implementation.
"""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure repo and package root are in sys.path
_strands_dir = Path(__file__).resolve().parent.parent
_repo_root = _strands_dir.parent
for p in (str(_repo_root), str(_strands_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Load local .env
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

from src.orchestration.strands_orchestrator import (
    StrandsDecisionSupportOrchestrator,
    build_strands_orchestrator,
    parse_clinician_input_direct,
)
from src.core.config import get_default_registry, load_scenario_extension
from src.tools.safety_gate_tool import run_safety_gate
from src.tools_legacy import csf_workup, check_calcium


def is_live_mode() -> bool:
    """Check if live mode is requested and configured (Anthropic API Key or AWS Bedrock)."""
    if "--offline" in sys.argv:
        return False
    if os.environ.get("STRANDS_OFFLINE_MODE", "").lower() in ("true", "1", "yes"):
        return False
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
    )


async def run_scenario_a_interactive():
    """Execute Scenario A (Q5): Ambiguity, unit mismatch, and resolution."""
    print("\n" + "=" * 80)
    print("SCENARIO A: Q5 ('Hb 13.5' - Multi-Agent Strands Supervisor & AgentCore)")
    print("=" * 80)

    live = is_live_mode()
    mode_str = "Live Claude (AWS Bedrock)" if live else "Offline Mock / Deterministic Pipeline"
    print(f"[*] Orchestration Mode: {mode_str}")

    orchestrator = build_strands_orchestrator(offline=not live, session_id="scenario-a-session")

    turns = [
        ("Turn 1: Ambiguous Term Without Unit", "Hb 13.5"),
        ("Turn 2: Provided Valid Unit (Resolves)", "Hb 13.5 | g/dL"),
        ("Turn 3: Provided Invalid Unit (Unit Mismatch)", "Hb 13.5 | mg/dL"),
    ]

    for label, query in turns:
        print(f"\n--- {label} ---")
        print(f"Clinician Query: \"{query}\"")

        res = orchestrator.process_query_direct(query)
        route = res.get("route")
        status = res.get("status")

        print(f"  [Safety Gate Route]: {route}")
        print(f"  [Resolution Status]: {status}")

        if route == "CLARIFY":
            print(f"  --> Prompt to Clinician: \"{res.get('clarification')}\"")
        elif route == "PROCEED":
            concept = res.get("concept", {})
            protocol = res.get("protocol", {}).get("protocol", {})
            print(f"  --> Resolved Concept: {concept.get('label')} [{concept.get('uri')}]")
            print(f"  --> Department: {concept.get('department')}")
            print(f"  --> Reference Range: {protocol.get('reference_range')}")
            print(f"  --> Panic Limits: {protocol.get('panic_limits')}")

            # If live, run agentic synthesis turn — falls back gracefully if API unavailable.
            if live:
                try:
                    agentic_res = orchestrator.process_query_agentic(query)
                    print(f"  --> Live Claude Clinical Synthesis:\n{agentic_res}")
                except Exception as exc:
                    print(
                        f"  [!] Live synthesis skipped — {type(exc).__name__}: {exc}\n"
                        "      Continuing with deterministic result above."
                    )


def run_scenario_b_csf():
    """Execute Scenario B (Q6): CSF emergency panel hierarchical taxonomy & tube ordering."""
    print("\n" + "=" * 80)
    print("SCENARIO B: Q6 (CSF Emergency Panel - Governed Tube Ordering, Closing Gap 11)")
    print("=" * 80)

    full_workup = csf_workup()
    print("\nFull Emergency CSF Workup (Pre-scoped by department & tube order):")
    for dept, tests in full_workup.items():
        print(f"\n  Department: {dept}")
        for t in tests:
            print(f"    - Tube {t['tube']}: {t['test']} [{t['uri']}]")

    print("\nDepartment-Scoped Workup (Hematology only):")
    hemat = csf_workup("hemat")
    for dept, tests in hemat.items():
        print(f"  Department: {dept}")
        for t in tests:
            print(f"    - Tube {t['tube']}: {t['test']} [{t['uri']}]")


def run_scenario_c_calcium():
    """Execute Scenario C (Q7): Calcium 4.8 mg/dL look-alike collision."""
    print("\n" + "=" * 80)
    print("SCENARIO C: Q7 (Calcium 4.8 mg/dL - Look-Alike Tests & Deterministic Collision)")
    print("=" * 80)

    val = 4.8
    unqualified = check_calcium(val)
    print(f"\nUnqualified result for Calcium {val} mg/dL:")
    print(f"  Status: {unqualified['status']}")
    for assay, interpretation in unqualified["readings"].items():
        print(f"    - {assay}: {interpretation}")
    print("  Outcome: Critical low vs Normal collision -> Routed to CLARIFY, prevents lethal IV calcium error.")

    qualified_total = check_calcium(val, "total")
    print(f"\nQualified 'Total Calcium' {val} mg/dL:")
    print(f"  Status: {qualified_total['status']}")
    print(f"  Readings: {qualified_total['readings']}")

    qualified_ionized = check_calcium(val, "ionized")
    print(f"\nQualified 'Ionized Calcium' {val} mg/dL:")
    print(f"  Status: {qualified_ionized['status']}")
    print(f"  Readings: {qualified_ionized['readings']}")


async def run_scenario_d_multiagent_troponin():
    """Execute Scenario D: Config-driven Cardiac Troponin look-alike test case via Strands A2A."""
    print("\n" + "=" * 80)
    print("SCENARIO D: DYNAMIC CONFIG-DRIVEN EXTENSION (Cardiac Troponin via Strands A2A)")
    print("=" * 80)

    registry = get_default_registry()
    # __file__ is strands-agents/src/runner.py — walk up src -> strands-agents -> repo root
    scenario_path = (
        Path(__file__).resolve().parent.parent.parent
        / "config"
        / "scenarios"
        / "scenario_d_troponin.yaml"
    )
    load_scenario_extension(scenario_path, registry)
    print(f"[*] Dynamically loaded scenario extension from: {scenario_path.name}")

    live = is_live_mode()
    mode_str = "Live Claude (AWS Bedrock)" if live else "Offline Mock"
    print(f"[*] Strands Multi-Agent Mode: {mode_str}")

    orchestrator = build_strands_orchestrator(offline=not live, session_id="troponin-session")

    turns = [
        ("Turn 1: Ambiguous Term Without Unit", "Troponin 15"),
        ("Turn 2: Valid Unit Matching Single Concept", "Troponin 15 | ng/L"),
        ("Turn 3: Unit Mismatch Against Extensible Concept", "Troponin 15 | mg/dL"),
    ]

    for label, query in turns:
        print(f"\n--- {label} ---")
        print(f"Clinician Query: \"{query}\"")

        res = orchestrator.process_query_direct(query)
        route = res.get("route")
        status = res.get("status")

        print(f"  [Safety Gate Route]: {route}")
        print(f"  [Resolution Status]: {status}")

        if route == "CLARIFY":
            print(f"  --> Prompt to Clinician: \"{res.get('clarification')}\"")
        elif route == "PROCEED":
            concept = res.get("concept", {})
            protocol = res.get("protocol", {}).get("protocol", {})
            print(f"  --> Resolved Concept: {concept.get('label')} [{concept.get('uri')}]")
            print(f"  --> Reference Range: {protocol.get('reference_range')}")
            print(f"  --> Panic Limits: {protocol.get('panic_limits')}")


async def main() -> None:
    """Run all four scenarios; each scenario is individually guarded."""
    for coro_factory, name in [
        (run_scenario_a_interactive, "Scenario A"),
        (run_scenario_d_multiagent_troponin, "Scenario D"),
    ]:
        try:
            await coro_factory()
        except Exception as exc:
            print(f"\n[!] {name} aborted: {type(exc).__name__}: {exc}")
            print("    Continuing to next scenario...\n")

    for fn, name in [
        (run_scenario_b_csf, "Scenario B"),
        (run_scenario_c_calcium, "Scenario C"),
    ]:
        try:
            fn()
        except Exception as exc:
            print(f"\n[!] {name} aborted: {type(exc).__name__}: {exc}")
            print("    Continuing to next scenario...\n")


if __name__ == "__main__":
    asyncio.run(main())
