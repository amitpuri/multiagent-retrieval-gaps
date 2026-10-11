"""
Safety Guard Agent: Deterministic safety invariants and collision gating.
Evaluates configured Gap Detectors in code to guarantee fail-closed enforcement.
"""
from __future__ import annotations

from typing import Any, Dict
from google.adk import Event
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole
from ontogate.detectors.engine import SafetyGateEngine
from ontogate.models import EvaluationContext, ResolutionStatus


def safety_guard_node(node_input: Dict[str, Any]) -> Event:
    """Deterministic routing and safety validation node. No LLM variance.
    
    Inspects resolution status and evaluates range collision detectors.
    Routes to:
      - 'PROCEED' if all invariants pass (RESOLVED).
      - 'CLARIFY' if ambiguous, unit mismatch, range collision, or not found.
    """
    engine = SafetyGateEngine()
    
    term = node_input.get("term", "")
    unit = node_input.get("unit", "")
    qualifier = node_input.get("qualifier", "")
    patient_value = node_input.get("patient_value")
    current_status = node_input.get("status", ResolutionStatus.UNKNOWN.value)

    # 1. If ontology resolver already failed, preserve and fail closed
    if current_status != ResolutionStatus.RESOLVED.value:
        try:
            status_enum = ResolutionStatus(current_status)
        except ValueError:
            # Unknown status string — treat as UNKNOWN and route to CLARIFY.
            # This covers statuses produced by other nodes (e.g. 'ATTESTATION_FAILED',
            # 'NO_RESOLVED_CANDIDATE') that are not members of ResolutionStatus.
            status_enum = ResolutionStatus.UNKNOWN
        route = engine.route_for(status_enum)
        
        a2a_msg = A2AMessage(
            sender=AgentRole.SAFETY_GUARD,
            recipient=AgentRole.CLARIFICATION_COORDINATOR,
            action=A2AAction.REQUEST_CLARIFICATION,
            payload=node_input,
            status=status_enum,
        )
        node_input["a2a_safety_message"] = a2a_msg.model_dump(mode="json")
        return Event(output=node_input, route=route)

    # 2. Check for range collisions or look-alike hazards if numeric value present
    context = EvaluationContext(
        term=term,
        unit=unit,
        qualifier=qualifier,
        patient_value=patient_value,
    )
    result = engine.evaluate(context)

    if not result.passed:
        node_input["status"] = result.status.value
        node_input["collision_details"] = result.details
        route = engine.route_for(result.status)
        a2a_msg = A2AMessage(
            sender=AgentRole.SAFETY_GUARD,
            recipient=AgentRole.CLARIFICATION_COORDINATOR,
            action=A2AAction.REQUEST_CLARIFICATION,
            payload=node_input,
            status=result.status,
        )
        node_input["a2a_safety_message"] = a2a_msg.model_dump(mode="json")
        return Event(output=node_input, route=route)

    # Invariants satisfied
    route = engine.route_for(ResolutionStatus.RESOLVED)
    a2a_msg = A2AMessage(
        sender=AgentRole.SAFETY_GUARD,
        recipient=AgentRole.PROTOCOL_RETRIEVER,
        action=A2AAction.FETCH_PROTOCOL,
        payload=node_input,
        status=ResolutionStatus.RESOLVED,
    )
    node_input["a2a_safety_message"] = a2a_msg.model_dump(mode="json")
    return Event(output=node_input, route=route)


def create_safety_guard_agent() -> Any:
    """Return the safety guard validation callable node."""
    return safety_guard_node
