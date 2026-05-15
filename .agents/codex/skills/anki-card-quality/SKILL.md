---
name: anki-card-quality
description: Use when creating, reviewing, validating, deduplicating, or cleaning Neurosurgery Anki cards. Short focused rules for card quality, cloze policy, deck taxonomy, and duplicate judgment.
---

# Anki Card Quality

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/anki-card-quality.md`

When this skill triggers:

1. Read `.agents/shared/commands/anki-card-quality.md`.
2. Apply it before enqueueing, reviewing, checking, flushing, editing, moving, suspending, or deleting Anki cards.
3. Do not duplicate or reinterpret the canonical card-quality rules here.
4. If this skill conflicts with a workflow contract, use the shared command file as the card-quality authority and the workflow contract for session mechanics.
