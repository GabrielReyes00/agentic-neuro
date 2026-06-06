---
name: service-log
description: Service-rotation debrief trigger; follow the brain-dump service-memory pathway.
---

# Service Log

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/service-log.md`

When this skill triggers:

1. Read `.agents/shared/commands/service-log.md`.
2. Follow that shared service-debrief contract, which routes capture through `.agents/shared/commands/brain-dump.md` while preserving service-origin memory writes.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/service-log`.
