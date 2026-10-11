---
name: domain-cardiology
description: Orientation to the cardiology biomarker ontology pack (cardiac troponins, natriuretic peptide, high-sensitivity CRP). Use to recognise the troponin I versus troponin T hazard and requests outside the scope of the pack.
license: Apache-2.0
metadata:
  roles: ontology_resolver clinical_synthesizer
  risk_class: clinical
  version: 1.0.0
  domain: cardiology
  references: domain-summary designation-index
---

# Cardiology biomarkers

`references/domain-summary.md` lists every observable this pack covers.
Anything not listed is out of scope: for example, NT-proBNP is a different
analyte from BNP and is not in this pack. Never substitute one for the other.

## Troponin I versus troponin T

"Troponin" or "cTn" without an I or T suffix is ambiguous
(`references/designation-index.md`). The two are different analytes, measured
on different assay platforms, with assay-specific decision limits. Never apply
a troponin I limit to a troponin T result or the reverse, and never pick one
for the clinician.

## Rules

- Decision limits are assay-specific and come only from the tools.
- Unit conversion is done by the tools, never by hand.
- Demonstration values in this pack are not clinically validated. Carry the
  unvalidated caveat whenever you present them.
