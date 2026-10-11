"""
Protocol Retriever Agent: Retrieves clinical reference data keyed by canonical LOINC URI.
Guarantees that retrieved guidelines and panic limits are strictly bound to verified concepts.

OKF:
Forwards OKF trust signals (trust_tier, concept_status, is_stale) from the
ontology resolver output into the result payload so the synthesis agent can
apply trust-calibrated phrasing without re-querying the registry.
"""

from typing import Any, Dict
from google.adk import Event
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole
from ontogate.config import get_default_registry
from ontogate.models import ResolutionStatus


def protocol_retriever_node(node_input: Dict[str, Any]) -> Event:
    """Protocol retrieval node grounded on resolved canonical concept URI.

    Forwards OKF trust signals from the ontology resolver into the result
    payload so the synthesis agent can produce trust-calibrated interpretations.
    """
    candidates = node_input.get("candidates", [])
    if candidates and "uri" in candidates[0]:
        uri = candidates[0]["uri"]
        reg = get_default_registry()
        protocol_def = reg.get_protocol(uri)

        if protocol_def:
            protocol_data = {
                "reference_range": protocol_def.reference_range,
                "panic_limits": protocol_def.panic_limits,
                "clinical_guideline": protocol_def.clinical_guideline,
                # OKF: include protocol-level trust signals
                "protocol_status": protocol_def.status,
                "protocol_verified_by": protocol_def.verified_by,
                "has_attested_computation": protocol_def.attested_computation is not None,
            }
        else:
            protocol_data = {"status": "NOT_FOUND"}

        # preserve the clinician's reported unit from the parsed input.
        # Do NOT substitute the concept's first expected_unit — that would silently
        # reclassify e.g. Hb 135 g/L against g/dL thresholds.
        reported_unit = node_input.get("unit", "")

        result = {
            "resolved_uri": uri,
            "concept": candidates[0],
            "protocol": protocol_data,
            "patient_value": node_input.get("patient_value"),
            "reported_unit": reported_unit,
            # OKF: propagate concept-level trust signals from ontology resolver
            "trust_tier": node_input.get("trust_tier"),
            "concept_status": node_input.get("concept_status"),
            "is_stale": candidates[0].get("is_stale", False),
            "stale_dropped": node_input.get("stale_dropped", []),
            "deprecated_dropped": node_input.get("deprecated_dropped", []),
        }

        a2a_msg = A2AMessage(
            sender=AgentRole.PROTOCOL_RETRIEVER,
            recipient=AgentRole.CLINICAL_SYNTHESIZER,
            action=A2AAction.SYNTHESIZE_INTERPRETATION,
            payload=result,
            status=ResolutionStatus.RESOLVED,
        )
        result["a2a_protocol_message"] = a2a_msg.model_dump(mode="json")
        return Event(output=result)

    return Event(output={"status": "NO_RESOLVED_CANDIDATE"})


def create_protocol_agent() -> Any:
    """Return protocol retriever callable node."""
    return protocol_retriever_node
