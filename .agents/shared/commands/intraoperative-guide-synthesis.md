# Intraoperative Guide Synthesis Module

Use this module when the main `/intraoperative-guide` workflow has structured source cards, a coverage ledger, and an approved operative knowledge map (`MAP_APPROVED` verdict) and must draft or revise the operative guide.

## Purpose

Transform the approved operative knowledge map, coverage ledger, compact source cards, expert knowledge, and gap-repair notes into a coherent standalone operative reference. This module writes the guide draft, but the draft is not final until it passes the expert completeness review (separate subagent) and deterministic validation.

## Depth Target: 85% Resident Mastery

The guide must contain enough material that a neurosurgery resident studying *only* this document achieves roughly **85% of the deep understanding** needed to perform and defend this procedure. The remaining 15% comes from hands-on cadaver/OR exposure and procedure-specific atlas figures.

This target is operationalized by the Coverage Matrix from decomposition. Every Coverage Matrix block must be addressable in the final draft. Sections may be compact when a block is genuinely simple for this procedure (e.g., neuromonitoring for an EVD), but no block may be silently dropped — compact treatment is fine, omission is not.

## Role

You are a senior neurosurgical fellow writing for a resident preparing to perform and defend the operation. Write with operative consequence, not encyclopedic trivia. The resident should be able to mentally rehearse the case, answer attending questions, recognize danger, and execute bail-outs.

Do not draft directly from raw RAG. Draft from `knowledge_map.json`, `coverage_ledger.json`, and the source-card rows referenced by those map blocks so the final guide reflects a complete procedure model rather than a stitched source summary.

## Structured Handoff Discipline

Use the structured artifacts as pointers:

- Expand `knowledge_map.json` block-by-block into readable prose.
- Use `coverage_ledger.json` as the checklist that every Coverage Matrix block appears in the draft.
- Pull source-card details only where a section needs numbers, controversy, anatomy-risk specificity, or citation support.
- Do not restate source-card takeaways mechanically. The guide is the synthesis layer, not a card dump.

## Drafting Standard

For every operative phase (pre-OR, intra-OR, and post-OR), include:

- Purpose of the phase.
- Landmarks that prove correct location or trajectory (intra-OR) or correct decision (pre-/post-OR).
- Structures at risk and why they are vulnerable.
- Technical decision points.
- Novice errors.
- Expert behavior.
- Recovery move if the step goes wrong.
- **Step rationale chain**: mechanical or anatomic goal → why this technique vs alternatives → consequence if skipped → downstream step it enables. This is the *WHY* layer and must be explicit, not implied.

For anatomy, expand only when it changes operative conduct. Anatomy expansion should connect location, blood supply or function, plane/corridor relationship, neurophysiologic role (what is lost if injured), injury syndrome, and avoidance or rescue.

For equipment, name items when the name changes what the resident asks for, prepares, recognizes, or uses. Do not pad with generic instrument lists.

For pitfalls and complications, use mechanism chains:

```text
operative step -> failure mechanism -> early recognition -> immediate action -> postoperative signature
```

## Required Guide Domains (Coverage Matrix mapping)

The final guide may use procedure-specific section headings, but every Coverage Matrix block from decomposition must be addressable in the draft. The reviewer will check coverage independent of heading text.

First-principle knowledge blocks shared across all neurosurgical procedures:

1. **Operative Mental Model** — short framing for intermediate/complex procedures; a `> [!tip] Operative Mental Model` callout is welcome.
2. **Pathology and Natural History** — disease mechanism, biomechanics or pathophysiology, untreated trajectory, when natural history forces surgery.
3. **Workup and Surgical Decision-Making** — imaging sequences/planes/findings with decision thresholds, adjunct studies (EMG/NCV, CTA/DSA, CT myelogram, dynamic films, perfusion, fMRI/DTI, neuropsych), timing logic.
4. **Indications, Contraindications, and Approach Selection** — alternative procedures compared with outcomes when relevant.
5. **Preoperative Planning** — implant/graft/side selection, image checklist, team and ancillary readiness, consent specifics.
6. **Room, Positioning, and Equipment Setup**.
7. **Anesthetic and Physiologic Plan** — MAP/CPP, ventilation, paralytic posture (monitoring compatibility), brain relaxation, cuff pressure, vasoactive readiness, surgeon-anesthesia communication points.
8. **Neuromonitoring Strategy** — modalities, signal-change thresholds, surgical response algorithms; or explicit justification when omitted.
9. **Step-by-Step Operative Walkthrough with Step Rationale** — every phase carries its rationale chain.
10. **Hemostasis Strategy** — phase-by-phase bleeding sources, control points, hemostatic tools, transfusion thresholds.
11. **Critical Moments**.
12. **Surgical Anatomy with Neurophysiologic Consequence**.
13. **Pitfalls and Fail-Safe Plans** — mechanism-linked, executable bail-outs.
14. **Endpoint / Completion Criteria** — what must be true before closure; intraoperative confirmation tools (ICG, doppler, intraop angio, intraop MRI/CT, monitoring stability, fluoroscopy).
15. **Variants and Intraoperative Decision Branches** — including conversion, staging, and abort criteria.
16. **Closure and Immediate Postoperative Management** — op-note essentials specific to this procedure.
17. **Complications and Signatures** — postop imaging interpretation (expected vs alarm), causal chain back to operative step.
18. **Outcomes and Evidence** — modern outcomes, comparative effectiveness, effect sizes, practice-changing trials/guidelines.
19. **Patient-Specific Modifiers** — host factors, anatomic variants, prior-surgery, pediatric/elderly/pregnancy.
20. **OR Team Choreography** — closed-loop communication points (compact when not conduct-critical).
21. **Pre-Scrub Mental Rehearsal** — consolidated 8–12 highest-yield mistakes with verbal cue and immediate avoidance/recovery, placed near the end of the guide.
22. **Mastery Objectives** — 5–10 testable, action-verb objectives.
23. **Related in This Vault** — only verified wikilinks.

Section organization may collapse adjacent blocks under one heading where readability benefits (e.g., "Workup and Approach Selection" combining 3 + 4), but the underlying knowledge must be present and the reviewer will check it block by block.

## Visual Reasoning (encouraged where it deepens rehearsal)

Mermaid diagrams are encouraged for material that is spatially or causally hard to convey in prose:

- Approach-selection decision trees.
- Failure-mode causality flows.
- Anatomic corridor schematics (compact).
- Hemostasis crisis algorithms.

Do not force a diagram when prose is clearer. If figures from a textbook would help mental rehearsal, include a short `## Reference Figures` subsection pointing to specific atlas/textbook figure numbers and pages so the resident knows what visuals to study alongside the guide. Visual reasoning is welcomed but not yet mandated — text completeness remains the priority until the workflow is fully calibrated.

## Readability and Obsidian Formatting

These guides are long. Make them inviting to read without making them decorative. Use Obsidian-native structure to help rehearsal:

- Start with the sanctioned RAG callout if RAG was used.
- For intermediate or complex procedures, include an early `## Operative Mental Model` section. A `> [!tip] Operative Mental Model` callout is appropriate when the model compresses into a memorable frame.
- Use `> [!warning] Critical Safety Point` callouts for wrong-level risk, airway risk, major vascular risk, cranial nerve risk, spinal cord risk, or other points that should interrupt the reader's attention.
- Use `> [!danger] Bail-Out` callouts for actionable rescue plans. Concise, executable, mechanism-linked.
- Use compact tables for approach-selection comparisons, complication signatures, or failure-mode causality when a table is clearer than prose.
- Keep prose as the main medium. Do not over-table, over-callout, add emoji, add ornamental dividers, or use decorative wording.
- Use short, descriptive subheadings within long sections so the guide can be scanned before an operation.

## Source Use

RAG and literature support should appear where they add specificity: pathology mechanism, workup thresholds, operative sequence, anatomy, approach comparison, complication signatures, technique variants, outcomes, implants, and controversial decisions. Do not cite every sentence.

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
- Update the operative knowledge map first if the gap reflects a missing concept, relationship, or failure mode rather than only weak wording — then return through map-review before re-drafting.
- Prefer targeted additions in the relevant section over appending a catch-all paragraph.
- Remove generic filler discovered by the reviewer.
- Preserve the guide as a coherent reference rather than a stitched sequence of answers.
- If a gap cannot be resolved from available sources, add best expert synthesis with appropriate uncertainty and flag the source limitation in the final user summary, not as an excuse inside the guide.
