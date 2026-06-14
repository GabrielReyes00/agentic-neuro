---
name: study-review
description: Use when Gabriel asks for /study-review, study review, or the related workflow; follows the shared agent-agnostic command contract. Memory-enabled Socratic review from an existing vault document or memory-driven weak-spot queue.
---

# Study Review

This Codex skill is a thin adapter. The startup source of truth is:

`.agents/shared/commands/study-review-startup.md`

When this skill triggers:

1. Read `.agents/shared/commands/study-review-startup.md`.
2. Follow that phase contract through the first learner-facing question.
3. After the first assessed answer, load `.agents/shared/commands/study-review-turn.md`.
4. Load `.agents/shared/commands/study-review-vault-repair.md` only at point of need, and `.agents/shared/commands/study-review-end.md` only at wrap-up.

Startup is silent. Do not announce that you are using this skill, and do not send intermediary progress updates while locating the document, reading the contract/document, running `startup-recall`, checking Anki overlay status, or setting `SESSION_TS`. If startup succeeds, the first learner-facing response should be one clinical question, with at most one short orientation clause. Do not narrate `handoff.summary` or list prior-session topics.

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Follow the phase contracts directly: run `study_memory.py startup-recall` at session start, read `startup_recall` plus `planning_brief` including `artifact_alignment` for doc review, log every assessed clinical answer after the learner responds, enqueue Anki cards per turn when warranted, and close with `end-session --json`.
