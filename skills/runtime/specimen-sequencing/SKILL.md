---
name: specimen-sequencing
description: Present panel workup output in exact physical tube sequence without reordering or merging. Enforce department routing boundaries.
license: Apache-2.0
metadata:
  roles: panel_coordinator
  risk_class: clinical
  bundle_sha256: pending
---

# Specimen Sequencing

This skill guides the presentation and routing of multi-step, multi-department specimen panels.

## Rules

1. Call `panel_workup` to retrieve canonical collection step sequences.
2. Present tube ordering exactly as returned by the tool.
3. Review standard panels in `references/panels.md`.
4. Never reorder collection steps, merge separate tube aliquots, or reassign department responsibilities.
5. Highlight departmental routing (e.g. Clinical Biochemistry, Microbiology, Hematology) for each individual container.
