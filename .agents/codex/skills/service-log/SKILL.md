---
name: service-log
description: Use when Gabriel debriefs a service rotation day ("today on X service at Y, I managed/learned...") to log de-identified service-origin learning and teach the surfaced gap in one pass.
---

# Service Log

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/service-log.md`

When this skill triggers:

1. Read `.agents/shared/commands/service-log.md`.
2. Follow that shared contract for de-identification, rotation resolution, service-lens retrieval, the one-pass teaching turn, service-origin memory writes, and optional isolated Anki.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/service-log`.
