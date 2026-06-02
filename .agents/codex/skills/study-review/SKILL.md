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

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Follow the shared contract directly: run `study_memory.py startup-recall` at session start and read `startup_recall` plus `planning_brief`, log every evaluated answer with the current claim-state judgment flags, enqueue Anki cards per turn when warranted, and close with `end-session --json`.
