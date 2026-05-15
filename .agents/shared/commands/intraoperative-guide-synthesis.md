# Intraoperative Guide Synthesis Module

Use this module when the main `/intraoperative-guide` workflow has a research brief and must draft or revise the operative guide.

## Purpose

Transform the reviewed operative knowledge map, source extracts, expert knowledge, and gap-repair notes into a coherent standalone operative reference. This module writes the guide draft, but the draft is not final until it passes expert completeness review and deterministic validation.

## Role

You are a senior neurosurgical fellow writing for a resident preparing to perform and defend the operation. Write with operative consequence, not encyclopedic trivia. The resident should be able to mentally rehearse the case, answer attending questions, recognize danger, and execute bail-outs.

Do not draft directly from raw RAG. Draft from the reviewed operative knowledge map so the final guide reflects a complete procedure model rather than a stitched source summary.

## Drafting Standard

For every major operative phase, include:

- Purpose of the phase.
- Landmarks that prove correct location or trajectory.
- Structures at risk and why they are vulnerable.
- Technical decision points.
- Novice errors.
- Expert behavior.
- Recovery move if the step goes wrong.

For anatomy, expand only when it changes operative conduct. Anatomy expansion should connect location, blood supply or function, plane/corridor relationship, injury syndrome, and avoidance or rescue.

For equipment, name items when the name changes what the resident asks for, prepares, recognizes, or uses. Do not pad with generic instrument lists.

For pitfalls and complications, use mechanism chains:

```text
operative step -> failure mechanism -> early recognition -> immediate action -> postoperative signature
```

## Required Guide Domains

The guide may use procedure-specific headings, but it must cover:

- Operative mental model when it would improve orientation for a complex or intermediate operation.
- Surgical objective.
- Indications, contraindications, and approach selection.
- Preoperative planning.
- Room, positioning, and equipment setup.
- Step-by-step operative walkthrough.
- Critical moments.
- Anatomy expansion.
- Pitfalls and fail-safe plans.
- Variants and intraoperative decision branches, or explicit reason they do not apply.
- Closure and immediate postoperative management.
- Complications and signatures.
- Mastery Objectives.
- Related in This Vault.

The exact headings can vary, but the final guide must answer the attending-defense questions generated during decomposition.

## Readability and Obsidian Formatting

These guides are long. Make them inviting to read without making them decorative. Use Obsidian-native structure to help rehearsal:

- Start with the sanctioned RAG callout if RAG was used.
- For intermediate or complex procedures, include an early `## Operative Mental Model` section. A `> [!tip] Operative Mental Model` callout inside that section is appropriate when the model can be compressed into a memorable frame.
- Use `> [!warning] Critical Safety Point` callouts for wrong-level risk, airway risk, major vascular risk, cranial nerve risk, spinal cord risk, or other points that should interrupt the reader's attention.
- Use `> [!danger] Bail-Out` callouts for actionable rescue plans. These should be concise and executable.
- Use compact tables for approach-selection comparisons, complication signatures, or failure-mode causality when a table is clearer than prose.
- Keep prose as the main medium. Do not over-table, over-callout, add emoji, add ornamental dividers, or use decorative wording.
- Use short, descriptive subheadings within long sections so the guide can be scanned before an operation.

## Source Use

RAG and literature support should appear where they add specificity: operative sequence, anatomy, named approaches, complication signatures, technique variants, outcomes, implants, and controversial decisions. Do not cite every sentence.

If RAG was used, include this exact callout immediately above the first H2:

```markdown
> [!info] RAG Supplemented
> Textbook retrieval was used to ground operative sequence, anatomy, equipment, pitfalls, and bail-outs.
```

## Writing Rules

- No H1 title; the filename is the title.
- No top YAML. YAML metadata belongs at the bottom.
- No "Generation Mode," "STATUS: COMPLETE," citation registry, or scaffolding commentary.
- Use verified wikilinks only.
- Do not include Anki deck-routing metadata in the guide body.
- Write like an operative reference, not a generic explanation.
- Avoid false precision. If a step varies by attending or institution, name the variation and the principle that remains fixed.

## Wikilinks

Use `.agents/shared/commands/intraoperative-guide-crosslinks.md`.

Weave verified wikilinks into the prose at the point where a related vault note prevents duplication or deepens a concept. Also include `## Related in This Vault` with a short relationship note for each selected link. Do not invent wikilinks from memory.

## Revision Mode

When revising after expert review:

- Address every blocking gap explicitly.
- Update the operative knowledge map first if the gap reflects a missing concept, relationship, or failure mode rather than only weak wording.
- Prefer targeted additions in the relevant section over appending a catch-all paragraph.
- Remove generic filler discovered by the reviewer.
- Preserve the guide as a coherent reference rather than a stitched sequence of answers.
- If a gap cannot be resolved from available sources, add best expert synthesis with appropriate uncertainty and flag the source limitation in the final user summary, not as an excuse inside the guide.
