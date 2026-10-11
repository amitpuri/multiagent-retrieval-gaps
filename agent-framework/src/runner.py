"""
Scenario Runner for Microsoft Agent Framework (MAF).
Runs Scenarios A, B, C, and D — matching the Google ADK and Strands implementations.
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ── Path setup ─────────────────────────────────────────────────────────────────
_agent_framework_dir = Path(__file__).resolve().parent.parent
_repo_root = _agent_framework_dir.parent

for p in (str(_repo_root), str(_agent_framework_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Load src/.env (contains OPENAI_API_KEY for local testing)
load_dotenv(dotenv_path=_agent_framework_dir / "src" / ".env", override=False)

from src.orchestration.workflow_runner import run_scenario
from ontogate.config import get_default_registry, load_scenario_extension
from src.tools import panel_workup


def is_live_mode() -> bool:
    """Check if live mode is requested and credentials are available."""
    if "--offline" in sys.argv:
        return False
    if os.environ.get("MAF_OFFLINE_MODE", "").lower() in ("true", "1", "yes"):
        return False
    return bool(
        os.environ.get("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
        or os.environ.get("AZURE_OPENAI_ENDPOINT")
        or os.environ.get("OPENAI_API_KEY")
    )


async def run_scenario_a():
    """Scenario A (Q5): Ambiguity, unit mismatch, and resolution — Hb."""
    print("\n" + "=" * 80)
    print("SCENARIO A: Q5 ('Hb 13.5' — Multi-Agent MAF Declarative Pipeline)")
    print("=" * 80)

    live = is_live_mode()
    mode = "Live via OPENAI_API_KEY (OpenAI Agents SDK)" if live else "Offline / Deterministic"
    print(f"[*] Mode: {mode}")

    turns = [
        ("Turn 1: Ambiguous — No Unit",         "Hb 13.5"),
        ("Turn 2: Valid Unit — Resolves",        "Hb 13.5 | g/dL"),
        ("Turn 3: Invalid Unit — Mismatch",      "Hb 13.5 | mg/dL"),
    ]

    for label, query in turns:
        print(f"\n--- {label} ---")
        print(f"Clinician Query: \"{query}\"")
        result = await run_scenario(query, offline=not live)
        _print_result(result)


def _print_workup(workup: dict) -> None:
    for tube in workup.get("tubes", []):
        print(f"\n  Tube {tube['tube']} — {tube['department']}")
        for t in tube["tests"]:
            print(f"    - {t['test_name']} [{t['uri']}]")


def run_scenario_b():
    """Scenario B (Q6): CSF emergency panel — tube sequence enforcement (Gap 11)."""
    print("\n" + "=" * 80)
    print("SCENARIO B: Q6 (CSF Emergency Panel — Governed Tube Ordering, Gap 11)")
    print("=" * 80)

    print("\nFull Emergency CSF Workup (ordered by the ontology's precedes relation):")
    _print_workup(panel_workup("csf_emergency_panel"))
    print("\nDepartment-Scoped Workup (Hematology only):")
    _print_workup(panel_workup("csf_emergency_panel", "hemat"))


async def run_scenario_c():
    """Scenario C (Q7): Calcium 4.8 mg/dL look-alike range collision."""
    print("\n" + "=" * 80)
    print("SCENARIO C: Q7 (Calcium 4.8 mg/dL — Look-Alike Collision, Gap 8)")
    print("=" * 80)

    live = is_live_mode()
    turns = [
        ("Unqualified — collision expected",     "Calcium 4.8 | mg/dL"),
        ("Qualified Total — resolved",           "Calcium 4.8 | mg/dL | total"),
        ("Qualified Ionized — resolved",         "Calcium 4.8 | mg/dL | ionized"),
    ]

    for label, query in turns:
        print(f"\n--- {label} ---")
        print(f"Clinician Query: \"{query}\"")
        result = await run_scenario(query, offline=not live)
        _print_result(result)


async def run_scenario_d():
    """Scenario D: Config-driven cardiac troponin extension via YAML."""
    print("\n" + "=" * 80)
    print("SCENARIO D: Dynamic Config-Driven Extension (Cardiac Troponin)")
    print("=" * 80)

    registry = get_default_registry()
    scenario_path = _repo_root / "config" / "scenarios" / "scenario_d_troponin.yaml"
    if scenario_path.exists():
        load_scenario_extension(scenario_path, registry)
        print(f"[*] Dynamically loaded: {scenario_path.name}")
    else:
        print(f"[!] Scenario file not found: {scenario_path} — running with base registry")

    live = is_live_mode()
    turns = [
        ("Turn 1: Ambiguous — No Unit",      "Troponin 15"),
        ("Turn 2: Valid Unit — Resolves",    "Troponin 15 | ng/L"),
        ("Turn 3: Unit Mismatch",            "Troponin 15 | mg/dL"),
    ]

    for label, query in turns:
        print(f"\n--- {label} ---")
        print(f"Clinician Query: \"{query}\"")
        result = await run_scenario(query, offline=not live)
        _print_result(result)


def _print_result(result: dict):
    """Pretty-print a pipeline result."""
    route = result.get("route", "UNKNOWN")
    status = result.get("status", "UNKNOWN")
    print(f"  [Safety Gate Route]: {route}")
    print(f"  [Resolution Status]: {status}")

    if route == "CLARIFY":
        print(f"  --> Clarification: \"{result.get('clarification', result.get('output', ''))}\"")
    elif route == "PROCEED":
        proto = result.get("protocol", {})
        protocol_detail = proto.get("protocol", {}) if isinstance(proto, dict) else {}
        candidates = result.get("resolved", {}).get("candidates", [])
        if candidates:
            c = candidates[0]
            print(f"  --> Resolved: {c.get('label')} [{c.get('uri')}]")
        if protocol_detail:
            print(f"  --> Reference Range: {protocol_detail.get('reference_range')}")
            print(f"  --> Panic Limits:    {protocol_detail.get('panic_limits')}")
        output = result.get("output", "")
        if output:
            print(f"  --> Output: {output}")
    else:
        print(f"  --> Output: {result.get('output', result)}")


async def main():
    await run_scenario_a()
    run_scenario_b()
    await run_scenario_c()
    await run_scenario_d()


if __name__ == "__main__":
    asyncio.run(main())
