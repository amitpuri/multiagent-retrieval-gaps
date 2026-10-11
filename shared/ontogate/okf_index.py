"""
Open Knowledge Format (OKF) Progressive Disclosure Index.
Provides lightweight in-memory catalog index of concepts for cheap pre-scoping,
triage routing, and progressive disclosure without loading heavy definitions.
Per OKF v0.2 §7.1.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from ontogate.config import OntologyRegistry


@dataclass
class ConceptIndexEntry:
    """Lightweight summary of an ontology concept for catalog/index views."""
    uri: str
    label: str
    type: str = "LabTest"
    tags: List[str] = field(default_factory=list)
    status: str = "stable"
    trust_tier: str = "unverified"
    alt_labels: List[str] = field(default_factory=list)


def build_index(registry: OntologyRegistry) -> List[ConceptIndexEntry]:
    """Build progressive disclosure index from an active OntologyRegistry.
    
    Excludes non-usable (deprecated) concepts per OKF §7.1 lifecycle rules.
    Extracts tags (department, specimen) and resolved trust tier.
    """
    entries: List[ConceptIndexEntry] = []
    for concept in registry.concepts.values():
        if not concept.is_usable():
            continue
        tags = [t for t in [concept.department, concept.specimen] if t]
        entries.append(
            ConceptIndexEntry(
                uri=concept.uri,
                label=concept.label,
                type="LabTest",
                tags=tags,
                status=concept.status,
                trust_tier=concept.trust_tier.value,
                alt_labels=list(concept.alt_labels),
            )
        )
    return entries


def search_index(index: List[ConceptIndexEntry], term: str) -> List[ConceptIndexEntry]:
    """Search concept index by matching term against label, alt_labels, or URI."""
    term_clean = term.strip().lower()
    if not term_clean:
        return []

    matches: List[ConceptIndexEntry] = []
    for entry in index:
        if (
            term_clean in entry.label.lower()
            or term_clean in entry.uri.lower()
            or any(term_clean == alias.lower() or term_clean in alias.lower() for alias in entry.alt_labels)
        ):
            matches.append(entry)
    return matches


def inspect_index_scope(index: List[ConceptIndexEntry], term: str) -> Dict[str, Any]:
    """Inspect index matches for cheap type + department pre-scoping.
    
    Returns:
        Dict with matches, match_count, department_scope (if all matches share a department),
        and is_empty boolean.
    """
    matches = search_index(index, term)
    departments = {entry.tags[0] for entry in matches if entry.tags}
    department_scope = departments.pop() if len(departments) == 1 else None

    return {
        "matches": matches,
        "match_count": len(matches),
        "department_scope": department_scope,
        "is_empty": len(matches) == 0,
    }


def export_index_markdown(index: List[ConceptIndexEntry]) -> str:
    """Render index as an OKF-style index.md table for documentation and agents."""
    lines = [
        "# Concept Index (OKF Progressive Disclosure)",
        "",
        "| URI | Label | Type | Tags | Status | Trust Tier |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in index:
        tags_str = ", ".join(entry.tags) if entry.tags else "-"
        lines.append(
            f"| `{entry.uri}` | {entry.label} | {entry.type} | {tags_str} | {entry.status} | {entry.trust_tier} |"
        )
    return "\n".join(lines)
