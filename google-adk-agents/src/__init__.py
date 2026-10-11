"""
Google ADK implementation of Laboratory Medicine Decision Support.
Based on 'Information Retrieval, Part III: When the Retriever Has to Decide'.
"""

import sys as _sys
from pathlib import Path as _Path


def _ensure_ontogate() -> None:
    """Make the shared ``ontogate`` package importable (installed wheel, else ``shared/`` in a checkout)."""
    try:
        import ontogate  # noqa: F401
    except ImportError:
        for parent in _Path(__file__).resolve().parents:
            if (parent / "shared" / "ontogate" / "__init__.py").is_file():
                _sys.path.insert(0, str(parent / "shared"))
                return
        raise


_ensure_ontogate()

from src.agents import MODEL, prompt_governed_agent, naive_agent, synthesize
from src.naive_kb import LAB_KB
from src.runner import (
    run_scenario_a_workflow,
    run_scenario_b_csf,
    run_scenario_c_calcium,
)
from src.tools import (
    attest_computation,
    classify_lookalikes,
    evaluate_safety_gate,
    fetch_grounded_protocol,
    panel_workup,
    resolve_lab_term,
    search_lab_kb,
)
from src.workflow import (
    build_lab_workflow,
    clarify,
    fetch_node,
    gate,
    parse,
    resolve_node,
    root_agent,
    route_for,
)

__all__ = [
    # Models & Agents
    "MODEL",
    "naive_agent",
    "prompt_governed_agent",
    "synthesize",
    # Naive baseline corpus
    "LAB_KB",
    # Tools (canonical contract)
    "search_lab_kb",
    "resolve_lab_term",
    "evaluate_safety_gate",
    "fetch_grounded_protocol",
    "attest_computation",
    "panel_workup",
    "classify_lookalikes",
    # Workflow
    "route_for",
    "parse",
    "resolve_node",
    "gate",
    "clarify",
    "fetch_node",
    "build_lab_workflow",
    "root_agent",
    # Runners
    "run_scenario_a_workflow",
    "run_scenario_b_csf",
    "run_scenario_c_calcium",
]
