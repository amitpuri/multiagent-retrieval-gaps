# Agent Framework — Azure AI Foundry (Coming Soon)

*Multi-Agent Retrieval-Gap Decision Support: Azure AI Foundry / Semantic Kernel Implementation*

---

> [!NOTE]
> This folder is a placeholder for the **Azure AI Foundry + Semantic Kernel** port of the
> Laboratory Medicine Decision Support system. Implementation is planned as the third
> framework alongside [`google-adk-agents/`](../google-adk-agents/) and [`strands-agents/`](../strands-agents/).

---

## Planned Stack

| Component | Azure Choice |
| :--- | :--- |
| **Agent framework** | Azure AI Foundry (Agents API) + Semantic Kernel |
| **Model** | Azure OpenAI — `gpt-4o` or `o3` via Azure endpoint |
| **Memory / Session** | Azure AI Foundry managed sessions |
| **Orchestration** | Semantic Kernel `KernelFunction` pipeline |
| **Safety gate** | Same deterministic `SafetyGateEngine` (shared `config/`) |
| **Tests** | `pytest` offline deterministic invariants (same pattern as other frameworks) |

## Planned Structure

```text
agent-framework/
├── src/
│   ├── .env                      # Azure OpenAI key + endpoint (gitignored)
│   ├── env.example               # Template
│   ├── agents/                   # Semantic Kernel agent roles
│   ├── core/                     # Shared: Pydantic models, detectors (symlink / copy from config/)
│   ├── orchestration/            # SK pipeline / planner
│   └── main.py
└── tests/
    ├── test_gate.py              # Shared deterministic safety invariants
    └── test_sk_agents.py         # Azure-specific agent contract tests
```

## Shared Configuration

All three frameworks consume the **same** declarative YAML configuration from [`config/`](../config/):

- `config/domains/laboratory_medicine/` — concepts, protocols, ranges, specimen rules
- `config/scenarios/` — Scenarios A–D gap detection playbooks

No Python code changes are required to add a new clinical gap scenario.

---

> **Status**: 🔜 Coming soon — contributions welcome.
