---
name: clarification-dialogue
description: Generate human-in-the-loop clarification prompts for missing qualifiers, ambiguous terms, or unit mismatches. Ask only for missing facets with ontology-admitted values.
license: Apache-2.0
metadata:
  roles: clarification_coordinator
  risk_class: clinical
  bundle_sha256: pending
---

# Clarification Dialogue

This skill defines rules for generating clinician clarification dialogues when the deterministic safety gate returns `CLARIFY`.

## Dialogue Invariants

1. State the exact reason for the safety stop identified by `evaluate_safety_gate`.
2. Use `build_clarification_prompt` to generate structured prompt text.
3. Consult `references/facet-questions.md` for standard phrasing per missing facet.
4. Limit offered choices strictly to allowed ontology facet values.
5. Never guess, assume default clinical units, or nudge the user toward a particular selection.
