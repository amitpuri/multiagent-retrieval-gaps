# Laboratory Medicine Decision Support with Google ADK 2.0, A2A & Clinical Ontologies

*When the Retriever Has to Decide: Reusable Multi-Agent Architecture, Configurable Gaps, and Deterministic Gating*

By Dr. Amit Puri · October 2026

> **In continuation to:** *[Information Retrieval Part I](https://www.linkedin.com/pulse/information-retrieval-dr-amit-puri-ahcec/)*, *[Part II: When Similarity Isn't Enough!](https://www.linkedin.com/pulse/information-retrieval-when-similarity-isnt-enough-dr-amit-puri-2rnzc/)*, and *[Recap & Closing](https://www.linkedin.com/pulse/recap-where-retrieval-gaps-diagnose-fix-dr-amit-puri-fhlwf)*.
---

## Executive Summary & TL;DR

- **An agent is a retriever that has to decide.** Every one of the 7 classical/RAG retrieval gaps still applies. Agents introduce four new failure modes: guessing instead of asking (Gap 8), safety rules relegated to probabilistic prompts (Gap 9), un-evaluated execution trajectories (Gap 10), and tool output treated as unscoped, trusted context (Gap 11).
- **An ontology's job in an agent is to define what a term means, and when to stop.** In laboratory medicine, terms like `"Hb"`, `"Calcium"`, `"CSF panel"`, and `"Troponin"` each conceal multiple distinct assays with different clinical units, reference ranges, or owning laboratory departments.
- **Generic & Abstract Architecture**: Hardcoded logic has been replaced with typed Pydantic models ([`src/core/models.py`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/models.py)) and five modular, reusable [`GapDetector`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/detectors/base.py) plugins: `AmbiguityDetector`, `UnitMismatchDetector`, `MissingQualifierDetector`, `RangeCollisionDetector`, and `SpecimenSequenceDetector`.
- **Declarative Configuration (Zero-Code Extensibility)**: All vocabularies, reference ranges, specimen sequencing rules, and gap scenarios are externalized into YAML files under [`config/`](file:///c:/repositories/repos/multiagent-retrieval-gaps/config/). Adding a new clinical gap or look-alike assay (e.g. Scenario D: Cardiac Troponin I vs T) requires **zero changes to Python code**.
- **Multi-Agent Coordination via Google ADK 2.0 & A2A**: The solution divides labor across six specialized agent roles communicating over structured Agent-to-Agent ([`A2AMessage`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/a2a/contracts.py)) contracts:
  - **Triage Orchestrator**: Ingests unstructured orders and coordinates the agent fleet.
  - **Ontology Resolver Agent**: Normalizes terms and resolves canonical LOINC concepts.
  - **Safety Guard Agent**: Code-deterministic gate running all five gap detectors and look-alike range collisions.
  - **Protocol Retriever Agent**: Fetches clinical reference data strictly by canonical URI.
  - **Clinical Synthesizer Agent**: Single-turn grounded LLM (Gemini 3.5 Flash) delivering calibrated interpretations.
  - **Clarification Coordinator**: Manages human-in-the-loop pauses (`RequestInput`) when the safety gate fails closed.
- **Zero-Cost Trajectory Evaluation in CI**: 28 safety invariants run in **~2.3 seconds** via `pytest` without making a single LLM or network call.

> [!TIP]
> The objective is not to find a universally "perfect" agent architecture, but to pinpoint **what failed**, **why it failed**, and **the smallest intervention that fixes it**.

---

## Architecture & Gaps Addressed

| Gap | Level | Addressed In | Implementation & Clinical Significance |
| :--- | :--- | :--- | :--- |
| **Gap 2: Unit Mismatch** | Agent Loop | [`src/core/detectors/unit_mismatch.py`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/detectors/unit_mismatch.py) | Standalone detector that explicitly rejects units not valid for any matched concept (e.g. `mg/dL` for Hemoglobin) rather than silently guessing the nearest assay. |
| **Gap 5: Missing Qualifier** | Agent Loop | [`src/core/detectors/missing_qualifier.py`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/detectors/missing_qualifier.py) | Flags numeric results in look-alike assay families (e.g. Calcium, Troponin) when no qualifier (`total`/`ionized`) is supplied, preventing collision-masked silent errors. |
| **Gap 8: Ambiguity & Silent Guessing** | Agent Loop | [`src/core/detectors/ambiguity.py`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/detectors/ambiguity.py) | Maps lab terms to LOINC concepts and returns explicit `AMBIGUOUS`, `UNIT_MISMATCH`, or `NOT_FOUND` statuses instead of silent guesses. |
| **Gap 9: Safety Rule in Prompt** | Agent Loop | [`src/orchestration/a2a_orchestrator.py`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/orchestration/a2a_orchestrator.py) | ADK 2.0 `Workflow` graph with a deterministic routing `safety_guard_node` and human-in-the-loop pause (`RequestInput`). Fails closed on uncertainty. |
| **Gap 10: Trajectory Never Evaluated** | Agent Loop | [`tests/`](file:///c:/repositories/repos/multiagent-retrieval-gaps/tests/) | Pure-code test suite verifying ontology resolution, collision detection, and gate fail-closed behavior in milliseconds without LLM calls. |
| **Gap 11: Tool Output Trusted, Unscoped** | Agent Loop | [`src/core/detectors/specimen_sequence.py`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/detectors/specimen_sequence.py) | Enforces CSF panel tube sequencing (Tube 1→2→3) and department scope boundaries to prevent specimen contamination. |
| **Range Collisions (Look-Alikes)** | Clinical Safety | [`src/core/detectors/range_collision.py`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/detectors/range_collision.py) | Evaluates numeric values against look-alike assay families (e.g. Total vs Ionized Calcium, Troponin I vs T) to prevent lethal classification errors. |
| **Dynamic Gap Extensibility** | Framework | [`config/scenarios/`](file:///c:/repositories/repos/multiagent-retrieval-gaps/config/scenarios/) | Enables declaration of new retrieval gaps and scenarios purely in YAML without modifying application source code. |

---

## Multi-Agent Architecture with Google ADK & A2A

```mermaid
flowchart TD
    Clinician([Clinician / Client Application]) -->|A2A Task Request| Triage[Triage Orchestrator Agent]

    subgraph MultiAgent_Fleet["Google ADK Multi-Agent Fleet (A2A Protocol)"]
        direction TB

        Triage -->|A2A: PARSE_REQUEST| OntologyAgent[Ontology Resolver Agent]
        OntologyAgent -->|Resolution State| SafetyGuard[Safety Guard Agent<br/><i>Deterministic Code Gate</i>]

        subgraph Gap_Detectors["SafetyGateEngine — 5 Pluggable Detectors"]
            AmbiguityDet["AmbiguityDetector (Gap 8)"]
            UnitMismatchDet["UnitMismatchDetector (Gap 2)"]
            MissingQualDet["MissingQualifierDetector (Gap 5)"]
            RangeCollisionDet["RangeCollisionDetector (Look-Alikes)"]
            SpecimenSeqDet["SpecimenSequenceDetector (Gap 11)"]
        end

        SafetyGuard -.-> Gap_Detectors

        SafetyGuard -- "status == RESOLVED (PROCEED)" --> ProtocolAgent[Protocol Retriever Agent<br/><i>Canonical URI Grounding</i>]
        ProtocolAgent -->|A2A: Grounded Protocol| SynthesisAgent[Clinical Synthesizer Agent<br/><i>Single-Turn Gemini 3.5 Flash</i>]

        SafetyGuard -- "Uncertain / Collision (CLARIFY)" --> ClarifyAgent[Clarification Coordinator Agent<br/><i>Human-in-the-Loop HITL</i>]
    end

    SynthesisAgent --> Deliver([Deliver Grounded Clinical Interpretation])
    ClarifyAgent --> RequestInput([adk_request_input: Prompt Clinician with Diagnosed Gap])
    RequestInput -.->|Clinician Clarification| Triage
```

### A2A Message Contracts ([`src/a2a/contracts.py`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/a2a/contracts.py))

Specialized subagents exchange structured [`A2AMessage`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/a2a/contracts.py) envelopes:

```python
class A2AMessage(BaseModel):
    message_id: str
    trace_id: str
    sender: AgentRole           # triage_orchestrator, ontology_resolver_agent, safety_guard_agent, ...
    recipient: AgentRole
    action: A2AAction           # PARSE_REQUEST, RESOLVE_CONCEPT, VALIDATE_SAFETY, FETCH_PROTOCOL, ...
    timestamp: float
    payload: Dict[str, Any]
    status: Optional[ResolutionStatus] = None
```

Live A2A trace (Scenario D — Troponin, Turn 2: resolved):
```text
  [A2A] triage_orchestrator --> ontology_resolver_agent: PARSE_REQUEST
  [A2A] ontology_resolver_agent --> safety_guard_agent: RESOLVE_CONCEPT (Status: RESOLVED)
  [A2A] safety_guard_agent --> protocol_retriever_agent: FETCH_PROTOCOL (Status: RESOLVED)
  [A2A] protocol_retriever_agent --> clinical_synthesizer_agent: SYNTHESIZE_INTERPRETATION
```

---

## Repository File Layout

```text
multiagent-retrieval-gaps/
├── config/
│   ├── domains/
│   │   └── laboratory_medicine/
│   │       ├── concepts.yaml        # Controlled vocabulary, LOINC mappings, synonyms, units
│   │       ├── protocols.yaml       # Clinical reference protocols & panic limits keyed by URI
│   │       ├── ranges.yaml          # Reference/critical limits & look-alike collision families
│   │       └── specimen_rules.yaml  # Specimen handling, aliquot rules & CSF tube sequencing
│   └── scenarios/
│       ├── scenario_a_hemoglobin.yaml       # Hb ambiguity & unit mismatch (Gap 2 & 8)
│       ├── scenario_b_csf_panel.yaml        # CSF emergency panel tube ordering (Gap 11)
│       ├── scenario_c_calcium_collision.yaml # Calcium look-alike range collision
│       └── scenario_d_troponin.yaml          # Dynamic extension: Troponin I vs T (zero-code)
├── src/
│   ├── a2a/
│   │   ├── __init__.py
│   │   └── contracts.py             # A2A Message envelopes, AgentRole, A2AAction, A2ATaskState
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py                # Typed Pydantic schemas (ConceptDefinition, NumericAssay, etc.)
│   │   ├── config.py                # YAML loader & cached in-memory OntologyRegistry
│   │   └── detectors/               # Pluggable retrieval gap detectors
│   │       ├── __init__.py          # Package exports for all 5 detectors + SafetyGateEngine
│   │       ├── base.py              # Abstract GapDetector base class
│   │       ├── ambiguity.py         # Gap 8: Ambiguity & silent guessing (multi-concept collision)
│   │       ├── unit_mismatch.py     # Gap 2: Standalone unit constraint violation detector
│   │       ├── missing_qualifier.py # Gap 5: Flags unqualified numeric orders in assay families
│   │       ├── range_collision.py   # Look-alike range collisions (Total vs Ionized Calcium, etc.)
│   │       ├── specimen_sequence.py # Gap 11: Scope boundaries & governed tube sequencing
│   │       └── engine.py            # SafetyGateEngine: Executes detectors & enforces fail-closed policy
│   ├── agents/                      # Specialized ADK Agent Roles
│   │   ├── __init__.py              # Unified exports & backwards-compatible agent instances
│   │   ├── triage_agent.py          # Triage Orchestrator Agent (fleet coordinator & A2A entrypoint)
│   │   ├── ontology_agent.py        # Ontology Resolver Agent
│   │   ├── safety_guard_agent.py    # Safety Guard Agent (deterministic gate node)
│   │   ├── protocol_agent.py        # Protocol Retriever Agent
│   │   ├── synthesis_agent.py       # Clinical Synthesizer Agent (single-turn Gemini)
│   │   └── clarification_agent.py   # Clarification Coordinator Agent (RequestInput pause)
│   ├── orchestration/
│   │   └── a2a_orchestrator.py      # ADK Workflow graph coordinating the agent fleet via A2A
│   ├── ontology.py                  # Dynamic facade loading from YAML config into legacy format
│   ├── tools.py                     # Legacy procedural tools delegating to generic engine
│   ├── workflow.py                  # ADK Workflow builder (delegates to multi-agent orchestrator)
│   ├── runner.py                    # Multi-scenario runner (Scenarios A, B, C, and Multi-Agent D)
│   ├── main.py                      # Main CLI entrypoint
│   └── env.example                  # Template for GEMINI_API_KEY
├── tests/
│   ├── test_gate.py                 # 12 original safety invariant tests (100% passing)
│   └── test_multiagent_extensible.py# 16 new tests: detectors, A2A contracts, YAML extensions, triage
└── requirements.txt
```

---

## The Demonstration Scenarios

All four scenarios are now declared as **declarative YAML configuration files** under `config/scenarios/`, making the system fully self-documenting and extensible.

### Scenario A (Q5): "Hb 13.5" — Same Label, Different Departments ([`scenario_a_hemoglobin.yaml`](file:///c:/repositories/repos/multiagent-retrieval-gaps/config/scenarios/scenario_a_hemoglobin.yaml))
- **Problem:** Clinician asks to interpret *"Hb 13.5"*. Lacking a unit, it could be CBC Hemoglobin (`13.5 g/dL` in Hematology = borderline normal) or Glycated Hemoglobin (`13.5%` in Biochemistry = severe diabetic emergency).
- **Resolution:** Caught by [`AmbiguityDetector`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/detectors/ambiguity.py), gate yields `RequestInput` asking for the unit. Supplying `g/dL` proceeds safely to LOINC `718-7`; supplying `mg/dL` triggers `UNIT_MISMATCH` (caught by [`UnitMismatchDetector`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/detectors/unit_mismatch.py)).

### Scenario B (Q6): CSF Emergency Panel — One Specimen, Many Owners (Gap 11) ([`scenario_b_csf_panel.yaml`](file:///c:/repositories/repos/multiagent-retrieval-gaps/config/scenarios/scenario_b_csf_panel.yaml))
- **Problem:** A single Lumbar Puncture specimen must be partitioned across 3 departments without cross-contamination.
- **Resolution:** [`SpecimenSequenceDetector`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/detectors/specimen_sequence.py) pre-scopes tests by tube sequence: Tube 1 (Biochem: Protein, Glucose), Tube 2 (Micro: Gram stain, Culture), Tube 3 (Hematology: Cell count). Prevents cell count contamination from traumatic puncture blood.

### Scenario C (Q7): Calcium 4.8 mg/dL — Look-Alike Tests & Range Collisions ([`scenario_c_calcium_collision.yaml`](file:///c:/repositories/repos/multiagent-retrieval-gaps/config/scenarios/scenario_c_calcium_collision.yaml))
- **Problem:** Clinician asks *"Calcium 4.8 mg/dL. Do we act?"* Total Calcium (`8.5-10.5 mg/dL`) at 4.8 is a **critical low** prompting emergency IV calcium; Ionized Calcium (`4.5-5.6 mg/dL`) at 4.8 is **normal**.
- **Resolution:** [`RangeCollisionDetector`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/detectors/range_collision.py) evaluates candidate assays against numeric thresholds. Conflicting classifications (`CRITICAL_LOW` vs `NORMAL`) flag a `RANGE_COLLISION`, forcing a human clarification before medication administration. [`MissingQualifierDetector`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/detectors/missing_qualifier.py) also fires for unqualified numeric results in the calcium family.

### Scenario D: Cardiac Troponin I vs T — Zero-Code Plug-and-Play Extension ([`scenario_d_troponin.yaml`](file:///c:/repositories/repos/multiagent-retrieval-gaps/config/scenarios/scenario_d_troponin.yaml))
- **Problem:** Clinician orders *"Troponin 15"*. Cardiac Troponin I is measured in `ng/mL` (critical > `0.40 ng/mL`); high-sensitivity Troponin T is measured in `ng/L` (critical > `52 ng/L`). Interpreting `15 ng/L` as `ng/mL` triggers a false-alarm cardiac catheterization; interpreting `15 ng/mL` as `ng/L` misses an acute myocardial infarction.
- **Resolution:** Declared entirely in [`config/scenarios/scenario_d_troponin.yaml`](file:///c:/repositories/repos/multiagent-retrieval-gaps/config/scenarios/scenario_d_troponin.yaml) without writing any Python code:
  - Dynamically registered into the [`OntologyRegistry`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/config.py) at runtime.
  - Flags `AMBIGUOUS` on `Troponin 15` and routes to `CLARIFY`.
  - Safely resolves to `PROCEED` when unit `ng/L` is provided (LOINC `6598-7`).
  - Rejects invalid unit `mg/dL` as `UNIT_MISMATCH`.
  - Coordinated entirely through the **multi-agent A2A fleet** (Scenario D is the only scenario using the full A2A orchestrator; Scenarios A/B/C use the single-workflow ADK graph for backward compatibility).

---

## Evaluating Agent Trajectories in Pure Code (Closing Gap 10)

Because resolution logic, gap detectors, collision engines, and routing gates are implemented in pure, deterministic code, safety invariants are verified in CI using `pytest` without LLM calls or network latency.

```bash
python -m pytest tests/ -v
```

Output:
```text

============================================================== test session starts ==============================================================
platform win32 -- Python 3.14.5, pytest-9.1.1, pluggy-1.6.0 -- C:\repositories\venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: C:\repositories\repos\multiagent-retrieval-gaps
configfile: pytest.ini
plugins: anyio-4.15.1, jaxtyping-0.3.11, typeguard-4.6.0, zarr-3.3.0
collected 28 items

tests/test_gate.py::test_hb_without_unit_is_ambiguous PASSED                                                                               [  3%]
tests/test_gate.py::test_hb_with_correct_unit_resolves PASSED                                                                              [  7%]
tests/test_gate.py::test_hb_with_invalid_unit_triggers_mismatch PASSED                                                                     [ 10%]
tests/test_gate.py::test_unknown_term_returns_not_found PASSED                                                                             [ 14%]
tests/test_gate.py::test_calcium_collision PASSED                                                                                          [ 17%]
tests/test_gate.py::test_calcium_with_qualifiers_resolves PASSED                                                                           [ 21%]
tests/test_gate.py::test_gate_fails_closed PASSED                                                                                          [ 25%]
tests/test_gate.py::test_csf_workup_grouping_and_tube_order PASSED                                                                         [ 28%]
tests/test_gate.py::test_csf_workup_scoped_by_department PASSED                                                                            [ 32%]
tests/test_gate.py::test_csf_workup_unknown_department PASSED                                                                              [ 35%]
tests/test_gate.py::test_fetch_grounded_protocol PASSED                                                                                    [ 39%]
tests/test_gate.py::test_parse_input_variations PASSED                                                                                     [ 42%]
tests/test_multiagent_extensible.py::test_registry_loads_baseline_domain PASSED                                                            [ 46%]
tests/test_multiagent_extensible.py::test_dynamic_scenario_extension_loading PASSED                                                        [ 50%]
tests/test_multiagent_extensible.py::test_generic_ambiguity_detector PASSED                                                                [ 53%]
tests/test_multiagent_extensible.py::test_generic_range_collision_detector PASSED                                                          [ 57%]
tests/test_multiagent_extensible.py::test_generic_specimen_sequence_detector PASSED                                                        [ 60%]
tests/test_multiagent_extensible.py::test_safety_gate_engine_fails_closed PASSED                                                           [ 64%]
tests/test_multiagent_extensible.py::test_a2a_message_contract_serialization PASSED                                                        [ 67%]
tests/test_multiagent_extensible.py::test_parse_clinician_input_qualifiers PASSED                                                          [ 71%]
tests/test_multiagent_extensible.py::test_unit_mismatch_detector_invalid_unit PASSED                                                       [ 75%]
tests/test_multiagent_extensible.py::test_unit_mismatch_detector_valid_unit_passes PASSED                                                  [ 78%]
tests/test_multiagent_extensible.py::test_unit_mismatch_detector_no_unit_skips PASSED                                                      [ 82%]
tests/test_multiagent_extensible.py::test_missing_qualifier_detector_flags_unqualified_numeric PASSED                                      [ 85%]
tests/test_multiagent_extensible.py::test_missing_qualifier_detector_passes_with_qualifier PASSED                                          [ 89%]
tests/test_multiagent_extensible.py::test_missing_qualifier_detector_passes_without_numeric PASSED                                         [ 92%]
tests/test_multiagent_extensible.py::test_all_scenario_yaml_files_exist PASSED                                                             [ 96%]
tests/test_multiagent_extensible.py::test_triage_agent_make_envelope PASSED                                                                [100%]

============================================================== 28 passed in 2.82s ===============================================================

```

---

## Getting Started & Execution

### Prerequisites & Installation

```bash
# Install dependencies
pip install -r requirements.txt
```

### Running the End-to-End Scenarios

Configure your Gemini API key in `src/.env` for live LLM synthesis (automatically falls back to offline stub mode if omitted or run with `--offline`):

```bash
# Live mode (requires GEMINI_API_KEY in src/.env)
python src/main.py

# Offline / deterministic stub mode (no API key needed)
python src/main.py --offline
```

### Sample Output Trace

```text

================================================================================
   Information Retrieval, Part III: When the Retriever Has to Decide
   Generic & Reusable Multi-Agent Architecture with Google ADK 2.0 & A2A
================================================================================

================================================================================
SCENARIO A: Q5 ('Hb 13.5') - ADK DETERMINISTIC WORKFLOW GRAPH
================================================================================
[*] Synthesis Mode: Live Gemini (gemini-3.5-flash)

--- Turn 1: Ambiguous test name without unit ---
Clinician message: 'Hb 13.5'
  [lab_demo@1/resolve_node@1] status=AMBIGUOUS
  [lab_demo@1/gate@1] route=CLARIFY
  [lab_demo@1/gate@1] status=AMBIGUOUS

  [PAUSED: adk_request_input]
  --> Gate Route: CLARIFY
  --> Prompt to Clinician: "Status AMBIGUOUS. Candidates: Hemoglobin [Mass/volume] in Blood, Hemoglobin A1c/Hemoglobin.total in Blood. Which test and unit?"


--- Turn 2: Follow-up providing unit 'g/dL' ---
Clinician message: 'Hb 13.5 | g/dL'
  [lab_demo@1/resolve_node@1] status=RESOLVED
  [lab_demo@1/gate@1] route=PROCEED
  [lab_demo@1/gate@1] status=RESOLVED
  [lab_demo@1/fetch_node@1] Protocol fetched for loinc:718-7
  [lab_demo@1/fetch_node@1] Reference range: Adult male 13.8-17.2 g/dL; adult female 12.1-15.1 g/dL
Direct use of automatic function calling (AFC) in AsyncModels.generate_content is not recommended. Instead, we recommend to use AFC in AsyncChat.send_message. Similarly, direct use of AFC in AsyncModels.generate_content_stream is not recommended. Instead, we recommend to use AFC in AsyncChat.send_message_stream.

  [lab_demo@1/clinical_synthesizer@1] Live Gemini Clinical Synthesis:

    **Resolved LOINC Concept:**
    *   **LOINC Code:** 718-7
    *   **Concept Label:** Hemoglobin [Mass/volume] in Blood (Hematology Department)

    ---

    **Protocol Parameters:**
    *   **Reference Range:**
        *   Adult male: 13.8 – 17.2 g/dL
        *   Adult female: 12.1 – 15.1 g/dL
    *   **Panic Limits:**
        *   Low: < 7.0 g/dL
        *   High: > 20.0 g/dL

    ---

    **Patient Value & Laboratory Interpretation:**
    *   **Patient Value:** 13.5 g/dL

    Because demographic information (biological sex) is not specified for this patient, the interpretation must be evaluated against both adult reference ranges:

    1.  **If the patient is an adult female:** The value of 13.5 g/dL is **within** the established reference range of 12.1 – 15.1 g/dL, indicating a normal hemoglobin level.
    2.  **If the patient is an adult male:** The value of 13.5 g/dL is **slightly below** the established reference range of 13.8 – 17.2 g/dL.

    **Panic Limit Evaluation:**
    Under both demographic protocols, the patient's value of 13.5 g/dL does not meet the criteria for a critical/panic value (it is well above the low panic limit of < 7.0 g/dL and well below the high panic limit of > 20.0 g/dL).

    *Clinical correlation with the patient's specific demographic profile is required to determine the final clinical status.*

--- Turn 3: Invalid unit 'mg/dL' submitted ---
Clinician message: 'Hb 13.5 | mg/dL'
  [lab_demo@1/resolve_node@1] status=UNIT_MISMATCH
  [lab_demo@1/gate@1] route=CLARIFY
  [lab_demo@1/gate@1] status=UNIT_MISMATCH

  [PAUSED: adk_request_input]
  --> Gate Route: CLARIFY
  --> Prompt to Clinician: "Status UNIT_MISMATCH. Candidates: Hemoglobin [Mass/volume] in Blood, Hemoglobin A1c/Hemoglobin.total in Blood. Which test and unit?"


================================================================================
SCENARIO B: Q6 (CSF Emergency Panel - Governed Tube Ordering, Closing Gap 11)
================================================================================

Full Emergency CSF Workup (Pre-scoped by department & tube order):

  Department: Clinical Biochemistry
    - Tube 1: Protein [Mass/volume] in CSF [loinc:2880-3]
    - Tube 1: Glucose [Mass/volume] in CSF [loinc:2342-4]

  Department: Microbiology
    - Tube 2: Microscopic observation [Identifier] in CSF by Gram stain [loinc:14357-8]
    - Tube 2: Bacteria identified in CSF by culture [loinc:606-4]

  Department: Hematology
    - Tube 3: Leukocytes [#/volume] in CSF [loinc:26465-5]
    - Tube 3: Neutrophils/Leukocytes in CSF [loinc:26512-4]

Department-Scoped Workup (Hematology only):
  Department: Hematology
    - Tube 3: Leukocytes [#/volume] in CSF [loinc:26465-5]
    - Tube 3: Neutrophils/Leukocytes in CSF [loinc:26512-4]

================================================================================
SCENARIO C: Q7 (Calcium 4.8 mg/dL - Look-Alike Tests & Deterministic Collision)
================================================================================

Unqualified result for Calcium 4.8 mg/dL:
  Status: RANGE_COLLISION
    - Total calcium: CRITICAL_LOW
    - Ionized calcium: NORMAL
  Outcome: Critical low vs Normal collision -> Routed to CLARIFY, prevents lethal IV calcium error.

Qualified 'Total Calcium' 4.8 mg/dL:
  Status: RESOLVED
  Readings: {'Total calcium': 'CRITICAL_LOW'}

Qualified 'Ionized Calcium' 4.8 mg/dL:
  Status: RESOLVED
  Readings: {'Ionized calcium': 'NORMAL'}

================================================================================
SCENARIO D: DYNAMIC CONFIG-DRIVEN EXTENSION (Cardiac Troponin via Multi-Agent A2A)
================================================================================
[*] Dynamically loaded scenario extension from: scenario_d_troponin.yaml
[*] Multi-Agent Orchestration Mode: Live Gemini (gemini-3.5-flash)

--- Turn 1: Ambiguous order 'Troponin 15' without unit (I vs T hazard) ---
Clinician message: 'Troponin 15'
  [A2A] triage_orchestrator --> ontology_resolver_agent: PARSE_REQUEST
  [A2A] ontology_resolver_agent --> safety_guard_agent: RESOLVE_CONCEPT (Status: AMBIGUOUS)
  [A2A Event] route=CLARIFY
  [A2A] ontology_resolver_agent --> safety_guard_agent: RESOLVE_CONCEPT (Status: AMBIGUOUS)
  [A2A] safety_guard_agent --> clarification_coordinator_agent: REQUEST_CLARIFICATION (Status: AMBIGUOUS)

  [A2A PAUSED: RequestInput to Clinician]
  --> Gate Route: CLARIFY
  --> Prompt: "Status AMBIGUOUS. Candidates: Troponin I.cardiac [Mass/volume] in Serum or Plasma, Troponin T.cardiac [Mass/volume] in Serum or Plasma. Which test and unit?"


--- Turn 2: Clinician clarifies unit 'ng/L' (resolves to hs-cTnT) ---
Clinician message: 'Troponin 15 | ng/L'
  [A2A] triage_orchestrator --> ontology_resolver_agent: PARSE_REQUEST
  [A2A] ontology_resolver_agent --> safety_guard_agent: RESOLVE_CONCEPT (Status: RESOLVED)
  [A2A Event] route=PROCEED
  [A2A] ontology_resolver_agent --> safety_guard_agent: RESOLVE_CONCEPT (Status: RESOLVED)
  [A2A] safety_guard_agent --> protocol_retriever_agent: FETCH_PROTOCOL (Status: RESOLVED)
  [A2A] protocol_retriever_agent --> clinical_synthesizer_agent: SYNTHESIZE_INTERPRETATION
  [multiagent_troponin_demo@1/protocol_retriever_node@1] Grounded Protocol fetched for loinc:6598-7
  [multiagent_troponin_demo@1/protocol_retriever_node@1] Reference range: < 14 ng/L

  [multiagent_troponin_demo@1/clinical_synthesizer@1] Multi-Agent Clinical Synthesis:

    Based on the protocol data provided, here is the clinical interpretation:

    *   **Resolved LOINC Concept:** Troponin T.cardiac [Mass/volume] in Serum or Plasma (LOINC: 6598-7)
    *   **Reference Range:** < 14 ng/L
    *   **Panic Limits:** High > 52 ng/L
    *   **Patient Value:** 15.0 ng/L

    ### Clinical Interpretation:
    The patient's Troponin T level of 15.0 ng/L is minimally elevated above the standard reference range limit of < 14 ng/L. This value remains below the defined critical panic limit of > 52 ng/L.

    According to the provided clinical guideline, an elevation in high-sensitivity Troponin T suggests acute coronary syndrome or myocardial strain. Because this result exceeds the normal reference threshold, it should be interpreted cautiously and correlated with the patient's clinical presentation, serial troponin measurements, and electrocardiogram findings.

--- Turn 3: Clinician submits incompatible unit 'mg/dL' ---
Clinician message: 'Troponin 15 | mg/dL'
  [A2A] triage_orchestrator --> ontology_resolver_agent: PARSE_REQUEST
  [A2A] ontology_resolver_agent --> safety_guard_agent: RESOLVE_CONCEPT (Status: UNIT_MISMATCH)
  [A2A Event] route=CLARIFY
  [A2A] ontology_resolver_agent --> safety_guard_agent: RESOLVE_CONCEPT (Status: UNIT_MISMATCH)
  [A2A] safety_guard_agent --> clarification_coordinator_agent: REQUEST_CLARIFICATION (Status: UNIT_MISMATCH)

  [A2A PAUSED: RequestInput to Clinician]
  --> Gate Route: CLARIFY
  --> Prompt: "Status UNIT_MISMATCH. Candidates: Troponin I.cardiac [Mass/volume] in Serum or Plasma, Troponin T.cardiac [Mass/volume] in Serum or Plasma. Which test and unit?"
```

---

## Ontological Principles for Multi-Agent Systems

Giving an LLM agent more tools without a semantic layer simply multiplies its opportunities to make confident errors. An ontology does not make an agent "smarter"—it establishes boundaries:

1. **Identity:** A governed definition of what terms mean across domains (LOINC, UCUM, SNOMED).
2. **Epistemic Discipline:** A formal representation of ambiguity that turns confusion into a first-class output.
3. **Deterministic Safety:** Clinical guardrails extracted from probabilistic prompts and enforced in deterministic code.
4. **Agent-to-Agent Division of Labor:** Specialized agent roles communicating via typed contracts, ensuring models reason while deterministic code gates actions.

When the retriever has to decide, the safest action it can take is knowing when to stop and ask.

---

## Production-Grade Architecture

This section extends the reference implementation toward a production-ready clinical decision support system, drawing on two architectural frameworks: a **fourteen-part agent memory taxonomy** and a **healthcare GraphRAG & ontology-driven multi-agent architecture**.

### Memory Architecture for Production Agents

A single vector store is not a memory system. Production agents require distinct memory types, each solving a different class of failure:

| # | Memory Type | Core Question | Agent Implementation |
| :--- | :--- | :--- | :--- |
| 1 | **Working / Context** | What is active right now? | Context window, scratchpad in ADK session |
| 2 | **Semantic** | What do I know to be true? | `OntologyRegistry` (YAML-loaded concepts, LOINC, UCUM) |
| 3 | **Episodic** | What happened before? | A2A trace log, trajectory store per `trace_id` |
| 4 | **Procedural** | How do I do this? | `config/scenarios/*.yaml` — reusable gap detection playbooks |
| 5 | **External / Retrieval** | What can I look up? | `ProtocolRetrieverAgent` — canonical URI grounding |
| 6 | **Parametric** | What did training teach me? | Gemini model weights (synthesis only, gated by safety guard) |
| 7 | **Prospective** | What must I do later? | ADK `RequestInput` — deferred clarification triggers |
| 8 | **Spatial** | Where are things? | YAML config tree, department + tube-scope maps |
| 9 | **Temporal** | When, in what order, how recent? | Bi-temporal records, `valid_from`/`valid_to` on recommendations |
| 10 | **Associative / Relational** | How are entities connected? | Property graph: `Recommendation → Concept → Qualifier` |
| 11 | **Social** | Who are the people? | Role-based ACLs on `DocumentVersion` and assertion tiers |
| 12 | **Meta-memory** | What do I know, and how sure? | `ResolutionStatus` (AMBIGUOUS / RESOLVED / NOT\_FOUND), provenance on every gap finding |
| 13 | **Collective / Organizational** | What does the group know? | Shared `OntologyRegistry`, governed Knowledge Release IDs |
| 14 | **Sensory / Perceptual** | What did I just observe? | Short-lived order parse buffer in `TriageAgent` |

The five memory types most critical for dependable agentic systems — and most often neglected — are:

- **Temporal** — know *when*, and what is still current. Implemented via bi-temporal fields (`valid_from`/`valid_to`, `recorded_at`) on `Recommendation` nodes and TTLs on ephemeral order-parse facts.
- **Spatial** — know *where* across physical and digital environments. Implemented via specimen tube maps and department scope boundaries in [`specimen_rules.yaml`](file:///c:/repositories/repos/multiagent-retrieval-gaps/config/domains/laboratory_medicine/specimen_rules.yaml).
- **Associative / Relational** — know *how things connect*. Implemented via the property graph knowledge model (see §Knowledge Model below) and typed A2A contracts in [`src/a2a/contracts.py`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/a2a/contracts.py).
- **Meta-memory** — know *what it knows, how well, and from where*. Implemented via `ResolutionStatus`, detector provenance, and fail-closed gating in [`src/core/detectors/engine.py`](file:///c:/repositories/repos/multiagent-retrieval-gaps/src/core/detectors/engine.py).
- **Collective / Organizational** — know *what the group knows*, and share it safely. Implemented via governed `OntologyRegistry`, Knowledge Release IDs, and role-based ACLs.

```mermaid
flowchart TD
    P[Perception: sensory buffer<br/><i>TriageAgent order parse</i>] --> W[Working memory: context window<br/><i>ADK session state</i>]
    W <--> R[Retrieval layer<br/><i>ProtocolRetrieverAgent</i>]
    R <--> E[Episodic store<br/><i>A2A trace log / trajectory</i>]
    R <--> S[Semantic store<br/><i>OntologyRegistry + LOINC concepts</i>]
    R <--> PR[Procedural store: skills<br/><i>config/scenarios YAML playbooks</i>]
    R <--> G[Relational graph<br/><i>Recommendation → Concept → Qualifier</i>]
    R <--> X[External sources<br/><i>Canonical URI protocols</i>]
    R <--> C[Collective / org memory<br/><i>Knowledge Release ID</i>]
    M[Meta layer: time · provenance · confidence<br/><i>ResolutionStatus + detector findings</i>] -.annotates.-> E
    M -.annotates.-> S
    M -.annotates.-> G
    M -.annotates.-> C
    W --> PM[Prospective memory: tasks, triggers<br/><i>ADK RequestInput / CLARIFY route</i>]
    PM --> W
```

#### Common Memory Failure Modes — and How This Architecture Prevents Them

| Failure | Root Cause | Prevention in This System |
| :--- | :--- | :--- |
| Agent follows an outdated instruction | No temporal validity / supersession | Bi-temporal `valid_from`/`valid_to` on `Recommendation` nodes; TTL on ephemeral facts |
| Agent re-explores the same environment every run | No persistent layout model | `OntologyRegistry` cached in-memory; specimen tube maps in YAML |
| Agent misses downstream impact of a change | Flat retrieval, no entity links | Property graph with typed edges (`EVIDENCED_BY`, `FOR_CONDITION`, `SUPERSEDES`) |
| Agent states guesses as facts | No confidence / provenance tracking | `ResolutionStatus` + detector provenance; fail-closed `SafetyGateEngine` |
| Agents give inconsistent answers to the same question | No shared, governed knowledge base | Governed `OntologyRegistry` + Knowledge Release IDs shared across agent fleet |
| Agent leaks one user's information to another | Missing scope / access control | Role-based ACLs on `DocumentVersion`; department scope boundaries enforced by `SpecimenSequenceDetector` |
| Memory grows without bound | No consolidation or forgetting policy | YAML config replaces ad-hoc state; TTLs and explicit supersession edges |

---

### Healthcare GraphRAG & Ontology-Driven System Architecture

```mermaid
flowchart TB
    UI["Clinician UI (Open WebUI + custom adapter)"] --> GW["API Gateway / AuthN-AuthZ"]
    GW --> ORCH["Query Orchestrator (ADK TriageAgent)"]

    subgraph SERVE["Serving Plane (online)"]
        ORCH --> TERM["Terminology Service (LOINC / SNOMED / UCUM)"]
        ORCH --> RET["Retrieval Service<br/>(graph + hybrid search, ACL-filtered)"]
        ORCH --> SYN["Synthesis Agent (Gemini)"]
        SYN --> VER["Verification Pipeline"]
        VER --> RULES["Clinical Rules Service<br/>(dose / interaction / contraindication)"]
    end

    subgraph INGEST["Ingestion Plane (offline, human-governed)"]
        SRC["Source docs"] --> PARSE["Layout-aware Parsing Service"]
        PARSE --> EXTR["Extraction Agent (proposes assertions)"]
        EXTR --> NORM["Normalisation via Terminology Service"]
        NORM --> CUR["Curation Queue (human review + conflict resolution)"]
        CUR --> STG[("Staging Graph")]
        STG --> EVAL["Evaluation Gate"]
        EVAL --> REL["Promote: Knowledge Release ID"]
    end

    REL --> GDB[("Graph DB (property graph)")]
    REL --> IDX[("OpenSearch: BM25 + vectors")]
    REL --> PG[("PostgreSQL: provenance, ACLs, releases")]
    RET --> GDB
    RET --> IDX
    RET --> PG
    VER --> AUDIT[("Append-only Audit Log")]
```

#### Agents vs. Services

| Component | Type | Rationale |
| :--- | :--- | :--- |
| Parsing (PDF, tables, OCR) | Service | Deterministic, testable |
| Terminology lookup / LOINC mapping | Service | Shared by both planes; no cross-swarm coupling |
| Extraction of candidate assertions | **Agent** (schema-constrained) | Needs language judgement; output is a *proposal* |
| Curation / conflict resolution | Human + tooling | Clinical accountability |
| Index writes | Service (outbox, idempotent) | No dual-write drift |
| ACL enforcement | Service | Must not be model-dependent |
| Query orchestration | **Agent** (ADK `TriageAgent`) | Decomposes multi-part questions |
| Ontology resolution | **Agent** (`OntologyResolverAgent`) | Language judgement + LOINC normalization |
| Safety gating | **Deterministic code** (`SafetyGateEngine`) | Must not be probabilistic |
| Synthesis | **Agent** (`ClinicalSynthesizerAgent`) | Language judgement |
| Entailment / verification check | **Agent** (separate model call) | Judgement against source spans |
| Dose / interaction / contraindication | Service (licensed drug KB) | Must be deterministic |

> [!IMPORTANT]
> **Safety rules must live in deterministic code, not in prompts.** This is Gap 9 in this repository. The `SafetyGateEngine` and its five pluggable detectors are pure-code gates that run before any LLM synthesis occurs.

---

### Knowledge Model (Property Graph)

#### Core Nodes

| Node | Key Attributes |
| :--- | :--- |
| `DocumentVersion` | `doc_id`, `version`, `publisher`, `effective_date`, `retired_date`, `acl`, `checksum` |
| `Chunk` | `text`, `span_offsets`, `section_path`, `page`, `embedding_ref` |
| `Assertion` | `type`, `status` (`proposed`/`approved`/`retired`), `confidence`, `extractor_version`, `reviewer` |
| `Recommendation` | `population`, `line_of_therapy`, `strength`, `evidence_level`, `status`, `valid_from`, `valid_to`, `recorded_at` |
| `Concept` | `code_system` (LOINC/SNOMED/RxNorm), `code`, `label`, `level` |
| `Qualifier` | `severity`, `laterality`, `stage`, `lab_threshold`, `ucum_unit` |

**Illustrative graph pattern (not clinical guidance):**

```
(DocumentVersion)-[:HAS_CHUNK]->(Chunk)
(Recommendation)-[:EVIDENCED_BY]->(Chunk)
(Recommendation)-[:FOR_CONDITION]->(Concept: condition)
(Recommendation)-[:FOR_POPULATION]->(Qualifier: population qualifier)
(Recommendation)-[:RECOMMENDS]->(Concept: drug or drug class)
(Concept: drug)-[:CAUTION_IN {qualifiers}]->(Concept: condition)
(Recommendation)-[:SUPERSEDES]->(Recommendation)
```

> [!NOTE]
> Bitemporal fields are mandatory: *valid time* (when guidance applies in the world) and *recorded time* (when the system learned it). Supersession is an explicit graph edge, not an overwrite.

#### Trust Tiers

| Tier | Content | Used For |
| :--- | :--- | :--- |
| **1** | Human-approved assertions | Answers, verification |
| **2** | Auto-extracted, high confidence, low risk | Retrieval hints only |
| **3** | Unreviewed proposals | **Never served** |

High-risk assertion types (dosing, contraindications, numeric thresholds) always require human approval (Tier 1).

---

### Ontology Strategy

| System | Role in This Architecture |
| :--- | :--- |
| **LOINC** | Primary backbone for lab test identity (currently implemented in `concepts.yaml`) |
| **UCUM** | Units — `UnitMismatchDetector` enforces UCUM-valid units per concept |
| **SNOMED CT** | Semantic backbone for conditions and findings (production extension) |
| **RxNorm** | Drugs; each node states its level (ingredient / clinical drug / branded) |
| **ICD-10 / ICD-10-CM** | Mapped, reporting-oriented view; not the backbone |
| **ATC** | Drug classes |
| **UMLS** | Cross-walk and synonym support |

> [!WARNING]
> All lookups must go through one **Terminology Service**. Agents must never invent codes. The current `OntologyResolverAgent` enforces this by rejecting any resolution not found in the governed `OntologyRegistry`.

---

### Ingestion Plane (Offline, Human-Governed)

1. **Trigger:** Workflow (e.g., Airflow) detects a new or updated guideline document; creates a `DocumentVersion` with ACL and effective dates.
2. **Parsing:** Layout-aware (multi-column, tables, footnotes, recommendation boxes, scanned pages with OCR). Low-confidence tables are routed to human review.
3. **Extraction:** Schema-constrained agent proposes assertions with exact source spans and negation/uncertainty/experiencer/temporality flags. Validators reject unsupported spans.
4. **Normalisation:** Codes assigned by the Terminology Service; unmapped terms go to a curation queue.
5. **Curation:** Humans approve high-risk assertions and resolve cross-document conflicts and supersession.
6. **Staging → Evaluation → Promote:** Run the gold-set evaluation gate; on pass, publish a **Knowledge Release ID**.
7. **Publish:** Outbox pattern writes graph, index, and provenance idempotently. Indexes can be rebuilt from the evidence store.

> [!CAUTION]
> Treat ingested documents as **data, not instructions**. Isolate extraction agents, constrain outputs to schemas, and give tools least privilege to prevent prompt injection via document content.

---

### Serving Plane (Online)

1. **AuthN/AuthZ:** User identity and document ACLs resolved before retrieval.
2. **Orchestration:** Decompose the query; identify population, condition, assay, and which guideline "current" refers to. Ask for missing population details rather than guessing (Gap 8).
3. **Entity Expansion:** Terminology Service returns codes and synonyms.
4. **Retrieval:** Parameterised, read-only graph query templates for known patterns; exploratory LLM-generated queries run only in a sandboxed read-only role. Combine with hybrid search (BM25 + dense). **ACL filters apply inside every query.**
5. **Synthesis:** Drafts an answer where each claim cites chunk/span IDs.
6. **Verification Pipeline (all layers must pass):**
   - **Citation integrity:** Cited spans exist and are in the stated document version
   - **Entailment:** Each claim is supported by its cited span
   - **Applicability:** Population/qualifiers match the question
   - **Currency:** Documents and recommendations are valid and not superseded
   - **Clinical rules:** Dose, interaction, contraindication via the Clinical Rules Service
   - **Guardrails:** PII filter, contextual grounding, policy checks
7. **Release after verify:** Stream only progress and evidence; release answer text once verification passes. On failure, return sources with a clear "could not verify" message.
8. **Response contract:** `answer`, `claims`, `citations` (span-level), `knowledge_release_id`, `warnings`.

---

### Security, Privacy & Regulatory

#### PHI
- One BAA-covered inference path; map every processor that can see prompts (model host, gateway, tracing, logs).
- PHI-safe telemetry: redact or hash prompts in traces; enforce retention limits; configure custom entities for MRNs and free-text identifiers.

#### Authorisation
- ACLs on `DocumentVersion`, propagated to chunks and assertions; enforced in graph queries, search filters, and citation rendering. UI-level RBAC is insufficient.

#### Audit
- Append-only, immutable audit log: `user`, `query`, `knowledge_release_id`, `retrieved_spans`, `verification_results`, `output_hash`. Observability tools (e.g., Langfuse) are for debugging, **not** the audit trail.

#### Regulatory Positioning
- Write an intended-use statement before build. Assess against FDA non-device CDS criteria (Section 520(o)(1)(E) FDCA; see updated FDA CDS guidance, **January 2026**). Design choices that matter: HCP-only audience, transparency of sources and basis, no directive single-answer outputs without review.
- Take regional equivalents (EU MDR, etc.) to counsel and a regulatory specialist.

---

### Evaluation & Quality Gates

| Gate | Check | Blocks Release If |
| :--- | :--- | :--- |
| **Extraction** | Gold set: entities, negation, tables, qualifiers | Below agreed precision/recall on high-risk types |
| **Retrieval** | Gold queries with known correct spans | Recall regression |
| **Verification** | Seeded false claims, wrong-population and superseded-guideline cases | Any unblocked unsafe claim |
| **Safety** | Red-team: prompt injection, ACL bypass, PHI leakage | Any critical failure |
| **Trajectory (Gap 10)** | 28 deterministic `pytest` invariants; no LLM calls | Any safety invariant regression (~2.3 s in CI) |
| **Regression** | Model, prompt, or ontology change | Any metric drop vs. last release |

> [!TIP]
> Trajectory evaluation (Gap 10) is already implemented in this repository. Running `python -m pytest tests/ -v` covers 28 safety invariants in ~2.3 seconds without any LLM or network calls — closing the evaluation gap at zero cost in CI.

---

### Technology Stack

| Layer | Production Choice | Notes |
| :--- | :--- | :--- |
| **Agent framework** | **Google ADK 2.2** (this repo) *or* **AWS Strands SDK** | Multi-Agent Workflows + A2A Communication Protocols; pin exact version; upgrades gated by evaluation |
| **Inference** | Single BAA-covered gateway; model aliases in config | No hard-coded model names; upgrades gated by evaluation |
| **Graph DB** | Property graph + openCypher/Cypher | Neptune (openCypher) *or* Neo4j (Cypher) |
| **Search** | OpenSearch (BM25 + dense vectors) | Derived from graph/evidence store |
| **Relational** | PostgreSQL | Provenance, ACLs, releases, sessions |
| **Parsing** | Textract / Unstructured.io + table QA | Airflow orchestration |
| **Terminology** | Terminology server over licensed SNOMED CT, RxNorm, LOINC, UCUM, ATC, ICD-10 | CI validates codes against terminology server |
| **Clinical rules** | Licensed drug knowledge base behind a service | NLM RxNav API was retired 2024 |
| **Guardrails** | Bedrock Guardrails (AWS) or equivalent as one layer | Not the verifier; does not validate dosage bounds |
| **Observability** | Langfuse or similar, PHI-redacted | Separate from audit log |
| **UI** | Open WebUI + custom adapter | Review current licence terms before productising |

> [!WARNING]
> Neptune supports Gremlin and openCypher on property graphs, and SPARQL on RDF graphs — these two models are **not cross-queryable**. Choose one and stay consistent. Neo4j uses Cypher, not Gremlin.

---

### Phased Roadmap

| Phase | Scope |
| :--- | :--- |
| **0. Foundations** | Intended-use statement, PHI data-flow map, licensing, Terminology Service, gold-set seed, LOINC `concepts.yaml` |
| **1. Single-domain pilot** | One specialty (lab medicine); ingestion with human curation; qualified `Recommendation` model; verification pipeline |
| **2. Hardening** | Clinical Rules Service, ACL enforcement, red-team, append-only audit log, Knowledge Release ID management |
| **3. Scale-out** | More domains (radiology, pharmacy), conflict resolution workflows, cost tiering (small models for routing/entailment), DR drills |

---

### Design Principles (Production Summary)

1. **Evidence is the source of truth; the graph is a derived index.** Every assertion links to exact source spans in a specific document version.
2. **Recommendations are first-class, qualified nodes** — not bare triples. Population, line of therapy, strength, evidence level, status, and validity windows are mandatory.
3. **Agents only where judgement is needed.** Parsing, terminology lookup, ACL checks, dose/interaction checks, and index writes are deterministic services.
4. **Humans gate the knowledge base.** Staging graph → evaluated release → promote. High-risk assertion types always require human approval.
5. **Verify against source, not against the graph's own LLM output.** Block unverified clinical text; never stream it.
6. **Never store a fact without its provenance.** Source, author, time of acquisition, and the chain of reasoning behind a derived fact are mandatory metadata.
7. **Prefer supersession over overwriting.** Keep history; mark what is current. Supersession is an explicit graph edge.
8. **Scope everything.** Decide whether each memory is private to a user, shared by a team, or organization-wide — and enforce it with ACLs, not UI conventions.
9. **Make forgetting explicit.** Define retention, decay, and deletion rules up front, especially for personal data and ephemeral order-parse facts.
10. **Evaluate memory directly.** Test recall, staleness handling, conflict resolution, and cross-session continuity — not just final task success.
