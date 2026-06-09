---
name: anki-deck-maintenance
description: Use when cleaning, rewriting, reorganizing, deduplicating, auditing, or rebuilding the current Neurosurgery Anki deck. Preserves review history and rebuilds the SQLite vector cache from live Anki.
---

# Anki Deck Maintenance

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/anki-deck-maintenance.md`

When this skill triggers:

1. Read `.agents/shared/commands/anki-deck-maintenance.md`.
2. Also read `.agents/shared/commands/anki-card-quality.md`.
3. Treat live Anki as ground truth and the SQLite vector cache as a rebuildable advisory cache.
4. Preserve scheduling history by updating notes and moving cards in place whenever possible.
