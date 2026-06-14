---
name: consult
description: Use when Gabriel asks for /consult, consult, how to perform a bedside task, or a bounded clinical decision ("when do you", "which X warrants Y"). Curbside consult — agent-chosen shape (procedure walk-through or decision/indication logic), verification questions, Anki cards, pocket-card vault note in Consults/. Follows the shared agent-agnostic command contract.
---

# Consult

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/consult.md`

When this skill triggers:

1. Read `.agents/shared/commands/consult.md`.
2. Follow that shared contract for workflow, behavior, artifacts, and capture.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/consult`.

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Use the shared contract's non-autologging instructions when answer or transfer capture is required.
