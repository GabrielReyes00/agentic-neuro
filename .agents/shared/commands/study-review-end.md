# Study Review End

Load when the session is ending. This phase writes the handoff, flushes Anki, and optionally curates memory.

## Synthesis Challenge

Before summarizing, ask Gabriel: "What are the 2-3 most important things from this session, and one thing you're still uncertain about?"

This is not a tracked claim. Use the answer to shape the session summary and next strategy.

## End Session

Run silently:

```bash
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "<1-3 sentence session summary>" \
  --next-strategy "<specific concepts, error types, and next teaching moves>" \
  --stats-json '<json>' \
  --json
```

`--next-strategy` must be actionable. Name the concept, gap, and next move. Do not write generic handoffs like "continue reviewing."

Read the JSON silently and remember `curation.recommended`.

## Integrity Check

Verify enough assessed exchanges were logged. If a clinical exchange was missed, run the missing `log-answer` before closing. If the handoff is generic, rerun `end-session` with a specific next strategy.

## Anki Review, Check, Flush

Run after `end-session`:

```bash
python3 src/anki_queue.py review --session "$SESSION_TS" --json
python3 src/anki_queue.py check --session "$SESSION_TS"
python3 src/anki_queue.py flush --session "$SESSION_TS"
```

Read queue output silently. Surface only useful counts or blockers: queued, created, duplicates needing review, failed cards, or unavailable AnkiConnect.

## Curation and Escalation

If `curation.recommended=true` after Anki flush, or if you logged a `correct=2` score on a concept associated with an active curation summary or relationship from startup, run the curation and escalation pass. Load `.agents/shared/commands/memory-curation.md` to execute the curation audit and write the new escalation summaries. If neither condition is met, stop.

