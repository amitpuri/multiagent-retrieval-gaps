# Shared Core (`ontogate`)

> **The Framework-Agnostic Clinical Ontology, Deterministic Safety Gate & FastMCP Tool Server**

`ontogate` is a pure-Python, zero-cloud-dependency shared library that centralizes the clinical knowledge models, deterministic safety gating, LOINC term resolution, UCUM unit conversions, and canonical FastMCP tools used by all three multi-agent frameworks in this repository:
- **Google ADK 2.0** (`google-adk-agents/`)
- **AWS Strands Agents SDK** (`strands-agents/`)
- **Microsoft Agent Framework** (`agent-framework/`)

---

## Key Invariants

1. **Deterministic Safety Gate (Gap 9):**
   `SafetyGateEngine` and all 7 pluggable gap detectors run in pure deterministic Python. **No LLM calls**, no probabilistic branching, and fail-closed routing (`PROCEED` only on `RESOLVED`; `AMBIGUOUS`, `UNIT_MISMATCH`, `RANGE_COLLISION`, `NOT_FOUND` all route to `CLARIFY`).
2. **Framework Independence:**
   Zero vendor SDK dependencies (no Google GenAI, no AWS Boto3/Bedrock, no Azure/OpenAI SDKs).
3. **Canonical Tool Contracts:**
   All clinical tools return typed `Dict[str, Any]` with an explicit `"status"` field matching `ResolutionStatus`.

---

## Package Structure

```text
shared/
├── pyproject.toml              # ontogate v1.0.0 package specification
├── pytest.ini                  # pythonpath = . ontogate
├── ontogate/
│   ├── models.py               # Pydantic schemas (TrustTier, ConceptDefinition, ReferenceInterval, etc.)
│   ├── config.py               # YAML pack loader & OntologyRegistry
│   ├── paths.py                # Repository root & knowledge artifact discovery
│   ├── parsing.py              # Ontology-aware clinician input parsing
│   ├── clarify.py              # Deterministic clinical clarification generation
│   ├── resolver.py             # LOINC concept resolution & semantic mapping
│   ├── units.py                # Canonical UCUM unit checks & conversions
│   ├── concept_graph.py        # Concept graph traversal, look-alikes & protocols
│   ├── okf_index.py            # Progressive disclosure catalog index (OKF §7.1)
│   ├── okf_writer.py           # Knowledge writeback & log.md maintenance
│   ├── attestation.py          # Deterministic numeric range attestation (OKF §5.4)
│   ├── catalog.py              # Model catalog loader (config/models.yaml)
│   ├── tools.py                # Canonical clinical tool contract implementations
│   ├── mcp_server.py           # FastMCP server (6 clinical tools via MCP protocol)
│   ├── validate.py             # Ontology integrity & schema validation rules
│   ├── ports.py                # Runtime ports (audit, telemetry, stores)
│   ├── release.py              # Knowledge release stamping & manifests
│   └── detectors/              # 7 pluggable deterministic gap detectors + SafetyGateEngine
│       ├── engine.py           # SafetyGateEngine (deterministic gate, fail-closed)
│       ├── ambiguity.py        # AmbiguityDetector (Gap 8)
│       ├── unit_mismatch.py    # UnitMismatchDetector (Gap 2)
│       ├── missing_qualifier.py# MissingQualifierDetector (Gap 5)
│       ├── missing_unit.py     # MissingUnitDetector
│       ├── range_collision.py  # RangeCollisionDetector (Look-Alikes)
│       ├── specimen_sequence.py# SpecimenSequenceDetector (Gap 11)
│       └── population_context.py# PopulationContextDetector
└── tests/                      # 78 deterministic unit & invariant tests
```

---

## Installation & Usage

### Local Development
Each framework mounts `shared/` via its `pytest.ini` (`pythonpath = . src ../shared`) and dynamic path detection in `ontogate.paths`.

### Production Containers
Dockerfiles install `ontogate` directly as a local wheel or package:
```dockerfile
COPY shared/ /tmp/shared/
RUN pip install --no-cache-dir "/tmp/shared[mcp]" && rm -rf /tmp/shared
```

---

## Running Invariant Tests

```bash
cd shared
python -m pytest tests/ -v
# 78 passed in ~0.6 s (pure Python, 0 LLM calls)
```
