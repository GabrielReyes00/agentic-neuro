---
name: grand-rounds
description: Use when Gabriel asks for /grand-rounds, grand rounds, or the related workflow; follows the shared agent-agnostic command contract. Build a neurosurgery grand rounds, case presentation, or journal club deck with PPTX output and vault note.
---

# Grand Rounds

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/grand-rounds.md`

When this skill triggers:

1. Read `.agents/shared/commands/grand-rounds.md`.
2. Follow that shared contract for workflow, behavior, artifacts, and capture.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/grand-rounds`.

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Use the shared contract's non-autologging instructions when answer or transfer capture is required.
