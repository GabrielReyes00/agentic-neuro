---
name: study-review
description: Use when Gabriel asks for /study-review, study review, or the related workflow; follows the shared agent-agnostic command contract. Memory-enabled Socratic review from an existing vault document or memory-driven weak-spot queue.
---

# Study Review

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/study-review.md`

When this skill triggers:

1. Read `.agents/shared/commands/study-review.md`.
2. Follow that shared contract for workflow, behavior, artifacts, and capture.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/study-review`.

Codex-specific note: Codex does not use the Gemini `BeforeAgent`/`AfterAgent` hook pair. This repo provides `src/codex_memory_after.py` as a Codex after-turn bridge: it reads Codex rollout transcripts, logs hook-parseable graded replies, queues study-review Anki candidates, and captures repaired transfer when detectable. Pre-session semantic planning still comes from `src/study_review_workflow.py start`; until Codex exposes a supported before-turn `additionalContext` hook, Codex agents must explicitly use the emitted plan/context at session start.
