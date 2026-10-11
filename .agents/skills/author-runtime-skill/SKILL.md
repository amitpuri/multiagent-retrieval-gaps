---
name: author-runtime-skill
description: >-
  Guidelines and clinical lint rules for authoring or updating runtime Agent Skills.
  Use when asked to "author a skill", "create a runtime skill", "update SKILL.md",
  or "add clinical skill".
---

# Skill: Author a Runtime Skill

## Purpose

Runtime Agent Skills (`skills/runtime/<name>/SKILL.md` and `skills/domains/<name>/SKILL.md`) provide role-scoped procedural guidance without embedding clinical thresholds directly into model prompts.

---

## Skill Package Structure

```
skills/
├── runtime/<skill-name>/
│   ├── SKILL.md                 # Main instructions with frontmatter
│   └── references/              # Detailed markdown references (optional)
│       └── *.md
└── skills.lock.json             # Manifest and sha256 checksums
```

---

## Frontmatter Schema

Every `SKILL.md` must begin with YAML frontmatter conforming to `agentskills.io`:

```markdown
---
name: <kebab-case-name>
description: >-
  <1-2 sentences explaining what the skill does and when the agent should use it.>
---
```

---

## Clinical Lint Rules (Strictly Enforced)

The build step (`python -m ontogate.skills build`) enforces:

1. **No `scripts/` directory**: Clinical skills do not execute arbitrary unverified scripts.
2. **No clinical numbers + units in procedural text**:
   - ❌ WRONG: "If potassium is above 5.0 mmol/L, trigger panic."
   - ✅ CORRECT: "Verify patient values against grounded protocols fetched via `fetch_grounded_protocol`."
   - *Rationale:* Clinical thresholds must come from the ontology and grounded protocols, never hardcoded in prompt prose.
3. **Canonical tool names only**:
   - Reference only canonical tools: `parse_clinician_input`, `resolve_lab_term`, `evaluate_safety_gate`, `fetch_grounded_protocol`, `attest_computation`, `build_clarification_prompt`, `panel_workup`.

---

## Build and Lock Step

After editing or creating a skill:

```bash
python -m ontogate.skills build
```

This command:
1. Lints all skill packages against clinical safety rules.
2. Packages each skill into `dist/skills/<skill-name>.zip`.
3. Computes SHA-256 hashes and updates `skills/skills.lock.json`.

Then verify:
```bash
python -m pytest shared/tests/test_skills_and_roles.py -v
```
