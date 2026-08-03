# Concept Extraction

Shared contract for writing reusable Obsidian concept cards after artifact-generating workflows.

Concept cards are clinical execution references. Each note should make one concept durable enough for a resident to recognize it, explain why it matters, discriminate it from nearby concepts, and apply it under pressure on rounds, in the ICU, or in the OR.

Run this only after a real vault artifact write for workflows that create durable reference material: `generate-report`, `intraoperative-guide`, `study-material`, `consult`, and `grand-rounds`.

## Target

Write 0-5 atomic concepts worth future wikilinking to. Zero is the correct
result when the source adds no genuinely new reusable concept:

```text
/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/<Concept Name>.md
```

Select concepts that are likely to recur across reports, guides, consults, study sessions, presentations, or Anki cards. Prefer concepts with clinical leverage: anatomy that changes exposure, a trial that changes selection, a sign that changes escalation, a classification that changes strategy, or a threshold that changes management.

Before drafting, search `Concepts/`, the vault index, and aliases for the same
memory trace. If a concept already exists, read it completely and merge only
nonduplicative source-supported material into a complete revised draft. Never
overwrite an existing concept without that review. Pass `--allow-existing` only
after the merge has been performed.

These especially sensitive notes also require explicit user approval and
`--allow-protected` before any update:

- `Neurosurgery Consult Workflow.md`
- `Neurosurgery Consult Checklists by Pathology.md`
- `Peripheral Nerve Injury Classifications (Seddon & Sunderland).md`

## Concept Card Shape

Every concept card opens with a high-density definition:

```markdown
**<Concept Name>**: <1-3 sentences that define the concept and name its clinical consequence.>
```

Then include these universal sections:

```markdown
## Quick Reference

## Clinical Use

## Durable Mental Model

## Critical Discriminators

## Execution Check

## Related In This Vault
```

Use one archetype-specific execution section:

- `## Surgical Coordinates` for anatomy, corridors, danger structures, and operative maneuvers.
- `## Evidence Card` for trials, guidelines, outcome studies, and major evidence claims.
- `## Consequence Matrix` for classifications, grading systems, staging, or named diagnostic signs.
- `## Bedside Decision Rule` for management thresholds, protocols, escalation triggers, and consult decisions.
- `## Imaging Read` for radiographic signs, imaging sequences, and interpretation pitfalls.

Use `## References` when the card contains trials, guidelines, classification rates, operative outcome numbers, management thresholds, drug/dose details, or other source-sensitive claims.

## Writing Standard

- **Quick Reference**: concise bullets with the core facts a reader should retrieve in seconds.
- **Clinical Use**: the decision, risk, operative step, diagnostic move, prognosis, or escalation that changes because of the concept.
- **Durable Mental Model**: one memorable mechanism, spatial analogy, decision rule, or causal chain that makes the concept persist.
- **Critical Discriminators**: nearby concepts, mimics, or tempting wrong frames, written as clinically meaningful contrasts.
- **Execution Check**: action-oriented bullets that state what the reader should be able to do with the concept tomorrow.
- **Related In This Vault**: verified wikilinks only, using `[[folder/note|Display]]` form.
- **References**: evidence-type-labelled bullets with links when available, for example:
  - `Primary study: [Trial title](https://doi.org/...).`
  - `Guideline/formal guidance: [Guideline title](https://...).`
  - `Internal textbook RAG: Youmans and Winn, 8th ed., Vol. X, p. Y.`

Keep the card compact. A concept card is deeper than a glossary entry but shorter than a report or consult pocket card.

## Metadata

Every concept card begins with native Obsidian frontmatter:

```markdown
---
aliases: [<abbreviations and search terms>]
created: YYYY-MM-DD
extracted_from: "<skill>: <source artifact title>"
domain: <canonical-domain>
summary: "<one-line index summary>"
tags: [type/concept, domain/<canonical-domain>, source/agent]
---
```

Canonical domains: `vascular`, `skull-base`, `tumor`, `spine`, `trauma`, `neurocritical-care`, `functional`, `pediatric`, `peripheral-nerve`, `anatomy`, `general`.

## Guard And Index

Draft to `data/Sessions/concept_<slug>.md` when needed, then validate/install:

```bash
python3 src/concept_guard.py install \
  --draft "data/Sessions/concept_<slug>.md" \
  --title "<Concept Name>"

python3 src/concept_guard.py validate \
  "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/<Concept Name>.md"
```

Parse guard JSON silently. Surface only pass/fail, installed path, and actionable structure errors.

For a reviewed merge, add `--allow-existing`. For a protected-note merge, add
both `--allow-existing --allow-protected` only after explicit user approval.

After writing concept cards, regenerate the domain-grouped index:

```bash
python3 src/index_builder.py Concepts
```

The builder groups by frontmatter `domain:` or `domain/<slug>` tags and uses `summary:` for the index detail line.
