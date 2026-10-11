# OKF Knowledge Update Log

Chronological record of changes to the knowledge corpus (TBox): designations,
observables, reference intervals, protocols, skills and verification events.
Per-request observations and attestations (ABox) are never recorded here — they
go to the runtime audit sink (`ontogate.ports.AuditPort`), redacted by default.

- 2026-10-11T00:00:00+00:00 | `ontology/domains/laboratory_medicine` | initial release 1.0.0 (observables, designations, facets, reference intervals, protocols, panels) | generated_by=reference_agent/gemini-2.5-pro | {'verified_by': 'human:dr_puri (observables, protocols)', 'intervals': 'unverified'}
- 2026-10-11T00:00:00+00:00 | `ontology/core` | initial release 1.0.0 (unit catalogue, relation catalogue with OWL characteristics, population facets, gate policy, trust policy and caveat wording, SHACL shapes) | generated_by=maintainers | {'verified_by': 'unverified'}
- 2026-10-11T00:00:00+00:00 | `ontology/domains/cardiology` | initial release 1.0.0 (troponin I/T look-alike pair, BNP, hsCRP, reference intervals, protocols) | generated_by=reference_agent/gemini-2.5-pro | {'verified_by': None, 'intervals': 'unverified'}
- 2026-10-11T00:00:00+00:00 | `skills/` | initial release 1.0.0 (6 runtime skills, 2 domain skills; references rendered from the ontology bundle; hashes in skills/skills.lock.json) | generated_by=maintainers | {'verified_by': 'unverified'}
