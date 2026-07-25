---
name: grand-rounds
description: Build and validate an editable neurosurgery PowerPoint with speaker notes, source-traced visuals, a vault presentation note, and optional rehearsal. Use when Gabriel asks for /grand-rounds, a case presentation, journal club slides, a PowerPoint from a Journal Club dossier, or a professional neurosurgical presentation deck.
---

# Grand Rounds

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/grand-rounds.md`

When this skill triggers:

1. Read `.agents/shared/commands/grand-rounds.md` completely.
2. Load only the case or article module selected by its router.
3. Read the shared deck module before authoring PowerPoint.
4. Follow the shared contracts for sources, assets, package validation, vault
   persistence, and optional rehearsal.
5. Do not duplicate or reinterpret the canonical workflow here.

Codex-specific note: use the installed Presentations skill and its current
`@oai/artifact-tool` workflow. Render and inspect every slide, run
`src/grand_rounds_guard.py`, and never use `python-pptx` to author the deck.
