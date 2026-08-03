# Intraoperative Guide Expert Review

Run after guide synthesis and after every repair cycle. This is the semantic and
provenance gate; structural validation cannot replace it.

## Reviewer Independence

Intermediate and complex guides use a reviewer independent from the writer: a
separate subagent when available or a fresh-context independent pass with a
bounded handoff. Record `expert_reviewer_subagent`,
`independent_fresh_context`, or `self_review_simple_only`. Simple procedures may
use rubric-driven self-review with justification.

Provide the current draft, decomposition/Coverage Matrix, approved knowledge
map, coverage ledger, latest verdict summary, and only the source cards needed
for source-sensitive checks. Do not preload raw RAG dumps or every prior verdict.

## Approval Standard

Approval means the guide meets the standalone preoperative readiness standard,
not merely that it is long or organized. Review each applicable block:

### Selection And Planning

- pathology, natural history, indication, timing, contraindications, and
  alternatives are causally connected;
- imaging/workup findings state how they change the plan;
- approach selection and patient/anatomic modifiers are defensible;
- consent and outcomes claims match the actual population and evidence.

### Room, Physiology, And Monitoring

- positioning, imaging, equipment, implants/grafts, team readiness, and time-out
  details are procedure-specific where they change conduct;
- anesthetic/physiologic targets and surgeon-anesthesia communication are
  explicit where relevant;
- monitoring modalities, warning patterns, and response algorithms are given,
  or omission is justified.

### Operative Execution

- each major phase states goal, maneuver, landmark, rationale, danger,
  consequence if wrong, recovery, and endpoint;
- anatomy connects location and neurophysiologic role to vulnerability, injury
  signature, avoidance, and rescue;
- hemostasis identifies likely sources, control points, agents, and crisis
  sequence;
- critical moments distinguish novice error from expert conduct;
- bail-outs are executable and include what to do while help arrives;
- completion criteria and confirmation tools are explicit before closure.

### Variants And Postoperative Causality

- variants, alternate approaches, conversion/abort thresholds, prior surgery,
  and host factors are addressed when applicable;
- immediate exam, imaging, orders, and alarm findings connect back to operative
  mechanism;
- outcomes and current evidence are included when they alter selection,
  technique, counseling, or surveillance;
- Pre-Scrub Mental Rehearsal captures the highest-value errors without a fixed
  item quota.

### Provenance Integrity

Check every quantitative, conduct-changing, cited, and wording-sensitive claim:

1. A source citation actually supports the entity, population, intervention,
   number, and limitation claimed.
2. Model knowledge is not decorated with a nearby source citation.
3. Unverified high-stakes specifics are labeled `model knowledge — verify` and
   `⚠ verify`.
4. Current evidence is present when outcomes, devices, guidelines, timing, or
   comparative strategy can change conduct. Anatomy-dominant content does not
   require a token “current outcomes” citation merely because the guide is
   complex.

Any provenance mislabel is blocking.

### Coverage And Attending Defense

Every applicable Coverage Matrix block must be satisfied or reasoned as not
applicable. Use procedure-family bank questions selectively by applicability and
stable ID. Generate fresh questions only where they probe a meaningful angle not
already tested. An unanswered applicable question becomes a gap; reviewers must
not manufacture a quota of questions or candidate defects.

## Verdict And Gap Quality

Return `APPROVED` when no blocking gap remains. Return `REVISION REQUIRED` for a
specific defect that could change selection, conduct, safety, rescue,
interpretation, provenance, or attending defense. Do not block on cosmetic
preference or demand arbitrary numbers of steps, citations, instruments, gaps,
or questions.

Every blocking gap names:

- the exact missing or unsupported content;
- Coverage Matrix/rubric block;
- clinical or operative consequence;
- target section;
- repair path; and
- focused query only when new evidence is actually needed.

## Verdict JSON

Write:

`data/Sessions/<Title>/verdicts/expert-review-cycle-<N>.json`

```json
{
  "checkpoint": "expert_review",
  "cycle": 1,
  "verdict": "APPROVED | REVISION REQUIRED",
  "procedure_title": "<Title>",
  "complexity": "simple | intermediate | complex",
  "reviewer_role": "expert_reviewer_subagent | independent_fresh_context | self_review_simple_only",
  "self_review_justification": null,
  "bank_questions_pulled": {
    "primary_family": null,
    "primary_family_ids": [],
    "secondary_family": null,
    "secondary_family_ids": [],
    "skipped_conditional": []
  },
  "fresh_attending_questions": [],
  "coverage_matrix_blocks_satisfied": 0,
  "coverage_matrix_blocks_total": 0,
  "provenance_check": {
    "claims_checked": 0,
    "mislabels_found": 0,
    "mislabels": []
  },
  "blocking_gaps": [
    {
      "gap": "<specific defect>",
      "rubric_block": "<block>",
      "coverage_matrix_block": "<stable block id>",
      "clinical_consequence": "<why it matters>",
      "repair_path": "existing_context | knowledge_map | internal_knowledge | RAG | PubMed",
      "suggested_query": null,
      "target_section": "<section>"
    }
  ],
  "nonblocking_notes": [],
  "coverage_ledger_updates": [],
  "handoff_summary": {
    "blocking_gap_count": 0,
    "repair_paths": [],
    "coverage": "<satisfied>/<total>",
    "one_sentence_rationale": "<summary>"
  },
  "rationale": "<why approved or what must change>",
  "timestamp": "<ISO-8601>"
}
```

After writing the JSON, return only verdict, blocking gaps, repair paths,
questions actually used, coverage, and rationale. The full JSON is the audit
trail.

## Repair Paths

- `existing_context`: source layer already contains the answer.
- `knowledge_map`: approved map contains the answer but synthesis diluted it.
- `internal_knowledge`: standard operative reasoning can repair it without a
  new citation; preserve verify-tier boundaries.
- `RAG`: focused textbook retrieval is needed.
- `PubMed`: current outcomes, devices, comparative strategy, or guidance is
  needed.

If approved, proceed to finalization. If revision is required, route only named
gaps through `intraoperative-guide-gap-repair.md` and rerun review.
