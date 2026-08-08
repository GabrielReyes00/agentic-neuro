# Anki Session Workflow

Single-purpose contract for Anki card generation, queue validation, and session flush.

Card quality, cloze policy, deck taxonomy, and duplicate judgment are governed by `.agents/shared/commands/anki-card-quality.md`. Read that file before drafting or validating queued cards.

Live deck rewrites, taxonomy cleanup, and vector cache rebuilds are governed by `.agents/shared/commands/anki-deck-maintenance.md`, not by this routine session workflow.

## Per-Answer Card Decision

For `study-review`, include one explicit `card_decision` in the same typed
`assess-turn` transaction as the exchange. Other legacy learning workflows make
the decision immediately after `log-answer`. A low score is evidence to
consider, not an automatic card mandate.
Protect durable, clinically useful memory traces; do not convert every miss into
Anki merely to satisfy a structural check.

Prefer `enqueue` for one to three atomic cards when the exchange exposed:

- an unstable threshold, dose, or time window;
- a dangerous exception or complication-recognition cue;
- a management-changing discriminator;
- a mechanism or anatomy-risk link that supports transfer; or
- a corrected trace likely to recur and worth spaced retrieval.

Use an explicit skip decision for routine correct recall, a trace already
protected by an equivalent live card, incidental low-value detail, or a
conversation that did not establish a durable testable trace. A score 0 or 1
may still be skipped when the miss was incidental, conflated, immediately
superseded, or better retested in context; record why.

Legacy paths use the `exchange_id` printed by `log-answer` and record exactly
one decision with `record-card-decision`. `study-review` does not run this
separate command because `assess-turn` persists the decision atomically.

```bash
python3 src/study_memory.py record-card-decision \
  --session "$SESSION_TS" --exchange-id <id> \
  --decision <enqueue|skip_routine_correct|skip_equivalent|skip_low_value|skip_not_durable|defer_unavailable> \
  --rationale "<required for every skip or defer>"
```

Then use the same exchange id for any enqueue. `enqueue` needs no rationale,
but it is incomplete until at least one linked card exists.

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
- Exception: portable cards from evaluated Shift Debrief Socratic turns, or during `/study-review` anchored to a `Shift Debriefs/` artifact, use `Neurosurgery::Shift Debriefs` with tag `shift-debrief` to keep lived-experience-origin teaching distinct from textbook/source-heavy decks. Site-local service conventions use `Neurosurgery::Service Learning`, service/site tags, and wording that preserves the local boundary.
- Do not create Anki cards during initial Shift Debrief capture; pending candidates become card-eligible only after evaluated learner answers.
- Tags: `<skill>,<error_type>` comma-separated, omitting error type if correct.
- Pass accurate `--topic` and `--concept` values at enqueue time. During flush, `anki_queue.py` adds stable metadata tags for future feedback retrieval: `topic/<slug>`, `concept/<slug>`, and `claim/<claim_id>`. Do not manually add, rewrite, or remove these stable tags. Preserve provenance tags such as `shift-debrief`, service/site tags, and workflow tags because they let startup recall keep formal, portable, and service-local Anki signals separate.

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

1. **Pre-Validation Eligibility Audit**:
   Review each assessed exchange as a question/answer pair and apply the
   Per-Answer Card Decision above. Every exchange needs one persisted decision.
   `enqueue` needs a linked card; every skip/defer needs a rationale and no
   queued card. The purpose is to prevent missed high-value traces while keeping
   low-value or duplicate material intentionally card-free.

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
   - **Card-Decision Guardrail**: `card_decision_blockers` means an assessed
     exchange lacks a decision, an `enqueue` decision lacks a linked card, or a
     skip decision conflicts with a queued card. Resolve that exact mismatch.
     Do not create a card solely to clear the guard when an explicit skip with a
     truthful rationale is the better learning decision.

4. Flush to Anki:

   ```bash
   python3 src/anki_queue.py flush --session "$SESSION_TS"
   ```

   `flush` re-runs duplicate gates silently and prints only its compact final JSON. It refuses to proceed if unresolved duplicate candidates remain. Use `--allow-duplicate-candidates` only after reviewing every candidate from `check` and judging remaining candidates false positives.

5. If AnkiConnect is unavailable, note it; the queue persists and can flush next session.

Anki queue stdout is internal bookkeeping. The learner-facing closeout should report only useful counts and blockers, for example queued, created, duplicates requiring review, failed, and unavailable AnkiConnect.
