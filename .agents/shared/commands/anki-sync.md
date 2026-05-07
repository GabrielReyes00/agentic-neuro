# Anki Sync

Manual flush + review for the real-time Anki pipeline.

## What this skill is NOT (anymore)

This is **no longer** the primary card-creation pathway. Cards are built
automatically as Gabriel studies: every `record-answer` call enqueues a
candidate, and the queue is drained on a schedule (every ~3 turns via
heartbeat, and once at session end via the post-session hook). You do
not need to run this skill at the end of a session to "make cards" —
that already happened.

Use this skill only when Gabriel explicitly asks to:

- Manually flush right now (outside the automatic cadence).
- See what's pending in the queue and what decks will be touched.
- Pull Anki review stats back into the KG (bidirectional sync) on demand.
- Resynthesize cards for a specific backlog file (legacy / rare).

## Trigger phrases

- "flush the Anki queue", "push pending cards to Anki", "sync Anki now"
- "what's pending for Anki", "show the card queue"
- "pull my Anki review stats", "update the KG from Anki"
- "rebuild cards from [file]" (legacy bulk path — keep as last resort)

## Default workflow (manual flush)

1. **Check pending.** Report queue size and which decks would be touched:

   ```bash
   cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
     python3 src/anki_realtime.py status
   ```

   If `pending` is `0`, say so and skip to step 4 (offer a stats sync).

2. **Preview (optional).** On `--dry-run` Gemini 3 Flash synthesizes cards
   but nothing is dispatched. Useful when Gabriel wants to audit the
   per-error-type cloze templates before they hit Anki.

   ```bash
   python3 src/anki_realtime.py flush --dry-run --skip-anki
   ```

3. **Live flush.** Drain the queue:

   ```bash
   python3 src/anki_realtime.py flush --min-queue 1
   ```

   Report the JSON metrics verbatim: `synthesized`, `deduped`, `created`,
   `duplicates`, `decks_touched`. Any entry under `errors` is a hard
   warning — tell Gabriel AnkiConnect may be down.

## Hard rules

- Never edit `data/Sessions/anki_queue.jsonl` directly. Treat it as
  opaque — the Python layer owns its format.
- Never call AnkiConnect directly from inside a skill turn. All writes
  go through `src/anki_realtime.py` so ChromaDB dedup stays authoritative.
- Models: the synthesis pass always uses Gemini 3 Flash
  (`gemini-3-flash-preview`). Do not swap it.
- Deck naming is fixed at `Neurosurgery::<Domain>::<Topic>`. The nine
  valid domains mirror the KG taxonomy: Vascular, Trauma, Tumor, Spine,
  Functional, Pediatric, Peripheral Nerve, Anatomy, General. Do not
  propose a different scheme on a whim — subsequent dedup and stats
  sync rely on deck stability.
- If AnkiConnect is unavailable, the queue stays intact and the flush
  will retry on the next natural trigger. Do not "repair" by clearing
  the queue file.

## Legacy bulk flow (only if explicitly requested)

The older blind-validated, image-enriched card authoring flow
(`data/Sessions/anki_sync_runs/`) is preserved for one-off backlog work,
e.g. "rebuild cards from this 40-page report". Invoke only on explicit
request. Steps:

1. Write source text to `data/Sessions/current_session_verbatim.txt`.
2. Resolve deck → `data/Sessions/anki_sync_runs/current_topic.json`.
3. Extract atomic claims → `current_claims.json`.
4. `python3 src/anki_sync_cli.py filter_novelty`.
5. Draft cards with blind validation → `final_cards.json`.
6. `python3 src/anki_sync_cli.py validate_final_cards`.
7. Image enrichment (optional) + `process_selected_images`.
8. `python3 src/anki_sync_cli.py dispatch`.

Stop and surface any failure. Do not fall back to the legacy path from
an automatic trigger — only on explicit user instruction.

## Finish

Concise one-screen summary: queue size, cards created, cards deduped,
decks touched, stats sync result. One line per number. No running
commentary. If everything was a no-op (queue empty, nothing to sync),
say so in one sentence.
