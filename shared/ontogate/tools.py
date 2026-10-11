"""
Canonical clinical tool contract — one implementation and one name per
capability, used by the MCP server and by every framework adapter.

=========================  ==================================================
Canonical tool             Purpose
=========================  ==================================================
parse_clinician_input      Ontology-aware parse of raw clinician text
resolve_lab_term           Term (+ unit, qualifier) → candidate observables
evaluate_safety_gate       Deterministic gate verdict: route + status + details
fetch_grounded_protocol    Protocol bound to exactly one observable URI
attest_computation         OKF §5.4 attestation; ``badge`` on PASS
build_clarification_prompt Deterministic clarification text for a gate result
panel_workup               Ordered, department-scoped specimen collection steps
=========================  ==================================================

``classify_lookalikes`` is a read-only helper (no routing) that shows how a value
reads under each look-alike candidate — used by demos and the clarification text.

Every function returns a ``dict`` containing ``"status"`` (agent invariant 3).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ontogate.config import OntologyRegistry, get_default_registry
from ontogate.models import EvaluationContext, ResolutionStatus

CANONICAL_TOOLS = (
    "parse_clinician_input",
    "resolve_lab_term",
    "evaluate_safety_gate",
    "fetch_grounded_protocol",
    "attest_computation",
    "build_clarification_prompt",
    "panel_workup",
)


def _reg(registry: Optional[OntologyRegistry]) -> OntologyRegistry:
    return registry or get_default_registry()


def _population(sex: str = "", age_band: str = "", population: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    pop = dict(population or {})
    if sex:
        pop["sex"] = sex.strip().lower()
    if age_band:
        pop["age_band"] = age_band.strip().lower()
    return pop


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

def parse_clinician_input(raw_text: str = "", text: str = "", query: str = "",
                          registry: Optional[OntologyRegistry] = None, **kwargs: Any) -> Dict[str, Any]:
    """Parse raw clinician text into term, value, unit, qualifier, population, department, panel."""
    from ontogate.parsing import parse_clinician_text

    raw = raw_text or text or query or kwargs.get("input", "") or ""
    out = parse_clinician_text(raw, _reg(registry))
    out["status"] = "PARSED"
    return out


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------

def resolve_lab_term(term: str, unit: str = "", qualifier: str = "",
                     registry: Optional[OntologyRegistry] = None) -> Dict[str, Any]:
    """Map a lab test name (+ unit, qualifier) to canonical observables. Never guesses.

    Returns ``RESOLVED`` (one observable), ``AMBIGUOUS`` (several, or the
    qualifier contradicts the term — then ``contradiction`` explains),
    ``UNIT_MISMATCH`` (unit valid for none) or ``NOT_FOUND``.
    """
    from ontogate.resolver import differing_facets, resolve

    reg = _reg(registry)
    res = resolve(reg, term, unit, qualifier)
    if not res.lexical:
        return {"status": ResolutionStatus.NOT_FOUND.value, "candidates": []}
    if res.unit_mismatch:
        return {"status": ResolutionStatus.UNIT_MISMATCH.value, "reported_unit": unit,
                "candidates": [c.to_view() for c in res.candidates]}
    views = [c.to_view() for c in res.candidates]
    if res.contradiction:
        return {"status": ResolutionStatus.AMBIGUOUS.value, "candidates": views,
                "contradiction": res.contradiction}
    if res.is_ambiguous:
        return {"status": ResolutionStatus.AMBIGUOUS.value, "candidates": views,
                "differing_facets": differing_facets(reg, res.candidates),
                "designation_kind": res.designation.kind if res.designation else None}
    out: Dict[str, Any] = {"status": ResolutionStatus.RESOLVED.value, "candidates": views}
    if res.redirected_from:
        out["superseded"] = res.redirected_from
    return out


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------

def evaluate_safety_gate(
    term: str = "",
    unit: str = "",
    qualifier: str = "",
    patient_value: Optional[float] = None,
    status: str = "UNKNOWN",
    sex: str = "",
    age_band: str = "",
    department: str = "",
    panel_id: str = "",
    registry: Optional[OntologyRegistry] = None,
) -> Dict[str, Any]:
    """Run the deterministic SafetyGateEngine. Fails closed: only RESOLVED → PROCEED."""
    from ontogate.clarify import build_clarification
    from ontogate.detectors.engine import SafetyGateEngine

    reg = _reg(registry)
    engine = SafetyGateEngine(reg)
    ctx = EvaluationContext(term=term, unit=unit, qualifier=qualifier, patient_value=patient_value,
                            population=_population(sex, age_band), department=department,
                            panel_id=panel_id or None)
    verdict = engine.evaluate(ctx)
    eval_status = verdict.status.value

    # An explicit upstream UNIT_MISMATCH is never downgraded by a weaker downstream verdict.
    if status == ResolutionStatus.UNIT_MISMATCH.value and verdict.status in (
        ResolutionStatus.RESOLVED, ResolutionStatus.AMBIGUOUS
    ):
        eval_status = ResolutionStatus.UNIT_MISMATCH.value

    route = engine.route_for(ResolutionStatus(eval_status))
    passed = route == "PROCEED"
    clarification = None
    if not passed:
        clarification = build_clarification(eval_status, verdict.message, verdict.candidates,
                                            verdict.details, reg)
    return {
        "route": route,
        "status": eval_status,
        "passed": passed,
        "triggered_gaps": [verdict.gap_name] if not passed else [],
        "clarification_prompt": clarification,
        "gate_message": verdict.message,
        "candidates": verdict.candidates,
        "details": _jsonable(verdict.details),
    }


def _jsonable(details: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in (details or {}).items() if k != "reading_detail"}


# ---------------------------------------------------------------------------
# protocol + attestation
# ---------------------------------------------------------------------------

def fetch_grounded_protocol(uri: str, registry: Optional[OntologyRegistry] = None) -> Dict[str, Any]:
    """Return the protocol bound to exactly one observable URI (invariant 7)."""
    reg = _reg(registry)
    proto = reg.protocols.get(uri)
    if proto is None or not proto.is_usable():
        return {"status": "NOT_FOUND"}
    return {
        "status": "RESOLVED",
        "uri": uri,
        "protocol_id": proto.id,
        "reference_range": proto.reference_range,
        "panic_limits": proto.panic_limits,
        "clinical_guideline": proto.clinical_guideline,
        "trust_tier": proto.trust_tier.value,
        "is_stale": proto.is_stale(),
        "status_lifecycle": proto.status,
    }


def attest_computation(value: float, uri: str, unit: str = "", sex: str = "", age_band: str = "",
                       registry: Optional[OntologyRegistry] = None) -> Dict[str, Any]:
    """Deterministically attest a value for an observable (OKF §5.4).

    A passing result always carries ``"badge": "[Attested ✓]"`` (invariant 5).
    """
    from ontogate.attestation import attest_numeric

    reg = _reg(registry)
    protocol = reg.protocols.get(uri)
    if protocol is None:
        return {"passed": False, "verdict": "FAIL", "status": "NOT_FOUND",
                "message": f"Protocol not found for URI: {uri}"}
    concept = reg.concepts.get(uri)
    if unit and concept is not None and not concept.supports_unit(unit):
        valid = ", ".join(concept.units) if concept.units else "unknown"
        return {"passed": False, "verdict": "FAIL", "status": "UNIT_MISMATCH",
                "message": (f"Reported unit '{unit}' is not valid for concept '{concept.label}'. "
                            f"Valid units: {valid}.")}
    result = attest_numeric(value, protocol, unit=unit, registry=reg, population=_population(sex, age_band))
    out: Dict[str, Any] = {
        "status": result.verdict,
        "passed": result.passed,
        "verdict": result.verdict,
        "attested_value": result.attested_value,
        "unit": unit,
        "uri": uri,
        "reference_range": result.expected_range,
        "panic_limits": protocol.panic_limits,
        "is_panic": result.is_panic,
        "classification": result.classification,
        "message": result.message,
    }
    if result.passed:
        out["badge"] = "[Attested ✓]"
    return out


# ---------------------------------------------------------------------------
# clarification
# ---------------------------------------------------------------------------

def build_clarification_prompt(status: str, candidates: Optional[List[Dict[str, Any]]] = None,
                               details: Optional[Dict[str, Any]] = None, message: str = "",
                               term: str = "", registry: Optional[OntologyRegistry] = None,
                               **kwargs: Any) -> Dict[str, Any]:
    """Deterministic clarification for a non-RESOLVED gate status."""
    from ontogate.clarify import build_clarification

    details = dict(details or kwargs.get("collision_details") or {})
    prompt = build_clarification(status, message, candidates or [], details, _reg(registry))
    return {"status": status, "clarification_prompt": prompt, "requires_clarification": True,
            "missing": details.get("missing", [])}


# ---------------------------------------------------------------------------
# panels
# ---------------------------------------------------------------------------

def panel_workup(panel: str = "csf_emergency_panel", department: str = "",
                 registry: Optional[OntologyRegistry] = None) -> Dict[str, Any]:
    """Ordered, department-scoped collection steps for a panel (Gap 11)."""
    from ontogate.detectors.specimen_sequence import SpecimenSequenceDetector

    reg = _reg(registry)
    found = reg.find_panel(panel) if panel not in reg.panels else (panel, reg.panels[panel])
    if not found:
        return {"status": "NOT_FOUND", "message": f"Panel '{panel}' not found"}
    result = SpecimenSequenceDetector(reg).evaluate(
        EvaluationContext(panel_id=found[0], department=department))
    if not result.passed:
        return {"status": result.status.value, "message": result.message}
    return {"status": "RESOLVED", "panel_id": found[0], "panel": result.details["panel_name"],
            "specimen": result.details["specimen"], "tubes": result.details["tubes"]}


# ---------------------------------------------------------------------------
# Read-only look-alike view
# ---------------------------------------------------------------------------

def classify_lookalikes(term: str, value: float, unit: str, qualifier: str = "",
                        registry: Optional[OntologyRegistry] = None) -> Dict[str, Any]:
    """Classify a value under every candidate ``term`` denotes, in ``unit`` (no routing decision)."""
    from ontogate.resolver import classify, collapse, resolve

    reg = _reg(registry)
    res = resolve(reg, term, unit, qualifier, value)
    readings: Dict[str, str] = {}
    for c in res.candidates:
        collapsed = collapse(classify(reg, c, value, unit, res.population))
        if collapsed:
            readings[c.name] = collapsed
    status = "RANGE_COLLISION" if len(set(readings.values())) > 1 else "RESOLVED"
    return {"status": status, "value": value, "unit": unit, "readings": readings}
