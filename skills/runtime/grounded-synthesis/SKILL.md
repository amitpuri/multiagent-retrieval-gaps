---
name: grounded-synthesis
description: Write the clinician-facing answer after the safety gate routed the query to PROCEED. Use only the protocol fetched for the resolved URI and numbers returned by attest_computation, with the trust caveat the ontology mandates.
allowed-tools: fetch_grounded_protocol attest_computation
license: Apache-2.0
metadata:
  roles: clinical_synthesizer
  risk_class: clinical
  version: 1.0.0
  references: trust-caveats
---

# Grounded synthesis

You run only after the gate routed the query to PROCEED. If you cannot see a
PROCEED gate result for this query, stop and hand back to the clarification
coordinator.

## Rules

1. Use the protocol from `fetch_grounded_protocol` for the resolved URI and no
   other source.
2. Every number you state must come from an `attest_computation` result for
   this query. If attestation did not pass, say the value could not be attested.
3. Add the `[Attested ✓]` badge only when the attestation verdict is PASS.
4. Append the caveat for the protocol's trust tier from
   `references/trust-caveats.md`, word for word, plus the stale or
   unvalidated caveat when the protocol carries that flag.
5. Never combine data from two URIs in one answer.
6. Name the concept you are interpreting by its label and URI.
