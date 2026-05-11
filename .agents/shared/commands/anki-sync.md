# Anki Sync

Manual flush, review, and card creation for the Anki pipeline.

## What this skill is NOT

This is **not** the primary card-creation pathway during study sessions. Cards are enqueued automatically as Gabriel studies: every `log-answer` call is followed by an `anki_queue.py enqueue` call, and the queue is flushed at session end. You do not need to run this skill at the end of a study session -- that already happened.

Use this skill only when Gabriel explicitly asks to:

- Manually flush right now (outside a study session).
- See what's pending in the queue.
- Create cards from scratch for a specific topic (not during a study session).

## Trigger phrases

- "flush the Anki queue", "push pending cards to Anki", "sync Anki now"
- "what's pending for Anki", "show the card queue"
- "make cards for [topic]", "save to Anki"

## Default workflow (manual flush)

1. **Check pending.**

   ```bash
   cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
   python3 src/anki_queue.py review
   ```

   If queue is empty, say so and stop.

2. **Novelty check.**

   ```bash
   python3 src/anki_queue.py check
   ```

   Review any duplicates surfaced. If genuinely duplicate, remove: `python3 src/anki_queue.py remove --claim-id "<id>"`. If the queued card tests something the matched card does not, keep it.

3. **Flush.**

   ```bash
   python3 src/anki_queue.py flush
   ```

   Report: cards created, duplicates filtered, decks touched. If AnkiConnect is unavailable, say so -- the queue persists and will flush next time.

## Card creation (on explicit request)

When Gabriel asks to create cards for a specific topic (not during a study session), generate cards following the shared learning contract's card rules and enqueue them:

```bash
python3 src/anki_queue.py enqueue \
  --session "manual" --exchange-id 0 \
  --deck "Neurosurgery::<Domain>::<Topic Title>" \
  --card-type <cloze|qa> \
  --topic "<topic>" --concept "<concept>" \
  --cloze "<text>" --answer "<text>" \
  --tags "anki-sync"
```

Then run the check and flush steps above.

## Hard rules

- Never edit `data/Sessions/anki_queue.jsonl` directly. The Python layer owns its format.
- Deck naming: `Neurosurgery::<Domain>::<Topic>`. Valid domains: Vascular, Trauma, Tumor, Spine, Functional, Pediatric, Peripheral Nerve, Anatomy, General.
- If AnkiConnect is unavailable, the queue stays intact. Do not "repair" by clearing the queue file.

## Finish

Concise one-screen summary: queue size, cards created, cards deduped, decks touched. One line per number. If everything was a no-op, say so in one sentence.
