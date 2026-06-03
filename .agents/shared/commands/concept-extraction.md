# Concept Extraction

Shared contract for writing reusable Obsidian concept stubs after artifact-generating workflows.

Run this only after a real vault artifact write for workflows that create durable reference material: `generate-report`, `intraoperative-guide`, `study-material`, `consult`, and `grand-rounds`. Do not run it for dry runs, failed validations, pure `study-review`, or quick answers.

## Target

Write 2-5 atomic concepts worth future wikilinking to:

```text
/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/<Concept Name>.md
```

Skip concepts that already exist. Never overwrite protected concept notes unless Gabriel explicitly asks.

Protected notes:

- `Neurosurgery Consult Workflow.md`
- `Neurosurgery Consult Checklists by Pathology.md`
- `Peripheral Nerve Injury Classifications (Seddon & Sunderland).md`

## Concept Shape

Concepts are glossary-level targets, not mini-reports. Create a stub only when the concept is likely to be referenced by future reports, guides, consults, or study sessions.

```markdown
**<Concept Name>**: <Core definition, 2-3 sentences.>

**Clinical Relevance**: <1-2 sentences.>

**Key Distinctions**: <Most important differentiating features.>

---
aliases: [<abbreviations>]
created: YYYY-MM-DD
extracted_from: "<skill>: <topic>"
tags: [type/concept, domain/<domain>, source/agent]
---
```

## Index

After writing concept stubs, regenerate the domain-grouped index with `python3 src/index_builder.py Concepts`. The builder groups by the `domain/<domain>` tag, so every stub must keep that tag and close its bottom YAML with a final `---` (an unterminated block parses as no metadata and the concept drops to `Uncategorized`). The index is a navigational surface; do not duplicate full concept definitions there.
