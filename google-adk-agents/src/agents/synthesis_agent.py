"""
Clinical Synthesis Agent: Calibrated interpretation synthesis without hallucination.
Single-turn ADK Agent grounded strictly on protocol data provided in the input payload.

OKF:
The agent instruction is now trust-aware: it adjusts its phrasing based on the
OKF trust tier (human-reviewed / machine-confirmed / unverified) and concept
lifecycle status (draft / stable / deprecated) of the resolved concept.

Per OKF §9: "Calibrated confidence — Trust tier can drive phrasing:
'per the human-reviewed definition…' vs. 'based on an unverified draft…'"
"""

from typing import Any, Literal, Optional
from google.adk import Agent

from ontogate.catalog import model_for

DEFAULT_MODEL = model_for("gcp")["id"]  # config/models.yaml

# OKF trust tier → hedging phrase for synthesis instruction
_TRUST_PHRASES: dict = {
    "human-reviewed": (
        "The resolved concept has been human-reviewed. "
        "Preface your interpretation with: 'Per the human-reviewed clinical definition,'"
    ),
    "machine-confirmed": (
        "The resolved concept is machine-confirmed but has NOT been human-reviewed. "
        "Preface your interpretation with: 'Based on machine-confirmed data (pending human review),'"
    ),
    "unverified": (
        "WARNING: The resolved concept is UNVERIFIED. "
        "Preface your interpretation with: 'NOTE — this concept is unverified; treat with caution.' "
        "Be especially conservative and recommend human clinical review."
    ),
}

# OKF lifecycle status → caveat phrase
_STATUS_PHRASES: dict = {
    "draft": " This protocol is marked DRAFT — values may not yet be authoritative.",
    "stable": "",
    "deprecated": (
        " WARNING: This protocol is DEPRECATED. "
        "Explicitly tell the clinician to use an updated protocol."
    ),
}


def create_synthesize_agent(
    model: Optional[str] = None,
    trust_tier: Literal["human-reviewed", "machine-confirmed", "unverified"] = "unverified",
    concept_status: Literal["draft", "stable", "deprecated"] = "stable",
    is_stale: bool = False,
) -> Agent:
    """Create single-turn synthesis agent with OKF trust-calibrated instruction.

    Args:
        model:          Gemini model identifier.
        trust_tier:     OKF trust tier of the resolved concept (drives hedging language).
        concept_status: OKF lifecycle status of the resolved concept.
        is_stale:       Whether the concept has passed its ``stale_after`` timestamp.

    Returns:
        An ADK Agent whose instruction is calibrated to the concept's trust posture.
    """
    chosen_model = model or DEFAULT_MODEL
    trust_phrase = _TRUST_PHRASES.get(trust_tier, _TRUST_PHRASES["unverified"])
    status_phrase = _STATUS_PHRASES.get(concept_status, "")
    stale_phrase = (
        " NOTE: This concept has passed its stale_after date — "
        "flag this to the clinician and recommend re-verification."
        if is_stale
        else ""
    )

    instruction = (
        "You are a clinical laboratory specialist. "
        "Interpret the patient's value using ONLY the protocol data provided in the input. "
        "Name the resolved LOINC concept, cite the reference range and panic limits, "
        "and provide a calibrated, cautious interpretation. Never speculate beyond the provided protocol. "
        "If the protocol is deprecated or stale, say so explicitly and do not interpret further.\n\n"
        f"Trust guidance: {trust_phrase}{status_phrase}{stale_phrase}\n\n"
        "Citation rule: At the end of your response, cite the source as: "
        "'[Source: <verified_by> / <generated_by>]'. "
        "If trust tier is unverified, add: '(unverified — human review recommended)'.\n\n"
        "If any figure is backed by an Attested Computation, state the attested value; "
        "do not compute or re-derive it yourself."
    )

    return Agent(
        name="clinical_synthesizer",
        model=chosen_model,
        mode="single_turn",
        instruction=instruction,
    )


def create_synthesize_agent_from_payload(
    payload: dict,
    model: Optional[str] = None,
) -> Agent:
    """Convenience factory: extract OKF signals from a protocol payload dict.

    The payload is expected to carry the trust_tier, concept_status, and
    is_stale keys emitted by the OKF-enriched ontology resolver.
    """
    trust_tier = payload.get("trust_tier") or "unverified"
    concept_status = payload.get("concept_status") or "stable"
    is_stale = bool(payload.get("is_stale", False))

    # Guard against unexpected values
    if trust_tier not in _TRUST_PHRASES:
        trust_tier = "unverified"
    if concept_status not in _STATUS_PHRASES:
        concept_status = "stable"

    return create_synthesize_agent(
        model=model,
        trust_tier=trust_tier,
        concept_status=concept_status,
        is_stale=is_stale,
    )


def verify_attestation_for_payload(payload: dict) -> tuple[bool, Optional["AttestationResult"]]:
    """Verify numeric attestation for a protocol payload if an AttestedComputation is defined.
    
    OKF §5.4 & §8.2: Blocks synthesis if attestation fails.
    
    Returns:
        Tuple of (passed: bool, attestation_result: Optional[AttestationResult]).
        If no attested_computation or patient_value is present, passes by default with None.
    """
    from ontogate.attestation import AttestationResult, attest_numeric
    from ontogate.config import get_default_registry

    proto_dict = payload.get("protocol", {})
    patient_val = payload.get("patient_value")

    # If no numeric value or no attestation required, pass through
    if patient_val is None or not proto_dict.get("has_attested_computation"):
        return True, None

    uri = payload.get("resolved_uri")
    if not uri:
        return True, None

    reg = get_default_registry()
    protocol_def = reg.get_protocol(uri)
    if not protocol_def or not protocol_def.attested_computation:
        return True, None

    reported_unit = payload.get("reported_unit") or payload.get("unit") or ""
    att_result = attest_numeric(
        value=float(patient_val),
        protocol=protocol_def,
        computation=protocol_def.attested_computation,
        unit=reported_unit,
    )
    return att_result.passed, att_result


def synthesis_gate_node(node_input: Any) -> Any:
    """Pre-synthesis gate node: verifies attestation before allowing interpretation.
    
    Routes to CLARIFY if attestation fails (e.g. out-of-spec or stale),
    or to PROCEED with an '[Attested ✓]' badge if attestation succeeds.
    """
    from google.adk import Event

    if hasattr(node_input, "output") and isinstance(node_input.output, dict):
        payload = node_input.output
    elif isinstance(node_input, dict):
        payload = node_input
    else:
        payload = {}

    passed, att_result = verify_attestation_for_payload(payload)

    if not passed and att_result:
        return Event(
            output={
                "status": "CLARIFY",
                "reason": f"Attestation failed: {att_result.message}",
                "attestation": att_result.model_dump(mode="json"),
                **payload,
            }
        )

    out = dict(payload)
    out["status"] = "PROCEED"
    if att_result:
        out["attestation_badge"] = "[Attested ✓]"
        out["attestation"] = att_result.model_dump(mode="json")
        # Attestations are ABox events → audit port (redacted), not knowledge/log.md (F1).
        from ontogate.ports import get_audit
        get_audit().record("attestation", {
            "uri": payload.get("resolved_uri", "unknown"), "patient_value": payload.get("patient_value"),
            "verdict": att_result.verdict, "node": "synthesis_gate_node",
        })

    return Event(output=out)
