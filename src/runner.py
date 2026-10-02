"""
Execution runner demonstrating ADK laboratory workflows using live Gemini models.
Loads GEMINI_API_KEY from src/.env and executes the three scenarios from:
'Information Retrieval, Part III: When the Retriever Has to Decide'
"""

import asyncio
import os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

# Ensure .env is loaded from src/.env or current working directory
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

from google.adk import Event, Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from src.agents import MODEL, grounded_agent_v1, naive_agent
from src.ontology import LAB_KB
from src.tools import check_calcium, csf_workup, search_lab_kb
from src.workflow import build_lab_workflow


def stub_synthesize(node_input: Any) -> Event:
    """Fallback stub for synthesis when no API key is available."""
    protocol = node_input.get("protocol", {})
    concept = node_input.get("concept", {})
    patient_value = node_input.get("patient_value")
    output_text = (
        f"[Synthesized Output - Grounded Interpretation]\n"
        f"Resolved Concept: {concept.get('label')} ({node_input.get('resolved_uri')})\n"
        f"Department: {concept.get('department')}\n"
        f"Patient Value: {patient_value}\n"
        f"Reference Range: {protocol.get('reference_range')}\n"
        f"Panic Limits: {protocol.get('panic_limits')}\n"
        f"Summary: Verified protocol retrieved via canonical ontology."
    )
    return Event(output=output_text)


async def run_scenario_a_workflow():
    """Execute Scenario A (Q5): Ambiguity resolution with ADK graph & live Gemini synthesis."""
    print("=" * 80)
    print("SCENARIO A: Q5 ('Hb 13.5') - ADK DETERMINISTIC WORKFLOW GRAPH")
    print("=" * 80)

    has_api_key = bool(os.environ.get("GEMINI_API_KEY"))
    target = None if has_api_key else stub_synthesize
    mode_str = f"Live Gemini ({MODEL})" if has_api_key else "Offline Stub"
    print(f"[*] Synthesis Mode: {mode_str}")

    workflow = build_lab_workflow(name="lab_demo", synthesize_target=target)
    runner = Runner(
        app_name="lab_app",
        agent=workflow,
        session_service=InMemorySessionService(),
        auto_create_session=True,
    )

    user_id = "clinician_dr_puri"
    session_id = "session_visit_d11"

    def make_msg(text: str) -> types.Content:
        return types.Content(role="user", parts=[types.Part(text=text)])

    test_turns = [
        ("Hb 13.5", "Turn 1: Ambiguous test name without unit"),
        ("Hb 13.5 | g/dL", "Turn 2: Follow-up providing unit 'g/dL'"),
        ("Hb 13.5 | mg/dL", "Turn 3: Invalid unit 'mg/dL' submitted"),
    ]

    for user_input, description in test_turns:
        print(f"\n--- {description} ---")
        print(f"Clinician message: '{user_input}'")
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=make_msg(user_input),
        ):
            node_name = event.node_info.path if event.node_info else "unknown"

            # Check for Human-in-the-loop pause (RequestInput)
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        if fc.name == "adk_request_input":
                            msg = fc.args.get("message", "")
                            print(f"\n  [PAUSED: adk_request_input]")
                            print(f"  --> Gate Route: CLARIFY")
                            print(f"  --> Prompt to Clinician: \"{msg}\"\n")
                    elif hasattr(part, "text") and part.text:
                        print(f"\n  [{node_name}] Live Gemini Clinical Synthesis:\n")
                        for line in part.text.strip().splitlines():
                            print(f"    {line}")

            if event.actions and event.actions.route:
                print(f"  [{node_name}] route={event.actions.route}")

            if event.output:
                if isinstance(event.output, dict):
                    status = event.output.get("status")
                    if status:
                        print(f"  [{node_name}] status={status}")
                    if "protocol" in event.output:
                        uri = event.output.get("resolved_uri")
                        proto = event.output.get("protocol", {})
                        print(f"  [{node_name}] Protocol fetched for {uri}")
                        print(f"  [{node_name}] Reference range: {proto.get('reference_range')}")
                elif isinstance(event.output, str):
                    print(f"  [{node_name}] {event.output}")


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


async def main():
    await run_scenario_a_workflow()
    run_scenario_b_csf()
    run_scenario_c_calcium()


if __name__ == "__main__":
    asyncio.run(main())
