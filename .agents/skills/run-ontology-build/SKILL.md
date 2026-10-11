---
name: run-ontology-build
description: >-
  Build and verify the knowledge release (integrity rules, skills lock, SHACL,
  OWL 2 RL, release manifest) after changing the ontology, skills or role specs.
  Use when asked to "build the release", "regenerate the skills lock", "run SHACL",
  "why does skills check fail", or after any edit under ontology/, skills/ or agents/.
---

# Skill: Run the Ontology Build

The ontology bundle hash pins the skills lock, so **any** edit under `ontology/`
(including `shapes.ttl`) makes `ontogate skills check` report `LOCK_DRIFT` until the
skills are rebuilt. Generated files are committed with the change that caused them.

## Commands

```bash
export PYTHONPATH=shared                       # PowerShell: $env:PYTHONPATH = "shared"
python -m ontogate validate                    # integrity rules: pack + scenario overlays
python -m ontogate skills build                # render references, lint, role checks, lock, dist/skills/*.zip
python -m ontogate skills check                # same, no writes; CI fails on drift
python -m ontogate rdf validate                # SHACL over ontology + roles/skills/tools graph
python -m ontogate build                       # all of the above + OWL 2 RL → dist/release/manifest.json
(cd agent-framework && python -m src.declarative)   # after editing agents/*.yaml
```

## Reading failures

| Message | Fix |
| :--- | :--- |
| `LOCK_DRIFT` / `REFERENCE_DRIFT` | run `ontogate skills build`, commit `skills/` |
| `NO_CLINICAL_NUMBERS`, `NO_ROUTING_VERBS` | move the value or the decision into the ontology / gate |
| `TOOL_NOT_GRANTED`, `SKILL_ROLE_MISMATCH` | align `allowed-tools` / `metadata.roles` with `agents/<role>.yaml` |
| SHACL `locked against bundle` | the lock is stale: `ontogate skills build` |
| SHACL interval / designation / sequence messages | fix the YAML the focus node names |

The RDF steps need the build extra: `pip install -e "shared[dev]"`.
