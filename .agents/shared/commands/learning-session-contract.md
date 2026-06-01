# Shared Learning Session Contract

Use this orchestration contract from any command that teaches, drills, simulates, or writes a review artifact.

This file is intentionally thin. The detailed rules live in focused shared modules so each policy has one home.

## Required Modules

Read the modules that apply to the workflow before acting:

| Module | Scope |
|---|---|
| `.agents/shared/commands/memory-operations.md` | Session start, topic/global summary selection, `log-answer`, `end-session`, integrity verification, invisible bookkeeping, entry formatting |
| `.agents/shared/commands/memory-retrieval.md` | How to interpret cards, learner graph signals, model surfaces, context surfaces, and truncation metadata |
| `.agents/shared/commands/adaptive-teaching-doctrine.md` | Socratic teaching behavior, cognitive friction, progressive reveal, repair/retest logic |
| `.agents/shared/commands/anki-session-workflow.md` | Per-answer card decisions, queue review, duplicate checking, Anki flush |
| `.agents/shared/commands/anki-card-quality.md` | Card quality, cloze policy, deck taxonomy, duplicate judgment |
| `.agents/shared/commands/memory-curation.md` | Optional post-flush curated summaries, learner graph edges, and shadow rules |
| `.agents/shared/commands/review-artifacts.md` | Vault artifact destinations, generated dashboard/readiness surfaces, cleanup |

## Core Sequence

For full learning workflows, execute the modules in this order:

1. **Session start**: follow `memory-operations.md` for topic-scoped versus global retrieval. Always use `--include-curated --include-model` for skill-driven summaries.
2. **Memory interpretation**: follow `memory-retrieval.md` before designing questions. If high-signal cards were omitted, run a suggested expansion command before teaching.
3. **Teaching loop**: follow `adaptive-teaching-doctrine.md`. Ask one question, stop, wait for the learner, evaluate, reveal progressively, and choose the next teaching move.
4. **After each answer**: log the evaluated exchange with `study_memory.py log-answer` per `memory-operations.md`; then decide whether to enqueue Anki cards per `anki-session-workflow.md` and `anki-card-quality.md`.
5. **Session end**: run `study_memory.py end-session --json` and the post-session integrity checks per `memory-operations.md`.
6. **Anki completion**: run queue review, `check`, and `flush` per `anki-session-workflow.md`.
7. **Optional curation**: if `end-session --json` reported `curation.recommended = true`, run the post-flush curation pass in `memory-curation.md`.
8. **Artifacts and cleanup**: follow the workflow-specific command contract plus `review-artifacts.md`.

`memory-maintenance.md` is not part of this sequence. Use it only for deliberate identity audits, reviewed topic merges, telemetry audits, or reference-graph loading.

## Routing Notes

- `study-review`, `consult`, and `study-material` usually need all modules above, unless their command contract explicitly narrows the behavior.
- `quick-answer` intentionally does not use this contract; it has its own lightweight contract at `.agents/shared/commands/quick-answer.md`.
- `brain-dump` captures de-identified service teaching as an artifact anchor and does not become an assessed learning session unless the learner chooses subsequent `study-review`.
- Reference-generating workflows such as `generate-report`, `intraoperative-guide`, and `grand-rounds` may use learner memory for context and artifacts for downstream review, but their specific command contracts control depth, citations, and artifact validation.

## Conflict Resolution

If this orchestration file conflicts with a focused module, the focused module wins for its scope.

If a workflow-specific command conflicts with a focused module, the workflow-specific command wins only for its explicitly specialized behavior; shared memory, Anki, curation, and cleanup mechanics still come from the focused modules unless the workflow contract says otherwise.
