# Study Review End

Load when Gabriel asks to stop or the intended material is substantially
covered. This phase commits the handoff before deleting ephemeral state, then
reviews and flushes any queued Anki cards.

## Optional Synthesis

Offer a brief synthesis challenge only after a meaningful session and only when
it adds learning value. Do not force an extra response after Gabriel asks to
stop. A synthesis or self-assessment is not a tracked clinical claim.

## Typed Close

Derive the priority inventory IDs, improved IDs, phase at close, unresolved
claims, and next teaching move from committed exchanges and the live map. Submit:

```bash
python3 src/study_memory.py close-session --stdin
```

```json
{
  "session_id": "<SESSION_TS>",
  "summary": "<specific 1-3 sentence evidence summary>",
  "next_strategy": "<concept/id + remaining gap + next teaching move>",
  "stats": {
    "priority_inventory_ids": [],
    "improved_inventory_ids": [],
    "session_progress": {}
  }
}
```

`next_strategy` must be actionable and inventory-aware when possible. The close
transaction persists the handoff and `study_runtime_sessions=done` before the
ephemeral session map is deleted. If the transaction fails, the map remains for
recovery. Compare the returned handoff skeleton with the requested priorities;
retry with the same session only when a material mismatch exists.

## Integrity And Anki

Before closing, every raw assessed response must have one typed turn envelope,
every graded claim must have a `claim_assessments` row, and every assessed
exchange must have one card decision. Pending adjudications are allowed but must
be named in the handoff and create no learner state.

After close, run the Anki review/check/flush sequence in
`anki-session-workflow.md`. Surface only useful counts and blockers.

If curation is recommended after flush, load `memory-curation.md`. Otherwise
stop with a concise learner-facing synthesis and the next review target.
