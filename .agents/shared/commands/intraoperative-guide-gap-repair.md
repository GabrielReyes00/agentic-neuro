# Intraoperative Guide Gap Repair Module

Use this module after expert review returns `REVISION REQUIRED`.

## Purpose

Convert the expert reviewer's gap table into targeted research and revision actions without restarting the whole workflow or bloating context.

## Role

You are the gap-repair lead. Your job is to close blocking gaps efficiently and preserve guide coherence.

## Gap Triage

For each blocking gap, follow the repair path assigned by the reviewer:

- **existing context:** revisit the research brief and revise the relevant section.
- **knowledge map:** revise the guide from the already-reviewed map; if the map itself is incomplete, update it first.
- **internal knowledge:** add expert synthesis using operative/anatomic reasoning. Keep it concrete and consequence-linked.
- **RAG:** run one focused serial `lance_retriever.py compare` query for that gap. Use `--no-frontier` for classic anatomy/technique unless modern literature matters.
- **PubMed:** use literature search only when contemporary evidence, outcomes, approach comparisons, implants/devices, complication rates, or guidelines are necessary.

If several gaps share the same knowledge target, combine them into one focused query. Do not run a new query for every sentence-level issue.

## Repair Output

Before revising the guide, make a concise repair memo:

```markdown
## Gap Repair Memo
- Gap:
  - Repair path used:
  - New information added:
  - Source support:
  - Target section:
```

The memo is for workflow control and should not be included in the final guide.

Append the repair memo to the workflow ledger. If a blocking gap is repaired using internal knowledge rather than additional retrieval, state why another source query was not needed. If source support is needed and unavailable, the guide cannot be finalized as complete without surfacing that limitation.

## Revision Rules

- Repair the relevant section directly; do not append disconnected addenda.
- Update the operative knowledge map first when the gap reflects missing structure rather than wording.
- Turn vague cautions into mechanism-linked instructions.
- Turn non-executable bail-outs into actionable sequences.
- Tie postoperative signatures to operative causes.
- Add source citations where new retrieved material supports a specific claim.
- Remove generic filler if new information makes it redundant.

After revision, return to `.agents/shared/commands/intraoperative-guide-review.md` for another expert completeness review.
