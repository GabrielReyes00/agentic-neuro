---
name: rag-workflow
description: Use when Gabriel asks for /rag-workflow, rag workflow, or the related workflow; follows the shared agent-agnostic command contract. Textbook-grounded RAG synthesis with gap check and Socratic follow-up.
---

# Rag Workflow

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/rag-workflow.md`

When this skill triggers:

1. Read `.agents/shared/commands/rag-workflow.md`.
2. Follow that shared contract for workflow, behavior, artifacts, and capture.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/rag-workflow`.

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Use the shared contract's non-autologging instructions when answer or transfer capture is required.
