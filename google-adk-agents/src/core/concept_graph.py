"""
Open Knowledge Format (OKF) Typed Concept Graph.
Provides graph traversal, multi-hop retrieval, and look-alike detection
over typed concept-to-concept and concept-to-protocol relationships.
Per OKF v0.2 §4 and §8.2.
"""

from collections import deque
from typing import Any, Dict, List, Optional, Set, Union
from src.core.config import OntologyRegistry
from src.core.models import ConceptLink, RelationshipKind


def get_direct_links(
    uri: str,
    registry: OntologyRegistry,
    kind: Optional[Union[RelationshipKind, str]] = None,
) -> List[ConceptLink]:
    """Return outgoing ConceptLinks for a given URI, optionally filtered by relationship kind."""
    concept = registry.concepts.get(uri)
    if not concept:
        return []

    target_kind = RelationshipKind(kind) if isinstance(kind, str) else kind

    if target_kind is None:
        return list(concept.links)
    return [lk for lk in concept.links if lk.kind == target_kind]


def neighbors(
    uri: str,
    registry: OntologyRegistry,
    kind: Optional[Union[RelationshipKind, str]] = None,
    depth: int = 1,
) -> List[str]:
    """Return unique URIs reachable from `uri` up to `depth` hops via typed links.
    
    OKF §8.2: 'link-following: after retrieving a hit, include its linked concepts'
    Traverses the graph using breadth-first search (BFS).
    
    Args:
        uri: Starting concept URI.
        registry: Active OntologyRegistry.
        kind: Optional RelationshipKind (or string) filter. If None, all link types are traversed.
        depth: Maximum number of hops (must be >= 1).
    
    Returns:
        List of reachable URIs in discovery order (excluding the origin URI).
    """
    if depth < 1:
        return []

    visited: Set[str] = {uri}
    discovered: List[str] = []
    # Queue stores tuples of (current_uri, current_depth)
    queue = deque([(uri, 0)])

    while queue:
        curr_uri, curr_depth = queue.popleft()
        if curr_depth >= depth:
            continue

        outgoing = get_direct_links(curr_uri, registry, kind=kind)
        for link in outgoing:
            target = link.target_uri
            if target not in visited:
                visited.add(target)
                discovered.append(target)
                # If target is also a registered concept, we can traverse deeper
                if target in registry.concepts:
                    queue.append((target, curr_depth + 1))

    return discovered


def find_lookalikes(uri: str, registry: OntologyRegistry) -> List[str]:
    """Return all look-alike hazard URIs linked to `uri` via SEE_ALSO relationships."""
    return neighbors(uri, registry, kind=RelationshipKind.SEE_ALSO, depth=1)


def find_governing_protocols(uri: str, registry: OntologyRegistry) -> List[str]:
    """Return all protocol URIs governing `uri` via GOVERNED_BY relationships."""
    return neighbors(uri, registry, kind=RelationshipKind.GOVERNED_BY, depth=1)


def concept_subgraph(
    uri: str,
    registry: OntologyRegistry,
    depth: int = 1,
) -> Dict[str, List[Dict[str, Any]]]:
    """Extract an adjacency subgraph around `uri` up to `depth` hops."""
    nodes = [uri] + neighbors(uri, registry, depth=depth)
    graph: Dict[str, List[Dict[str, Any]]] = {}

    for node in nodes:
        links = get_direct_links(node, registry)
        graph[node] = [
            {
                "target_uri": lk.target_uri,
                "kind": lk.kind.value,
                "description": lk.description,
            }
            for lk in links
        ]

    return graph
