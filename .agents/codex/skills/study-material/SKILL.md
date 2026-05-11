---
name: study-material
description: Use when Gabriel asks for /study-material, study material, or the related workflow; follows the shared agent-agnostic command contract. Generate validated Study Material from PDF/PPTX/markdown or drill an existing Study Material note.
---

# Study Material

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/study-material.md`

When this skill triggers:

1. Read `.agents/shared/commands/study-material.md`.
2. Follow that shared contract for workflow, behavior, artifacts, and capture.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/study-material`.

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Use the shared contract's non-autologging instructions when answer or transfer capture is required.
