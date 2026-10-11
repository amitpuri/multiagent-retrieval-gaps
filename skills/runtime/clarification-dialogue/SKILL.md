---
name: clarification-dialogue
description: Ask the clinician the clarification question the safety gate requires. Use when the gate route is CLARIFY (ambiguous term, unit mismatch, missing qualifier, range collision or missing population). Ask one question per missing facet and offer only the ontology's values.
allowed-tools: build_clarification_prompt
license: Apache-2.0
metadata:
  roles: clarification_coordinator
  risk_class: clinical
  version: 1.0.0
  references: facet-questions
---

# Clarification dialogue

## Steps

1. Call `build_clarification_prompt` with the gate result you were handed.
2. State the reason the gate stopped, in one sentence, using the gate's status.
3. Ask the question from the tool result. For a missing facet, use the
   question and the allowed values in `references/facet-questions.md`.

## Rules

- One question per missing facet; never combine two facets into one question.
- Offer exactly the allowed values, in the listed order.
- Never suggest which value is likely and never fill in a unit or qualifier.
- Never interpret the patient value while the query is unresolved.
