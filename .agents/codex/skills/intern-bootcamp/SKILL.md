---
name: intern-bootcamp
description: Use when Gabriel asks for /intern-bootcamp, intern-bootcamp, intern bootcamp, internbootcamp, bootcamp, night-float drill, cross-cover simulation, or PGY-1 neurosurgery triage practice; follows the shared agent-agnostic command contract.
---

# Intern Bootcamp

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/intern-bootcamp.md`

When this skill triggers:

1. Read `.agents/shared/commands/intern-bootcamp.md`.
2. Follow that shared contract for workflow, behavior, artifacts, and capture.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/intern-bootcamp`.

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Use the shared contract's non-autologging instructions when answer or transfer capture is required.
