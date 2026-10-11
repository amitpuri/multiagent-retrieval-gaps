"""
OKF Attested Computation gate (OKF v0.2 §5.4, §9).

Deterministic attestation of a numeric claim for an observable: the value is
converted with the ontology's unit catalogue into each applicable reference
interval's unit, checked against the protocol's sanctioned parameters, and
classified for panic limits. A protocol without structured reference intervals
cannot be attested (fail closed).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ontogate.models import AttestedComputation, ProtocolDefinition, ReferenceInterval

CRITICAL = {"CRITICAL_LOW", "CRITICAL_HIGH"}


class AttestationResult(BaseModel):
    """Result of a deterministic attestation check over a numeric claim."""
    passed: bool
    verdict: str                  # "PASS" | "FAIL" | "STALE"
    executed_check: str
    attested_value: Optional[float]
    expected_range: str
    is_panic: bool = False
    message: str = ""
    classification: Dict[str, str] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _analyte_id(analyte: str, registry: Any) -> Optional[str]:
    a = (analyte or "").strip().lower()
    if not a:
        return None
    if a in registry.analytes:
        return a
    for aid, entity in registry.analytes.items():
        if entity.label.lower() == a:
            return aid
    return None


def convert_unit(value: float, from_unit: str, to_unit: str, analyte: str = "") -> Optional[float]:
    """Convert between clinical units using the ontology's unit catalogue.

    Mass ↔ molar conversion needs a named analyte with a declared molar mass;
    without one the result is None (no analyte is ever assumed).
    """
    from ontogate.config import get_default_registry
    from ontogate.units import convert

    registry = get_default_registry()
    return convert(value, from_unit, to_unit, registry, analyte=_analyte_id(analyte, registry))


def _result(passed: bool, verdict: str, check: str, value: float, expected: str, message: str,
            is_panic: bool = False, classification: Optional[Dict[str, str]] = None) -> AttestationResult:
    return AttestationResult(passed=passed, verdict=verdict, executed_check=check, attested_value=value,
                             expected_range=expected, is_panic=is_panic, message=message,
                             classification=classification or {})


def attest_numeric(
    value: float,
    protocol: ProtocolDefinition,
    computation: Optional[AttestedComputation] = None,
    unit: str = "",
    registry: Any = None,
    population: Optional[Dict[str, str]] = None,
) -> AttestationResult:
    """Attest a patient value against a sanctioned protocol computation (OKF §5.4).

    Checks, in order: staleness; non-negativity; structured intervals exist;
    unit conversion into the interval's unit; declared parameter bounds
    (``expected_min`` / ``expected_max`` / ``require_in_range``); panic detection
    from the critical limits. The agent supplies values only — it cannot alter
    the computation.
    """
    comp = computation or protocol.attested_computation
    check = comp.attester if (comp and comp.attester) else "deterministic_range_checker"
    expected = protocol.reference_range

    if protocol.is_stale():
        return _result(False, "STALE", check, value, expected, "Protocol is stale — attestation rejected.")
    if value < 0.0:
        return _result(False, "FAIL", check, value, expected,
                       f"Value {value} is physiologically implausible or negative (must be ≥ 0).")

    if registry is None:
        from ontogate.config import get_default_registry
        registry = get_default_registry()
    concept = registry.concepts.get(protocol.governs or "")
    intervals: List[ReferenceInterval] = []
    if concept is not None:
        intervals = [i for i in registry.intervals_for(concept.uri) if i.applies_to(population or {})]
    if not intervals:
        return _result(False, "FAIL", check, value, expected,
                       f"No structured reference interval governs '{protocol.governs}'; attestation not possible.")

    from ontogate.units import convert

    target_unit = intervals[0].unit
    val = convert(value, unit or target_unit, target_unit, registry, analyte=concept.measures)
    if val is None:
        return _result(False, "FAIL", check, value, expected,
                       f"Cannot convert reported unit '{unit}' to protocol unit '{target_unit}'.")
    classification: Dict[str, str] = {}
    for interval in intervals:
        iv = convert(value, unit or target_unit, interval.unit, registry, analyte=concept.measures)
        if iv is not None:
            classification[interval.population_label()] = interval.classify(iv)
    is_panic = any(c in CRITICAL for c in classification.values())

    params = comp.parameters if comp else {}
    normal = intervals[0].normal if len(intervals) == 1 else (None, None)
    failure = _parameter_failure(value, val, params, normal, expected)
    if failure:
        return _result(False, "FAIL", check, value, failure[0], failure[1], is_panic, classification)
    return _result(True, "PASS", check, value, expected,
                   "Deterministic computation and range check attested [Attested ✓].", is_panic, classification)


def _parameter_failure(value: float, val: float, params: Dict[str, Any], normal: Tuple[Optional[float], Optional[float]],
                       expected_text: str) -> Optional[Tuple[str, str]]:
    expected_min = params.get("expected_min")
    expected_max = params.get("expected_max")
    if expected_min is not None and val < float(expected_min):
        return f"[{expected_min}, {expected_max}]", f"Value {value} falls below expected minimum {expected_min}."
    if expected_max is not None and val > float(expected_max):
        return f"[{expected_min}, {expected_max}]", f"Value {value} exceeds expected maximum {expected_max}."
    if params.get("require_in_range"):
        low, high = normal
        if low is not None and high is not None and not (low <= val <= high):
            return expected_text, f"Value {value} falls outside reference range [{low}, {high}]."
    return None
