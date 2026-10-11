"""
Triage Supervisor Agent using Strands Agents SDK.
Acts as the central orchestrator coordinating parsing, ontology resolution,
deterministic safety gating, protocol retrieval, and clinical synthesis.
"""
import threading
from typing import Any, Dict, Optional
from strands import Agent, tool
from strands.models.model import Model

from src.tools.parse_tool import parse_clinician_input
from src.tools.ontology_tool import resolve_lab_term
from src.tools.safety_gate_tool import evaluate_safety_gate
from src.tools.protocol_tool import fetch_grounded_protocol
from src.tools.clarification_tool import build_clarification_prompt
from src.agents.synthesis_agent import create_synthesis_agent


def _run_in_clean_thread(func, *args, **kwargs) -> Any:
    """Run a callable in an isolated OS thread to prevent ContextVar / OpenTelemetry token collision."""
    result = []
    error = []

    def target():
        try:
            result.append(func(*args, **kwargs))
        except Exception as e:
            error.append(e)

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


def create_triage_orchestrator(model: Optional[Model] = None) -> Agent:
    """Create the Triage Supervisor Agent.

    The supervisor strictly enforces the clinical decision sequence:
      1. parse_clinician_input
      2. resolve_lab_term
      3. evaluate_safety_gate (deterministic, mandatory)
         - PROCEED -> fetch_grounded_protocol -> synthesize_interpretation
         - CLARIFY -> build_clarification_prompt -> return to clinician
    """
    synthesis_agent = create_synthesis_agent(model=model)
    # Mute sub-agent stream output so it returns its final result cleanly to supervisor
    synthesis_agent.callback_handler = lambda **k: None

    @tool
    def synthesize_interpretation(
        resolved_uri: str,
        concept: Any = None,
        protocol: Any = None,
        patient_value: Optional[float] = None,
    ) -> str:
        """Invoke the Clinical Synthesizer Agent for grounded interpretation.

        Args:
            resolved_uri: Canonical LOINC URI.
            concept: Resolved concept dictionary or label.
            protocol: Protocol dictionary with reference ranges and panic limits.
            patient_value: Numeric patient result.
        """
        import json

        concept_dict = concept if isinstance(concept, dict) else {}
        if isinstance(concept, str):
            try:
                concept_dict = json.loads(concept)
            except Exception:
                concept_dict = {"label": concept}

        protocol_dict = protocol if isinstance(protocol, dict) else {}
        if isinstance(protocol, str):
            try:
                protocol_dict = json.loads(protocol)
            except Exception:
                protocol_dict = {"clinical_guideline": protocol}

        prompt = (
            f"Interpret the following verified laboratory result:\n"
            f"- LOINC URI: {resolved_uri}\n"
            f"- Concept: {concept_dict.get('label', 'Unknown')} ({concept_dict.get('department', 'N/A')})\n"
            f"- Patient Value: {patient_value}\n"
            f"- Reference Range: {protocol_dict.get('reference_range', 'N/A')}\n"
            f"- Panic Limits: {protocol_dict.get('panic_limits', 'N/A')}\n"
            f"- Guideline: {protocol_dict.get('clinical_guideline', 'Standard laboratory review')}\n"
            f"Provide a calibrated, grounded clinical interpretation."
        )

        def _do_synthesis():
            from src.models.provider import get_strands_model

            sub_model = get_strands_model()
            synth_agent = create_synthesis_agent(model=sub_model)
            synth_agent.callback_handler = lambda **k: None
            return str(synth_agent(prompt))

        return str(_run_in_clean_thread(_do_synthesis))

    return Agent(
        model=model,
        system_prompt=(
            "You are the Triage Supervisor Agent for a clinical laboratory decision support system.\n"
            "You MUST execute the following sequence for every clinician query:\n"
            "1. Call parse_clinician_input with the raw text.\n"
            "2. Call resolve_lab_term with the extracted term, unit, qualifier, and patient_value.\n"
            "3. MANDATORY: Call evaluate_safety_gate with the resolution result. Never bypass this gate.\n"
            "   - If gate route is 'PROCEED': call fetch_grounded_protocol, then synthesize_interpretation.\n"
            "   - If gate route is 'CLARIFY': call build_clarification_prompt and return the prompt "
            "directly to the clinician. Do NOT call protocol or synthesis.\n"
            "Never hallucinate clinical values or bypass safety invariants."
        ),
        tools=[
            parse_clinician_input,
            resolve_lab_term,
            evaluate_safety_gate,
            fetch_grounded_protocol,
            synthesize_interpretation,
            build_clarification_prompt,
        ],
    )


create_triage_agent = create_triage_orchestrator


def make_triage_envelope(
    raw_text: str,
    term: str,
    unit: str = "",
    qualifier: str = "",
    patient_value: Any = None,
):
    """Construct the initial A2A envelope dispatched by the Triage Orchestrator."""
    from src.a2a.contracts import A2AAction, A2AMessage, AgentRole

    return A2AMessage(
        sender=AgentRole.TRIAGE,
        recipient=AgentRole.ONTOLOGY_RESOLVER,
        action=A2AAction.PARSE_REQUEST,
        payload={
            "raw_text": raw_text,
            "term": term,
            "unit": unit,
            "qualifier": qualifier,
            "patient_value": patient_value,
        },
    )
