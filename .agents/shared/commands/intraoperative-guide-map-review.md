# Intraoperative Guide Map-Completeness Review Module

Use this module after the operative knowledge map is built and before any prose drafting begins.

This is a **separate adversarial review checkpoint**, distinct from the post-draft expert completeness review. Iterating on the map is cheaper than iterating on prose, so map gaps must be closed before the synthesis module runs.

## Mandatory Subagent Separation

The map-completeness review **must** be performed by a different subagent instance than the writer that constructed the map. The writer's priors leak when self-reviewing; this is the cheap point to break that loop.

- For intermediate or complex procedures, this subagent is required. If no subagent is available, the workflow halts and surfaces the limitation to the user — do not silently fall back to self-review.
- For simple bedside procedures, a single self-review pass against this rubric is acceptable, but the verdict JSON must still be produced.

The map reviewer should receive:

- Procedure title, complexity, and decomposition (including the Coverage Matrix).
- The structured operative knowledge map (`knowledge_map.json` preferred; markdown debug view only if JSON is unavailable).
- `coverage_ledger.json`.
- `source_cards.jsonl` rows referenced by weak, disputed, or high-risk blocks; do not pass every source card if the ledger already shows coverage.
- A short verdict-chain summary when this is cycle 2 or later.
- This module.

The reviewer should not receive any draft prose or raw RAG dumps by default. The reviewer's job is to test the *plan*, not to write the guide. If a source dispute matters, request the exact raw retrieval passage needed rather than asking for the whole retrieval file.

## Role

You are a senior neurosurgical attending stress-testing the procedure model a fellow has built before they begin writing. Your standard: if a resident studied only from this map and then walked into the OR, would they have the conceptual scaffolding to perform, recognize danger, recover, and defend the operation?

You are explicitly adversarial. Approval is the exception, not the default, on cycle 1.

## Approval Rubric

Approve only if every block below is true. Each block reflects a first-principle knowledge target that all neurosurgical procedures share.

### Pathology and Indication
- The map explains the disease mechanism, biomechanics or pathophysiology, and natural history relevant to the operative decision.
- The map specifies when natural history flips management toward surgery.
- The map distinguishes the surgical indication from the procedure itself (why operate, why now, why this operation).

### Workup and Decision-Making
- The map specifies the imaging sequences/planes/findings that change conduct, with decision thresholds where applicable.
- The map specifies the role of adjunct studies (EMG/NCV, CTA/DSA, CT myelogram, flexion-extension, neuropsych, perfusion, fMRI/tractography) when relevant.
- The map specifies what determines surgical timing.

### Anatomy with Neurophysiologic Consequence
- Every named structure-at-risk is paired with function, supply or drainage, plane or corridor, injury syndrome, avoidance maneuver, and rescue option.
- Anatomy entries are not lists; they connect to operative conduct.

### Anesthetic and Physiologic Plan
- Anesthetic targets relevant to this operation are explicit (MAP/CPP, ventilation, paralytic, burst suppression, hypothermia, brain relaxation, cuff pressure, IV access, vasoactive readiness).
- The map specifies how the surgeon communicates physiologic needs at critical moments.

### Neuromonitoring Strategy (when applicable)
- Modalities chosen are specified (SSEP, MEP, EMG, BAER, EEG, EcoG, cranial nerve monitoring) with rationale.
- The map specifies signal-change thresholds and the surgical response to each loss pattern.
- If neuromonitoring is intentionally not used, the map states why.

### Hemostasis Strategy
- The map names the predictable bleeding sources by phase.
- It specifies proximal/distal control points obtained before risky steps.
- It specifies tools and sequences (bipolar settings, hemostatic agents, packing, clip-trap-repair logic, transfusion thresholds).

### Operative Sequence with Step Rationale
- Every operative phase has: objective, landmark, action, structure-at-risk, decision point, novice error, expert behavior, recovery move, **and an explicit step-rationale chain (mechanical/anatomic goal → why this technique → consequence if skipped → downstream step it enables)**.
- Pre-OR phases (workup, plan, consent, setup arrival) and post-OR phases (extubation, 24h, 30d, follow-up) receive the same treatment when they change conduct.

### Critical Moments and Bail-Outs
- The highest-risk maneuvers are isolated with expert-vs-novice behavior and the consequence of failure.
- Bail-outs are executable, not exhortative ("call for help" alone is not a bail-out).

### Endpoint / Completion Criteria
- The map names what must be true before closure: decompression endpoint, resection threshold, clipping/coiling confirmation, hardware position, hemostasis, intraoperative imaging or doppler, neuromonitoring stability.
- The map specifies what intraoperative tools confirm completion (ICG, indocyanine, intraop angio, intraoperative MRI/CT, neuromonitoring, doppler, fluoroscopy).

### Outcomes and Evidence
- The map captures contemporary outcomes, comparative evidence, effect sizes where decision-relevant, and known controversies.
- It identifies practice-changing trials or guidelines worth citing.

### Patient-Specific Modifiers
- Host factors (bone biology, age, comorbidities, anticoagulation, prior radiation, pregnancy, pediatric vs adult).
- Anatomic variants (vascular loops, accessory drainage, anomalous innervation, transitional vertebrae).
- Prior-surgery variants (scarred plane, hardware in situ, prior approach).

### Closure, Postoperative Surveillance, and Causality
- The map ties postoperative checks and complications back to the operative step that caused them.
- The map specifies expected postoperative imaging findings vs alarms.
- The map specifies follow-up cadence and recurrence/failure surveillance.

### OR Team Choreography (when conduct-relevant)
- The map names the closed-loop communication points: time-out, vascular control announcement, neuromonitoring change, transfusion call, conversion announcement, abort criteria call.

### Attending Defense Coverage
- Attending defense questions written during decomposition are answered by the map.
- The reviewer must also generate **at least three fresh attending questions** independent of the writer's list, and confirm the map answers them. Fresh questions must be recorded in the verdict.
- Cross-check the map against the curated bank in `.agents/shared/commands/intraoperative-guide-attending-bank.md`: pull all universal questions plus at least 4 of the primary-family questions. The map (not yet the prose) must contain the mental scaffolding to answer each pulled question. Skip-with-reason is allowed for conditional-tag questions.

## Adversarial Discipline

On cycle 1, the reviewer must surface at least three candidate gaps before declaring `MAP_APPROVED`. If the reviewer cannot generate three plausible gap candidates, the review is too shallow — re-read the map and try again.

A gap is "blocking" if a resident reading only this map would mis-execute, mis-recognize danger, fail to rescue, or fail attending defense. Non-blocking gaps are recorded but do not prevent map approval.

## Verdict JSON

Write a verdict file to:

```text
data/Sessions/<Title>/verdicts/map-review-cycle-<N>.json
```

Format:

```json
{
  "checkpoint": "map_review",
  "cycle": 1,
  "verdict": "MAP_APPROVED" | "MAP_GAPS",
  "procedure_title": "<Title>",
  "complexity": "simple" | "intermediate" | "complex",
  "reviewer_role": "map_reviewer_subagent" | "self_review_simple_only",
  "bank_question_ids_checked": ["U01", "U02", "S03"],
  "fresh_attending_questions": ["<question 1>", "<question 2>", "<question 3>"],
  "candidate_gaps_surfaced": <integer, ≥3 on cycle 1>,
  "blocking_gaps": [
    {
      "gap": "...",
      "rubric_block": "anatomy / anesthesia / hemostasis / ...",
      "repair_path": "internal knowledge | RAG | PubMed | knowledge_map_revision",
      "suggested_query": "..."
    }
  ],
  "nonblocking_notes": ["..."],
  "coverage_ledger_updates": [
    {"block_id": "hemostasis_strategy", "review_status": "gap", "note": "..."}
  ],
  "rationale": "<2-4 sentences on why approved or what must improve>",
  "timestamp": "<ISO-8601>"
}
```

The verdict JSON is a workflow artifact. It must exist before the synthesis module runs. The finalize module verifies the chain. To control token use, the reviewer should return only the compact delta summary to the orchestrator after writing the JSON: verdict, blocking gaps, repair paths, fresh questions, affected coverage block IDs, and rationale. Do not echo the full bank pull or full JSON unless explicitly requested. Store attending-bank question IDs, not full bank-question text; the bank file is canonical.

## Gap Report Format (when MAP_GAPS)

In addition to the verdict JSON, return a markdown gap table to the orchestrator:

```markdown
## Verdict
MAP_GAPS

## Blocking Map Gaps
| Gap | Rubric block | Why it matters intraoperatively | Repair path | Suggested query |
|---|---|---|---|---|
| ... | ... | ... | internal / RAG / PubMed / knowledge_map_revision | ... |

## Fresh Attending Questions Used
- ...
- ...
- ...

## Non-blocking Notes
- ...
```

Keep this returned table delta-focused. The full JSON on disk is the audit trail; the chat/handoff is the working summary.

## Termination

If three map-review cycles still fail to approve on intermediate procedures (five on complex), escalate to the user with the unresolved gaps. Do not begin drafting prose from an unapproved map.
