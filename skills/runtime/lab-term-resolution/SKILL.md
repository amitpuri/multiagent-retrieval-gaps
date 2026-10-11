---
name: lab-term-resolution
description: Present the result of resolving a clinician's lab term to canonical LOINC observables. Use when reporting resolve_lab_term output, especially when a designation is ambiguous; list every candidate and never choose one.
allowed-tools: resolve_lab_term
license: Apache-2.0
metadata:
  roles: ontology_resolver
  risk_class: clinical
  version: 1.0.0
  references: designation-index
---

# Lab term resolution

## Steps

1. Call `resolve_lab_term` with the term, unit, qualifier and value you were given.
2. Report the status and every candidate exactly as returned: label, URI,
   department, admitted units and trust tier.
3. If the status is AMBIGUOUS, look the designation up in
   `references/designation-index.md` and state what tells the candidates apart.

## Rules

- Never choose between candidates, rank them, or say which is more common.
- Never translate a unit or qualifier yourself; the tool already normalised it.
- Deprecated concepts are never offered as candidates. Do not mention them.
