# Study Session Architect

Use only when the user explicitly asks what to study, requests a study plan, or wants a 30-minute study session.

Follow `.agents/shared/commands/learning-session-contract.md`.

## Step 0: Readiness and Continuity

Check readiness:

```bash
head -80 "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/ACGME Readiness.md" 2>/dev/null
```

If present, rank lowest-coverage domains and ask the user to choose a domain, general, or skip.

Check continuity:

```bash
python3 src/knowledge_graph.py last_session_narrative --skill "study-session"
```

Use prior strategy, confusions, teaching failures, `data/Sessions/adaptive_next_item.json`, `data/Sessions/adaptive_teaching.json`, `data/Sessions/proactive_probe.json`, and `data/Sessions/tutor_strategy.json` to choose topics, question jobs, and approach. Treat sparse adaptive recommendations as priors; override them when the user's requested topic, safety, or document priority requires it.

If the user has selected a specific Obsidian document or named source, do not run a general prior-miss backlog before that source. Apply Requested-Document Priority from the shared learning contract.

## Step 1: Gather Signals

```bash
python3 src/knowledge_graph.py review_queue --n 5
python3 src/knowledge_graph.py gaps --top 5 [--rotation "<DOMAIN_FILTER>"]
python3 src/knowledge_graph.py transfer_candidates --n 3
python3 src/knowledge_graph.py cognitive_patterns
python3 src/knowledge_graph.py calibration_profile
python3 src/knowledge_graph.py dashboard
```

If no domain filter is chosen, infer rotation context if available and rerun gaps with that rotation.

## Step 2: Compose 30-Minute Plan

| Component | Time | Source | Skip Rule |
|---|---:|---|---|
| Recall Bridge | 3 min | Review queue | Skip if empty |
| Targeted Remediation | 8 min | Error-typed gaps | Skip if none |
| New Territory | 12 min | Top gap | Never skip |
| Transfer Challenge | 7 min | Transfer candidates | Skip if none |

Redistribute skipped time to New Territory unless a better target is obvious.

Remediation routing:

| Error type | Mode |
|---|---|
| `numerical_recall` | rapid fill-in drill |
| `conceptual_confusion` | forced disambiguation |
| `cross_contamination` | confusable-pair vignette |
| `application_failure` | focused scenario |
| `reasoning_gap` | causal scaffold |

Recurring cognitive pattern: insert a short process intervention. Calibration issue: ask for confidence before answers.

Adaptive routing:

| Signal | Use |
|---|---|
| `adaptive_next_item.items[0].difficulty_band = remediate` | Start with prerequisite repair before transfer |
| `adaptive_next_item.items[0].difficulty_band = zpd` | Use as the main 8-12 minute target |
| `adaptive_teaching.approach` | Use as the first remediation move if it fits the error type |
| `proactive_probe.status = popped` | Insert as a single bridge question only if it is prerequisite, confusable, or safety-critical |
| `tutor_strategy.question_job` | Use as the first question's hidden job |
| `tutor_strategy.mastery_ladder.next_rung` | Aim the session's next probe at this rung unless the answer reveals a lower prerequisite gap |
| `tutor_strategy.learning_yield_optimizer.targets` | Prefer as the session target list when the user asks what to study |
| `tutor_strategy.concept_bottlenecks.targets` | Test one relevant bottleneck before downstream remediation |
| `tutor_strategy.cross_context_transfer_matrix.next_transfer_gap` | Use for Transfer Challenge |
| `tutor_strategy.compression_card` | Use at close for one-breath schema, danger rule, discriminator, and rescue move |

## Step 3: Present Plan

Show components, selected topics, mode rationale, skipped components, and time redistribution. Ask for approval before execution.

## Step 4: Execute

Set `SESSION_TS` once. Ask one question at a time. After every evaluated learner answer in Recall Bridge or Remediation, log with `--skill "study-session"`.

Follow the Cognitive Friction Protocol from the shared learning contract. Each prompt must end at the question; do not append hints, answer context, expected findings, or explanatory teaching until after Gabriel commits to an answer.

After each committed answer, use the Progressive Landscape Reveal Protocol. Reveal one layer, then ask the next probe. Label nearby material as "still hidden for active recall" until it has been probed or the learner asks for the map.

Component behavior:

1. Recall Bridge: retrieval-first, no RAG unless needed for correction.
2. Remediation: use the error-matched mode.
3. New Territory: run RAG workflow, usually `neuro-scaffold`; use discrimination format when confusable pairs exist.
4. Transfer Challenge: one scenario in a new clinical context, then log both transfer outcome and answer content.

Transfer logging:

```bash
python3 src/memory_orchestrator.py record-transfer \
  --session-ts "$SESSION_TS" --turn <N> --skill "study-session" \
  --topic "<topic>" --concept "<concept>" \
  --context "<new clinical context>" --answer "<learner answer>" \
  [--success] [--transfer-level "applied_to_vignette|applied_under_time_pressure"]
```

If the transfer question is built around a reusable clinical or operative case,
also log a case memory with `record-case`.

Heartbeat after Components 1-2 and again at finalization.

## Step 5: Summary and Finish

Summarize component outcomes, resolved and unresolved gaps, one learner-pattern insight, and next-session priority. Offer Anki, another session, or end.

Finalize heartbeat with gap details, run `session-summary --apply`, write a rich final draft to `data/Sessions/study_session_<slug>_artifact.md`, then install and validate it with the Final Artifact Guard:

```bash
python3 src/learning_artifact_guard.py install \
  --artifact-type "study-session" \
  --draft "data/Sessions/study_session_<slug>_artifact.md" \
  --title "<Primary Topic Title>" \
  --topic "<topics>" \
  --domain "<domain>" \
  --min-words 250

python3 src/learning_artifact_guard.py validate \
  "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Review Sessions/<Primary Topic Title>.md" \
  --artifact-type "study-session" \
  --min-words 250
```

The final note must include the required sections from the shared learning contract. A checkpoint-only `Review Sessions` file is not completion. After validation passes, run concept extraction, `promote-core-profile --apply`, `consolidate --mode apply`, and the post-session hook.
