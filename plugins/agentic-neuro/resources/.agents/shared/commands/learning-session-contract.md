# Shared Learning Session Contract

Use this orchestration contract from any command that teaches, drills, simulates, or writes a review artifact.

## Required Modules

Read only the modules that apply to the current phase. Do not preload later-phase modules before the first learner-facing question; this keeps startup fast.

| Module | Scope |
|---|---|
| `.agents/shared/commands/study-review-startup.md` + `tutor-state.md` | Typed startup, bounded state, artifact freshness, and first question |
| `.agents/shared/commands/study-review-turn.md` | Atomic multi-claim grading, repair, card disposition, and next question |
| `.agents/shared/commands/study-review-vault-repair.md` | Point-of-need Obsidian repair/contrast |
| `.agents/shared/commands/study-review-end.md` | Integrity-gated close, handoff, Anki flush, and curation |
| `.agents/shared/commands/memory-operations.md` | Legacy compatibility and explicit memory audits; not routine study-review entry |
| `.agents/shared/commands/memory-retrieval.md` | Rich/audit profile interpretation; not routine study-review entry |
| `.agents/shared/commands/vault-intelligence.md` | Optional point-of-need Obsidian section retrieval |
| `.agents/shared/commands/rag-routing.md` | Point-of-need textbook retrieval tier, batching, evidence, and serialization |
| `.agents/shared/commands/adaptive-teaching-doctrine.md` | Tutor voice, teaching modes, field-to-teaching-move mapping, and Socratic voice |
| `.agents/shared/commands/anki-session-workflow.md` | Per-answer card decisions and queue flushing |
| `.agents/shared/commands/anki-card-quality.md` | Card quality, clozes, taxonomy, and duplicate checks |
| `.agents/shared/commands/memory-curation.md` | Post-flush curated summaries, graph edges, and shadow rules |
| `.agents/shared/commands/review-artifacts.md` | Vault artifact destinations and generated dashboards |

## Core Sequence & Graded Release

1. **Pre-Question Minimal Path**:
   - Load the runtime projection, `study-review-startup.md`, and `tutor-state.md`.
   - Run `study_memory.py start-session --stdin`. In document mode, use the artifact map only when its current content hash is verified; otherwise rebuild it from the current document.
   - Ask one clinical question and stop. Use `handoff.next_action` silently; do not quote `handoff.summary` or narrate startup.
2. **Teaching Loop**:
   - Load `study-review-turn.md` and `adaptive-teaching-doctrine.md`.
   - Submit one `study_memory.py assess-turn --stdin` transaction per raw learner response. Independently grade every claim and include one card disposition.
   - Load `anki-card-quality.md` only when that disposition is `enqueue`.
   - If needed, load `vault-intelligence.md`, `study-review-vault-repair.md`, or `rag-routing.md` after the first question.
3. **Session End**:
   - Load `study-review-end.md`; run typed integrity and `close-session --stdin` before deleting ephemeral state.
   - Metacognitive synthesis prompts shape the session handoff rather than tracked claim state.
   - Follow `anki-session-workflow.md` for any queued cards. Load `memory-curation.md` only when recommended.

## Routing Notes

- `study-review` startup uses `.agents/shared/commands/study-review-startup.md`, `tutor-state.md`, and typed `start-session`.
- `consult`, `study-material`, and research/report workflows may retrieve vault context before synthesis when requested.
- `shift-debrief` captures de-identified teaching. It does not become learner state until Socratic review/testing is logged.

## Conflict Resolution

- Workflow-specific commands override shared modules only for specialized behavior; memory/Anki rules remain invariant.
