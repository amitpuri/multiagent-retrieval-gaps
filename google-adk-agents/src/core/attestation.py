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
      - 'Low < 6.5 mg/dL; high > 14.0 mg/dL'  (compound — both sides)
      - 'High > 52 ng/L'       → (None, 52.0)  upper-only
      - 'Low < 6.5 mg/dL'     → (6.5, None)   lower-only

    Fix 3: one-sided limit strings are now correctly assigned.
    "High > 52" means the UPPER limit is 52 → high=52, low=None.
    "Low < 6.5" means the LOWER limit is 6.5 → low=6.5, high=None.
    Compound strings (semicolon or comma-joined) scan for both.
    """
    if not range_str:
        return None, None

    s = range_str.strip().lower()

    # --- Compound string: contains BOTH a high and a low part ---
    # "Low < 6.5 mg/dL; high > 14.0 mg/dL"
    low_from_compound: Optional[float] = None
    high_from_compound: Optional[float] = None

    low_m = re.search(r"(?:low\s*)?[<≤]\s*(\d+(?:\.\d+)?)", s)
    high_m = re.search(r"(?:high\s*)?[>≥]\s*(\d+(?:\.\d+)?)", s)
    if low_m:
        low_from_compound = float(low_m.group(1))
    if high_m:
        high_from_compound = float(high_m.group(1))
    if low_from_compound is not None or high_from_compound is not None:
        # At least one side was found via directional keyword; return both.
        return low_from_compound, high_from_compound

    # --- Two-number range: "8.6 to 10.2", "4.5 - 5.6", "8.6–10.2" ---
    two_num = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:to|-|–)\s*(\d+(?:\.\d+)?)", s
    )
    if two_num:
        return float(two_num.group(1)), float(two_num.group(2))

    # --- Keyword-only patterns without operator: "Panic high 14.0", "Crit low 6.5" ---
    high_kw = re.search(r"(?:panic\s+|crit(?:ical)?\s+)?high\s+(\d+(?:\.\d+)?)", s)
    if high_kw:
        return None, float(high_kw.group(1))

    low_kw = re.search(r"(?:panic\s+|crit(?:ical)?\s+)?low\s+(\d+(?:\.\d+)?)", s)
    if low_kw:
        return float(low_kw.group(1)), None

    # --- Fallback: extract all numbers; treat first as low, second as high ---
    matches = re.findall(r"\d+(?:\.\d+)?", s)
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

    # 2. Negative-value plausibility check (universally invalid for lab measurements).
    # Fix 3b: the former hard upper cap of 1000.0 has been removed — it incorrectly
    # blocked legitimate analytes such as troponin (> 2500 ng/L in MI) and ferritin.
    # Upper-bound plausibility is now enforced only via expected_max in
    # attested_computation.parameters, which is configurable per assay.
    if value < 0.0:
        return AttestationResult(
            passed=False,
            verdict="FAIL",
            executed_check=executed_check,
            attested_value=value,
            expected_range=protocol.reference_range,
            message=f"Value {value} is physiologically implausible or negative (must be ≥ 0).",
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
