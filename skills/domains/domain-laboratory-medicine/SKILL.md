---
name: domain-laboratory-medicine
description: Orientation to the laboratory medicine ontology pack. Use to check which observables, panels and look-alike hazards the pack covers before resolving or interpreting a lab query, and to recognise requests outside its scope.
license: Apache-2.0
metadata:
  roles: ontology_resolver clinical_synthesizer
  risk_class: clinical
  version: 1.0.0
  domain: laboratory_medicine
  references: domain-summary designation-index
---

# Laboratory medicine

`references/domain-summary.md` lists every observable and panel this pack
covers, with its department, units and trust tier. Anything not listed is out
of scope: say so rather than answering from general knowledge.

## Look-alike hazards

`references/designation-index.md` lists the designations that denote more
than one observable, such as a short form shared by an analyte and its
glycated fraction. Treat each as a hazard: the candidates differ in meaning
and must never be interchanged.

## Rules

- This skill orients you; it never supplies values. Reference and critical
  intervals come only from the tools.
- Demonstration values in this pack are not clinically validated. Carry the
  unvalidated caveat whenever you present them.
