# Intraoperative Guide Research Module

Use this module whenever the main `/intraoperative-guide` workflow reaches operative research. This module is agent-agnostic and should be read freshly at the research checkpoint.

## Purpose

Build compact, high-yield **structured source cards** and a **coverage ledger** for one operative guide without bloating the final synthesis context. The output of this module is not the guide. It is a structured source layer that the operative knowledge-map builder can use to construct the procedure model.

The research checkpoint enforces a **per-domain retrieval matrix**: each Coverage Matrix block from decomposition that is not covered by internal expert knowledge requires at least one focused query.

## Role

You are the operative research fellow. Your job is to retrieve and extract conduct-changing knowledge: pathology, workup, operative sequence, anatomy-risk relationships, instruments, decision points, pitfalls, bail-outs, variants, outcomes, and postoperative signatures.

Do not write polished prose. Do not summarize everything retrieved. Extract what changes what a resident must do, anticipate, explain, or rescue in the OR. Raw retrieval dumps may be written to disk for audit, but they must not be passed forward as ordinary context. Prefer machine-readable artifacts over prose briefs.

## Serial Retrieval Rule

Run `lance_retriever.py compare` queries in series. Do not run multiple retrieval calls in parallel; the local embedding stack can contend during model loading and stall. Latency is acceptable when each query is genuinely closing a coverage gap.

Established anatomy and classic operative technique should usually use `--no-frontier`:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "<focused operative query>" --stdout --no-frontier
```

Omit `--no-frontier` when modern literature materially affects patient selection, approach comparison, outcomes, implants, devices, endoscopy, navigation/robotics, radiosurgery adjuncts, monitoring, or complication rates. At least one outcomes query per intermediate or complex procedure should omit `--no-frontier`.

## Structured Source-Card Rule

After each retrieval query, immediately produce source cards. Source cards are the only retrieval artifact normally passed into knowledge mapping, synthesis, or review.

Preferred command shape:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "<focused operative query>" \
  --card-json \
  --card-output "data/Sessions/<Title>/source_cards_q<N>.jsonl" \
  --card-prefix "Q<N>-CARD" \
  --coverage-block "<coverage_block>" \
  --max-passages 6 \
  --max-takeaways 4 \
  [--no-frontier | --frontier-max-chars 6000]
```

Then concatenate or index the per-query cards into:

```text
data/Sessions/<Title>/source_cards.jsonl
```

Each JSONL file begins with a manifest row followed by card rows. The canonical compact card fields are:

```json
{
  "card_id": "Q3-CARD-02",
  "citation": "Youmans ... p.851",
  "page_start": 851,
  "takeaways": ["..."],
  "numbers_thresholds_effects": ["..."],
  "raw_ref": {"child_id": "...", "source_key": "...", "chunk_index": 12}
}
```

Coverage lives in `coverage_ledger.json`; do not repeat query and coverage metadata on every card row unless debugging with `--verbose-cards`. The agent may add a brief `agent_synthesis` field when the extractive card needs a one-sentence operative interpretation, but do not expand cards into prose paragraphs. Keep raw `rag_q<N>.md` files only for audit or narrow re-checking. Do not paste them into prompts after source-card extraction unless a reviewer names a specific passage-level dispute.

For human debugging only, a short generated markdown view may be written to:

```text
data/Sessions/<Title>/source_cards.md
```

The markdown view is not canonical and should not be passed to reviewers if `source_cards.jsonl` and the coverage ledger are available.

## Coverage Ledger

Maintain a compact machine-readable coverage ledger as the main workflow data bus:

```text
data/Sessions/<Title>/coverage_ledger.json
```

Shape:

```json
{
  "procedure_title": "<Title>",
  "complexity": "simple|intermediate|complex",
  "coverage_blocks": {
    "surgical_anatomy": {
      "status": "covered|internal_only|weak|unresolved",
      "source_card_ids": ["Q3-CARD-02"],
      "map_block_id": "anatomy_risk",
      "guide_section": "Surgical Anatomy with Neurophysiologic Consequence",
      "review_status": "pending|approved|gap",
      "notes": "short conduct-relevant note"
    }
  },
  "raw_rag_policy": "audit_only"
}
```

Update the ledger at research, map review, expert review, and gap repair. Reviewers should receive the ledger and only the source cards relevant to weak or disputed blocks whenever possible.

## Per-Domain Retrieval Matrix (depth floor by complexity)

Use the decomposition module's Retrieval Plan as the starting point. The agent must demonstrate coverage of every Coverage Matrix block. A block may be covered by internal expert knowledge **only if** the agent records a one-line justification in the verdict JSON — silent omission is a workflow failure.

Minimum focused-query floors (these are coverage floors, not creativity ceilings — query more whenever a gap remains):

- **Simple procedure (e.g., EVD, lumbar drain, burr-hole washout):** at least 3 queries. Must include: operative sequence; anatomy-risk; complication/bail-out. Frontier optional.
- **Intermediate procedure (e.g., ACDF, VP shunt, laminectomy, routine tumor exposure):** at least 6 queries. Must include: operative sequence; anatomy-risk (≥2 queries for distinct structure groups); complications/bail-outs; equipment/setup or anesthesia/neuromonitoring; outcomes/evidence comparison. ≥1 query omits `--no-frontier`.
- **Complex procedure (e.g., aneurysm clipping, AVM, far lateral/transcondylar, petrosectomy, bypass, endoscopic skull base, deformity correction):** at least 10 queries. Must cover all Coverage Matrix blocks not justifiably handled by internal knowledge alone, including pathology/natural history, workup interpretation, anatomy in multiple corridors, anesthetic/physiologic plan, neuromonitoring, hemostasis, endpoint criteria, outcomes/evidence, patient-specific modifiers. ≥2 queries omit `--no-frontier`.

These floors are not quotas to pad — they exist because the dry-run data shows the agent converging on 3 queries even for intermediate procedures, which cannot cover the matrix. If a block is genuinely simple for this operation, document it in the verdict rather than skipping.

## Query Domains to Cover

Use the decomposition's Coverage Matrix as the master list. The classic domains below remain useful and should appear as discrete queries when the block is not internal-knowledge-only:

- Pathology mechanism and natural history.
- Imaging interpretation, decision thresholds, adjunct studies.
- Operative sequence and named phases.
- Positioning, incision, exposure, bone work, reconstruction, closure.
- Surgical anatomy, corridors, fascial planes, bony limits, venous drainage, vascular territories, cranial nerves, tracts, perforators, adjacent compartments.
- Danger zones and injury signatures.
- Equipment and setup specifics that change conduct.
- Anesthetic and physiologic plan (MAP/CPP, ventilation, paralytic, burst suppression, brain relaxation).
- Neuromonitoring modalities and signal-change response algorithms.
- Hemostasis strategy: predictable bleeding sources, control points, hemostatic agents, transfusion thresholds.
- Critical maneuvers and expert-vs-novice errors.
- Bail-outs for bleeding, lost plane, wrong exposure, CSF leak, swelling, hardware malposition, implant failure, inability to proceed.
- Endpoint and intraoperative completion confirmation (ICG, doppler, angio, intraop MRI/CT, monitoring stability).
- Immediate postoperative surveillance and complication signatures.
- Variants, conversions, abort criteria, approach-selection alternatives.
- Outcomes, comparative evidence, practice-changing trials/guidelines.
- Patient-specific modifiers (host factors, anatomic variants, prior surgery, pediatric/elderly/pregnancy).

## Research Brief Output

The research brief is now optional. Use it only as a generated human-readable view or when a model cannot consume JSONL reliably. The canonical research handoff is:

- `source_cards.jsonl`
- `coverage_ledger.json`
- `research.json`

If a brief is produced, keep it short: target 500-900 words for intermediate procedures and 900-1,400 words for complex procedures. Do not restate every card. Summarize only source mix, limitations, and unresolved questions.

```markdown
## Source Pack
- Source mix:
- Retrieval limitations:
- Coverage-block tally: <blocks covered by RAG> / <blocks covered by internal knowledge> / <total>
- Source-card file: data/Sessions/<Title>/source_cards.md

## Pathology and Workup Extracts
- Mechanism / natural history:
- Imaging interpretation cue:
- Decision threshold:
- Source support:

## Operative Sequence Extracts
- Phase:
  - Conduct-changing details:
  - Step rationale (mechanical/anatomic why, downstream consequence):
  - Source support:

## Anatomy-Risk Extracts
- Structure/space:
  - Function / supply / plane:
  - Why vulnerable:
  - Injury signature:
  - Avoidance or rescue:
  - Source support:

## Anesthetic, Physiologic, Neuromonitoring, and Hemostasis Extracts
- Topic:
  - Conduct-changing details:
  - Source support:

## Equipment and Setup Extracts
- Item/setup choice:
  - When it matters:
  - Consequence of wrong choice:
  - Source support:

## Critical Maneuver Extracts
- Maneuver:
  - Expert behavior:
  - Novice error:
  - Consequence:
  - Rescue:
  - Source support:

## Endpoint / Completion Criteria Extracts
- Criterion:
  - Confirmation method:
  - Source support:

## Pitfalls, Bail-Outs, and Complications
- Problem:
  - Mechanism:
  - Early recognition:
  - Immediate action:
  - Postoperative surveillance:
  - Source support:

## Outcomes and Evidence Extracts
- Outcome / trial / guideline:
  - Effect size or comparator:
  - Practice impact:
  - Source support:

## Variants, Patient Modifiers, and Decision Branches
- Branch / modifier:
  - Trigger:
  - Different conduct:
  - Source support:

## Unresolved Questions
- Question:
  - Why it matters:
  - Repair path: existing context / internal knowledge / RAG / PubMed
  - Suggested focused query:
```

## Verdict JSON

Write research-checkpoint status to:

```text
data/Sessions/<Title>/verdicts/research.json
```

Format:

```json
{
  "checkpoint": "research",
  "procedure_title": "<Title>",
  "complexity": "simple" | "intermediate" | "complex",
  "query_count": <integer>,
  "queries_without_frontier": <integer>,
  "queries_with_frontier": <integer>,
  "queries_per_coverage_block": {
    "pathology_and_natural_history": <int>,
    "workup_and_decision_making": <int>,
    "indications_contraindications_approach": <int>,
    "preoperative_planning": <int>,
    "room_positioning_equipment": <int>,
    "anesthetic_physiologic_plan": <int>,
    "neuromonitoring_strategy": <int>,
    "hemostasis_strategy": <int>,
    "operative_sequence": <int>,
    "critical_moments": <int>,
    "surgical_anatomy": <int>,
    "pitfalls_bailouts": <int>,
    "endpoint_completion_criteria": <int>,
    "variants_decision_branches": <int>,
    "closure_postoperative": <int>,
    "complications_signatures": <int>,
    "outcomes_evidence": <int>,
    "patient_specific_modifiers": <int>,
    "or_team_choreography": <int>
  },
  "blocks_covered_by_internal_knowledge_only": ["<block>: <one-line justification>"],
  "minimum_floor_met": true | false,
  "frontier_outcomes_query_present": true | false,
  "retrieval_limitations": "<short note>",
  "source_cards_path": "data/Sessions/<Title>/source_cards.jsonl",
  "coverage_ledger_path": "data/Sessions/<Title>/coverage_ledger.json",
  "research_brief_path": "data/Sessions/<Title>/research_brief.md or null",
  "raw_retrieval_files_retained_for_audit": true | false,
  "raw_retrieval_files_not_used_as_downstream_context": true | false,
  "card_json_canonical": true | false,
  "timestamp": "<ISO-8601>"
}
```

If `minimum_floor_met` is false, the workflow does not advance to knowledge mapping until additional queries are run or each missing block has a recorded internal-knowledge justification.

For intermediate and complex procedures, `frontier_outcomes_query_present` is a **hard gate**, not just a flag. If it is false, the workflow cannot proceed to finalization — run at least one outcomes query without `--no-frontier` and update `research.json`. The validator and finalize module both refuse to advance when this gate is unmet for intermediate/complex tiers.

## Context Discipline

If a subagent is used for research, it should return only the source-card path, the research brief, the exact query list it ran, and the verdict JSON. It should not return full retrieval dumps unless the main agent explicitly requests a narrow passage.
