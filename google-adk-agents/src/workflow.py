"""
ADK 2.0 Deterministic Workflow Graph for Laboratory Medicine.
Closes Gap 9 (Safety rule lives in prompt) by moving routing policy
out of prompt text into code-enforced graph orchestration with
deterministic gating and Human-In-The-Loop pauses (RequestInput).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, Generator, Optional, Union
from google.adk import Agent, Event, Workflow
from google.adk.events import RequestInput
from src.agents import MODEL, create_synthesize_agent
from src.core.detectors.engine import SafetyGateEngine
from src.core.models import EvaluationContext
from src.tools import fetch_grounded_protocol, resolve_lab_term

logger = logging.getLogger(__name__)


def route_for(status: str) -> str:
    """Pure routing function, easy to unit test.
    
    Fails closed on unknown statuses: only 'RESOLVED' proceeds to clinical protocol fetch;
    everything else ('AMBIGUOUS', 'UNIT_MISMATCH', 'NOT_FOUND', 'RANGE_COLLISION', 'UNKNOWN')
    routes to 'CLARIFY'.
    """
    return "PROCEED" if status == "RESOLVED" else "CLARIFY"


def parse(node_input: Any) -> Event:
    """Parser node: extracts test term, optional value, and reported unit from clinician input.

    Supports formats::

        Hb
        Hb | g/dL
        Hb 13.5 | g/dL
        Calcium 4.8 | mg/dL
        Calcium 4.8 | total | mg/dL   ← two-pipe: qualifier then unit
        Calcium 4,8 | mg/dL           ← comma-decimal normalised
        Na+ -3 | mEq/L                ← negative value preserved
        25-OH vitamin D 18 | ng/mL   ← leading digit not confused with value

    Rules:
    - Only a digit sequence that is *preceded by whitespace or start-of-string*
      (not by a letter, hyphen, or other non-space) is treated as a numeric value.
    - Comma-decimal notation (``4,8``) is normalised to ``4.8`` before parsing.
    - A leading ``-`` immediately before the digit group is treated as a negative sign
      only when the character before it is whitespace or start-of-string.
    - Fix 5: a comma followed by exactly three digits (e.g. ``1,250``) is treated as
      an ambiguous thousands separator.  patient_value is set to None so the gate
      routes to CLARIFY rather than silently dividing by 1000.
    """
    if hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text
    elif isinstance(node_input, dict) and "text" in node_input:
        text = node_input["text"]
    else:
        text = str(node_input)

    left, _, rest = text.partition("|")
    left_str = left.strip()

    # Two-pipe format: "Calcium 4.8 | total | mg/dL"
    if "|" in rest:
        qualifier_str, _, unit_str = rest.partition("|")
        qualifier_str = qualifier_str.strip()
        unit_str = unit_str.strip()
    else:
        qualifier_str = ""
        unit_str = rest.strip()

    # Fix 5: ambiguous thousands-separator guard.
    # "Troponin 1,250 | ng/L" must NOT silently become 1.25.
    ambiguous_thousands = bool(re.search(r"\b\d+,\d{3}\b", left_str))

    # Normalise comma-decimal notation (e.g. "4,8" -> "4.8") only when NOT thousands.
    left_normalised = left_str
    patient_value: Optional[float] = None
    ambiguous_value: bool = False
    if not ambiguous_thousands:
        left_normalised = re.sub(r"(\d),(\d)", r"\1.\2", left_str)

        # Match a numeric value that is:
        #  - preceded only by whitespace or start-of-string, AND
        #  - NOT immediately followed by a hyphen or word character.
        val_pattern = r"(?:^|(?<=\s))(-?\d+(?:\.\d+)?)(?![\w-])"
        all_val_matches = re.findall(val_pattern, left_normalised)

        # Fix Issue 5: multiple candidate values — flag as ambiguous instead of
        # silently picking the first.  "Calcium 48 4.8 | total | mg/dL" would
        # otherwise silently use 48 and discard 4.8.
        if len(all_val_matches) > 1:
            ambiguous_value = True
            patient_value = None
        elif all_val_matches:
            patient_value = float(all_val_matches[0])

    # Strip the matched number (including its optional sign) from the term.
    cleaned_term = re.sub(r"(?:^|(?<=\s))-?\d+(?:\.\d+)?(?![\w-])", "", left_normalised).strip()
    term = cleaned_term if cleaned_term else left_str.strip()

    return Event(
        output={
            "term": term,
            "unit": unit_str,
            "qualifier": qualifier_str,
            "patient_value": patient_value,
            "raw_text": text,
            "ambiguous_thousands": ambiguous_thousands,
            "ambiguous_value": ambiguous_value,
        }
    )


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
    return Event(output=resolution)


def gate(node_input: Dict[str, Any]) -> Event:
    """Deterministic routing node — no LLM invocation.

    Fix 5 + Fix 9: previously read only the ``status`` key from resolve_node
    output and routed on it — bypassing SafetyGateEngine and all its detectors
    (RangeCollisionDetector, MissingQualifierDetector, etc.).  Now runs the full
    SafetyGateEngine so this workflow path is identical to the harness path.

    Special cases:
    - Ambiguous thousands separator from parser → immediate CLARIFY.
    - Engine verdict overrides resolver-level status.
    """
    # Ambiguous thousands guard (Fix 5)
    if node_input.get("ambiguous_thousands"):
        clarification = (
            "Value contains an ambiguous comma that looks like a thousands separator "
            "(e.g. '1,250'). Please resend with an unambiguous decimal format."
        )
        output = dict(node_input)
        output["status"] = "AMBIGUOUS"
        output["clarification"] = clarification
        return Event(output=output, route="CLARIFY")

    # Fix Issue 5: multiple numeric values in input — don't silently pick the first.
    if node_input.get("ambiguous_value"):
        clarification = (
            "Input contains multiple numeric values (e.g. 'Calcium 48 4.8'). "
            "Please resend with a single unambiguous numeric value."
        )
        output = dict(node_input)
        output["status"] = "AMBIGUOUS"
        output["clarification"] = clarification
        return Event(output=output, route="CLARIFY")

    engine = SafetyGateEngine()
    ctx = EvaluationContext(
        term=node_input.get("term", ""),
        unit=node_input.get("unit", ""),
        qualifier=node_input.get("qualifier", ""),
        patient_value=node_input.get("patient_value"),
    )
    verdict = engine.evaluate(ctx)
    route = engine.route_for(verdict.status)

    output = dict(node_input)
    output["status"] = verdict.status.value if hasattr(verdict.status, "value") else str(verdict.status)
    output["gate_message"] = verdict.message
    output["gate_candidates"] = verdict.candidates
    if not verdict.passed:
        output["clarification"] = verdict.message
    return Event(output=output, route=route)


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
        # Fix 2: carry the clinician's original reported unit, not the concept's
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

    Fix 10: this node was defined but not wired into the workflow graph.
    It now sits between fetch_node and the synthesiser.

    Checks whether the retrieved protocol was successfully attested.  If the
    attestation failed (e.g. stale protocol, unit mismatch, out-of-range) the
    node routes to 'CLARIFY' instead of letting unattested data flow into the
    synthesis response.  This closes the gap where a stale or misconfigured
    protocol could produce a synthesised answer without a badge.

    Fix (Issue 3): also routes to CLARIFY when there is no resolved URI or
    protocol.  fetch_node returns status='NO_RESOLVED_CANDIDATE' in this case;
    without this guard the synthesiser would run with no protocol data.
    """
    protocol = node_input.get("protocol", {})
    patient_value = node_input.get("patient_value")
    resolved_uri = node_input.get("resolved_uri", "")
    reported_unit = node_input.get("reported_unit", "")

    # Fix Issue 3: fail closed when fetch_node found no resolved candidate.
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

            # Fix 17: Log verified attestation into OKF audit trail
            try:
                from src.core.okf_writer import record_concept_update
                record_concept_update(
                    uri=resolved_uri,
                    change=f"attested_value={patient_value} {reported_unit}",
                    agent_id="workflow/synthesis_gate_node",
                    details={"status": "ATTESTED", "badge": attest_result.get("badge")},
                )
            except Exception as audit_exc:
                logger.warning(
                    "Failed to record OKF audit log for URI %s: %s",
                    resolved_uri,
                    audit_exc,
                    exc_info=True,
                )
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

    Graph Topology (Fix 10 — synthesis_gate_node now wired in)::

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
