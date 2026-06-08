---
description: Memory-enabled Socratic review from a vault document or weak-spot queue.
argument-hint: [topic-or-document-or-review-request]
---

# Study Review

The user invoked `/study-review` with: $ARGUMENTS

Read and follow `.agents/shared/commands/study-review-startup.md`.

Load later phase contracts only when needed: `.agents/shared/commands/study-review-turn.md` after the first assessed answer, `.agents/shared/commands/study-review-vault-repair.md` for point-of-need Obsidian supplementation, and `.agents/shared/commands/study-review-end.md` at wrap-up.

At startup, run the shared `study_memory.py startup-recall` command and read `startup_recall` plus `planning_brief` before teaching. Do not substitute raw `summary` for session initialization.

Startup is silent. Do not announce the workflow or send intermediary progress updates while locating the document, reading the contract/document, running `startup-recall`, checking Anki overlay status, or setting `SESSION_TS`; open with one clinical question unless blocked. At most include one short orientation clause. Do not narrate `handoff.summary` or list prior-session topics.

This command writes no vault artifact. The memory layer is the durable record.
