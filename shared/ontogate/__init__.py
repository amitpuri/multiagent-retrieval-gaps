"""
ontogate — the shared, framework-agnostic ontology and deterministic safety-gate core.

Imported directly by google-adk-agents, strands-agents and agent-framework.
Contains no LLM calls and no cloud SDK dependencies.

Modules
-------
models / config      Ontology entities and the pack loader / registry
resolver / units     Ontology-derived term resolution and unit conversion
detectors            Deterministic gap detectors and the SafetyGateEngine
attestation          OKF §5.4 attested computation over reference intervals
parsing / clarify    Clinician input parser and deterministic clarification text
tools / mcp_server   Canonical tool contract and its MCP server
validate             Ontology integrity rules
rdf_export           SKOS / OWL / SHACL / PROV-O export and the ontology bundle
catalog              Model catalog (config/models.yaml)
skills / roles       Runtime Agent Skills build and role specifications
skill_refs           Skill references rendered from the ontology
cloud_stores         Skill stores per cloud (GCS, S3, Azure Blob) behind SkillStorePort
cli                  `ontogate` command line (validate, skills, rdf, build)
ports / release      Runtime ports (audit, telemetry, stores) and release identity
"""

__version__ = "1.0.0"

from ontogate.attestation import AttestationResult, attest_numeric, convert_unit
from ontogate.concept_graph import (
    concept_subgraph,
    find_governing_protocols,
    find_lookalikes,
    get_direct_links,
    neighbors,
)
from ontogate.config import OntologyRegistry, get_default_registry, load_domain_config, load_scenario_extension
from ontogate.models import (
    AttestedComputation,
    ConceptDefinition,
    ConceptLink,
    ConceptSource,
    Designation,
    EvaluationContext,
    Facet,
    GapEvaluationResult,
    Observable,
    ProtocolDefinition,
    ReferenceInterval,
    RelationshipKind,
    ResolutionStatus,
    TrustTier,
)
from ontogate.okf_index import (
    ConceptIndexEntry,
    build_index,
    export_index_markdown,
    inspect_index_scope,
    search_index,
)
from ontogate.okf_writer import format_log_entry, read_update_log, record_concept_update

from ontogate.roles import RoleSpec, load_all_role_specs, load_role_spec
from ontogate.skills import SkillPackage, build_skills, check_skills, lint_skill_package, skills_for_role, verify_skills_lock

# Optional layers import on demand: ontogate.rdf_export (needs the [rdf] extra)
# and ontogate.cloud_stores (cloud SDKs are imported lazily per store).

__all__ = [
    "TrustTier", "RelationshipKind", "ResolutionStatus", "ConceptLink", "ConceptSource",
    "AttestedComputation", "ConceptDefinition", "Observable", "Designation", "Facet",
    "ReferenceInterval", "ProtocolDefinition", "EvaluationContext", "GapEvaluationResult",
    "OntologyRegistry", "load_domain_config", "load_scenario_extension", "get_default_registry",
    "ConceptIndexEntry", "build_index", "search_index", "inspect_index_scope", "export_index_markdown",
    "get_direct_links", "neighbors", "find_lookalikes", "find_governing_protocols", "concept_subgraph",
    "record_concept_update", "format_log_entry", "read_update_log",
    "AttestationResult", "attest_numeric", "convert_unit",
    "RoleSpec", "load_role_spec", "load_all_role_specs",
    "SkillPackage", "build_skills", "check_skills", "lint_skill_package", "skills_for_role",
    "verify_skills_lock",
]
