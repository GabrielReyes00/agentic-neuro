# Shared Learning Session Contract

Use this orchestration contract from any command that teaches, drills, simulates, or writes a review artifact.

## Required Modules

Read only the modules that apply to the current phase. Do not preload later-phase modules before the first learner-facing question; this keeps startup fast.

| Module | Scope |
|---|---|
| `.agents/shared/commands/study-review-startup.md` | Startup only: routing, recall, and first question |
| `.agents/shared/commands/study-review-turn.md` | Per-turn grading, logging, Anki enqueue, and next question |
| `.agents/shared/commands/study-review-vault-repair.md` | Point-of-need Obsidian repair/contrast |
| `.agents/shared/commands/study-review-end.md` | Session end: synthesis, end-session, Anki flush, curation |
| `.agents/shared/commands/memory-operations.md` | Session start, logging, end-session, and integrity checks |
| `.agents/shared/commands/memory-retrieval.md` | Interpreting cards, graph signals, model surfaces, and truncation |
| `.agents/shared/commands/vault-intelligence.md` | Optional point-of-need Obsidian section retrieval |
| `.agents/shared/commands/adaptive-teaching-doctrine.md` | Tutor voice, teaching modes, field-to-teaching-move mapping, and Socratic voice |
| `.agents/shared/commands/anki-session-workflow.md` | Per-answer card decisions and queue flushing |
| `.agents/shared/commands/anki-card-quality.md` | Card quality, clozes, taxonomy, and duplicate checks |
| `.agents/shared/commands/memory-curation.md` | Post-flush curated summaries, graph edges, and shadow rules |
| `.agents/shared/commands/review-artifacts.md` | Vault artifact destinations and generated dashboards |

## Core Sequence & Graded Release

1. **Pre-Question Minimal Path**:
   - Read the command adapter contract and requested doc.
   - Run `study_memory.py startup-recall` and read using `.agents/shared/commands/study-review-startup.md`; for doc review, verify/build `planning_brief.artifact_alignment` before teaching.
   - Ask one clinical question and stop. Use `handoff.next_action` silently; do not quote `handoff.summary` or narrate startup.
2. **Teaching Loop**:
   - Load `study-review-turn.md` and `adaptive-teaching-doctrine.md`.
   - Log to `study_memory.py log-answer` and apply `anki-session-workflow.md`/`anki-card-quality.md`.
   - If needed, load `vault-intelligence.md` / `study-review-vault-repair.md` after the first question.
3. **Session End**:
   - Load `study-review-end.md` and `memory-operations.md` to run the synthesis challenge and duplicate checks.
   - Metacognitive synthesis prompts shape the session handoff rather than tracked claim state.
   - Run `anki_queue.py flush`. If curation is recommended or an active curation is resolved, load `memory-curation.md` for curation and escalation.

## Routing Notes

- `study-review` startup uses `.agents/shared/commands/study-review-startup.md` and `startup-recall`.
- `consult`, `study-material`, and research/report workflows may retrieve vault context before synthesis when requested.
- `brain-dump` captures de-identified teaching. It does not become learner state until Socratic review/testing is logged.

## Conflict Resolution

- Workflow-specific commands override shared modules only for specialized behavior; memory/Anki rules remain invariant.
