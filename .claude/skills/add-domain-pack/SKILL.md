---
name: add-domain-pack
description: >-
  Add a new clinical domain pack (ontology/domains/<id>/) with its domain skill and
  competency questions, without changing shared code or role specs. Use when asked to
  "add a domain", "add a new specialty", "onboard cardiology/nephrology/...", or
  "reuse the gate for another domain".
---

# Skill: Add a Domain Pack

A domain is data. The gate, resolver, tools, roles and frameworks are reused
unchanged — `shared/tests/test_domain_reuse.py` fails if shared code names a pack.
Use `ontology/domains/cardiology/` as the worked example.

## Steps

1. **Pack** — create `ontology/domains/<id>/` with `domain.yaml` (manifest: `id`,
   `version`, `imports: [core]`, `label`, `description`, `disclaimer`, `files`), then
   `vocabulary.yaml`, `analytes.yaml`, `facets.yaml`, `observables.yaml`,
   `designations.yaml`, `intervals.yaml`, `protocols.yaml` (and `panels.yaml` if any).
   Every file starts with `schema_version: "1.0.0"`.
2. **Look-alikes** — a designation that denotes more than one observable must have
   `kind: ambiguous`; `confusable_with` must be symmetric. Units must be in
   `ontology/core/core.yaml`.
3. **Provenance** — demonstration values carry `clinically_unvalidated: true` and
   `verified_by: null`. Never mark generated values as human-verified.
4. **Domain skill** — `skills/domains/domain-<id with - for _>/SKILL.md` with
   `metadata.domain: <id>`, `metadata.roles: ontology_resolver clinical_synthesizer`
   and `metadata.references: domain-summary designation-index`. Do not list it in any
   role spec: roles with `domain_skills: true` load it automatically.
5. **Competency questions** — `config/scenarios/scenario_<x>_<id>.yaml` with
   `domain: <id>` and `test_cases` (input text, expected gap, route, concept or candidates).
6. **Knowledge log** — append an initial-release line to `knowledge/log.md`.

## Verify

```bash
python -m ontogate validate ontology/domains/<id>
python -m ontogate skills build          # renders the domain skill's references, relocks
python -m ontogate rdf validate --domain <id>
python -m pytest shared/tests/test_competency_questions.py shared/tests/test_domain_reuse.py
python conformance/run.py                # the new CQs on ADK, Strands and MAF
```
