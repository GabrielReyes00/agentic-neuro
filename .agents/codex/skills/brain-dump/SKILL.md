---
name: brain-dump
description: Use when Gabriel asks for a brain dump from shift, ward teaching, or a senior-resident correction for de-identified synthesis, provenance verification, and optional later study review.
---

# Brain Dump

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/brain-dump.md`

When this skill triggers:

1. Read `.agents/shared/commands/brain-dump.md`.
2. Follow that shared contract for de-identification, verification, artifact writing, memory anchor semantics, and optional review.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/brain-dump`.
