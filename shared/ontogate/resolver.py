"""
Ontology-derived term resolution — the single semantics shared by every
detector, MCP tool and framework adapter.

Pipeline for (term, unit, qualifier, value, population):

1. Lexical candidates: designations / labels → usable observables (deprecated
   observables are redirected via ``superseded_by`` or dropped).
2. Unit filter: keep observables that admit the reported unit.
3. Qualifier: population value (e.g. ``female``) → population context; facet
   value (e.g. ``total``, ``ica``) → keep observables with that facet value;
   otherwise a whole-word match against labels (e.g. ``I`` / ``T``).
   A facet value the single remaining observable does not carry is a contradiction.
4. Readings: classify the value under each candidate's applicable reference
   intervals after deterministic unit conversion.

Nothing here calls a model; everything is derived from the loaded registry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ontogate.config import OntologyRegistry
from ontogate.models import ConceptDefinition, Designation, ReferenceInterval
from ontogate.units import convert

CRITICAL = {"CRITICAL_LOW", "CRITICAL_HIGH"}


@dataclass
class Reading:
    """One classification of a value under one reference interval."""
    uri: str
    name: str
    unit: str
    population: str
    classification: str
    interval_id: str
    trust_tier: str
    clinically_unvalidated: bool

    def as_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class Resolution:
    """Everything the gate needs to know about one evaluation context."""
    term: str
    unit: str
    qualifier: str
    value: Optional[float]
    population: Dict[str, str]
    designation: Optional[Designation] = None
    lexical: List[ConceptDefinition] = field(default_factory=list)
    unit_filtered: List[ConceptDefinition] = field(default_factory=list)
    candidates: List[ConceptDefinition] = field(default_factory=list)
    unit_mismatch: bool = False
    qualifier_facet: Optional[Tuple[str, str]] = None
    qualifier_population: Optional[Tuple[str, str]] = None
    contradiction: Optional[str] = None
    redirected_from: List[str] = field(default_factory=list)

    @property
    def is_ambiguous(self) -> bool:
        return len(self.candidates) > 1

    @property
    def resolved(self) -> Optional[ConceptDefinition]:
        return self.candidates[0] if len(self.candidates) == 1 else None


# ---------------------------------------------------------------------------
# Lexical candidates
# ---------------------------------------------------------------------------

def lexical_candidates(registry: OntologyRegistry, term: str) -> Tuple[List[ConceptDefinition], List[str]]:
    """Return usable observables for a term, following ``superseded_by`` for deprecated ones."""
    found = registry.find_concepts(term) if term.strip() else []
    usable: List[ConceptDefinition] = []
    redirected: List[str] = []
    for c in found:
        if c.is_usable():
            usable.append(c)
        elif c.superseded_by and c.superseded_by in registry.concepts:
            target = registry.concepts[c.superseded_by]
            if target.is_usable():
                usable.append(target)
                redirected.append(c.uri)
    unique: Dict[str, ConceptDefinition] = {c.uri: c for c in usable}
    return list(unique.values()), redirected


def _whole_word(qualifier: str) -> "re.Pattern[str]":
    q = re.escape(qualifier.strip().lower())
    if len(qualifier.strip()) == 1:
        return re.compile(rf"(?:^|\s){q}\b", re.IGNORECASE)
    return re.compile(rf"\b{q}\b", re.IGNORECASE)


def resolve(
    registry: OntologyRegistry,
    term: str,
    unit: str = "",
    qualifier: str = "",
    value: Optional[float] = None,
    population: Optional[Dict[str, str]] = None,
    candidate_uris: Iterable[str] = (),
) -> Resolution:
    """Resolve an evaluation context against the ontology."""
    res = Resolution(term=term.strip(), unit=unit.strip(), qualifier=qualifier.strip(),
                     value=value, population=dict(population or {}))
    res.designation = registry.find_designation(res.term) if res.term else None
    lexical, redirected = lexical_candidates(registry, res.term)
    if not lexical:
        lexical = [registry.concepts[u] for u in candidate_uris if u in registry.concepts]
    res.lexical, res.redirected_from = lexical, redirected

    # 2. Unit filter
    cands = list(lexical)
    if res.unit and cands:
        filtered = [c for c in cands if c.supports_unit(res.unit)]
        if not filtered:
            res.unit_mismatch = True
            res.unit_filtered = []
            res.candidates = cands
            return res
        cands = filtered
    res.unit_filtered = list(cands)

    # 3. Qualifier
    if res.qualifier:
        pop = registry.population_value(res.qualifier)
        facet = registry.facet_value(res.qualifier)
        if pop is not None:
            res.qualifier_population = pop
            res.population.setdefault(pop[0], pop[1])
        elif facet is not None:
            res.qualifier_facet = facet
            fid, fval = facet
            matching = [c for c in cands if c.facets.get(fid) == fval]
            if matching:
                cands = matching
            elif cands and all(fid in c.facets for c in cands):
                target = cands[0] if len(cands) == 1 else None
                label = target.label if target else ", ".join(c.name for c in cands)
                res.contradiction = (
                    f"Qualifier '{res.qualifier}' ({fid}={fval}) contradicts term or concept '{label}'."
                )
        elif len(cands) > 1:
            pattern = _whole_word(res.qualifier)
            matching = [c for c in cands if any(pattern.search(t) for t in [c.label, c.name, *c.alt_labels])]
            if matching:
                cands = matching
    res.candidates = cands
    return res


# ---------------------------------------------------------------------------
# Readings
# ---------------------------------------------------------------------------

def applicable_intervals(registry: OntologyRegistry, concept: ConceptDefinition,
                         population: Dict[str, str]) -> List[ReferenceInterval]:
    return [i for i in registry.intervals_for(concept.uri) if i.applies_to(population)]


def classify(registry: OntologyRegistry, concept: ConceptDefinition, value: float, unit: str,
             population: Dict[str, str]) -> List[Reading]:
    """Classify ``value`` (expressed in ``unit``) under every applicable interval."""
    readings: List[Reading] = []
    for interval in applicable_intervals(registry, concept, population):
        converted = convert(value, unit, interval.unit, registry, analyte=concept.measures)
        if converted is None:
            continue
        readings.append(Reading(
            uri=concept.uri, name=concept.name, unit=unit, population=interval.population_label(),
            classification=interval.classify(converted), interval_id=interval.id,
            trust_tier=interval.trust_tier.value, clinically_unvalidated=interval.clinically_unvalidated,
        ))
    return readings


def collapse(readings: List[Reading]) -> Optional[str]:
    """Single classification if all readings agree, else a ``|``-joined set (population divergence)."""
    classes = sorted({r.classification for r in readings})
    if not classes:
        return None
    return classes[0] if len(classes) == 1 else "|".join(classes)


def shared_units(concepts: List[ConceptDefinition]) -> List[str]:
    """Units every candidate admits, ordered by the first candidate's preference."""
    if not concepts:
        return []
    first = concepts[0].units
    lowered = [set(u.lower() for u in c.units) for c in concepts[1:]]
    return [u for u in first if all(u.lower() in s for s in lowered)]


@dataclass
class CollisionAssessment:
    """Result of comparing a value across look-alike candidates."""
    applicable: bool
    divergent: bool
    readings: Dict[str, str]
    readings_unit: Optional[str]
    detail: List[Dict[str, Any]]
    units_checked: List[str]


def assess_collision(registry: OntologyRegistry, res: Resolution) -> CollisionAssessment:
    """Compare a value across >1 candidates in every unit they share (or the reported unit)."""
    cands = res.candidates
    if res.value is None or len(cands) < 2:
        return CollisionAssessment(False, False, {}, None, [], [])
    units = [res.unit] if res.unit else shared_units(cands)
    if not units:
        # Candidates use disjoint units: the unit alone disambiguates (Hb vs HbA1c).
        return CollisionAssessment(False, False, {}, None, [], [])
    divergent = False
    display: Dict[str, str] = {}
    detail: List[Dict[str, Any]] = []
    for i, unit in enumerate(units):
        per_candidate: Dict[str, str] = {}
        for c in cands:
            rs = classify(registry, c, res.value, unit, res.population)
            detail.extend(r.as_dict() for r in rs)
            collapsed = collapse(rs)
            if collapsed is not None:
                per_candidate[c.name] = collapsed
        if len(per_candidate) >= 2 and len(set(per_candidate.values())) > 1:
            divergent = True
        if i == 0:
            display = per_candidate
    return CollisionAssessment(True, divergent, display, units[0], detail, units)


@dataclass
class PopulationAssessment:
    """Whether the population context changes the classification of a resolved value."""
    readings: Dict[str, str]
    divergent: bool
    critical_divergent: bool
    facets: List[str]


def assess_population(registry: OntologyRegistry, concept: ConceptDefinition, value: float,
                      unit: str, population: Dict[str, str]) -> PopulationAssessment:
    rs = classify(registry, concept, value, unit, population)
    by_pop = {r.population: r.classification for r in rs}
    classes = set(by_pop.values())
    crit = {c in CRITICAL for c in classes}
    facets: Set[str] = set()
    for i in applicable_intervals(registry, concept, population):
        facets |= {k for k, v in i.population.items() if v != "any" and k not in population}
    return PopulationAssessment(
        readings=by_pop,
        divergent=len(classes) > 1,
        critical_divergent=len(classes) > 1 and len(crit) > 1,
        facets=sorted(facets),
    )


def differing_facets(registry: OntologyRegistry, cands: List[ConceptDefinition]) -> Dict[str, List[str]]:
    """Facets on which the candidates differ → the values they take."""
    out: Dict[str, List[str]] = {}
    for fid in registry.facets:
        values = {c.facets.get(fid) for c in cands}
        if len(values) > 1 and None not in values:
            out[fid] = sorted(v for v in values if v)
    return out
