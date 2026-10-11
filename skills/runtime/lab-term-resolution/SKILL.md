---
name: lab-term-resolution
description: Resolve clinician laboratory terms and designations to canonical observables. Present all candidates without guessing when terms are ambiguous.
license: Apache-2.0
metadata:
  roles: ontology_resolver
  risk_class: clinical
  bundle_sha256: pending
---

# Laboratory Term Resolution

This skill guides the ontology resolver on mapping colloquial designations and abbreviations to canonical LOINC observables.

## Guidelines

1. Call `resolve_lab_term` with the clinician query term.
2. Review candidate observables and designations against `references/designation-index.md`.
3. When multiple candidates share a designation without differentiating qualifiers, return all matching candidates.
4. Never arbitrarily choose a single candidate when designations are ambiguous.
5. Propagate canonical LOINC URIs and admitted UCUM dimensions.
