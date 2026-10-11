"""
Attested computation tool for Strands Agents.
``@tool`` wrapper over the canonical ``ontogate.tools.attest_computation``:
classifies a value against the governing reference interval deterministically.
"""
from typing import Any, Dict
from strands import tool
from ontogate.tools import attest_computation as _attest_computation


@tool
def attest_computation(value: float, uri: str, unit: str = "", sex: str = "", age_band: str = "") -> Dict[str, Any]:
    """Deterministically attest a patient value for one observable URI.

    Args:
        value: Reported patient value.
        uri: Resolved observable URI (e.g. 'loinc:718-7').
        unit: Reported UCUM unit; converted to the interval's unit when admitted.
        sex: Optional population facet value.
        age_band: Optional population facet value.

    Returns:
        dict with verdict (PASS/FAIL), the attested classification and the interval used.
    """
    return _attest_computation(value=value, uri=uri, unit=unit, sex=sex, age_band=age_band)
