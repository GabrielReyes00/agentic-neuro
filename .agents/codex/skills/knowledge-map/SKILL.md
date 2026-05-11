---
name: knowledge-map
description: Use when Gabriel asks for /knowledge-map, knowledge-map, knowledge map, gaps, dashboard, ACGME readiness, learner progress, due review items, or the review queue; follows the shared agent-agnostic command contract.
---

# Knowledge Map

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/knowledge-map.md`

When this skill triggers:

1. Read `.agents/shared/commands/knowledge-map.md`.
2. Follow that shared contract for workflow, behavior, artifacts, and capture.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/knowledge-map`.

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Use the shared contract's non-autologging instructions when answer or transfer capture is required.
