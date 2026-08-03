# Intraoperative Guide Synthesis

Draft the guide only after `knowledge_map.json` has `MAP_APPROVED`. Use the map,
coverage ledger, referenced source cards, and repair notes. The draft is not final
until independent expert review and deterministic validation pass.

## Readiness Standard

Write a standalone reference that lets a resident plan, mentally execute,
recognize danger, recover, and defend the procedure while naming what still
requires supervised OR, cadaver, atlas, or point-of-care confirmation. Never use
a numerical mastery estimate.

Every applicable Coverage Matrix block must be findable in the draft, but section
headings are procedure-specific and adjacent blocks may be combined. Compact
treatment is acceptable for a genuinely simple block; silent omission is not.

## Draft From Relationships

Expand `knowledge_map.json` rather than copying source cards. For each important
operative phase, preserve:

```text
objective → landmark → action → rationale/alternative → danger → recognition →
avoidance or rescue → endpoint → downstream step or postoperative signature
```

Anatomy belongs when it changes conduct: where encountered, functional or
vascular role, why vulnerable, injury syndrome, and avoidance/rescue. Equipment
belongs when its identity changes what the resident must request, prepare, or do.
Pitfalls use the causal chain:

```text
operative step → failure mechanism → early recognition → immediate action →
escalation/abort → postoperative signature
```

## Content Families

Use the Coverage Matrix to shape the guide. Applicable content ordinarily falls
into these families, which may be combined or renamed:

- disease mechanism, natural history, workup, imaging, indications,
  contraindications, timing, alternatives, and approach selection;
- patient-specific planning, consent, positioning, room/equipment, anesthesia,
  physiology, monitoring, hemostasis, and team choreography;
- phase-by-phase operative walkthrough with landmarks, step rationale, critical
  moments, variants, and conversion/abort decisions;
- anatomy-risk and neurophysiologic consequences;
- pitfalls, bail-outs, completion criteria, confirmation tools, closure, and
  procedure-specific op-note essentials;
- immediate postoperative management, expected-versus-alarm findings,
  complications, surveillance, outcomes, and evidence limits.

Intermediate and complex guides should open with a compact `## Operative Mental
Model` and include `## Pre-Scrub Mental Rehearsal` near the end: only the
highest-value errors, each with a recognition or verbal cue and immediate
avoidance/recovery. Every guide ends with testable `## Mastery Objectives` and
`## Related in This Vault`; neither section has a numerical quota.

## Visual And Obsidian Use

Use Mermaid only when a decision tree, spatial corridor, or failure pathway is
clearer than prose. Point to specific atlas/textbook figures when external visual
study is necessary. Use warning/danger callouts sparingly for true safety points
and executable bail-outs; avoid decorative dividers, card grids, emoji, or table
overuse.

No H1. Begin with native frontmatter carrying canonical domain, summary,
provenance, complexity, `internal_knowledge_used`, and current/incomplete status. Keep
workflow scaffolding and Anki routing out of the note. Use verified wikilinks
only, following `intraoperative-guide-crosslinks.md`.

## Provenance

Draft from source-card pointers and use exact locators where claims need support.
If RAG was used, place immediately before the first H2:

```markdown
> [!info] RAG Supplemented
> Textbook retrieval was used to ground operative sequence, anatomy, equipment, pitfalls, and bail-outs.
```

Apply provenance at the claim:

- **RAG-grounded:** cite the retrieved source card's exact textbook/page or PMID.
- **Model knowledge — verified:** cite the confirming source found during repair.
- **Model knowledge — verify:** label unsourced synthesis and mark conduct-changing
  doses, physiologic targets, dimensions, hardware specifics, or outcome numbers
  `⚠ verify`.

Never attach a citation to unsupported model content. Provenance labels do not
excuse thin rationale, rescue, or complication logic. Name attending/site
variation and preserve the universal principle rather than asserting a local
preference as standard.

## Revision

After expert review, repair each named gap in its natural section. Revise and
rereview the knowledge map first when the gap is conceptual, relational, or a
missing failure mode. Prefer targeted integration over a catch-all appendix;
remove filler and keep the guide coherent. If support remains unavailable,
preserve the explicit uncertainty and route final status through the incomplete
artifact policy rather than implying completion.
