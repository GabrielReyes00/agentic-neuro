# Anki Session Workflow

Single-purpose contract for Anki card generation, queue validation, and session flush.

Card quality, cloze policy, deck taxonomy, and duplicate judgment are governed by `.agents/shared/commands/anki-card-quality.md`. Read that file before drafting or validating queued cards.

Live deck rewrites, taxonomy cleanup, and vector cache rebuilds are governed by `.agents/shared/commands/anki-deck-maintenance.md`, not by this routine session workflow.

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
- Exception: portable cards from evaluated Brain Dump Socratic turns, or during `/study-review` anchored to a `Brain Dumps/` artifact, use `Neurosurgery::Brain Dumps` with tag `brain-dump` to keep lived-experience-origin teaching distinct from textbook/source-heavy decks. Site-local service conventions use the service-learning routing defined in `brain-dump.md`/`service-log.md`.
- Do not create Anki cards during initial Brain Dump capture; pending candidates become card-eligible only after evaluated learner answers.
- Tags: `<skill>,<error_type>` comma-separated, omitting error type if correct.
- Pass accurate `--topic` and `--concept` values at enqueue time. During flush, `anki_queue.py` adds stable metadata tags for future feedback retrieval: `topic/<slug>`, `concept/<slug>`, and `claim/<claim_id>`. Do not manually add, rewrite, or remove these stable tags. Preserve provenance tags such as `brain-dump`, service/site tags, and workflow tags because they let startup recall keep formal, portable, and service-local Anki signals separate.

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

1. **Pre-Validation Extraction Audit**:
   Before reviewing or checking the queue, the agent must perform a systematic, turn-by-turn audit of every single Q&A exchange from the session (reviewing the agent's question/teaching and the learner's response together as a pair):
   - For each turn, verify: *"Did we draft cards that encapsulate all critical nominal and quantitative facts in this exchange (e.g., anatomical structures, surgical procedures, drug names, dosage numbers, threshold windows, and named classifications)?"*
   - If an important clinical threshold, anatomical structure, or key diagnostic/management discriminator was discussed but has NO enqueued card, the agent MUST immediately run `anki_queue.py enqueue` to draft the missing card for that specific exchange.
   - Once every turn has been audited and verified to have been "Anki extracted", continue to the steps below.

2. Review queued cards:

   ```bash
   python3 src/anki_queue.py review --session "$SESSION_TS" --json
   ```

   Parse the compact JSON silently. Verify every queued card for atomicity, numbers/thresholds/dosages, and match to discussed material. Rewrite or remove true problems before flushing. Do not paste the review JSON into the learner-facing transcript.

3. Run duplicate and quality check:

   ```bash
   python3 src/anki_queue.py check --session "$SESSION_TS"
   ```

   Parse the compact JSON silently and surface only actionable blockers or final counts.
   - **Duplicate Candidates**: If `duplicate_candidates` is non-empty, compare by tested memory trace, not wording. Remove true duplicates with `python3 src/anki_queue.py remove --claim-id "<id>"`. Keep false positives when the queued card tests something the existing card does not.
   - **Uncarded Misses Guardrail**: If `quality_warnings` contains `uncarded_missed_exchange`, this means a concept logged in SQLite as a miss (`score < 2`) lacks an enqueued card. **The agent is structurally blocked from completing the session** and MUST run the corresponding `enqueue` command for the missing exchange before proceeding.

4. Flush to Anki:

   ```bash
   python3 src/anki_queue.py flush --session "$SESSION_TS"
   ```

   `flush` re-runs duplicate gates silently and prints only its compact final JSON. It refuses to proceed if unresolved duplicate candidates remain. Use `--allow-duplicate-candidates` only after reviewing every candidate from `check` and judging remaining candidates false positives.

5. If AnkiConnect is unavailable, note it; the queue persists and can flush next session.

Anki queue stdout is internal bookkeeping. The learner-facing closeout should report only useful counts and blockers, for example queued, created, duplicates requiring review, failed, and unavailable AnkiConnect.
