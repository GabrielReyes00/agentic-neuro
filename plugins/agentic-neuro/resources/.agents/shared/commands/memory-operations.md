# Memory Operations

`study-review` uses the typed `start-session`, `assess-turn`, and
`close-session` interface owned by its phase contracts. The legacy
`startup-recall`, `log-answer`, separate card-decision, and `end-session`
commands below remain compatibility surfaces for other learning workflows.
Never translate a typed multi-claim study-review response back into multiple
legacy exchanges: one raw learner answer must remain one exchange with one or
more independently assessed claims.

Schema v8 adds `turn_assessments` (idempotent envelopes),
`claim_assessments` (accuracy, independence, reasoning depth, safety,
demonstrated operation, and pending adjudication), `study_runtime_sessions`
(outer lifecycle), and `learner_profile` (explicit expectation context). Existing
`exchanges`, `claim_results`, `claim_state`, scheduler, retrieval cards, and
knowledge maps remain authoritative and backward compatible. A
`pending_adjudication` row never creates or changes `claim_state`.

Single-purpose contract for active learner-memory reads/writes during learning workflows.

## Shell Prefix

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate
```

## Active Store

**DB:** `data/study_memory.db` | **CLI:** `src/study_memory.py`

The claim-centered memory database is the only active learner-memory store. There is no dual-write workflow.

The agent owns all memory bookkeeping. The user never types memory commands.

Every memory command in this contract must be executed, not simulated. Do not reason about what a command would return. Run it, read the actual output, and build the teaching plan from real data.

## Session Start

Context-pulling is mode-conditional. The wrong command at the wrong time causes topic drift.

Set one `SESSION_TS` before startup recall and reuse it for all logging, Anki, and session-end commands:

```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```

**Document-anchored sessions**: user named a vault document, including doc-anchored `/study-review`, `/study-material` drill, shift-debrief review, and procedure-specific workflows. Pass `--profile doc --doc` so document-family identity is resolved and the agent receives the compact document-primary startup brief.

```bash
python3 src/study_memory.py startup-recall --profile doc --topic "<topic>" --doc "<folder>/<file>.md" --session "$SESSION_TS"
```

Do not expand just because counts or omitted fields are nonzero. If `startup_recall.ready_to_teach=true` and `startup_recall.pre_question_expansion_allowed=false`, begin from the compact brief and ask the first question. Use `--profile audit` only after startup is blocked, the compact brief is incoherent, or the learner explicitly asks for a memory audit.

For document review, also read `planning_brief.artifact_alignment`. If it is missing, stale, or only a family match, build/verify the persisted artifact map from the full artifact and rerun startup once:

```bash
python3 src/study_memory.py artifact-map-upsert --topic "<topic>" --doc "<folder>/<file>.md" --stdin
```

The payload is compact JSON: `artifact_title`, optional `content_hash`, and `concepts[]` with `artifact_concept`, `inventory_concept_id` when resolvable, `role`, `confidence`, `source_sections`, and `unresolved_reason`. This stores the artifact map in SQLite, separate from the vault note body.

**Topic-anchored sessions without a vault document**: user named a topic or clinical question but no artifact is known.

```bash
python3 src/study_memory.py startup-recall --topic "<topic>" --lens general --session "$SESSION_TS"
```

This command is topic-scoped. It resolves canonical topic identity, computes policy from the full personalized evidence set, and returns a bounded agent-ready brief with exact traces for the highest-priority claims. `deferred_evidence.counts` records compacted material; use `node-recall` only after selecting a concept. Do not run global retrieval or pre-question audit expansion. Unrelated open errors must not influence a chosen-topic session.

**Service/site-specific sessions**: user asks how a condition is handled on a named service or site.

```bash
python3 src/study_memory.py startup-recall --lens service --service "<service>" --site "<site>" --session "$SESSION_TS" [--context "<case/topic>"]
```

Use only `service_gaps` and `conventions` unless the learner explicitly asks to compare local practice against formal study knowledge.

**Memory-driven custom review only**: user asked what to study, to drill weak spots, to build a custom session, to go after open errors, or a similar memory-first request with no named topic.

```bash
python3 src/study_memory.py startup-recall --global --lens general --session "$SESSION_TS"
```

Global startup recall surfaces a compact high-signal candidate set, due conceptual checks, pending Shift Debrief candidates, learner-model profiles, and recent session handoff state while suppressing scaffolds by default. It intentionally returns `startup_recall.ready_to_teach = false`: read `startup_recall.deferred_high_signal`, select candidate topics, then run topic-scoped `startup-recall --topic "<candidate>" --lens general` for each chosen topic. Use `--include-global-scaffolds` only if no stronger due gaps dominate and broad target selection needs scaffold context.

In all modes, read output silently. Start from `planning_brief`, then inspect raw surfaces only when the brief is ambiguous, diagnostics require audit, or topic-scoped memory mode reports unresolved omitted high-signal material. Do not paste recall into chat, summarize it as a menu, or telegraph prior misses. The data shapes questioning; it does not shape narration.

`startup-recall` already emits JSON-like structured output and does not accept `--json`. Do not add a `--json` flag to `startup-recall` commands.

## Pre-Session Verification

After running the appropriate `startup-recall` command, read the full JSON and verify:

1. **Retrieval completeness**: inspect `startup_recall`, `counts`, `omitted`, and `retrieval_guidance`. `profile=doc` and topic-scoped `profile=memory` are intentionally compact; `retrieval_guidance.full_policy_computed_before_compaction=true` means deferred counts are discoverability metadata, not a pre-question fetch instruction. When `ready_to_teach=true`, begin from the brief. Use point-of-need `node-recall` for the selected concept; use `--profile audit` only for a blocked or explicit learner-model audit. Global startup still requires topic selection and a topic-scoped rerun.
2. **Planning-brief validation**: read `planning_brief.agent_validation_checkpoint`. Accept only 1-3 `contextual_frontier` candidates that are clinically central, scope-compatible, and useful for explaining an active gap or deepening transfer. Reject tangents. Record the accepted and rejected candidate ids in a silent internal note.
3. **Returning session**: if `startup_recall.routing_required = true`, validate a returned `resolution_candidate`, then rerun `startup-recall --profile doc --topic "<canonical candidate>" --doc "<folder>/<file>.md" --session "$SESSION_TS"` for document review or `startup-recall --topic "<canonical candidate>" --lens general --session "$SESSION_TS"` for topic-only review. Clarify with the learner only if the intended curriculum remains ambiguous.
4. **Coherence**: handoff, open claims, repairs, and accepted frontier candidates must relate to the requested topic. If output is unrelated, resolve the topic and rerun topic/doc-scoped `startup-recall`.
5. **New topic**: `new_topic_orientation.status=new_topic_no_learner_history` is a valid inventory-grounded ORIENT state. Proceed without treating weak lexical neighbors as prior mastery. If the inventory map is genuinely empty, proceed with calibration.

## After Every Assessed Q&A

```bash
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" --topic "<topic>" --concept "<concept>" \
  --question "<your question, verbatim>" --answer "<user's answer, verbatim>" \
  --correct <0|1|2> \
  [--correction "<text>"] [--error-type "<type>"] [--misconception "<text>"] \
  [--doc "<path>"] [--skill "<skill>"] \
  [--tested-claim "<what was being tested>"] \
  [--learner-claim "<compact summary of committed answer>"] \
  [--demonstrated-edge "<what the learner got right, required for partial credit>"] \
  [--missing-edge "<missing threshold/discriminator/step/mechanism>"] \
  [--corrected-rule "<replacement rule>"] \
  [--clinical-consequence "<why this matters clinically>"] \
  [--retest-prompt-shape "<how to test this next time>"] \
  [--teaching-intervention "<what explanation/contrast/scaffold was actually used>"] \
  [--learning-operation "<recall|discrimination|quantification|sequencing|mechanism|transfer>"] \
  [--teaching-intent "<new_material|retest_open_gap|repair_after_miss|transfer_check|retention_check|synthesis>"] \
  [--expected-answer-edge "<exact discriminator/threshold/step required for full credit>"] \
  [--coverage-role "<primary_doc|related_topic_probe|repair_probe|synthesis|memory_probe>"] \
  [--source-section "<document section or heading when known>"] \
  [--source-anchor "<subheading, TU id, or local anchor when known>"] \
  [--curriculum-unit "<compact unit label when useful>"] \
  [--answer-mode "<unaided|prompted|after_hint|after_teaching|self_corrected>"] \
  [--confidence-observed "<low|medium|high|hesitant|fluent>"] \
  [--teaching-move "<initial_probe|contrastive_drill|mechanism_first|order_set|premortem|visual_probe|changed_frame_retest|other>"] \
  [--strict-telemetry] \
  [--priority "<urgent|high|medium|low>"] \
  [--match-claim-state-id <id>] [--new-claim] \
  [--repairs-claim-state-ids "<id,id,...>"] \
  [--shift-debrief-candidate-id <id>] \
  [--inventory-concept-id "<inventory.concept_id>"] [--cognitive-op "<recall|discrimination|quantification|sequencing|mechanism|transfer>"]
```

Correctness: `2` = correct without hints | `1` = right direction, missing details | `0` = wrong or misconception.

**Identity layer.** Pass `--inventory-concept-id` whenever the probed concept resolves to a canonical inventory node — it is the key the policy, mastery, and ACGME readiness run on. Matching is Identity-first inside the scoped map; explicit out-of-scope rows stay unmatched; lexical is only a fallback for unbound concepts. After each assessed study-review exchange, `log-answer` prints a `binding={status}` line: `explicit` (you passed the id), `inferred` (lexically matched — provisional, pass the id next turn), or `unresolved` (no node matched — a possible inventory gap; see `inventory-authoring.md`, do not force a wrong binding). `--cognitive-op` is an alias for `--learning-operation`; pass it whenever the operation is known. The full field taxonomy is in `memory-retrieval.md` ("Writing Better Memory").

Agent judgment fields are required when applicable:

- For assessed learning exchanges, always pass `--strict-telemetry`, `--answer-mode`, `--confidence-observed`, and `--teaching-move`. Strict mode requires a real `--tested-claim`; a partial or miss (`--correct 0|1`) also requires `--error-type`, the exact missing/wrong edge, and the corrected rule. Partial credit (`--correct 1`) additionally requires `--demonstrated-edge` so future agents know both what was preserved and what still failed. Pass `--misconception` only for an explicit wrong belief, and `--teaching-intervention` after an explanation, contrast, scaffold, or repair was actually delivered. On rejection, read the `Remedy:` line and rerun; nothing was written. Do not use strict mode for artifact-anchor bookkeeping.
- Use `--priority` when clinical or educational stakes are clearer than fallback heuristics. Default to `urgent` for safety-critical intern errors, `high` for active management-changing gaps, `medium` for partial/lower-stakes gaps, and `low` only for durable scaffolds or low-stakes context.
- Use `--match-claim-state-id` for intentional retests of existing `must_retest` or `recent_repair` cards.
- Use `--new-claim` when wording overlaps an existing claim but the cognitive target is genuinely different.
- Use `--repairs-claim-state-ids` only when a correct answer explicitly repairs other open claim states.
- Use `--shift-debrief-candidate-id` when an evaluated answer tests a pending Shift Debrief candidate. This marks the candidate reviewed and links it to the resulting claim state.
- After every assessed `log-answer`, persist one `record-card-decision` using the
  returned exchange id. The Anki workflow owns eligibility. Learner score is an
  input, not an automatic command to create a card.

## Shift Debrief Review Candidates

Initial `/shift-debrief` capture logs unreviewed concepts with:

```bash
python3 src/study_memory.py shift-debrief-candidate-add \
  --session "$SESSION_TS" --topic "<topic>" --concept "<concept>" \
  --doc "Shift Debriefs/<Title>.md" \
  --prompt "<future Socratic question>" \
  --claim "<claim to test>" \
  --provenance-tier "<tier>" \
  --origin <assessed|service> [--rotation <id>] [--convention]
```

Candidates are review obligations/interests, not `claim_state`. List them with:

```bash
python3 src/study_memory.py shift-debrief-candidate-list [--topic "<topic>"] [--status pending]
```

Only `log-answer --shift-debrief-candidate-id <id>` converts a candidate into learner-state evidence.

## Session End

```bash
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "<1-3 sentence recap>" \
  --next-strategy "<specific directive for next session>" \
  --stats-json '<json>' \
  --json
```

Always pass `--json`. `--stats-json` carries compact session statistics (e.g. exchange counts by score) and matches the `study-review-end.md` recipe; pass `'{}'` when no stats apply. Read the returned `curation.recommended` flag silently, then continue to the Anki queue workflow. The default text output is preserved for ad-hoc CLI use; skills use JSON so the curation hook is visible.

For deliberate audits, identity repair, topic merges, or database maintenance
outside a teaching loop, load `memory-maintenance.md`; never preload it during
ordinary recall.

## Post-Session Integrity Verification

After `end-session`, verify:

1. **Exchange count**: run `python3 src/study_memory.py status` or inspect session rows if needed. If the count is low, re-run missing `log-answer` calls before proceeding.
2. **Summary cross-check**: run `python3 src/study_memory.py summary --topic "<topic>" --limit 8 --scaffold-limit 2 --include-curated --include-model` and verify the `session_handoff` reflects the summary and next strategy. Raw `summary` is appropriate here because this is an integrity audit, not startup recall.
3. **Next-strategy quality**: it must name specific concepts, error types, and teaching moves. If generic, rewrite and re-run `end-session`.

## Entry Formatting

**TOPIC**: lowercase, 3-8 words, condition + context.

Good: `evd management in icu`, `icp monitoring in tbi`

Bad: `ICP`, `EVD Management in the ICU for External Ventricular Drain Patients`

**CONCEPT**: lowercase, specific testable fact or distinction.

Under `--strict-telemetry`, concept labels must stay at `<=16` words and `<=140` characters. Put the full clinical rule in `--tested-claim`, not `--concept`.

Good: `cpp target 60-70 mmhg`, `lundberg a vs b wave distinction`

Bad: `CPP`, `waves`

Never log a tracked concept for a session-synthesis, self-assessment, or "consolidate what you learned" prompt. A closing metacognitive question is a teaching move, not an assessed clinical claim — its substance belongs in the `end-session` summary, never as a `log-answer` concept. Tracked concepts must name a clinical fact a future agent can retest.

**ERROR_TYPE**: one of `conceptual_confusion`, `numerical_recall`, `cross_contamination`, `application_failure`, `reasoning_gap`, `omission`.

**MISCONCEPTION**: the specific wrong belief, never "user was unsure".

Good: `believed barbiturate coma is first-line for refractory icp`

Bad: `incorrect`, `unsure`

## Invisible Bookkeeping

Memory commands are internal. Parse compact JSON silently; do not print commands, JSON payloads, raw stdout, or raw stderr into the learner-facing transcript. You must still read and reason about every memory command's output. Silent means invisible to the learner, not invisible to the agent. Surface only concise counts, status, and actionable warnings on failure.
