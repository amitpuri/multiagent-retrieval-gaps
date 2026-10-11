---
name: grounded-synthesis
description: Write clinician-facing interpretation after safety gate returned PROCEED. Ground exclusively on protocol data fetched for the resolved URI and numbers returned by attest_computation.
license: Apache-2.0
metadata:
  roles: clinical_synthesizer
  risk_class: clinical
  bundle_sha256: pending
---

# Grounded Clinical Synthesis

This skill dictates synthesis rules for grounded clinical interpretation.

## Invariants

1. Execute only after the safety gate has returned `PROCEED`.
2. Call `fetch_grounded_protocol` with the resolved URI. Use no outside clinical protocol source.
3. Every stated numeric reference interval or panic threshold must originate from an `attest_computation` call in the current turn.
4. Include the badge `[Attested ✓]` only when the attestation verdict is `PASS`.
5. Apply the mandatory trust-tier disclaimer from `references/trust-caveats.md`.
6. Never merge or interpolate reference values across distinct LOINC URIs.
