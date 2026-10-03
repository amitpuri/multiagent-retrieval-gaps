"""
MAF Workflow Runner — loads declarative agents and the clinical decision workflow,
then runs a single clinical query through the pipeline.

Architecture (plan-aligned):
  1. Deterministic tool chain runs FIRST (parse → resolve → safety gate).
     The safety gate is NEVER delegated to an LLM — it is always pure Python.
  2. MAF AgentFactory is used ONLY for LLM-enriched output text (best-effort).
     If agent_framework is not installed, the deterministic result is returned directly.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

# ── Path setup ─────────────────────────────────────────────────────────────────
_agent_framework_dir = Path(__file__).resolve().parent.parent.parent
_repo_root = _agent_framework_dir.parent

for p in (str(_repo_root), str(_agent_framework_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Load src/.env
load_dotenv(dotenv_path=_agent_framework_dir / "src" / ".env", override=False)

AGENT_DIR = _agent_framework_dir / "declarative-agents"
WORKFLOW_DIR = _agent_framework_dir / "declarative-workflows"

from src.tools import (
    parse_clinician_input,
    resolve_ontology,
    run_safety_gate,
    fetch_protocol,
    build_clarification_prompt,
)

TOOL_BINDINGS: Dict[str, Any] = {
    "parse_clinician_input":    parse_clinician_input,
    "resolve_ontology":         resolve_ontology,
    "run_safety_gate":          run_safety_gate,
    "fetch_protocol":           fetch_protocol,
    "build_clarification_prompt": build_clarification_prompt,
}


def _is_offline() -> bool:
    return (
        "--offline" in sys.argv
        or os.getenv("MAF_OFFLINE_MODE", "false").lower() in ("true", "1", "yes")
    )


def _try_load_agents() -> dict:
    """Attempt to load MAF declarative agents. Returns empty dict if not available."""
    try:
        from src.models.provider import build_agent_factory
        agent_factory = build_agent_factory(offline=False, bindings=TOOL_BINDINGS, safe_mode=False)
        agents = {}
        for yaml_file in sorted(AGENT_DIR.glob("*.yaml")):
            try:
                agent = agent_factory.create_agent_from_yaml_path(yaml_file)
                agents[agent.name] = agent
            except Exception:
                pass
        return agents
    except (ImportError, RuntimeError):
        return {}


async def run_scenario(raw_query: str, offline: bool | None = None) -> Dict[str, Any]:
    """Load the declarative workflow and run a single clinical query.

    Args:
        raw_query: Raw clinician input (e.g. "Hb 13.5 | g/dL").
        offline:   If True, use offline/mock mode; if None, auto-detect from env/argv.

    Returns:
        Result dict from the workflow with route, status, and output.
    """
    if offline is None:
        offline = _is_offline()

    if offline:
        return _offline_pipeline(raw_query)

    # ── Step 1: Deterministic tool chain (safety gate NEVER delegated to LLM) ──
    parsed = parse_clinician_input(raw_query)
    resolved = resolve_ontology(
        term=parsed["term"],
        unit=parsed["unit"],
        qualifier=parsed["qualifier"],
        patient_value=parsed["patient_value"],
    )
    gate = run_safety_gate(
        term=resolved["term"],
        unit=resolved["unit"],
        qualifier=resolved["qualifier"],
        patient_value=resolved["patient_value"],
        status=resolved["status"],
    )
    route = gate["route"]

    # ── Step 2: Attempt MAF agent enrichment (best-effort, fails gracefully) ──
    agents = _try_load_agents()

    # ── PROCEED path ────────────────────────────────────────────────────────────
    if route == "PROCEED":
        candidates = resolved.get("candidates", [])
        if candidates:
            resolved_uri = candidates[0].get("uri", "")
            concept = candidates[0]
            protocol_data = fetch_protocol(
                resolved_uri=resolved_uri,
                concept=concept,
                patient_value=parsed["patient_value"],
            )
        else:
            protocol_data = {}

        output_text = ""
        protocol_agent = agents.get("protocol_retriever")
        if protocol_agent is not None:
            try:
                proto = protocol_data.get("protocol", {})
                agent_prompt = (
                    f"Summarise protocol for: term={resolved.get('term')}, "
                    f"unit={resolved.get('unit')}, "
                    f"reference_range={proto.get('reference_range')}, "
                    f"panic_limits={proto.get('panic_limits')}."
                )
                resp = await protocol_agent.run(agent_prompt)
                output_text = resp.text if hasattr(resp, "text") and resp.text else str(resp)
            except Exception:
                output_text = ""

        prefix = "[LIVE]" if agents else "[LIVE-DETERMINISTIC]"
        return {
            "route": route,
            "status": gate["status"],
            "parsed": parsed,
            "resolved": resolved,
            "gate": gate,
            "protocol": protocol_data,
            "output": output_text or (
                f"{prefix} PROCEED — {resolved.get('status')} | "
                f"Protocol fetched for {protocol_data.get('resolved_uri', 'N/A')}"
            ),
        }

    # ── CLARIFY path ────────────────────────────────────────────────────────────
    clarification = build_clarification_prompt(
        status=gate["status"],
        candidates=gate.get("candidates", []),
        term=parsed["term"],
        collision_details=gate.get("details"),
    )
    clarification_text = clarification.get("clarification_prompt", "")

    clarification_agent = agents.get("clarification_agent")
    if clarification_agent is not None:
        try:
            resp = await clarification_agent.run(
                f"Generate a clinician-friendly clarification for: {clarification_text}"
            )
            clarification_text = resp.text if hasattr(resp, "text") and resp.text else clarification_text
        except Exception:
            pass

    prefix = "[LIVE]" if agents else "[LIVE-DETERMINISTIC]"
    return {
        "route": route,
        "status": gate["status"],
        "parsed": parsed,
        "resolved": resolved,
        "gate": gate,
        "clarification": clarification_text,
        "output": f"{prefix} CLARIFY — {gate['status']} | {clarification_text}",
    }


def _offline_pipeline(raw_query: str) -> Dict[str, Any]:
    """Deterministic offline pipeline — calls tools directly, no LLM or AgentFactory."""
    parsed = parse_clinician_input(raw_query)
    resolved = resolve_ontology(
        term=parsed["term"],
        unit=parsed["unit"],
        qualifier=parsed["qualifier"],
        patient_value=parsed["patient_value"],
    )
    gate = run_safety_gate(
        term=resolved["term"],
        unit=resolved["unit"],
        qualifier=resolved["qualifier"],
        patient_value=resolved["patient_value"],
        status=resolved["status"],
    )

    route = gate["route"]

    if route == "PROCEED":
        candidates = resolved.get("candidates", [])
        if candidates:
            resolved_uri = candidates[0].get("uri", "")
            concept = candidates[0]
            protocol_data = fetch_protocol(
                resolved_uri=resolved_uri,
                concept=concept,
                patient_value=parsed["patient_value"],
            )
        else:
            protocol_data = {}

        return {
            "route": route,
            "status": gate["status"],
            "parsed": parsed,
            "resolved": resolved,
            "gate": gate,
            "protocol": protocol_data,
            "output": f"[OFFLINE] PROCEED — {resolved.get('status')} | "
                      f"Protocol fetched for {protocol_data.get('resolved_uri', 'N/A')}",
        }

    clarification = build_clarification_prompt(
        status=gate["status"],
        candidates=gate.get("candidates", []),
        term=parsed["term"],
        collision_details=gate.get("details"),
    )
    return {
        "route": route,
        "status": gate["status"],
        "parsed": parsed,
        "resolved": resolved,
        "gate": gate,
        "clarification": clarification["clarification_prompt"],
        "output": f"[OFFLINE] CLARIFY — {gate['status']} | {clarification['clarification_prompt']}",
    }
