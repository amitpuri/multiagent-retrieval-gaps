# agent-framework — Microsoft Agent Framework (MAF) Implementation

*Framework 3 of the Multi-Agent Retrieval-Gap System (MARS)*
*Laboratory Medicine Decision Support — Declarative Agents + Agent Harness on Microsoft Agent Framework*

---

## Overview

This directory implements the clinical laboratory decision-support pipeline using the
**[Microsoft Agent Framework (MAF)](https://github.com/microsoft/agent-framework)** Python SDK,
with a strong preference for **declarative agents** (`kind: Prompt` YAML) and a
**declarative workflow** (`WorkflowFactory`).

It is the third framework port alongside:

| Framework | Directory | Model |
|:---|:---|:---|
| Google ADK | [`google-adk-agents/`](../google-adk-agents/) | Gemini 2.0 Flash |
| AWS Strands | [`strands-agents/`](../strands-agents/) | Claude 3.5 on Bedrock |
| **Microsoft MAF** | **`agent-framework/`** (this directory) | **gpt-5 via Azure AI Foundry / OpenAI** |

All three frameworks share the same **deterministic `SafetyGateEngine`**, the same **A2A message
contracts**, and the same **`config/` YAML knowledge base** — zero code change is required to add a
new clinical gap scenario.

---

## Architecture

```
Clinician query
      │
      ▼
clinical_decision_workflow.yaml   ← WorkflowFactory (stable)
      │
      ▼
triage_orchestrator.yaml          ← AgentFactory (experimental) — kind: Prompt
      │ calls tools (plain Python, bound via YAML bindings:)
      ├── parse_clinician_input()
      ├── resolve_ontology()        → LOINC concept resolution
      └── run_safety_gate()         → SafetyGateEngine (deterministic, no LLM)
                │
      ┌─────────┴──────────┐
  PROCEED                CLARIFY
      │                     │
      ▼                     ▼
protocol_retriever    clarification_coordinator
clinical_synthesizer      (HITL pause)
```

**Safety Gate** is deterministic pure-Python code. It evaluates five pluggable gap detectors:

| Detector | Gap |
|:---|:---|
| `AmbiguityDetector` | Gap 8 — ambiguous lab term |
| `UnitMismatchDetector` | Gap 2 — unit not supported by concept |
| `MissingQualifierDetector` | Gap 5 — qualifier needed (e.g. total vs. ionized) |
| `RangeCollisionDetector` | Look-alike test collision |
| `SpecimenSequenceDetector` | Gap 11 — tube ordering violation |

---

## Agent Harness

Beyond the declarative workflow runner, the implementation includes a full
**[MAF Agent Harness](https://learn.microsoft.com/en-us/agent-framework/concepts/harness?pivots=programming-language-python)**
(`src/harness/`) — the runtime scaffolding that turns a language model into a long-running
clinical decision agent with conversation state, planning todos, operating modes, and approval
policies.

### Harness Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│                     MAF Terminal Harness Console UX                       │
│  /todos · /mode [plan|execute] · /scenario <A-D> · /status · /clear      │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │
┌─────────────────────────────────────▼─────────────────────────────────────┐
│              ClinicalHarnessAgent  (create_clinical_harness_agent)        │
│  • Harness Instructions — clinical safety policies & fail-closed guards   │
│  • Agent Instructions  — LOINC synthesis & clinical decision support      │
├──────────────────────────────────────────┬────────────────────────────────┤
│ Context & State Providers                │ Middleware & Approval Policy   │
│  • ClinicalTodoProvider (4-step todos)   │  • SafetyGateApprovalPolicy    │
│  • ClinicalModeProvider (Plan/Execute)   │  • Standing auto-approvals     │
│  • HarnessSession (per-turn history)     │  • HITL gate on CLARIFY path   │
├──────────────────────────────────────────┴────────────────────────────────┤
│ Tool Pipeline (Plain Python — same bindings as YAML agents)               │
│  parse_clinician_input() → resolve_ontology() → run_safety_gate()         │
│  fetch_protocol()        → build_clarification_prompt()                   │
├───────────────────────────────────────────────────────────────────────────┤
│ Chat Client Layer (auto-detected)                                         │
│  Azure AI Foundry · Azure OpenAI · OpenAI Agents SDK · Offline Mock       │
└───────────────────────────────────────────────────────────────────────────┘
```

### Harness Capability Matrix

| Capability | Behaviour in Clinical Harness |
|:---|:---|
| **Function invocation** | All 6 clinical tools auto-wired with approval policy |
| **Per-turn history persistence** | `HarnessSession` persists each model call |
| **Todo tracking** | `ClinicalTodoProvider` — 4-step diagnostic workflow checklist |
| **Agent modes** | `ClinicalModeProvider` — `PLAN` (analysis only) and `EXECUTE` (full pipeline) |
| **Tool approval** | `SafetyGateApprovalPolicy` — standing approvals for lookups; HITL on `CLARIFY` |
| **Session isolation** | `agent.create_session()` — independent session IDs per clinical interaction |
| **Terminal UX** | Interactive REPL with `/todos`, `/mode`, `/scenario`, `/status`, `/clear`, `/exit` |

### Factory API (matches MAF `create_harness_agent`)

```python
from src.harness import create_clinical_harness_agent, AgentMode

# Default — EXECUTE mode, all tools registered
agent = create_clinical_harness_agent()

# Custom instructions and context window
agent = create_clinical_harness_agent(
    name="clinical_decision_harness",
    harness_instructions="Use tools deliberately. Never bypass the safety gate.",
    agent_instructions="You are a laboratory medicine decision support specialist.",
    max_context_window_tokens=128_000,
)

# Per-query session
session = agent.create_session()
response = await agent.run("Hb 13.5 | g/dL", session=session)
print(response.text)   # [PROCEED] Standardized LOINC concept: Hemoglobin...
print(response.route)  # PROCEED
print(response.status) # RESOLVED
```

### Plan vs Execute Modes

```python
# PLAN mode — analyse gaps without executing protocol retrieval
response = await agent.run("Calcium 4.8 | mg/dL", mode=AgentMode.PLAN)
# → [PLAN MODE] Diagnostic Analysis: AMBIGUOUS | Recommend: Clarify with clinician

# EXECUTE mode — run full pipeline
response = await agent.run("Hb 13.5 | g/dL", mode=AgentMode.EXECUTE)
# → [PROCEED] Hemoglobin [loinc:718-7] | Reference Range: 13.8–17.2 g/dL
```

---

## Technology Stack

| Layer | Implementation |
|:---|:---|
| **Agent definitions** | `kind: Prompt` YAML in `declarative-agents/` |
| **Workflow** | `WorkflowFactory` + `InvokeAgent / If` in `declarative-workflows/` |
| **Agent Harness** | `ClinicalHarnessAgent` + `create_clinical_harness_agent()` factory in `src/harness/` |
| **Agent loader** | `AgentFactory.create_agent_from_yaml_path()` (experimental) |
| **Model** | `gpt-5` via Azure AI Foundry · Azure OpenAI · OpenAI Agents SDK (local) |
| **Tool binding** | Plain Python functions — no `@tool` or `@kernel_function` decorator |
| **Safety gate** | `SafetyGateEngine` (shared — identical to ADK and Strands) |
| **Knowledge config** | `../config/` YAML (shared across all three frameworks) |
| **A2A contracts** | `A2AMessage` Pydantic schema (identical across frameworks) |
| **Tests** | 44 offline `pytest` invariants — 0 LLM calls, ~1.2 s |

---

## Credential Modes

The implementation auto-detects credentials in priority order:

| Priority | Mode | Env var | Use case |
|:---|:---|:---|:---|
| 1 | **Azure AI Foundry** | `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | Production |
| 2 | **Azure OpenAI direct** | `AZURE_OPENAI_ENDPOINT` | Direct Azure endpoint |
| 3 | **OpenAI Agents SDK** | `OPENAI_API_KEY` | Local development / fallback |
| 4 | **Offline mock** | `MAF_OFFLINE_MODE=true` | CI / deterministic testing |

---

## Getting Started

### 1. Install dependencies

```bash
cd agent-framework
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp src/env.example src/.env
```

Edit `src/.env`. Choose **one** option:

```ini
# Option A — Azure AI Foundry (production)
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://your-project.api.azureml.ms
FOUNDRY_MODEL=gpt-5

# Option B — Azure OpenAI direct
# AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# AZURE_OPENAI_DEPLOYMENT=gpt-5

# Option C — OpenAI API key (local / fallback)
# OPENAI_API_KEY=sk-...
```

> The `src/.env` included in this repo already contains `OPENAI_API_KEY` for local testing.

### 3. Run all scenarios (live)

```bash
python src/main.py
```

### 4. Run offline (no API calls — deterministic mock)

```bash
python src/main.py --offline
```

### 5. Run a single scenario (via WorkflowFactory runner)

```bash
python src/main.py --scenario A   # Hb 13.5 — ambiguity, unit mismatch, resolution
python src/main.py --scenario B   # CSF emergency panel — tube ordering (Gap 11)
python src/main.py --scenario C   # Calcium 4.8 — look-alike collision (Gap 8)
python src/main.py --scenario D   # Cardiac Troponin — config-driven extension
```

### 6. Launch the interactive Agent Harness console

```bash
# Interactive REPL — accepts clinical queries and slash commands
python src/main.py --harness

# At the clinician> prompt:
#   Hb 13.5              → submit a clinical query
#   /todos               → show 4-step diagnostic workflow checklist
#   /mode plan           → switch to PLAN mode (gap analysis only)
#   /mode execute        → switch to EXECUTE mode (full pipeline)
#   /scenario A          → run Scenario A through the harness
#   /status              → session ID, active mode, registered tools
#   /clear               → reset session memory
#   /exit                → quit
```

### 7. Run scenarios through the Harness (non-interactive)

```bash
python src/main.py --harness-scenario A   # Hb — ambiguity, unit mismatch, resolution
python src/main.py --harness-scenario B   # CSF emergency panel (Gap 11)
python src/main.py --harness-scenario C   # Calcium look-alike collision (Gap 8)
python src/main.py --harness-scenario D   # Cardiac Troponin extension
python src/main.py --harness-scenario all # All four scenarios via harness
```

### 8. Run the test suite

```bash
# All 44 deterministic safety invariants — no LLM calls, ~1.2 s
python -m pytest tests/ -v --rootdir=. -p no:logfire
```

---

## Directory Structure

```text
agent-framework/
├── conftest.py                          # sys.path wiring — shared ADK core
├── pytest.ini                           # testpaths = tests, pythonpath = . ..
├── requirements.txt                     # MAF + openai + azure-identity + pydantic
├── load_env.sh                          # Source credentials from src/.env
│
├── declarative-agents/                  # ← 6 × kind:Prompt YAML agent definitions
│   ├── triage_orchestrator.yaml         # Primary entrypoint — all 5 tools bound
│   ├── ontology_resolver.yaml           # LOINC concept resolution
│   ├── safety_guard.yaml                # Deterministic gate — fail-closed (Gap 9)
│   ├── protocol_retriever.yaml          # Reference range + panic limits
│   ├── clinical_synthesizer.yaml        # Grounded LLM synthesis (only after PROCEED)
│   └── clarification_coordinator.yaml   # HITL pause — returns gap to clinician
│
├── declarative-workflows/
│   └── clinical_decision_workflow.yaml  # InvokeAgent + If/Then/Else routing
│
└── src/
    ├── .env                             # Active credentials (gitignored)
    ├── env.example                      # Template — commit this, not .env
    ├── a2a/contracts.py                 # A2AMessage, AgentRole, A2AAction (parity with ADK/Strands)
    ├── core/                            # Shim → google-adk-agents/src/core/ (shared)
    │   ├── __init__.py                  # sys.modules pre-registration (namespace shim)
    │   └── models.py                    # importlib.util loader for ADK models
    ├── harness/                         # ← MAF Agent Harness (src/harness/)
    │   ├── __init__.py                  # Public exports
    │   ├── agent.py                     # ClinicalHarnessAgent + create_clinical_harness_agent()
    │   ├── session.py                   # HarnessSession — per-turn history & state
    │   ├── providers.py                 # ClinicalTodoProvider, ClinicalModeProvider,
    │   │                                #   SafetyGateApprovalPolicy
    │   └── console.py                   # Interactive terminal UX — /todos /mode /scenario
    ├── tools/                           # Plain Python functions — no decorator needed
    │   ├── parse_tool.py                # parse_clinician_input() — multi-pipe aware
    │   ├── ontology_tool.py             # resolve_ontology()
    │   ├── safety_gate_tool.py          # run_safety_gate()  ← NEVER call LLM
    │   ├── protocol_tool.py             # fetch_protocol()
    │   ├── clarification_tool.py        # build_clarification_prompt()
    │   └── csf_tool.py                  # csf_workup() — tube-scoped emergency panel
    ├── models/provider.py               # Credential auto-detection + AgentFactory builder
    ├── orchestration/workflow_runner.py # MAF live path + offline fast-path
    ├── runner.py                        # Scenarios A–D (matches ADK/Strands pattern)
    └── main.py                          # CLI entry point (--harness, --harness-scenario)

tests/
├── test_gate.py                         # 23 invariants: gate routing, parse, YAML, A2A
├── test_offline_pipeline.py             # 10 invariants: full pipeline, schema, fail-closed
└── test_harness.py                      # 11 invariants: harness init, session, todos,
                                         #   modes, approval policy, async pipeline runs
```

---

## Clinical Scenarios

| Scenario | Query | Gap(s) | Expected Route |
|:---|:---|:---|:---|
| **A — Hb ambiguous** | `Hb 13.5` | Gap 8 | CLARIFY |
| **A — Hb unit mismatch** | `Hb 13.5 \| mg/dL` | Gap 2 | CLARIFY |
| **A — Hb resolved** | `Hb 13.5 \| g/dL` | — | PROCEED |
| **B — CSF panel** | Emergency CSF workup | Gap 11 | Tube order enforced |
| **C — Calcium collision** | `Calcium 4.8 \| mg/dL` | Gap 8 | CLARIFY (collision) |
| **D — Troponin** | `Troponin 15 \| ng/L` | Gap 8 / 2 | CLARIFY / PROCEED |

---

## Shared Configuration

All three frameworks consume the **same** declarative YAML knowledge base from [`../config/`](../config/):

```
config/
├── domains/laboratory_medicine/    # Concepts, protocols, ranges, specimen rules
└── scenarios/                      # Scenario A–D gap detection playbooks
```

No Python code changes are required to add a new clinical gap scenario — add a YAML file to
`config/scenarios/` and call `load_scenario_extension()`.

---

## Cross-Framework Safety Invariants

These invariants hold identically in all three framework implementations:

```python
# All of these must return route == "CLARIFY" regardless of framework
parse("Hb 13.5")          → AMBIGUOUS  → CLARIFY   # Gap 8
parse("Hb 13.5 | mg/dL")  → UNIT_MISMATCH → CLARIFY # Gap 2
parse("Calcium 4.8 | mg/dL") → AMBIGUOUS → CLARIFY  # Gap 8 (two LOINC concepts)
parse("")                  → NOT_FOUND  → CLARIFY   # Gap 9 — fail closed

# Only this resolves
parse("Hb 13.5 | g/dL")   → RESOLVED   → PROCEED
```

---

## Key Design Decisions

**Why declarative YAML agents?**
`kind: Prompt` YAML separates the agent's identity (model, instructions, tools) from the
orchestration logic. Any of the 6 agents can be swapped, upgraded, or tuned without touching Python.

**Why are tools plain Python functions?**
MAF binds functions via the `bindings:` key in the agent YAML — no decorator needed.
This makes every tool reusable across multiple agents without framework coupling, and makes
the tools testable as pure Python without any MAF dependency.

**Why is the safety gate never in `instructions:`?**
The `safety_guard.yaml` instructions only say *"call run_safety_gate"*. The gate logic itself
is deterministic Python (`SafetyGateEngine`) — it cannot be overridden by prompt injection or
LLM reasoning drift. This is the Gap 9 fix.

**Why a `src/core/` shim instead of a copy?**
Both `agent-framework/src/` and `google-adk-agents/src/` use the `src.*` Python namespace.
A direct file copy would cause a namespace collision. The `importlib.util` shim pre-registers
all ADK core modules in `sys.modules` under their canonical names, resolving the conflict cleanly
without duplicating any clinical logic.

---

## References

| Resource | URL |
|:---|:---|
| Microsoft Agent Framework | https://github.com/microsoft/agent-framework |
| MAF declarative agent samples | `python/samples/02-agents/declarative/` |
| MAF declarative workflow samples | `python/samples/03-workflows/declarative/` |
| `kind: Prompt` YAML schema | `declarative-agents/agent-samples/chatclient/GetWeather.yaml` |
| Conditional workflow schema | `python/samples/03-workflows/declarative/conditional_workflow/` |

---

> **Status**: ✅ Implementation complete — 44/44 tests passing.
> Includes: WorkflowFactory declarative pipeline + MAF Agent Harness (session, todos, modes, approval policy, terminal UX).
> Model: `gpt-5` via `OPENAI_API_KEY` (local) or Azure AI Foundry (production).
