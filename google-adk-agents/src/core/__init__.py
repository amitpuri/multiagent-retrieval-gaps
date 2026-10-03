"""
Core package for the generic and reusable multi-agent retrieval-gap framework.
Enhanced with Open Knowledge Format (OKF) index, graph traversal, audit writeback, and attestation.
"""

from src.core.attestation import AttestationResult, attest_numeric, parse_range_bounds
from src.core.concept_graph import (
    concept_subgraph,
    find_governing_protocols,
    find_lookalikes,
    get_direct_links,
    neighbors,
)
from src.core.config import OntologyRegistry, get_default_registry, load_domain_config
from src.core.models import (
    AttestedComputation,
    ConceptDefinition,
    ConceptLink,
    ConceptSource,
    ProtocolDefinition,
    RelationshipKind,
    TrustTier,
)
from src.core.okf_index import (
    ConceptIndexEntry,
    build_index,
    export_index_markdown,
    inspect_index_scope,
    search_index,
)
from src.core.okf_writer import format_log_entry, read_update_log, record_concept_update

__all__ = [
    # Models
    "TrustTier",
    "RelationshipKind",
    "ConceptLink",
    "ConceptSource",
    "AttestedComputation",
    "ConceptDefinition",
    "ProtocolDefinition",
    # Config
    "OntologyRegistry",
    "load_domain_config",
    "get_default_registry",
    # OKF Index (Phase 5)
    "ConceptIndexEntry",
    "build_index",
    "search_index",
    "inspect_index_scope",
    "export_index_markdown",
    # Concept Graph (Phase 6)
    "get_direct_links",
    "neighbors",
    "find_lookalikes",
    "find_governing_protocols",
    "concept_subgraph",
    # OKF Writer (Phase 7)
    "record_concept_update",
    "format_log_entry",
    "read_update_log",
    # Attestation (Phase 8)
    "AttestationResult",
    "attest_numeric",
    "parse_range_bounds",
]
