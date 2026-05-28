# Anki Session Workflow

Single-purpose contract for Anki card generation, queue validation, and session flush.

Card quality, cloze policy, deck taxonomy, and duplicate judgment are governed by `.agents/shared/commands/anki-card-quality.md`. Read that file before drafting or validating queued cards.

Live deck rewrites, taxonomy cleanup, and Chroma rebuilds are governed by `.agents/shared/commands/anki-deck-maintenance.md`, not by this routine session workflow.

## Per-Answer Card Decision

Immediately after each `log-answer`, decide whether to generate cards for that exchange.

Generate 1-3 atomic cards when:

- `correct < 2`
- `correct == 2` but the answer missed an intern-critical nuance you corrected
- the exchange exposed a high-risk threshold, management-changing distinction, mechanism that explains multiple decisions, or complication where delayed recognition matters

Skip routine correct answers with no teaching extension.

The `log-answer` command prints `OK exchange_id=N`; use that N as `--exchange-id` for queue linkage.

## Mechanical Constraints

- One fact per card, reviewable in under 10 seconds.
- Never omit numbers: doses, thresholds, measurements, rates, or time windows.
- Cloze text max 240 chars; QA answer text max 500 chars.
- Prompt usually <=35 words; Basic backs usually <=45 words.
- Cloze blanks target the testable fact: threshold, drug, structure, classification, or key distinction. Never blank context words, verbs, or preamble.
- Use `{{c1::target}}` for single-blank cloze. Multi-cloze is allowed only when all deletions are tightly related to one concept and each is independently worth testing.
- Cloze answer text is queue-review metadata only and is not written into Anki `Back Extra`.
- QA backs must be self-contained.
- Deck: `Neurosurgery::<Domain>::<Topic Title>`.
- Exception: `/intraoperative-guide` uses `Neurosurgery::Procedures::<Operative Guide Title>`.
- Exception: cards explicitly created from `/brain-dump`, or during `/study-review` anchored to a `Brain Dumps/` artifact, use `Neurosurgery::Brain Dumps` with tag `brain-dump` to keep institution- and lived-experience-origin teaching distinct from textbook/source-heavy decks.
- Tags: `<skill>,<error_type>` comma-separated, omitting error type if correct.

## Enqueue

For cloze cards:

```bash
python3 src/anki_queue.py enqueue \
  --session "$SESSION_TS" --exchange-id <id> \
  --deck "Neurosurgery::<Domain>::<Topic>" \
  --card-type cloze \
  --topic "<session topic>" --concept "<tested concept>" \
  --cloze "<text>" \
  --tags "<skill>,<error_type>"
```

For QA cards:

```bash
python3 src/anki_queue.py enqueue \
  --session "$SESSION_TS" --exchange-id <id> \
  --deck "Neurosurgery::<Domain>::<Topic>" \
  --card-type qa \
  --topic "<session topic>" --concept "<tested concept>" \
  --front "<text>" --back "<text>" \
  --tags "<skill>,<error_type>"
```

## Queue Validation And Flush

Run this after `end-session --json`.

1. Review queued cards:

   ```bash
   python3 src/anki_queue.py review --session "$SESSION_TS"
   ```

   Verify atomicity, numbers/thresholds/dosages, and match to discussed material. Rewrite or remove true problems before flushing.

2. Run duplicate and quality check:

   ```bash
   python3 src/anki_queue.py check --session "$SESSION_TS"
   ```

   If `duplicate_candidates` is non-empty, compare by tested memory trace, not wording. Remove true duplicates with `python3 src/anki_queue.py remove --claim-id "<id>"`. Keep false positives when the queued card tests something the existing card does not.

3. Flush to Anki:

   ```bash
   python3 src/anki_queue.py flush --session "$SESSION_TS"
   ```

   `flush` re-runs duplicate gates and refuses to proceed if unresolved duplicate candidates remain. Use `--allow-duplicate-candidates` only after reviewing every candidate from `check` and judging remaining candidates false positives.

4. If AnkiConnect is unavailable, note it; the queue persists and can flush next session.
