---
name: list-textbooks
description: Use when Gabriel asks for /list-textbooks, list textbooks, or the related workflow; follows the shared agent-agnostic command contract. List all textbooks and sources loaded in the RAG vector database.
---

# List Textbooks

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/list-textbooks.md`

When this skill triggers:

1. Read `.agents/shared/commands/list-textbooks.md`.
2. Follow that shared contract for workflow, behavior, artifacts, and capture.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/list-textbooks`.

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Use the shared contract's non-autologging instructions when answer or transfer capture is required.
