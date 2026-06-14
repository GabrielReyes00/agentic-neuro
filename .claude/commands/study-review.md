---
name: study-review
description: Socratic review from an existing vault document (Reports/, Study Material/, or Brain Dumps/) — memory-enabled, doc-anchored, no vault artifact.
---

# Study Review

Read and follow `.agents/shared/commands/study-review-startup.md` for startup. Load `.agents/shared/commands/study-review-turn.md` after the first assessed answer, `.agents/shared/commands/study-review-vault-repair.md` only at point of need, and `.agents/shared/commands/study-review-end.md` only at wrap-up.

At session start, execute the shared `study_memory.py startup-recall` command exactly as specified. Read `startup_recall` and `planning_brief` before teaching, including `artifact_alignment` for doc review. Do not substitute a raw `summary` call or skip the returned routing checkpoint.

Startup is silent. Do not announce the workflow or send intermediary progress updates while locating the document, reading the contract/document, running `startup-recall`, checking Anki overlay status, or setting `SESSION_TS`; open with one clinical question unless blocked. At most include one short orientation clause. Do not narrate `handoff.summary` or list prior-session topics.
