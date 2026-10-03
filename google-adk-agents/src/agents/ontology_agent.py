"""
Ontology Resolver Agent: Normalizes clinical queries and maps terms to LOINC concepts.

OKF Enhancement (Phase 3):
- Filters out deprecated concepts before returning candidates.
- Flags stale concepts and excludes them from resolution (configurable).
- Ranks candidates by OKF trust tier (human-reviewed > machine-confirmed > unverified).
- Propagates trust_tier, concept_status, and stale_signals into the output payload
  so downstream agents (synthesis, safety gate) can calibrate their behaviour.
"""

from typing import Any, Dict, List, Optional
from google.adk import Agent, Event
from src.a2a.contracts import A2AAction, A2AMessage, AgentRole
from src.core.config import OntologyRegistry, get_default_registry
from src.core.models import (
    ConceptDefinition,
    EvaluationContext,
    ResolutionStatus,
    TrustTier,
)

# Trust tier preference order for ranking (lower index = higher preference)
_TRUST_ORDER: Dict[TrustTier, int] = {
    TrustTier.HUMAN_REVIEWED: 0,
    TrustTier.MACHINE_CONFIRMED: 1,
    TrustTier.UNVERIFIED: 2,
}


def _rank_by_trust(concepts: List[ConceptDefinition]) -> List[ConceptDefinition]:
    """Sort candidates by OKF trust tier, most trusted first."""
    return sorted(concepts, key=lambda c: _TRUST_ORDER[c.trust_tier])


def resolve_term_with_registry(
    term: str,
    unit: str = "",
    registry: Optional[OntologyRegistry] = None,
) -> Dict[str, Any]:
    """Map a lab test name and optional unit to canonical concepts using OntologyRegistry.

    OKF Phase 3 behaviour:
    1. Lexical matching (unchanged).
    2. Drop deprecated concepts immediately — they are never returned.
    3. Separate stale from fresh candidates; exclude stale from resolution.
    4. Apply unit constraint if provided.
    5. Rank remaining candidates by OKF trust tier.
    6. Emit RESOLVED / AMBIGUOUS / NOT_FOUND / UNIT_MISMATCH as before,
       plus ``stale_dropped``, ``trust_tier``, and ``concept_status`` metadata.

    Returns:
        dict with keys:
          status           – ResolutionStatus value string
          candidates       – list of concept view dicts (via to_view())
          stale_dropped    – list of URIs excluded due to staleness
          deprecated_dropped – list of URIs excluded due to deprecated status
          trust_tier       – TrustTier of the winning concept (if RESOLVED), else None
          concept_status   – lifecycle status of the winning concept (if RESOLVED), else None
    """
    reg = registry or get_default_registry()
    raw_candidates = reg.find_concepts(term.strip())

    # ---- OKF: Drop deprecated concepts (lifecycle gate) ----
    deprecated_dropped = [c.uri for c in raw_candidates if not c.is_usable()]
    usable = [c for c in raw_candidates if c.is_usable()]

    if not usable:
        return {
            "status": ResolutionStatus.NOT_FOUND.value,
            "candidates": [],
            "stale_dropped": [],
            "deprecated_dropped": deprecated_dropped,
            "trust_tier": None,
            "concept_status": None,
        }

    # ---- OKF: Separate stale concepts (freshness gate) ----
    stale_dropped = [c.uri for c in usable if c.is_stale()]
    fresh = [c for c in usable if not c.is_stale()]

    # If all usable candidates are stale, fall back to stale ones with a warning
    # rather than returning NOT_FOUND (they are usable but flagged)
    if not fresh:
        fresh = usable  # use stale as fallback; stale_dropped stays populated

    # ---- Unit constraint ----
    if unit:
        u = unit.strip()
        matched = [c for c in fresh if c.supports_unit(u)]
        if not matched:
            return {
                "status": ResolutionStatus.UNIT_MISMATCH.value,
                "reported_unit": unit,
                "candidates": [c.to_view() for c in fresh],
                "stale_dropped": stale_dropped,
                "deprecated_dropped": deprecated_dropped,
                "trust_tier": None,
                "concept_status": None,
            }
        fresh = matched

    # ---- OKF: Rank by trust tier ----
    fresh = _rank_by_trust(fresh)

    status = (
        ResolutionStatus.RESOLVED.value
        if len(fresh) == 1
        else ResolutionStatus.AMBIGUOUS.value
    )

    # Resolved concept metadata for downstream trust-aware agents
    winning = fresh[0] if len(fresh) == 1 else None
    return {
        "status": status,
        "candidates": [c.to_view() for c in fresh],
        "stale_dropped": stale_dropped,
        "deprecated_dropped": deprecated_dropped,
        "trust_tier": winning.trust_tier.value if winning else None,
        "concept_status": winning.status if winning else None,
    }


def ontology_resolver_node(node_input: Any) -> Event:
    """ADK Workflow node for ontology resolution, wrapping state in A2A envelope.

    Emits OKF trust and staleness signals in the output payload so the
    downstream safety gate and synthesis agent can calibrate responses.
    """
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
            "units to canonical LOINC identifiers. Never guess if ambiguous. "
            "Deprecated or stale concepts must not be returned. "
            "Always report the trust tier of the resolved concept."
        ),
    )
