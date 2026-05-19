---
name: quick-answer
description: Use when Gabriel asks for /quick-answer, quick answer, or a brief isolated neurosurgery/neuroanatomy/neurocritical care question that should be answered directly with lightweight memory logging and optional Anki.
---

# Quick Answer

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/quick-answer.md`

When this skill triggers:

1. Read `.agents/shared/commands/quick-answer.md`.
2. Follow that shared contract for workflow, behavior, and capture.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/quick-answer`.

Codex-specific note: this workflow intentionally does not use the shared learning-session contract, does not run startup memory recall, and does not create Anki cards unless Gabriel explicitly asks for them after the answer.
