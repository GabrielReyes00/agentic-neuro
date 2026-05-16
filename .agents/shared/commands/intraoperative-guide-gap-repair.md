# Intraoperative Guide Gap Repair Module

Use this module after expert review returns `REVISION REQUIRED`.

## Purpose

Convert the expert reviewer's gap table into targeted research and revision actions without restarting the whole workflow or bloating context.

## Role

You are the gap-repair lead. Your job is to close blocking gaps efficiently and preserve guide coherence.

## Cycle Budget by Complexity

Each complexity tier has a finite cycle budget. The cycle count includes the first expert review cycle that produced `REVISION REQUIRED`.

- **Simple procedure:** maximum 2 expert review cycles total.
- **Intermediate procedure:** maximum 3 expert review cycles total.
- **Complex procedure:** maximum 5 expert review cycles total.

If the budget is exhausted and the draft still has `REVISION REQUIRED`, escalate to the user with the unresolved gaps surfaced verbatim. Do not write a known-incomplete real guide with a disclaimer.

## Escalation Ladder

The escalation ladder forces the workflow to broaden source recruitment when repeated repairs fail to close the same gap class.

- **Cycle 1 → 2:** repair using the reviewer-assigned path (existing context, knowledge map, internal knowledge, RAG, or PubMed). No automatic escalation required.
- **Cycle 2 → 3:** if any blocking gap repeats from the prior cycle, at least one **PubMed query** is mandatory for that gap, even if not the originally-assigned path. The reviewer's prior repair path was not enough.
- **Cycle 3 → 4 (complex procedures only):** if any blocking gap repeats again, the operative knowledge map must be revised first, then the guide is re-drafted from the revised map. Map-completeness review is rerun before re-drafting if the map changes substantially.
- **Cycle 4 → 5 (complex procedures only):** if any blocking gap still repeats, escalate to user. Surface the unresolved gap, the repair paths attempted, and what was learned. Ask whether to (a) ship with explicit gap labeling in the user-facing summary, (b) defer until a new source becomes available, or (c) abort the guide.

A repeating gap is one whose `rubric_block` and `coverage_matrix_block` match a prior cycle's blocking gap, regardless of textual rewording.

## Gap Triage

For each blocking gap, follow the repair path assigned by the reviewer (subject to the escalation ladder):

- **existing context:** revisit the research brief and revise the relevant section.
- **knowledge map:** revise the guide from the already-approved map; if the map itself is incomplete, update it first and rerun map-completeness review before re-drafting.
- **internal knowledge:** add expert synthesis using operative/anatomic reasoning. Keep it concrete and consequence-linked.
- **RAG:** run one focused serial `lance_retriever.py compare` query for that gap. Use `--no-frontier` for classic anatomy/technique unless modern literature matters.
- **PubMed:** use literature search when contemporary evidence, outcomes, approach comparisons, implants/devices, complication rates, or guidelines are necessary, and whenever the escalation ladder mandates it.

If several gaps share the same knowledge target, combine them into one focused query. Do not run a new query for every sentence-level issue.

## Retrieval Economy

Additional retrieval is allowed only when one of these is true:

- A blocking gap has repair path `RAG` or `PubMed`.
- The escalation ladder mandates PubMed because a gap repeated.
- Existing source cards contain a contradiction or uncertainty that affects conduct.

Before running a new query, check whether the compact source cards or research brief already contain the needed fact. If they do, repair from existing context. If a new query is needed, compress it immediately into a new source card section named `Gap Repair Q<N>` and pass forward only that card, not the raw retrieval dump.

## Repair Output

Before revising the guide, write a repair memo:

```markdown
## Gap Repair Memo (cycle N)
- Gap:
  - Rubric block:
  - Coverage Matrix block:
  - Repair path used:
  - Escalation rule triggered: yes/no (which rule)
  - New information added:
  - Source support:
  - Target section:
```

The memo is for workflow control and should not be included in the final guide.

Keep the repair memo compact. Target 60-120 words per blocking gap. The verdict JSON is the durable audit; the memo should support the next edit, not restate the whole review.

Append the repair memo to the workflow ledger. If a blocking gap is repaired using internal knowledge rather than additional retrieval, state why another source query was not needed. If source support is needed and unavailable, the guide cannot be finalized as complete without surfacing that limitation.

## Verdict JSON

Write a gap-repair verdict file to:

```text
data/Sessions/<Title>/verdicts/gap-repair-cycle-<N>.json
```

Format:

```json
{
  "checkpoint": "gap_repair",
  "cycle": <integer>,
  "procedure_title": "<Title>",
  "complexity": "simple" | "intermediate" | "complex",
  "gaps_addressed": [
    {
      "gap": "...",
      "rubric_block": "...",
      "coverage_matrix_block": "...",
      "repair_path_used": "existing context | knowledge_map | internal_knowledge | RAG | PubMed",
      "is_repeating_gap": true | false,
      "escalation_rule_triggered": "<rule id or 'none'>",
      "new_query_run": "<verbatim query or null>",
      "source_support_added": "<short description or 'none'>",
      "target_section": "..."
    }
  ],
  "map_revision_required": true | false,
  "map_review_rerun": true | false,
  "user_escalation_required": true | false,
  "user_escalation_reason": "<only present when user_escalation_required is true>",
  "timestamp": "<ISO-8601>"
}
```

## Revision Rules

- Repair the relevant section directly; do not append disconnected addenda.
- Update the operative knowledge map first when the gap reflects missing structure rather than wording, then re-run map-completeness review before re-drafting.
- Turn vague cautions into mechanism-linked instructions.
- Turn non-executable bail-outs into actionable sequences.
- Tie postoperative signatures to operative causes.
- Add source citations where new retrieved material supports a specific claim.
- Remove generic filler if new information makes it redundant.

After revision, return to `.agents/shared/commands/intraoperative-guide-review.md` for another expert completeness review (separate subagent).
