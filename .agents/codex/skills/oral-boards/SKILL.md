---
name: oral-boards
description: Use when Gabriel asks for /oral-boards, oral boards, or the related workflow; follows the shared agent-agnostic command contract. Neurosurgery oral-board and primary-board case practice with examiner scoring.
---

# Oral Boards

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/oral-boards.md`

When this skill triggers:

1. Read `.agents/shared/commands/oral-boards.md`.
2. Follow that shared contract for workflow, behavior, artifacts, and capture.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/oral-boards`.

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Use the shared contract's non-autologging instructions when answer or transfer capture is required.
