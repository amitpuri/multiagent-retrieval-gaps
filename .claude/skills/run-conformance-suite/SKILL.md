---
name: run-conformance-suite
description: >-
  Check that ADK (GCP), Strands (AWS) and MAF (Azure) make identical decisions on every
  competency question, offline or against a deployed endpoint. Use when asked to
  "check cross-cloud parity", "run conformance", "do all frameworks agree", or after
  changing a framework adapter, tool wrapper or server.
---

# Skill: Run the Conformance Suite

## Offline (every framework, every competency question)

```bash
python conformance/run.py            # each framework's own tool wrappers vs the canonical core
python -m pytest conformance         # the same as tests, plus the live runner against each server
python conformance/live.py --asgi maf    # one framework's server, in-process, credentials blanked
```

`run.py` probes each framework in its own process (all three use the package name
`src`) and diffs status, route, resolved URI, candidates, readings, attestation, panel
order and the published A2A AgentCard against the canonical `ontogate` result.

## Against a deployment

```bash
python conformance/live.py --endpoint <service-url> [--token <bearer>]
```

The runner reads `/.well-known/agent-card.json`, refuses a service that serves a
different ontology bundle than your checkout, and asks only the questions that
service's domain pack can answer. Every `deployment/*/test-service.*` script runs it.

## When a framework diverges

The report (`dist/conformance/report.json`) names the case and the differing fields.
Typical causes: a wrapper that drops parsed context (population, department, panel)
before the gate, a renamed tool argument, or a server path that bypasses the shared
tools. Fix the adapter; never change an expectation to match one framework.
