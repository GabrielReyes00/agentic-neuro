# Grand Rounds Rehearsal

Load only after a completed presentation is saved and Gabriel accepts rehearsal.
Deck creation alone is not learner mastery.

Offer:

- **Faculty Q&A:** adversarial defense of decisions, study interpretation,
  limitations, applicability, and missing must-haves.
- **Talk Run-Through:** slide-by-slide thesis, transitions, pacing, and delivery.

Then read the full presentation note and follow:

- `.agents/shared/commands/memory-operations.md`
- `.agents/shared/commands/memory-retrieval.md`
- `.agents/shared/commands/adaptive-teaching-doctrine.md`
- `.agents/shared/commands/anki-session-workflow.md`
- `.agents/shared/commands/anki-card-quality.md`

Start `study_memory.py startup-recall --profile doc` with the presentation note and
`--skill "grand-rounds"`. Ask one question at a time and stop. Use the deck's
anticipated questions, presentation risks, and What Not To Say material.

For Talk Run-Through, ask Gabriel for the thesis and transition of each slide,
then tighten language and pacing. For Faculty Q&A, require exact denominators,
bounded causal claims, patient applicability, and a defensible practice verdict.

At completion, append dated rehearsal notes through `grand_rounds_writer.py`, run
`end-session` with an actionable next strategy, and review/check/flush any queued
Anki cards. Create cards only from evaluated misses or unstable durable anchors.
