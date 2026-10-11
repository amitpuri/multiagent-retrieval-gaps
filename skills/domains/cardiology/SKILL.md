---
name: domain-cardiology
description: Domain skill for cardiology biomarker decision support. Guides resolution, interpretation, and look-alike disambiguation for cTnI, cTnT, BNP, and hsCRP without hardcoding any reference values.
license: Apache-2.0
metadata:
  roles: ontology_resolver,clinical_synthesizer,triage_orchestrator
  risk_class: clinical
  bundle_sha256: pending
---

# Cardiology Domain Skill

This domain skill governs the use of the **cardiology** ontology pack
(ontology/domains/cardiology/) and applies to queries about cardiac biomarkers:
Troponin I (cTnI), Troponin T (cTnT), BNP, and high-sensitivity CRP (hsCRP).

## Domain Rules

### 1. Look-alike Hazard: cTnI vs cTnT

The abbreviation "cTn" or "Troponin" without an I/T qualifier is **ambiguous**.
Troponin I (loinc:10839-9) and Troponin T (loinc:6598-7) are:
- Different analytes measured by different assay platforms
- Governed by different protocols with different 99th-percentile URLs
- Never interchangeable in interpretation

**When valuate_safety_gate returns AMBIGUOUS for "Troponin" or "cTn":**
Call uild_clarification_prompt to ask specifically: *"Is this Troponin I (cTnI) or Troponin T (cTnT)? These have different reference limits and are measured by different assays."*

### 2. Assay-Specific Interpretation

Reference limits for cTnI and cTnT are assay-specific.
- The protocol retrieved by etch_grounded_protocol carries the guideline source.
- Never apply a cTnI URL to a cTnT result or vice versa.
- Consult eferences/troponin-assay-notes.md for assay platform awareness.

### 3. BNP vs NT-proBNP

BNP (loinc:42637-9) and NT-proBNP are different analytes with different LOINC codes,
different cutoffs, and different half-lives. The gate will return NOT_FOUND for NT-proBNP
if this domain pack is loaded alone — do not substitute BNP values.

### 4. hsCRP Units

hsCRP (loinc:30522-7) is reported in mg/L (SI) or mg/dL. Both units are admitted
(eferences/designation-index.md). Unit conversion is handled by ttest_computation
and must not be done manually.

### 5. Synthesis

All synthesis follows the grounded-synthesis runtime skill invariants:
- Execute only after gate returns PROCEED.
- Cite only values returned by ttest_computation.
- Apply [Attested ✓] badge only on PASS verdict.
- Apply the trust-tier disclaimer from eferences/trust-caveats.md.
