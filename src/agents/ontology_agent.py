"""
Ontology Resolver Agent: Normalizes clinical queries and maps terms to LOINC concepts.
"""

from typing import Any, Dict, Optional
from google.adk import Agent, Event
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole
from src.core.config import OntologyRegistry, get_default_registry
from src.core.models import EvaluationContext, ResolutionStatus


def resolve_term_with_registry(
    term: str,
    unit: str = "",
    registry: Optional[OntologyRegistry] = None,
) -> Dict[str, Any]:
    """Map a lab test name and optional unit to canonical concepts using OntologyRegistry."""
    reg = registry or get_default_registry()
    t = term.strip()
    candidates = reg.find_concepts(t)

    if not candidates:
        return {"status": ResolutionStatus.NOT_FOUND.value, "candidates": []}

    if unit:
        u = unit.strip()
        matched = [c for c in candidates if c.supports_unit(u)]
        if not matched:
            return {
                "status": ResolutionStatus.UNIT_MISMATCH.value,
                "reported_unit": unit,
                "candidates": [c.to_view() for c in candidates],
            }
        candidates = matched

    status = (
        ResolutionStatus.RESOLVED.value
        if len(candidates) == 1
        else ResolutionStatus.AMBIGUOUS.value
    )
    return {
        "status": status,
        "candidates": [c.to_view() for c in candidates],
    }


def ontology_resolver_node(node_input: Any) -> Event:
    """ADK Workflow node for ontology resolution, wrapping state in A2A envelope."""
    data = node_input if isinstance(node_input, dict) else {}
    term = data.get("term", "")
    unit = data.get("unit", "")
    qualifier = data.get("qualifier", "")
    patient_value = data.get("patient_value")

    reg = get_default_registry()
    resolution = resolve_term_with_registry(term, unit, reg)

    # Formulate A2A message response
    a2a_msg = A2AMessage(
        sender=AgentRole.ONTOLOGY_RESOLVER,
        recipient=AgentRole.SAFETY_GUARD,
        action=A2AAction.RESOLVE_CONCEPT,
        payload=resolution,
        status=ResolutionStatus(resolution["status"]),
    )

    output = dict(resolution)
    output["term"] = term
    output["unit"] = unit
    output["qualifier"] = qualifier
    output["patient_value"] = patient_value
    output["a2a_message"] = a2a_msg.model_dump(mode="json")

    return Event(output=output)


def create_ontology_agent(model: str = "gemini-3.5-flash") -> Agent:
    """Create an ADK Agent wrapping ontology resolution."""
    return Agent(
        name="ontology_resolver",
        model=model,
        instruction=(
            "You are an ontology resolution specialist. Map incoming lab terms and reported "
            "units to canonical LOINC identifiers. Never guess if ambiguous."
        ),
    )
