# Memory Operations

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

**Topic-anchored sessions**: user named a topic, document, or clinical question, including `/consult`, `/brain-dump`, `/study-material`, doc-anchored `/study-review`, and procedure-specific workflows.

```bash
python3 src/study_memory.py summary --topic "<topic>" --limit 8 --scaffold-limit 2 --include-curated --include-model
```

This command is topic-scoped. Do not run global retrieval in this mode. Unrelated open errors must not influence a chosen-topic session.

**Memory-driven custom review only**: user asked what to study, to drill weak spots, to build a custom session, to go after open errors, or a similar memory-first request with no named topic.

```bash
python3 src/study_memory.py summary --limit 12 --scaffold-limit 0 --include-curated --include-model
```

Global `summary` surfaces high-signal active retest cards, due conceptual checks, learner-model profiles, and recent session handoff state while suppressing scaffolds by default. Use `--include-global-scaffolds` only if no stronger due gaps dominate and broad target selection needs scaffold context.

In all modes, read output silently. Do not paste it into chat, summarize it as a menu, or telegraph prior misses. The data shapes questioning; it does not shape narration.

## Pre-Session Verification

After running `summary`, read the full JSON and verify:

1. **Retrieval completeness**: inspect `counts`, `omitted`, and `retrieval_guidance`. If `retrieval_guidance.omitted_high_signal` is non-empty, run a suggested expansion command before teaching.
2. **Returning session**: if this is a known topic but `cards`, `counts`, and `omitted` are empty, run `python3 src/study_memory.py resolve-topic --topic "<topic>" [--doc "<folder>/<file>.md"]`, fix the topic, and re-run summary.
3. **Coherence**: card topics, claims, and session handoffs must relate to the requested topic. If output is unrelated, resolve the topic and re-run summary.
4. **New topic**: if no review file exists and summary is genuinely empty, proceed with calibration.

Set one `SESSION_TS` at the first learner-facing question and reuse it for the whole session:

```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```

## After Every Q&A

```bash
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" --topic "<topic>" --concept "<concept>" \
  --question "<your question, verbatim>" --answer "<user's answer, verbatim>" \
  --correct <0|1|2> \
  [--correction "<text>"] [--error-type "<type>"] [--misconception "<text>"] \
  [--doc "<path>"] [--skill "<skill>"] \
  [--tested-claim "<what was being tested>"] \
  [--learner-claim "<compact summary of committed answer>"] \
  [--missing-edge "<missing threshold/discriminator/step/mechanism>"] \
  [--corrected-rule "<replacement rule>"] \
  [--clinical-consequence "<why this matters clinically>"] \
  [--retest-prompt-shape "<how to test this next time>"] \
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
  [--repairs-claim-state-ids "<id,id,...>"]
```

Correctness: `2` = correct without hints | `1` = right direction, missing details | `0` = wrong or misconception.

Agent judgment fields are required when applicable:

- For assessed learning exchanges, always pass `--strict-telemetry`, `--answer-mode`, `--confidence-observed`, and `--teaching-move`. Strict mode also requires `--tested-claim` (or `--corrected-rule`/`--correction`) so the stored claim is a real testable statement rather than auto-generated boilerplate. It rejects incomplete or uncontrolled telemetry before writing. Do not use strict mode for quick-answer or artifact-anchor bookkeeping.
- Use `--priority` when clinical or educational stakes are clearer than fallback heuristics. Default to `urgent` for safety-critical intern errors, `high` for active management-changing gaps, `medium` for partial/lower-stakes gaps, and `low` only for durable scaffolds or low-stakes context.
- Use `--match-claim-state-id` for intentional retests of existing `must_retest` or `recent_repair` cards.
- Use `--new-claim` when wording overlaps an existing claim but the cognitive target is genuinely different.
- Use `--repairs-claim-state-ids` only when a correct answer explicitly repairs other open claim states.

## Session End

```bash
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "<1-3 sentence recap>" \
  --next-strategy "<specific directive for next session>" \
  --json
```

Always pass `--json`. Read the returned `curation.recommended` flag silently, then continue to the Anki queue workflow. The default text output is preserved for ad-hoc CLI use; skills use JSON so the curation hook is visible.

## Post-Session Integrity Verification

After `end-session`, verify:

1. **Exchange count**: run `python3 src/study_memory.py status` or inspect session rows if needed. If the count is low, re-run missing `log-answer` calls before proceeding.
2. **Summary cross-check**: run `python3 src/study_memory.py summary --topic "<topic>" --limit 8 --scaffold-limit 2 --include-curated --include-model` and verify the `session_handoff` reflects the summary and next strategy.
3. **Next-strategy quality**: it must name specific concepts, error types, and teaching moves. If generic, rewrite and re-run `end-session`.

## Entry Formatting

**TOPIC**: lowercase, 3-8 words, condition + context.

Good: `evd management in icu`, `icp monitoring in tbi`

Bad: `ICP`, `EVD Management in the ICU for External Ventricular Drain Patients`

**CONCEPT**: lowercase, specific testable fact or distinction.

Good: `cpp target 60-70 mmhg`, `lundberg a vs b wave distinction`

Bad: `CPP`, `waves`

Never log a tracked concept for a session-synthesis, self-assessment, or "consolidate what you learned" prompt. A closing metacognitive question is a teaching move, not an assessed clinical claim — its substance belongs in the `end-session` summary, never as a `log-answer` concept. Tracked concepts must name a clinical fact a future agent can retest.

**ERROR_TYPE**: one of `conceptual_confusion`, `numerical_recall`, `cross_contamination`, `application_failure`, `reasoning_gap`, `omission`.

**MISCONCEPTION**: the specific wrong belief, never "user was unsure".

Good: `believed barbiturate coma is first-line for refractory icp`

Bad: `incorrect`, `unsure`

## Invisible Bookkeeping

Memory commands are internal. Do not print commands, JSON payloads, raw stdout, or raw stderr into the learner-facing transcript. You must still read and reason about every memory command's output. Silent means invisible to the learner, not invisible to the agent. Surface only concise warnings on failure.
