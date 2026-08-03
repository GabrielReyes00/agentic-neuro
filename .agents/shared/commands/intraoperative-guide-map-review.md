# Intraoperative Guide Map Review

Run after `knowledge_map.json` is built and before prose synthesis. This is an
independent adversarial review of the operative model, not a rewrite.

## Reviewer Independence

Intermediate and complex procedures use a reviewer independent from the writer:
a separate subagent when available, otherwise a fresh-context reviewer pass
that receives only the structured handoff. Record one of:

- `map_reviewer_subagent`
- `independent_fresh_context`
- `self_review_simple_only`

Simple procedures may use the last option with a justification. Ordinary
same-context self-editing is not an independent review.

Provide the reviewer:

- title, complexity, decomposition, and Coverage Matrix;
- `knowledge_map.json`;
- `coverage_ledger.json`;
- only source-card rows supporting weak, disputed, quantitative, or high-risk
  blocks; and
- the prior compact verdict summary on later cycles.

Do not provide draft prose or bulk raw retrieval. The reviewer tests the plan.

## Approval Standard

Approve only when every applicable Coverage Matrix block gives the resident the
mental structure needed to act, recognize danger, recover, and defend the plan.
Test:

- pathology, natural history, indication, timing, contraindications, and
  alternatives;
- imaging and workup findings with the conduct change each produces;
- positioning, room, equipment, anesthesia, physiology, and monitoring;
- phase-by-phase goals, landmarks, step rationale, danger anatomy, hemostasis,
  endpoint criteria, and novice-versus-expert behavior;
- executable bail-outs, conversion/abort criteria, and equipment or exposure
  failure;
- patient modifiers, anatomy variants, prior surgery, and alternate approaches;
- postoperative surveillance, imaging, complications, and operative causality;
- outcomes/current evidence when those claims change selection or conduct; and
- source coverage, limitations, and explicit internal-only blocks.

Use the attending bank only as an applicability-filtered cross-check. Select
questions that probe the highest-risk assumptions for this procedure and record
their stable IDs. Generate independent questions when needed to test an angle
not already represented. Do not pull every “universal” question and do not
manufacture a minimum number of questions or gaps.

A blocking gap is one that could cause mis-selection, mis-execution, missed
danger, failed rescue, or indefensible reasoning. Record polish separately.
Approval is appropriate whenever no blocking gap remains—even on cycle one.

## Verdict

Write:

`data/Sessions/<Title>/verdicts/map-review-cycle-<N>.json`

```json
{
  "checkpoint": "map_review",
  "cycle": 1,
  "verdict": "MAP_APPROVED | MAP_GAPS",
  "procedure_title": "<Title>",
  "complexity": "simple | intermediate | complex",
  "reviewer_role": "map_reviewer_subagent | independent_fresh_context | self_review_simple_only",
  "self_review_justification": null,
  "bank_question_ids_checked": [],
  "fresh_attending_questions": [],
  "coverage_matrix_blocks_satisfied": 0,
  "coverage_matrix_blocks_total": 0,
  "blocking_gaps": [
    {
      "gap": "<specific missing relationship or action>",
      "rubric_block": "<block>",
      "coverage_matrix_block": "<stable block id>",
      "repair_path": "existing_context | internal_knowledge | RAG | PubMed | knowledge_map_revision",
      "suggested_query": null
    }
  ],
  "nonblocking_notes": [],
  "coverage_ledger_updates": [],
  "rationale": "<why the map is or is not ready>",
  "timestamp": "<ISO-8601>"
}
```

After writing the JSON, return only verdict, blocking gaps, repair paths,
affected block IDs, questions actually used, and rationale. Store bank IDs, not
copied bank text.

If the verdict is `MAP_GAPS`, repair the structured map and rerun this review.
Do not draft prose from an unapproved map. When the cycle budget is exhausted,
surface the unresolved gaps and attempted repairs to the user.
