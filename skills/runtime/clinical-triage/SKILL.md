---
name: clinical-triage
description: Enforce standard order of operations for clinical laboratory queries. Call parse, resolution, and deterministic gate in order. Never answer before the gate returns PROCEED.
license: Apache-2.0
metadata:
  roles: triage_orchestrator
  risk_class: clinical
  bundle_sha256: pending
---

# Clinical Triage

This skill instructs the triage orchestrator on the mandatory sequence of actions for handling clinical laboratory queries.

## Order of Operations

1. **Parse Clinician Input:**
   Call `parse_clinician_input` to extract terms, units, qualifiers, and raw observations.
2. **Resolve Laboratory Terms:**
   Call `resolve_lab_term` with the extracted label to find candidate canonical observables.
3. **Evaluate Safety Gate:**
   Pass the context to `evaluate_safety_gate`.
4. **Branch Deterministically:**
   - If the gate returns `PROCEED`, route to protocol retrieval and grounded clinical synthesis.
   - If the gate returns `CLARIFY`, halt immediately and hand off to the clarification coordinator. Never attempt to guess or answer ahead of the gate.
