---
name: domain-laboratory-medicine
description: Domain orientation for laboratory medicine decision support. Outlines controlled vocabulary scope, analyte families, and departmental boundaries.
license: Apache-2.0
metadata:
  roles: ontology_resolver, clinical_synthesizer
  risk_class: clinical
  bundle_sha256: pending
---

# Domain Skill: Laboratory Medicine

This domain skill provides orientation on the clinical scope and diagnostic conventions of the laboratory medicine domain pack.

## Scope of Coverage

- **Analytes:** Hemoglobin, Glycated Hemoglobin, Total Calcium, Ionized Calcium, Cardiac Troponins (cTnI, hs-cTnT), and CSF Panels.
- **Controlled Vocabularies:** LOINC for observables, UCUM for units, and SNOMED CT for specimens.
- **Reference Material:** Consult `references/okf-summary.md` for catalog overview.
- **Clinical Caveat:** Procedural skills define behavioral workflows; all actual limits and intervals must be retrieved dynamically via deterministic MCP tools.
