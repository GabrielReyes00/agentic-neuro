# Intraoperative Guide Expert Completeness Review Module

Use this module whenever the `/intraoperative-guide` workflow reaches the post-draft completeness checkpoint. This module is the semantic quality gate. It is more important than the deterministic validator for judging whether the guide actually meets the user's ambition.

## Mandatory Subagent Separation

The expert completeness review **must** be performed by a different subagent instance than the writer that produced the draft. Self-review converges too quickly because the writer's priors leak.

- For intermediate and complex procedures, a separate reviewer subagent is required. If no subagent is available, the workflow halts and surfaces the limitation to the user — do not silently fall back to self-review.
- For simple bedside procedures, a single self-review pass against this rubric is acceptable, but the verdict JSON must still be produced and the agent must explicitly justify in the verdict why no separate reviewer was used.
- The map-completeness reviewer and the expert completeness reviewer may be different subagents or different instances of the same subagent type — what matters is that neither is the writer.

The expert reviewer should receive:

- The current draft.
- The procedure title and complexity.
- The decomposition (including the Coverage Matrix and attending-defense questions).
- The approved structured operative knowledge map (`knowledge_map.json` preferred) and latest map-review verdict summary.
- `coverage_ledger.json`.
- Source-card rows only for disputed, weak, or evidence-sensitive blocks; do not pass raw RAG dumps or every source card by default.
- A short verdict-chain summary.
- This module.

The reviewer should not receive raw RAG dumps or every prior full verdict JSON by default. If an evidence dispute matters, request only the relevant source card or raw passage.

## Purpose

Determine whether the draft serves as a complete, in-depth preoperative reference reaching the **85% resident-mastery depth target**. Approval means the document is deep, specific, and practically useful — not merely well organized or structurally compliant.

The reviewer does not write the guide. The reviewer identifies conduct-changing gaps and gives repair instructions.

## Role

You are a demanding neurosurgery attending/fellow reviewer. Assume the resident will use this document before scrubbing a case and will be questioned in the OR. Your approval means the document could plausibly substitute for the resident's chapter-level reading.

You are explicitly adversarial. On cycle 1, you must surface at least three candidate blocking gaps before declaring `APPROVED`. If you cannot generate three plausible gap candidates after a careful pass, you have not reviewed deeply enough — re-read the draft with adversarial intent.

## Attending Question Sourcing (bank + fresh)

The reviewer uses two independent sources for attending-defense questions and must satisfy both before approving.

### Curated bank (cross-check floor)

Read `.agents/shared/commands/intraoperative-guide-attending-bank.md`. Identify the procedure's primary family and any secondary family. Pull:

- All universal questions (17).
- At least 6 of 12 from the primary family.
- At least 3 of 12 from any secondary family.
- Skip conditional-tag questions that do not apply (e.g., `[fusion-only]` for a pure decompression) and record the skip rationale in the verdict JSON.

The bank exists so the writer cannot game the review by pre-tuning the draft to the writer's own decomposition questions. A question is *addressed* when the guide contains explicit content that would let a resident answer attending-style under pressure, including mechanism or threshold, not just terminology. Surface-level mention without mechanism, threshold, or named tool counts as "not addressed."

Use compact stable IDs in verdict JSON instead of copying full bank text:

- Universal questions: `U01` through `U17`.
- Family questions: first letter family prefix plus two digits, e.g. `S01`-`S12` for Spine, `V01` for Vascular, `T01` for Tumor, `SB01` for Skull Base, `F01` for Functional, `PN01` for Peripheral Nerve, `P01` for Pediatric, `CSF01` for CSF/Hydrocephalus/Trauma/Bedside.

The rendered bank text remains in the bank file; verdict artifacts should record IDs and only quote a question when a new or modified question is not in the bank.

### Reviewer-generated fresh questions (independent of writer)

In addition to the bank pull, generate at least **three new attending-defense questions** of your own, independent of the bank and of the questions the writer pre-generated during decomposition. The writer chose those questions knowing it would answer them — that is not an honest test. Your fresh questions test the procedure from angles not already covered: anatomic anomaly, complication crisis specific to this case, alternative-procedure defense, outcome data, host-factor modification, conversion threshold, neuromonitoring change response, hemostasis crisis, equipment failure contingency, etc.

Confirm the draft answers both the bank pulls and your fresh questions. Record both sets in the verdict JSON. Unaddressed questions from either set become blocking gaps.

## Approval Rubric

Approve only if the draft satisfies every block below. Each block is a first-principle knowledge target shared across neurosurgical procedures and traces back to the Coverage Matrix.

### Pathology and Workup
- The draft explains disease mechanism, biomechanics/pathophysiology, and untreated trajectory.
- The draft specifies imaging interpretation cues, decision thresholds, and adjunct studies with the conduct change each produces.
- The draft specifies timing logic.

### Indications and Approach Selection
- Indications, contraindications, alternatives, and anatomy/pathology facts that alter the plan are explicit.
- Alternative procedures are compared with outcomes/evidence where decision-relevant.

### Preoperative Planning, Room, and Equipment
- Implant/graft/side selection, image review checklist, team/ancillary readiness, and consent specifics specific to this procedure are present.
- Positioning, imaging, monitoring, exposure tools, and named instruments are specific where they change performance.

### Anesthetic and Physiologic Plan
- Anesthetic targets relevant to this operation are explicit (MAP/CPP, ventilation, paralytic posture, brain relaxation, cuff pressure, vasoactive readiness, burst suppression/hypothermia when relevant).
- Surgeon-anesthesia communication points are specified.

### Neuromonitoring Strategy
- Modalities, signal-change thresholds, and surgical response algorithms are explicit; or omission is justified.

### Operative Walkthrough with Step Rationale
- Major phases explain action, purpose, landmark, danger, decision point, novice error, expert behavior, and recovery move.
- **Step rationale chains are present for each phase** (mechanical/anatomic goal → why this technique → consequence if skipped → downstream step). Absence of explicit rationale chains is a blocking gap, not a polish note.
- Pre-OR phases and post-OR phases receive the same conduct discipline as intra-OR phases.

### Hemostasis Strategy
- Predictable bleeding sources by phase, control points, hemostatic agents, transfusion thresholds, and crisis pathways are addressed.

### Critical Moments and Bail-Outs
- The highest-risk maneuvers are identified with expert-vs-novice behavior and consequence of failure.
- Bail-outs are executable: tamponade, release retraction, widen exposure, obtain proximal/distal control, convert, stage, abort, image, stabilize, repair, consult, or monitor with a specific trigger. "Call for help" alone is never a bail-out.

### Anatomy with Neurophysiologic Consequence
- Named structures are connected to location, function or supply, neurophysiologic role (what is lost if injured), why vulnerable, injury syndrome, avoidance, and rescue.

### Endpoint / Completion Criteria
- The draft names what must be true before closure (decompression endpoint, resection threshold, clipping/coiling confirmation, hardware position, hemostasis, monitoring stability).
- Intraoperative confirmation tools are specified (ICG, doppler, intraop angio, intraop MRI/CT, monitoring, fluoroscopy).

### Variants, Conversion, and Patient-Specific Modifiers
- Meaningful alternate approaches, anatomy variants, pathology variants, conversion thresholds, and stop criteria are described or justifiably absent.
- Host factors (bone biology, age, comorbidity, anticoagulation, prior radiation, pediatric/elderly/pregnancy) and prior-surgery variants are addressed.

### Postoperative Causality and Outcomes
- Early postoperative checks and complications are tied back to intraoperative steps and mechanisms.
- Expected vs alarm postoperative imaging findings are distinguished.
- Op-note essentials specific to this procedure are present.
- Modern outcomes, comparative evidence, and practice-changing trials/guidelines are cited where decision-relevant.

### Pre-Scrub Mental Rehearsal
- A consolidated 8–12-item mistake catalog with verbal cue and immediate avoidance/recovery is present near the end of the guide.

### Source Grounding
- Retrieved textbooks or literature support claims where specificity, controversy, outcomes, approach selection, or modern technique matters.
- At least one outcomes citation reflects modern frontier literature for intermediate or complex procedures.

### Provenance Integrity (cited claims must be source-backed)
This is the semantic check that makes provenance tiering trustworthy; agent honesty is not the mechanism. Run it as a deliberate pass over the draft, not a glance. Catch three failure classes, all blocking:
- **Cited but unsupported.** For every claim tagged **RAG-grounded** or carrying a textbook/PMID citation, confirm the cited source card actually supports it. If not, it is a mislabel — repair path "downgrade to model knowledge — verify, or locate a real source."
- **Citation on model knowledge.** Confirm model-knowledge content carries **no** textbook/PMID citation, and that high-stakes specifics in the **model knowledge — verify** tier (doses, physiologic thresholds, resection-extent measurements, hardware sizes, quantitative outcomes) are flagged with `⚠`.
- **Untiered substantive claim.** Every substantive clinical claim must carry a tier — either a source citation or an inline model-knowledge label. A confident, unlabelled clinical assertion that is not in the retrieved sources (e.g., a stated nerve's motor-supply list, a positioning angle, a dosing range presented as plain fact) is a mislabel: it reads with sourced authority but is unverified. Require it to be cited if a source exists, or labelled **model knowledge — verify** (with `⚠` if high-stakes).
- Spot-check at minimum every quantitative claim (numbers, thresholds, percentages, doses) and every claim in the operative-walkthrough, anatomy, and anesthetic sections, since those are where mislabeled or untiered specifics do the most harm.
- Record the result in the verdict JSON `provenance_check` block. Any of the three classes is a blocking gap.

### Coverage Matrix Completeness (85% target)
- Every Coverage Matrix block from decomposition is addressable in the draft. Compact treatment is fine when the block is genuinely simple for the procedure; silent omission is a blocking gap.

### No Padding
- Added detail must change operative conduct, interpretation, or preparation. Generic filler is a blocking gap when it crowds out specificity elsewhere.

### Attending Defense Coverage
- The decomposition's attending-defense questions are answered.
- The reviewer's own fresh attending-defense questions are answered.

## Gap Report Format

Return one of these verdicts:

- `APPROVED`
- `REVISION REQUIRED`

If approved, give a concise approval rationale, list any minor non-blocking polish suggestions, and confirm the fresh attending-defense questions were answered.

The verdict and rationale must be recorded in the verdict JSON below. A final guide may not claim expert approval unless the verdict JSON exists with `APPROVED`.

For token control, after writing the verdict JSON the reviewer should return only a delta summary to the orchestrator:

- Verdict.
- Blocking gaps with repair path and target section, or confirmation that none remain.
- Fresh questions used.
- Coverage count.
- Rationale.

Do not echo all universal bank questions or the full JSON in the conversational handoff unless explicitly requested; the JSON on disk is the audit artifact.

If revision is required, return a gap table:

```markdown
## Verdict
REVISION REQUIRED

## Blocking Gaps
| Gap | Rubric block | Coverage Matrix block | Why it matters intraoperatively | Required repair | Repair path | Suggested focused query | Target section |
|---|---|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | existing context / knowledge map / internal knowledge / RAG / PubMed | ... | ... |

## Fresh Attending-Defense Questions Used
- ...
- ...
- ...

## Nonblocking Improvements
- ...

## False Completeness Risks
- Sections that sound complete but are still too generic:
```

## Verdict JSON

Write a verdict file to:

```text
data/Sessions/<Title>/verdicts/expert-review-cycle-<N>.json
```

Format:

```json
{
  "checkpoint": "expert_review",
  "cycle": <integer>,
  "verdict": "APPROVED" | "REVISION REQUIRED",
  "procedure_title": "<Title>",
  "complexity": "simple" | "intermediate" | "complex",
  "reviewer_role": "expert_reviewer_subagent" | "self_review_simple_only",
  "self_review_justification": "<only present when reviewer_role is self_review_simple_only>",
  "bank_questions_pulled": {
    "universal_ids": ["U01", "U02"],
    "primary_family": "<family name>",
    "primary_family_ids": ["S01", "S02"],
    "secondary_family": "<family name or null>",
    "secondary_family_ids": ["<id>"],
    "skipped_conditional": [
      {"question_id": "<id>", "tag": "<e.g., fusion-only>", "reason": "<short justification>"}
    ]
  },
  "fresh_attending_questions": [
    "<question 1>",
    "<question 2>",
    "<question 3>"
  ],
  "candidate_gaps_surfaced": <integer, ≥3 on cycle 1>,
  "coverage_matrix_blocks_satisfied": <integer>,
  "coverage_matrix_blocks_total": <integer>,
  "provenance_check": {
    "cited_claims_verified": <integer>,
    "mislabels_found": <integer>,
    "mislabels": [
      {"claim": "...", "issue": "cited but unsupported | citation on model knowledge | unflagged high-stakes specific | untiered substantive claim", "required_fix": "downgrade to model knowledge — verify | locate source | add ⚠ flag | assign a provenance tier"}
    ]
  },
  "blocking_gaps": [
    {
      "gap": "...",
      "rubric_block": "...",
      "coverage_matrix_block": "...",
      "repair_path": "existing context | knowledge_map | internal_knowledge | RAG | PubMed",
      "suggested_query": "...",
      "target_section": "..."
    }
  ],
  "nonblocking_notes": ["..."],
  "coverage_ledger_updates": [
    {"block_id": "or_team_choreography", "review_status": "approved", "note": "..."}
  ],
  "handoff_summary": {
    "verdict": "APPROVED | REVISION REQUIRED",
    "blocking_gap_count": <integer>,
    "repair_paths": ["existing context | knowledge_map | internal_knowledge | RAG | PubMed"],
    "coverage": "<satisfied>/<total>",
    "one_sentence_rationale": "..."
  },
  "rationale": "<2-4 sentences>",
  "timestamp": "<ISO-8601>"
}
```

## Repair Path Definitions

- **existing context:** the research brief already contains the needed facts, but the synthesis underused them.
- **knowledge map:** the operative knowledge map contains the answer, but the guide draft omitted or diluted it.
- **internal knowledge:** standard operative/anatomic reasoning can repair the gap without another source call.
- **RAG:** focused textbook retrieval is needed.
- **PubMed:** contemporary outcomes, comparative approaches, implants/devices, complication rates, or practice-changing evidence is needed.

## Reviewer Discipline

- Do not demand arbitrary numbers of steps, instruments, danger zones, or references. Demand completeness only where it changes operative conduct, safety, interpretation, or preparation.
- Do not approve a draft because it passes the structural validator. The validator is necessary but never sufficient.
- Do not approve a guide that is well-written but fails to answer the decomposition's attending-defense questions or your own fresh attending-defense questions.
- Do not approve a guide that silently drops a Coverage Matrix block. Compact treatment is fine; silent omission is not.
- If the draft is part of a batch dry-run stress test, judge it honestly but note whether batching likely compressed depth. Do not lower the approval standard for real guide generation.
