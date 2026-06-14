---
name: study_review
description: Socratic review from an existing vault document (Reports/, Study Material/, or Brain Dumps/) — memory-enabled, doc-anchored, no vault artifact.
---

# Study Review

Gemini runtime wrapper for `/study-review`. Start from `.agents/shared/commands/study-review-startup.md`; load later phase files only when that phase is reached. This file adds only Gemini-specific runtime constraints.

## Gemini Runtime Constraints

### Session Start

Execute the shared `study_memory.py startup-recall` command exactly as specified. Read `startup_recall` and `planning_brief` before teaching, including `artifact_alignment` for doc review. Do not substitute a raw `summary` call or skip the returned routing checkpoint.

Startup is silent. Do not announce the workflow or send intermediary progress updates while locating the document, reading the contract/document, running `startup-recall`, checking Anki overlay status, or setting `SESSION_TS`; open with one clinical question unless blocked. At most include one short orientation clause. Do not narrate `handoff.summary` or list prior-session topics.

### Per-Turn Sequence (mandatory, after every assessed clinical answer)

Load `.agents/shared/commands/study-review-turn.md` once, after the first assessed answer; it governs every later turn. After the learner answers an assessed clinical question and you grade/correct, execute this sequence silently before asking the next question:

1. **Log the answer**: `python3 src/study_memory.py log-answer ...`. Read the output — it prints `OK exchange_id=N` and a self-sufficient `policy=...` line; obey the policy for the next question.
2. **Enqueue Anki cards** if warranted using `python3 src/anki_queue.py enqueue ...` and the exchange_id from logging.

Both steps use the same `SESSION_TS`. Do not defer enqueue to session end — cards must be enqueued per turn so the queue reflects the full session.

### Session End

Load `.agents/shared/commands/study-review-end.md` and follow it in full and in order. Do not skip ahead to the Anki queue:

1. **Synthesis challenge**: ask the closing metacognitive question per the shared contract (not a tracked claim).
2. **End session**: `python3 src/study_memory.py end-session --session "$SESSION_TS" --summary "..." --next-strategy "..." --stats-json '<json>' --json`. The `--next-strategy` must be specific and actionable. Read `curation.recommended` silently.
3. **Integrity check**: verify all assessed exchanges were logged; run any missing `log-answer` before closing.
4. **Anki queue** (only after `end-session`):
   - `python3 src/anki_queue.py review --session "$SESSION_TS" --json`
   - `python3 src/anki_queue.py check --session "$SESSION_TS"` — mandatory duplicate-candidate and quality-warning review
   - `python3 src/anki_queue.py flush --session "$SESSION_TS"`
5. **Curation**: if `curation.recommended=true` after the flush, load `.agents/shared/commands/memory-curation.md` and run the curation and escalation pass.

All Anki card work uses `anki_queue.py`. There is no other pipeline.
