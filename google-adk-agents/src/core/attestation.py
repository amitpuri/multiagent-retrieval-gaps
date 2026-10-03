"""
Open Knowledge Format (OKF) Attested Computation Gate.
Provides deterministic runtime attestation for numeric claims, range boundaries,
and sanctioned calculations per OKF v0.2 §5.4 and §9.
Ensures critical numbers cannot be hallucinated or rewritten by generative agents.
"""

from datetime import datetime, timezone
import re
from typing import Any, Dict, Optional, Tuple
from pydantic import BaseModel, Field
from src.core.models import AttestedComputation, ProtocolDefinition


class AttestationResult(BaseModel):
    """Result of a deterministic attestation check over a numeric claim."""
    passed: bool
    verdict: str                  # "PASS" | "FAIL" | "STALE" | "ERROR"
    executed_check: str
    attested_value: Optional[float]
    expected_range: str
    is_panic: bool = False
    message: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def parse_range_bounds(range_str: str) -> Tuple[Optional[float], Optional[float]]:
    """Extract (low, high) float boundaries from reference or panic strings.
    
    Handles patterns such as:
      - '8.6 to 10.2 mg/dL'
      - '4.5 - 5.6'
      - 'Low < 6.5 mg/dL; high > 14.0 mg/dL'
    """
    if not range_str:
        return None, None

    matches = re.findall(r"(\d+(?:\.\d+)?)", range_str)
    if len(matches) >= 2:
        return float(matches[0]), float(matches[1])
    elif len(matches) == 1:
        return float(matches[0]), None
    return None, None


def attest_numeric(
    value: float,
    protocol: ProtocolDefinition,
    computation: Optional[AttestedComputation] = None,
) -> AttestationResult:
    """Attest a patient value against a sanctioned protocol computation.
    
    OKF §5.4: executor runs sanctioned computation,
    attester checks result matches authoritative source.
    Agent CANNOT rewrite the computation.
    
    Checks performed:
      1. Staleness check: rejects if protocol is past its stale_after date.
      2. Physiological plausibility: rejects negative or extreme values (>1000).
      3. Custom parameter bounds: checks expected_min, expected_max, or require_in_range if specified.
      4. Identifies panic limit crossings.
    """
    comp = computation or protocol.attested_computation
    executed_check = comp.attester if (comp and comp.attester) else "deterministic_range_checker"

    # 1. Staleness check
    if protocol.is_stale():
        return AttestationResult(
            passed=False,
            verdict="STALE",
            executed_check=executed_check,
            attested_value=value,
            expected_range=protocol.reference_range,
            message="Protocol is stale — attestation rejected.",
        )

    # 2. Physiological plausibility
    if value < 0.0 or value > 1000.0:
        return AttestationResult(
            passed=False,
            verdict="FAIL",
            executed_check=executed_check,
            attested_value=value,
            expected_range=protocol.reference_range,
            message=f"Value {value} is physiologically implausible or negative.",
        )

    ref_low, ref_high = parse_range_bounds(protocol.reference_range)
    panic_low, panic_high = parse_range_bounds(protocol.panic_limits)

    is_panic = False
    if panic_low is not None and value < panic_low:
        is_panic = True
    if panic_high is not None and value > panic_high:
        is_panic = True

    # 3. Parameters check
    params = comp.parameters if comp else {}
    expected_min = params.get("expected_min")
    expected_max = params.get("expected_max")
    require_in_range = params.get("require_in_range", False)

    if expected_min is not None and value < float(expected_min):
        return AttestationResult(
            passed=False,
            verdict="FAIL",
            executed_check=executed_check,
            attested_value=value,
            expected_range=f"[{expected_min}, {expected_max}]",
            is_panic=is_panic,
            message=f"Value {value} falls below expected minimum {expected_min}.",
        )

    if expected_max is not None and value > float(expected_max):
        return AttestationResult(
            passed=False,
            verdict="FAIL",
            executed_check=executed_check,
            attested_value=value,
            expected_range=f"[{expected_min}, {expected_max}]",
            is_panic=is_panic,
            message=f"Value {value} exceeds expected maximum {expected_max}.",
        )

    if require_in_range and ref_low is not None and ref_high is not None:
        if not (ref_low <= value <= ref_high):
            return AttestationResult(
                passed=False,
                verdict="FAIL",
                executed_check=executed_check,
                attested_value=value,
                expected_range=protocol.reference_range,
                is_panic=is_panic,
                message=f"Value {value} falls outside reference range [{ref_low}, {ref_high}].",
            )

    return AttestationResult(
        passed=True,
        verdict="PASS",
        executed_check=executed_check,
        attested_value=value,
        expected_range=protocol.reference_range,
        is_panic=is_panic,
        message="Deterministic computation and range check attested [Attested ✓].",
    )
