"""
Execution runner demonstrating ADK laboratory workflows using live Gemini models.
Loads GEMINI_API_KEY from src/.env and executes the three scenarios from:
'Information Retrieval, Part III: When the Retriever Has to Decide'
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

# Configure UTF-8 encoding for standard streams (Windows compatibility)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure repo and package root are in sys.path
_adk_dir = Path(__file__).resolve().parent.parent
_repo_root = _adk_dir.parent
for p in (str(_repo_root), str(_adk_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Ensure .env is loaded from src/.env or current working directory
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

from google.adk import Event, Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from src.agents import MODEL, prompt_governed_agent, naive_agent
from src.naive_kb import LAB_KB
from src.tools import classify_lookalikes, evaluate_safety_gate, panel_workup, search_lab_kb
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


def is_live_mode() -> bool:
    """Check if a Gemini API key is configured and not forced offline."""
    if "--offline" in os.sys.argv:
        return False
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    return bool(key)


async def run_scenario_a_workflow():
    """Execute Scenario A (Q5): Ambiguity resolution with ADK graph & live Gemini synthesis."""
    print("=" * 80)
    print("SCENARIO A: Q5 ('Hb 13.5') - ADK DETERMINISTIC WORKFLOW GRAPH")
    print("=" * 80)

    live = is_live_mode()
    target = None if live else stub_synthesize
    mode_str = f"Live Gemini ({MODEL})" if live else "Offline Stub"
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


def _print_workup(workup: dict) -> None:
    for tube in workup.get("tubes", []):
        print(f"\n  Tube {tube['tube']} — {tube['department']}")
        for t in tube["tests"]:
            print(f"    - {t['test_name']} [{t['uri']}]")


def run_scenario_b_csf():
    """Execute Scenario B (Q6): CSF emergency panel — governed tube order (Gap 11)."""
    print("\n" + "=" * 80)
    print("SCENARIO B: Q6 (CSF Emergency Panel - Governed Tube Ordering, Gap 11)")
    print("=" * 80)
    print("\nFull Emergency CSF Workup (ordered by the ontology's precedes relation):")
    _print_workup(panel_workup("csf_emergency_panel"))
    print("\nDepartment-Scoped Workup (Hematology only):")
    _print_workup(panel_workup("csf_emergency_panel", "hemat"))


def run_scenario_c_calcium():
    """Execute Scenario C (Q7): Calcium 4.8 mg/dL look-alike collision."""
    print("\n" + "=" * 80)
    print("SCENARIO C: Q7 (Calcium 4.8 mg/dL - Look-Alike Tests & Deterministic Collision)")
    print("=" * 80)

    val = 4.8
    readings = classify_lookalikes("calcium", val, "mg/dL")["readings"]
    gate = evaluate_safety_gate(term="calcium", unit="mg/dL", patient_value=val)
    print(f"\nUnqualified Calcium {val} mg/dL:")
    for assay, interpretation in readings.items():
        print(f"    - {assay}: {interpretation}")
    print(f"  Gate: {gate['status']} -> {gate['route']}")
    print(f"  Clarification: {gate['clarification_prompt']}")

    for qualifier in ("total", "ionized"):
        gate = evaluate_safety_gate(term="calcium", unit="mg/dL", qualifier=qualifier, patient_value=val)
        print(f"\nQualified '{qualifier}' Calcium {val} mg/dL:")
        print(f"  Gate: {gate['status']} -> {gate['route']}  Readings: {gate['details'].get('readings')}")


async def run_scenario_d_multiagent_troponin():
    """Execute Scenario D: Config-driven Cardiac Troponin look-alike test case via Multi-Agent A2A."""
    print("\n" + "=" * 80)
    print("SCENARIO D: DYNAMIC CONFIG-DRIVEN EXTENSION (Cardiac Troponin via Multi-Agent A2A)")
    print("=" * 80)

    # 1. Dynamically load scenario D from YAML into default registry
    from ontogate.config import get_default_registry, load_scenario_extension
    from src.orchestration.a2a_orchestrator import build_multiagent_workflow

    registry = get_default_registry()
    # __file__ is google-adk-agents/src/runner.py — walk up src -> google-adk-agents -> repo root
    scenario_path = Path(__file__).resolve().parent.parent.parent / "config" / "scenarios" / "scenario_d_troponin.yaml"
    load_scenario_extension(scenario_path, registry)
    print(f"[*] Dynamically loaded scenario extension from: {scenario_path.name}")

    live = is_live_mode()
    target = None if live else stub_synthesize
    mode_str = f"Live Gemini ({MODEL})" if live else "Offline Stub"
    print(f"[*] Multi-Agent Orchestration Mode: {mode_str}")

    workflow = build_multiagent_workflow(name="multiagent_troponin_demo", synthesize_target=target)
    runner = Runner(
        app_name="multiagent_lab_app",
        agent=workflow,
        session_service=InMemorySessionService(),
        auto_create_session=True,
    )

    user_id = "clinician_dr_puri"
    session_id = "session_troponin_ext"

    def make_msg(text: str) -> types.Content:
        return types.Content(role="user", parts=[types.Part(text=text)])

    test_turns = [
        ("Troponin 15", "Turn 1: Ambiguous order 'Troponin 15' without unit (I vs T hazard)"),
        ("Troponin 15 | ng/L", "Turn 2: Clinician clarifies unit 'ng/L' (resolves to hs-cTnT)"),
        ("Troponin 15 | mg/dL", "Turn 3: Clinician submits incompatible unit 'mg/dL'"),
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

            # Check for HITL Pause
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        if fc.name == "adk_request_input":
                            msg = fc.args.get("message", "")
                            print(f"\n  [A2A PAUSED: RequestInput to Clinician]")
                            print(f"  --> Gate Route: CLARIFY")
                            print(f"  --> Prompt: \"{msg}\"\n")
                    elif hasattr(part, "text") and part.text:
                        print(f"\n  [{node_name}] Multi-Agent Clinical Synthesis:\n")
                        for line in part.text.strip().splitlines():
                            print(f"    {line}")

            if event.actions and event.actions.route:
                print(f"  [A2A Event] route={event.actions.route}")

            if event.output and isinstance(event.output, dict):
                # Inspect A2A envelopes
                if "a2a_triage_message" in event.output:
                    m = event.output["a2a_triage_message"]
                    sender = m["sender"] if isinstance(m["sender"], str) else m["sender"].value
                    recip = m["recipient"] if isinstance(m["recipient"], str) else m["recipient"].value
                    action = m["action"] if isinstance(m["action"], str) else m["action"].value
                    print(f"  [A2A] {sender} --> {recip}: {action}")
                if "a2a_message" in event.output:
                    m = event.output["a2a_message"]
                    sender = m["sender"] if isinstance(m["sender"], str) else m["sender"].value
                    recip = m["recipient"] if isinstance(m["recipient"], str) else m["recipient"].value
                    action = m["action"] if isinstance(m["action"], str) else m["action"].value
                    status = m.get("status", "")
                    if status and not isinstance(status, str):
                        status = status.value
                    print(f"  [A2A] {sender} --> {recip}: {action} (Status: {status})")
                if "a2a_safety_message" in event.output:
                    m = event.output["a2a_safety_message"]
                    sender = m["sender"] if isinstance(m["sender"], str) else m["sender"].value
                    recip = m["recipient"] if isinstance(m["recipient"], str) else m["recipient"].value
                    action = m["action"] if isinstance(m["action"], str) else m["action"].value
                    status = m.get("status", "")
                    if status and not isinstance(status, str):
                        status = status.value
                    print(f"  [A2A] {sender} --> {recip}: {action} (Status: {status})")
                if "a2a_protocol_message" in event.output:
                    m = event.output["a2a_protocol_message"]
                    sender = m["sender"] if isinstance(m["sender"], str) else m["sender"].value
                    recip = m["recipient"] if isinstance(m["recipient"], str) else m["recipient"].value
                    action = m["action"] if isinstance(m["action"], str) else m["action"].value
                    print(f"  [A2A] {sender} --> {recip}: {action}")
                if "protocol" in event.output:
                    uri = event.output.get("resolved_uri")
                    proto = event.output.get("protocol", {})
                    print(f"  [{node_name}] Grounded Protocol fetched for {uri}")
                    print(f"  [{node_name}] Reference range: {proto.get('reference_range')}")


def _summarise(res) -> str:
    """Build a rich one-line output summary from a HarnessResponse.

    Priority order:
      1. res.text      — model generated prose (direct Gemini output)
      2. res.protocol  — grounded protocol fields (uri, reference_range, etc.)
      3. tool results  — last tool call result dict surfaced as key=value pairs
      4. res.clarification — HITL clarification question
      5. generic fallback based on route/status
    """
    # 1. Model prose (first non-empty stripped line)
    if res.text and res.text.strip():
        lines = [line.strip() for line in res.text.splitlines() if line.strip()]
        if lines:
            first = lines[0]
            # If the first line is just a status header like "[PROCEED]" or "[CLARIFY]",
            # append the second line for richer context
            if len(lines) > 1 and first in ("[PROCEED]", "[CLARIFY]", "[PROCEED [Attested ✓]]"):
                return f"{first} {lines[1]}"[:220]
            return first[:220]

    # 2. Protocol fields
    p = res.protocol or {}
    p = p.get("protocol", p)
    if p:
        parts = []
        if p.get("uri") or p.get("loinc_uri"):
            parts.append(f"URI: {p.get('uri') or p.get('loinc_uri')}")
        if p.get("reference_range"):
            parts.append(f"Ref range: {p['reference_range']}")
        if p.get("panic_limits"):
            parts.append(f"Panic: {p['panic_limits']}")
        elif p.get("panic_low") is not None or p.get("panic_high") is not None:
            parts.append(f"Panic: {p.get('panic_low')}–{p.get('panic_high')}")
        if p.get("unit"):
            parts.append(f"Unit: {p['unit']}")
        if parts:
            badge = " [Attested ✓]" if getattr(res, "attested", False) else ""
            return f"[{res.route}{badge}] " + " | ".join(parts)

    # 3. Last tool call result (flatten to key=value pairs, skip large blobs)
    if res.tool_calls:
        last = res.tool_calls[-1]
        result = last.result or {}
        if isinstance(result, dict):
            snippets = []
            for k, v in result.items():
                if k in ("candidates", "departments"):
                    continue  # skip big lists
                sv = str(v)
                if len(sv) < 120:
                    snippets.append(f"{k}={sv}")
            if snippets:
                return f"[{last.tool_name}] " + " | ".join(snippets[:4])

    # 4. Clarification question
    if res.clarification:
        return f"[CLARIFY] {res.clarification}"

    # 5. Generic fallback
    return f"[{res.route}] {res.status}"


async def run_harness_scenarios():
    """Execute all clinical scenarios through the newly constructed FastMCP Agent Harness."""
    from src.harness.agent import ClinicalADKHarness

    print("\n" + "=" * 80)
    print("  GOOGLE ADK AGENT HARNESS (FASTMCP PROTOCOL & CONTINUOUS REASONING LOOP)")
    print("=" * 80)

    live = is_live_mode()
    mode_str = f"Live Gemini ({MODEL})" if live else "Offline Deterministic Harness"
    print(f"[*] Harness Execution Mode: {mode_str}\n")

    harness = ClinicalADKHarness(offline=not live)

    # ── Scenario A via Harness: Hb Ambiguity Resolution ─────────────────────
    print("-" * 80)
    print("HARNESS SCENARIO A: 'Hb 13.5' Multi-turn Reasoning & Unit Disambiguation")
    print("-" * 80)
    session_a = harness.create_session("harness_session_a")
    turns = [
        ("Turn 1 (Ambiguous term without unit):", "Hb 13.5"),
        ("Turn 2 (Clinician provides valid unit 'g/dL'):", "Hb 13.5 | g/dL"),
        ("Turn 3 (Clinician submits invalid unit 'mg/dL'):", "Hb 13.5 | mg/dL"),
    ]
    for desc, query in turns:
        print(f"\n{desc} '{query}'")
        res = await harness.run(prompt=query, session=session_a)
        print(f"  [Route]: {res.route} | [Status]: {res.status} | [HITL Paused]: {res.is_hitl_paused}")
        if res.attested:
            print("  --> [Attested ✓] Numeric range certified by authoritative protocol.")
        if res.tool_calls:
            print(f"  --> MCP Tools Executed ({len(res.tool_calls)}): {[t.tool_name for t in res.tool_calls]}")
        print(f"  [Output Summary]: {_summarise(res)}")

    # ── Scenario B via Harness: Emergency CSF Tube Sequence ─────────────────
    print("\n" + "-" * 80)
    print("HARNESS SCENARIO B: CSF Emergency Panel Governed Tube Ordering")
    print("-" * 80)
    session_b = harness.create_session("harness_session_b")
    res_b = await harness.run(prompt="CSF workup | hematology", session=session_b)
    print(f"  [Route]: {res_b.route} | [Status]: {res_b.status}")
    print(f"  --> MCP Tools Executed: {[t.tool_name for t in res_b.tool_calls]}")
    print(f"  [Output Summary]: {_summarise(res_b)}")

    # ── Scenario C via Harness: Calcium Look-alike Collision ────────────────
    print("\n" + "-" * 80)
    print("HARNESS SCENARIO C: Calcium 4.8 mg/dL Look-alike Collision")
    print("-" * 80)
    session_c = harness.create_session("harness_session_c")
    res_c1 = await harness.run(prompt="Calcium 4.8 mg/dL", session=session_c)
    print(f"Unqualified Calcium 4.8 mg/dL:")
    print(f"  [Route]: {res_c1.route} | [Status]: {res_c1.status} | [HITL Paused]: {res_c1.is_hitl_paused}")
    print(f"  [Clarification]: {res_c1.clarification}")

    res_c2 = await harness.run(prompt="Total Calcium 4.8 mg/dL | mg/dL", session=session_c)
    print(f"\nQualified Total Calcium 4.8 mg/dL:")
    print(f"  [Route]: {res_c2.route} | [Status]: {res_c2.status}")
    if res_c2.attested:
        print("  --> [Attested ✓] Certified against Total Calcium reference boundaries.")
    print(f"  [Output Summary]: {_summarise(res_c2)}")


async def main():
    if "--harness" in sys.argv:
        await run_harness_scenarios()
    else:
        await run_scenario_a_workflow()
        run_scenario_b_csf()
        run_scenario_c_calcium()
        await run_scenario_d_multiagent_troponin()


if __name__ == "__main__":
    asyncio.run(main())
