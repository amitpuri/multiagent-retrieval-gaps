---
name: update-model-catalog
description: >-
  Change which model a cloud or role uses (config/models.yaml), including Claude
  effort and OpenAI reasoning effort per role. Use when asked to "upgrade the model",
  "switch to a new Gemini/Claude/GPT version", "change the model for a role", or when
  the retirement warning fires.
---

# Skill: Update the Model Catalog

`config/models.yaml` is the only place a model ID may appear.
`shared/tests/test_model_catalog.py` scans code, scripts, templates, agent YAML and
every README (not `docs/`) and fails on any ID outside the catalog.

## Steps

1. Verify the new model in the provider's documentation and in your region (Bedrock
   inference profile, Vertex model garden, Foundry model catalogue and SKU).
2. Add it under `catalog:` with `provider`, `family`, `status` and, where relevant,
   `bedrock_id` (AWS) or `version` + `api` (Azure). Set `retire_after` when known.
3. Point `deployments.<cloud>.default` (or a role under `roles:`) at it. Keep per-role
   `role_effort` / `role_reasoning_effort` explicit.
4. Replace the ID wherever the guard reports it (deploy defaults, README tables).
5. Re-run conformance and, for a role down-tier, the live evals first.

```bash
python -m pytest shared/tests/test_model_catalog.py
./run-all-tests.sh
```
