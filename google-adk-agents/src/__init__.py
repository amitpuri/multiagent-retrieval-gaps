"""
Google ADK implementation of Laboratory Medicine Decision Support.
Based on 'Information Retrieval, Part III: When the Retriever Has to Decide'.
"""

from src.agents import MODEL, grounded_agent_v1, naive_agent, synthesize
from src.ontology import CONCEPTS, CSF_TESTS, LAB_KB, PROTOCOLS, RANGES
from src.runner import (
    run_scenario_a_workflow,
    run_scenario_b_csf,
    run_scenario_c_calcium,
)
from src.tools import (
    check_calcium,
    classify,
    csf_workup,
    fetch_grounded_protocol,
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
    "grounded_agent_v1",
    "synthesize",
    # Ontology Knowledge
    "CONCEPTS",
    "PROTOCOLS",
    "CSF_TESTS",
    "RANGES",
    "LAB_KB",
    # Tools
    "search_lab_kb",
    "resolve_lab_term",
    "fetch_grounded_protocol",
    "csf_workup",
    "classify",
    "check_calcium",
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
