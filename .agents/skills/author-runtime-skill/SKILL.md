---
name: author-runtime-skill
description: >-
  Author or change a runtime Agent Skill (skills/runtime/<name>/ or a domain
  skill under skills/domains/) and its role wiring. Use when asked to "author a
  skill", "create a runtime skill", "update SKILL.md", "add a domain skill" or
  "give a role new guidance".
---

# Skill: Author a Runtime Skill

Runtime skills carry **procedure** for one or more agent roles. Knowledge
(terms, units, facets, intervals, caveat wording) lives in the ontology; the
skill's `references/` are **rendered from it**, never hand-written. Routing is
the gate's decision, never a skill's.

## Layout

```
skills/
├── runtime/<name>/SKILL.md            # procedure for one or more roles
│   └── references/<ref>.md            # GENERATED from the ontology (do not edit)
├── domains/domain-<pack-id>/SKILL.md  # orientation to one domain pack
└── skills.lock.json                   # content hashes + the bundle they were built from
agents/<role>.yaml                     # which role loads which skill, and its tool grants
shared/ontogate/templates/skills/      # reference templates (designation-index, facet-questions,
                                       #   trust-caveats, panels, domain-summary)
```

## Frontmatter

```markdown
---
name: lab-term-resolution              # = directory name, ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$, ≤ 64 chars, unquoted
description: What it does and when to use it. Unquoted, ≤ 1,024 chars.
allowed-tools: resolve_lab_term        # every canonical tool the body names
license: Apache-2.0
metadata:
  roles: ontology_resolver             # roles that load it (must match agents/<role>.yaml)
  risk_class: clinical                 # clinical | general
  version: 1.0.0
  references: designation-index        # optional: references rendered from the ontology
  domain: laboratory_medicine          # domain skills only; name must be domain-<pack id>
---
```

## Wiring a role

- A runtime skill is loaded by listing it under `skills:` in `agents/<role>.yaml`
  **and** naming that role in the skill's `metadata.roles`. Both directions are checked.
- Domain skills are never listed by name: a role with `domain_skills: true` loads
  `domain-<pack id>` for every pack it serves, so a new pack needs no role edit.
- Every tool in `allowed-tools` must be granted to every role that loads the skill.
- `safety_guard` is a code node: no model, no skills.

## Rules `ontogate skills build` enforces

Format and stores: name/description limits, name equals directory, unquoted
fields, body ≤ ~5k tokens, archive ≤ 10 MB, no control characters, no remote URLs.

Clinical (`risk_class: clinical`), across SKILL.md **and** references:
1. No `scripts/` directory.
2. No number followed by a clinical unit (e.g. a value in mg/dL, mmol/L, ng/L, %).
3. No routing or defaulting language ("proceed if", "assume the unit", "default to").
   Prohibitions are fine: "never assume the unit".
4. Tool names in backticks must be canonical MCP tools listed in `allowed-tools`.

Role consistency (RoleSkillShape, also checked in SHACL by `ontogate rdf validate`):
roles and skills agree in both directions; no code node loads skills; tools are granted.

## Commands

```bash
python -m ontogate skills build    # render references, lint, check roles, write lock + dist/skills/*.zip
python -m ontogate skills check    # same checks, no writes; fails on reference or lock drift (CI)
python -m ontogate skills role ontology_resolver   # the hash-verified directories a role loads
python -m pytest shared/tests/test_skills_and_roles.py
```

Changing the ontology changes the bundle hash, so re-run `ontogate skills build`
and commit the regenerated references and `skills.lock.json` with it.

## Adding a reference type

Add a renderer to `shared/ontogate/skill_refs.py` (`RENDERERS`) and a template
`shared/ontogate/templates/skills/<name>.md.j2`. Rendered text must stay free of
clinical numbers — the lint runs over references too.
