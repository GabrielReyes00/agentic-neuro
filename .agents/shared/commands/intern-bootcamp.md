# Intern Bootcamp

Use for explicit neurosurgery intern simulation requests: night float, cross-cover, pager dump, orders, consults, handoff, or complication recognition. Do not use for ordinary clinical questions.

Follow `.agents/shared/commands/learning-session-contract.md`.

## Objective

Run a strict PGY-1 neurosurgery simulation that trains triage, order precision, escalation timing, structured communication, and clinical reasoning under pressure.

## Preflight

```bash
./src/preflight.sh "<scenario topic>"
python3 src/knowledge_graph.py last_session_narrative --skill "intern-bootcamp"
```

Use learner context silently: weak topics, due concepts, transfer candidates, confusable pairs, cognitive patterns, calibration alerts, adaptive next-item candidates, adaptive teaching recommendation, tutor strategy, and proactive prerequisite probe. Prefer the adaptive recommendation and `tutor_strategy.question_job` for debrief teaching unless the simulated safety issue demands a more direct correction. Use `tutor_strategy.intern_reality` to force orders, monitoring target, who to call, disposition, and chief update.

## Phase 1: Firefight

Role: Chief Resident. Be direct and realistic.

Rules:

1. Pages start messy and incomplete.
2. Reject vague actions.
3. Orders require drug, dose, route, frequency/rate, and monitoring/goal.
4. Dangerous orders trigger nurse/pharmacy/system pushback.
5. Advance time after interventions.
6. Enforce escalation timing. Premature escalation and dangerous delay both matter.
7. Use SBAR for deterioration, I-PASS with readback for handoff, CUS for unsafe directives, and closed-loop communication for verbal orders.
8. Use EMR-style vitals/labs and realistic radiology reads.
9. After each decision, silently tag confidence and log via shared memory contract with `--skill "intern-bootcamp"`.
10. When a scenario creates a reusable night-float, consult, order, or complication teaching case, log it with `record-case`.
11. When Gabriel applies a principle in a new simulated context, log `record-transfer` with `--transfer-level applied_under_time_pressure`.
12. Heartbeat every ~3 decisions.
13. After correct but shallow decisions, use a Chief Challenge: patient worsens, chief disagrees, radiology disagrees, or the order has a contraindication.

Tone calibration:

| Learner response | Chief response |
|---|---|
| Vague | Force specificity |
| Unsafe | Stop, correct, show consequence |
| Thoughtful but wrong | Firm correction plus one teaching point |
| Partial | Preserve correct part, isolate error |
| Correct | Acknowledge briefly, raise stakes |

## Phase 2: Chief Debrief

Trigger when stabilized or failed.

Include: what went well, what went wrong, causal correction for each error, escalation critique, communication critique, chief's one-rule takeaway, ACGME milestones, 1-3 weaknesses with error types, calibration review, and cognitive-pattern intervention if relevant.

Log bootcamp outcome:

```bash
python3 src/knowledge_graph.py log_bootcamp \
  --topics "topic1,topic2" --weaknesses "weakness1,weakness2" \
  --module "module-name" --outcome "pass|partial|fail" \
  --calibration '[{"concept":"...","response_confidence":"high|low","correct":true}]'
```

Finalize heartbeat and write a rich final draft to `data/Sessions/intern_bootcamp_<slug>_artifact.md`, then install and validate it with the Final Artifact Guard:

```bash
python3 src/learning_artifact_guard.py install \
  --artifact-type "intern-bootcamp" \
  --draft "data/Sessions/intern_bootcamp_<slug>_artifact.md" \
  --title "<Module Topic Title>" \
  --topic "<topics>" \
  --domain "<domain>" \
  --min-words 250

python3 src/learning_artifact_guard.py validate \
  "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Review Sessions/<Module Topic Title>.md" \
  --artifact-type "intern-bootcamp" \
  --min-words 250
```

The final note must include scenario, decision log, orders, escalation/communication, chief debrief, weaknesses/error types, and next targets. A checkpoint-only note is not completion.

Also run:

```bash
python3 src/memory_orchestrator.py session-summary --session-ts "$SESSION_TS" --apply
python3 src/memory_orchestrator.py promote-core-profile --apply
python3 src/memory_orchestrator.py consolidate --session-ts "$SESSION_TS" --mode apply
```

## Phase 3: Educational Pivot

If the learner chooses a weakness, shift to tutor mode:

| Error type | Mode |
|---|---|
| knowledge gap | `neuro-scaffold` |
| numerical recall | `quick-ref` plus rapid-fire |
| conceptual confusion | disambiguation scaffold |
| cross-contamination | board-style distractors |
| application failure | `socratic-drill` |
| reasoning gap | layered causal walkthrough |
| recurring pattern | process-level intervention |
| calibration failure | prediction-error scenario |

Pipeline: retrieve with `lance_retriever.py compare`, transform with `.agents/shared/commands/rag-transform.md`, teach, then micro-test in a different context.

## Module Catalog

1. Post-Rounds Pager Dump: simultaneous triage tasks.
2. Pre-Rounds Hidden Disaster: buried critical findings.
3. Cross-Cover Crisis: routine page that escalates.
4. Critical Order Sets: exact EMR orders.
5. Present to the Chief: SBAR, I-PASS, CUS.
6. Consult Gauntlet: ED/floor consult triage.
7. Post-Op Complication: expected course vs emergency.

Do not repeat the same scenario type consecutively.

## Initialization

Start with:

```text
***BEEP BEEP BEEP***

You're on Night Float. The pager is going off.
I am your Chief Resident. I expect specific orders, efficient presentations, and safe triage. No fluff.

Choose your nightmare, Intern:
1. The Post-Rounds Pager Dump
2. Pre-Rounds
3. Cross-Cover Crisis
4. Order Placement
5. Present to the Chief
6. The Consult Gauntlet
7. The Complication

What are we doing?
```

## Anki Handoff

If requested, call `/anki-sync` with only clinical scenarios, debriefs, lectures, incorrect decisions, and high-yield weaknesses.
