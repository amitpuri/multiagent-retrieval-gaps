---
name: deploy-and-teardown
description: >-
  Deploy the agents to Google Cloud, AWS or Azure and remove everything afterwards so
  nothing keeps billing. Use when asked to "deploy to GCP/AWS/Azure", "tear down",
  "clean up the cloud resources", "what is still costing money", or "destroy the
  deployment".
---

# Skill: Deploy and Tear Down

Deploying creates billable resources in the user's account: confirm with the user
before running any deploy or delete. Every deploy is paired with its teardown.

## Deploy

```bash
deployment/gcloud-scripts/deploy.sh [--use-agent-runtime]   # Cloud Run (+ ADK AdkApp on Agent Runtime)
deployment/aws-scripts/deploy.sh                            # AgentCore runtime + memory (App Runner only with APP_RUNNER_FALLBACK=true)
deployment/az-scripts/deploy.sh                             # Container Apps + Foundry
```

Each deploy first runs `python -m ontogate build` (fails closed on any knowledge error),
publishes the locked skills if a store is configured, and appends every resource it
**creates** to `deployment/<cloud>-scripts/.deployed/ledger.tsv`. Then run
`test-service.sh`, which also asks the live service every applicable competency question.

## Tear down

```bash
deployment/<cloud>-scripts/destroy.sh          # plan: what the deploy created, newest first
deployment/<cloud>-scripts/destroy.sh --yes    # delete it (PowerShell: destroy.ps1 -Yes)
```

- Only ledger resources are deleted; reused resources (an existing Foundry account) are not.
- Failures stay in the ledger; re-run to retry.
- No ledger (an older or manual deploy): `--discover`. On Azure, the resource group is
  deleted only with `--delete-resource-group <name>`.
- GCP project IAM grants are review-only unless `--include-iam`.
- Read the "billed while they exist" list it prints (build and staging buckets, skill
  stores) and remove those by hand if they were created for this deployment.

Adding a resource to a deploy script? Record it (`record_created <kind> …` /
`Record-Created "<kind>" …`) and give the kind a handler in `deployment/teardown.py`;
`deployment/tests/test_teardown.py` fails otherwise.
