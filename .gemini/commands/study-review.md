---
name: study_review
description: Socratic review from an existing vault document (Reports/, Study Material/, or Brain Dumps/) — memory-enabled, doc-anchored, no vault artifact.
---

# Study Review

Gemini runtime wrapper for `/study-review`. The canonical contract lives in `.agents/shared/commands/study-review.md`; follow it for all workflow and behavior. This file adds only Gemini-specific runtime constraints.

## Gemini Runtime Constraints

### Session Start

Execute the shared `study_memory.py startup-recall` command exactly as specified. Read `startup_recall` and `planning_brief` before teaching. Do not substitute a raw `summary` call or skip the returned routing checkpoint.

### Per-Turn Sequence (mandatory, after every evaluated answer)

After the learner answers and you grade/correct, execute this two-step sequence silently before asking the next question:

1. **Log the answer**: `python3 src/study_memory.py log-answer ...` per the shared contract. Read the output — it prints `OK exchange_id=N`.
2. **Enqueue Anki cards** (if warranted): `python3 src/anki_queue.py enqueue ...` using the exchange_id from step 1. Follow `.agents/shared/commands/anki-session-workflow.md` and `.agents/shared/commands/anki-card-quality.md` for card rules and when to generate cards.

Both steps use the same `SESSION_TS`. Do not defer enqueue to session end — cards must be enqueued per turn so the queue reflects the full session.

### Session End

At session end, follow the shared contract's Anki Queue Validation and Flush protocol:
1. `python3 src/anki_queue.py review --session "$SESSION_TS" --json`
2. `python3 src/anki_queue.py check --session "$SESSION_TS"` — mandatory duplicate-candidate and quality-warning review
3. `python3 src/anki_queue.py flush --session "$SESSION_TS"`

All Anki card work uses `anki_queue.py`. There is no other pipeline.
