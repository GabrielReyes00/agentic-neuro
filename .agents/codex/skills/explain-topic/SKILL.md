---
name: explain-topic
description: Use when Gabriel asks for /explain-topic, explain topic, or the related workflow; follows the shared agent-agnostic command contract. Expert mechanistic explanation at brief, standard, or deep depth.
---

# Explain Topic

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/explain-topic.md`

When this skill triggers:

1. Read `.agents/shared/commands/explain-topic.md`.
2. Follow that shared contract for workflow, behavior, artifacts, and capture.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/explain-topic`.

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Use the shared contract's non-autologging instructions when answer or transfer capture is required.
