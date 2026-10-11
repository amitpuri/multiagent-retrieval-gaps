"""
ADK 2.0 Deterministic Workflow Graph for Laboratory Medicine.
Closes Gap 9 (Safety rule lives in prompt) by moving routing policy
out of prompt text into code-enforced graph orchestration with
deterministic gating and Human-In-The-Loop pauses (RequestInput).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Generator, Optional, Union
from google.adk import Agent, Event, Workflow
from google.adk.events import RequestInput
from src.agents import MODEL, create_synthesize_agent
from src.tools import evaluate_safety_gate, fetch_grounded_protocol, resolve_lab_term
from ontogate.parsing import parse_clinician_text

logger = logging.getLogger(__name__)


def route_for(status: str) -> str:
    """Pure routing function, easy to unit test.
    
    Fails closed on unknown statuses: only 'RESOLVED' proceeds to clinical protocol fetch;
    everything else ('AMBIGUOUS', 'UNIT_MISMATCH', 'NOT_FOUND', 'RANGE_COLLISION', 'UNKNOWN')
    routes to 'CLARIFY'.
    """
    return "PROCEED" if status == "RESOLVED" else "CLARIFY"


def parse(node_input: Any) -> Event:
    """Parser node: ontology-aware parse of clinician input (shared ``ontogate`` parser).

    Pipe segments are classified by vocabulary — unit, facet qualifier,
    population (sex / age band), department — not by position::

        Hb | g/dL
        Hb 13.5 | g/dL
        Calcium 4.8 | total | mg/dL
        Calcium 4,8 | mg/dL           ← comma-decimal normalised
        Hb 13.5 | female | g/dL       ← population context
        Na+ -3 | mEq/L                ← negative value preserved
        Troponin 1,250 | ng/L         ← ambiguous thousands separator → value None
    """
    if hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text
    elif isinstance(node_input, dict) and "text" in node_input:
        text = node_input["text"]
    else:
        text = str(node_input)
    return Event(output=parse_clinician_text(text))


def resolve_node(node_input: Dict[str, Any]) -> Event:
    """Ontology resolution node: maps term, unit, and qualifier to canonical LOINC concepts."""
    term = node_input.get("term", "")
    unit = node_input.get("unit", "")
    qualifier = node_input.get("qualifier", "")
    resolution = resolve_lab_term(term, unit, qualifier=qualifier)

    # Carry forward patient value, qualifier, unit, term, and parse metadata for downstream
    # gate / synthesis.  unit is forwarded so fetch_node can preserve reported_unit.
    resolution["term"] = term
    resolution["patient_value"] = node_input.get("patient_value")
    resolution["qualifier"] = qualifier
    resolution["unit"] = unit
    resolution["ambiguous_thousands"] = node_input.get("ambiguous_thousands", False)
    resolution["ambiguous_value"] = node_input.get("ambiguous_value", False)
    resolution["population"] = node_input.get("population", {})
    resolution["department"] = node_input.get("department", "")
    resolution["panel_id"] = node_input.get("panel_id")
    return Event(output=resolution)


def gate(node_input: Dict[str, Any]) -> Event:
    """Deterministic routing node — no LLM invocation.

    Runs the full SafetyGateEngine (via the canonical ``evaluate_safety_gate``
    tool), so this workflow path and the harness path reach identical verdicts.

    Special cases:
    - Ambiguous thousands separator from parser → immediate CLARIFY.
    - Engine verdict overrides resolver-level status.
    """
    # Ambiguous thousands guard
    if node_input.get("ambiguous_thousands"):
        clarification = (
            "Value contains an ambiguous comma that looks like a thousands separator "
            "(e.g. '1,250'). Please resend with an unambiguous decimal format."
        )
        output = dict(node_input)
        output["status"] = "AMBIGUOUS"
        output["clarification"] = clarification
        return Event(output=output, route="CLARIFY")

    # multiple numeric values in input — don't silently pick the first.
    if node_input.get("ambiguous_value"):
        clarification = (
            "Input contains multiple numeric values (e.g. 'Calcium 48 4.8'). "
            "Please resend with a single unambiguous numeric value."
        )
        output = dict(node_input)
        output["status"] = "AMBIGUOUS"
        output["clarification"] = clarification
        return Event(output=output, route="CLARIFY")

    population = node_input.get("population") or {}
    verdict = evaluate_safety_gate(
        term=node_input.get("term", ""),
        unit=node_input.get("unit", ""),
        qualifier=node_input.get("qualifier", ""),
        patient_value=node_input.get("patient_value"),
        sex=population.get("sex", ""),
        age_band=population.get("age_band", ""),
        department=node_input.get("department", ""),
        panel_id=node_input.get("panel_id") or "",
    )

    output = dict(node_input)
    output["status"] = verdict["status"]
    output["gate_message"] = verdict["gate_message"]
    output["gate_candidates"] = verdict["candidates"]
    output["gate_details"] = verdict["details"]
    if not verdict["passed"]:
        output["clarification"] = verdict["clarification_prompt"]
    return Event(output=output, route=verdict["route"])


def clarify(node_input: Dict[str, Any]) -> Generator[RequestInput, None, None]:
    """Human-in-the-loop pause node. No LLM invocation here.
    
    Yields RequestInput to pause the workflow until clinician provides missing unit or test.
    """
    status = node_input.get("status", "UNKNOWN")
    candidates = node_input.get("candidates", [])
    labels = ", ".join(c.get("label", "") for c in candidates) or "none"
    message = f"Status {status}. Candidates: {labels}. Which test and unit?"
    yield RequestInput(message=message)


def fetch_node(node_input: Dict[str, Any]) -> Event:
    """Protocol retrieval node: grounded strictly on resolved canonical URI."""
    candidates = node_input.get("candidates", [])
    if candidates and "uri" in candidates[0]:
        uri = candidates[0]["uri"]
        protocol_data = fetch_grounded_protocol(uri)
        # carry the clinician's original reported unit, not the concept's
        # first expected_unit.  Substituting expected_units[0] would silently
        # reclassify e.g. Hb 135 g/L against g/dL thresholds.
        reported_unit = node_input.get("unit", "")
        result = {
            "resolved_uri": uri,
            "concept": candidates[0],
            "protocol": protocol_data,
            "patient_value": node_input.get("patient_value"),
            "reported_unit": reported_unit,
        }
        return Event(output=result)
    return Event(output={"status": "NO_RESOLVED_CANDIDATE"})


def synthesis_gate_node(node_input: Dict[str, Any]) -> Event:
    """Attestation gate between protocol retrieval and synthesis.

    Sits between fetch_node and the synthesiser.

    Checks whether the retrieved protocol was successfully attested.  If the
    attestation failed (e.g. stale protocol, unit mismatch, out-of-range) the
    node routes to 'CLARIFY' instead of letting unattested data flow into the
    synthesis response.  This closes the gap where a stale or misconfigured
    protocol could produce a synthesised answer without a badge.

    Also routes to CLARIFY when there is no resolved URI or
    protocol.  fetch_node returns status='NO_RESOLVED_CANDIDATE' in this case;
    without this guard the synthesiser would run with no protocol data.
    """
    protocol = node_input.get("protocol", {})
    patient_value = node_input.get("patient_value")
    resolved_uri = node_input.get("resolved_uri", "")
    reported_unit = node_input.get("reported_unit", "")

    # fail closed when fetch_node found no resolved candidate.
    if not resolved_uri or node_input.get("status") == "NO_RESOLVED_CANDIDATE":
        output = dict(node_input)
        output["status"] = "NO_RESOLVED_CANDIDATE"
        output["clarification"] = (
            "No resolved protocol URI is available. "
            "The ontology lookup did not find a unique grounded concept — "
            "please provide more specific test name, unit, or qualifier."
        )
        return Event(output=output, route="CLARIFY")

    # Attempt attestation if we have a value and a URI.
    if patient_value is not None and resolved_uri:
        from src.harness.mcp_server import attest_computation  # type: ignore
        try:
            attest_result = attest_computation(
                value=float(patient_value),
                uri=resolved_uri,
                unit=reported_unit,
            )
            output = dict(node_input)
            output["attestation"] = attest_result
            if not attest_result.get("passed"):
                output["status"] = "ATTESTATION_FAILED"
                output["clarification"] = (
                    f"Attestation failed for value {patient_value} {reported_unit} "
                    f"against protocol {resolved_uri}: {attest_result.get('message', '')}"
                )
                return Event(output=output, route="CLARIFY")

            # Attestations are ABox events: they go to the audit port (redacted),
            # never into the git-tracked knowledge log.
            from ontogate.ports import get_audit
            get_audit().record("attestation", {
                "uri": resolved_uri, "unit": reported_unit, "patient_value": patient_value,
                "verdict": attest_result.get("verdict"), "badge": attest_result.get("badge"),
                "is_panic": attest_result.get("is_panic"), "node": "workflow/synthesis_gate_node",
            })
        except Exception as exc:
            output = dict(node_input)
            output["attestation"] = {"passed": False, "error": str(exc)}
            output["status"] = "ATTESTATION_ERROR"
            output["clarification"] = f"Attestation raised an error: {exc}"
            return Event(output=output, route="CLARIFY")
    else:
        # No value to attest — pass through without badge.
        output = dict(node_input)
        output["attestation"] = {"passed": None, "message": "No numeric value to attest"}

    return Event(output=output, route="PROCEED")


def build_lab_workflow(
    name: str = "lab_gate",
    synthesize_target: Union[Agent, Callable[[Any], Event], None] = None,
) -> Workflow:
    """Build and return an ADK Workflow graph with deterministic gating.

    Graph Topology::

        START → parse → resolve_node → gate
        gate --PROCEED→ fetch_node → synthesis_gate_node
          synthesis_gate_node --PROCEED→ synthesize_target
          synthesis_gate_node --CLARIFY→ clarify (attestation failed)
        gate --CLARIFY→ clarify (Human-in-the-loop pause)
    """
    if synthesize_target is None:
        synthesize_target = create_synthesize_agent()

    return Workflow(
        name=name,
        edges=[
            ("START", parse, resolve_node, gate),
            (gate, {"PROCEED": fetch_node, "CLARIFY": clarify}),
            (fetch_node, synthesis_gate_node),
            (synthesis_gate_node, {"PROCEED": synthesize_target, "CLARIFY": clarify}),
        ],
    )


# Default workflow using the single-turn synthesize agent
root_agent = build_lab_workflow()

# Re-export multi-agent orchestrator workflow
from src.orchestration.a2a_orchestrator import (
    build_multiagent_workflow,
    parse_clinician_input,
)
