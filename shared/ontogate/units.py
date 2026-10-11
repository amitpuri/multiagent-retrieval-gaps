"""
Deterministic unit conversion from the ontology.

Units come from the core catalogue (UCUM code → dimension + factor to the
dimension's base unit). Mass ↔ substance conversion uses the analyte's declared
molar mass. Nothing is inferred from text and no analyte is assumed: anything not
derivable from the ontology returns ``None`` and callers fail closed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ontogate.config import OntologyRegistry

_MASS = "mass_concentration"        # base g/L
_SUBSTANCE = "substance_concentration"  # base mol/L


def same_unit(a: str, b: str) -> bool:
    return bool(a) and bool(b) and a.strip().lower() == b.strip().lower()


def convert(
    value: float,
    from_unit: str,
    to_unit: str,
    registry: "OntologyRegistry",
    analyte: Optional[str] = None,
) -> Optional[float]:
    """Convert ``value`` between units, or return None when not derivable."""
    if not from_unit or not to_unit or same_unit(from_unit, to_unit):
        return value
    src = registry.unit(from_unit)
    dst = registry.unit(to_unit)
    if src is None or dst is None:
        return None
    base = value * src.factor
    if src.dimension == dst.dimension:
        return base / dst.factor
    molar_mass = None
    if analyte:
        a = registry.analytes.get(analyte)
        molar_mass = a.molar_mass_g_mol if a else None
    if molar_mass is None:
        return None
    if src.dimension == _SUBSTANCE and dst.dimension == _MASS:
        return (base * molar_mass) / dst.factor
    if src.dimension == _MASS and dst.dimension == _SUBSTANCE:
        return (base / molar_mass) / dst.factor
    return None


def convertible(from_unit: str, to_unit: str, registry: "OntologyRegistry", analyte: Optional[str] = None) -> bool:
    return convert(1.0, from_unit, to_unit, registry, analyte) is not None
