---
name: specimen-sequencing
description: Present a panel workup as its ordered collection steps. Use when the clinician asks for a panel or multi-tube collection; keep the tool's step order and department routing exactly.
allowed-tools: panel_workup
license: Apache-2.0
metadata:
  roles: panel_coordinator
  risk_class: clinical
  version: 1.0.0
  references: panels
---

# Specimen sequencing

## Steps

1. Call `panel_workup` with the panel the clinician named.
2. Present each step in the returned order with its department and the
   observables it includes. `references/panels.md` lists the known panels.

## Rules

- Never reorder, merge or drop steps.
- Never reassign a step to another department.
- If the tool does not recognise the panel, say so and list the known panels.
