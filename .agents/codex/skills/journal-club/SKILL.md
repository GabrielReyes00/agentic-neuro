---
name: journal-club
description: Analyze and critically interpret a supplied peer-reviewed neurosurgery article PDF, teach its paper-specific foundations to an intern, reconstruct its decisive results, place it in historical and current neurosurgical context, and create a validated Journal Club mastery dossier with optional guided review or faculty-defense practice. Use when Gabriel asks for /journal-club, journal-club preparation, deep article breakdown, help understanding a paper before presenting it, or preparation to defend an assigned article. Do not use for slide creation; that belongs to grand-rounds.
---

# Journal Club

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/journal-club.md`

When this skill triggers:

1. Read `.agents/shared/commands/journal-club.md` completely.
2. Read its focused analysis and artifact modules at the phases it specifies.
3. Follow the shared contract for PDF inspection, research, teaching posture,
   artifact validation, vault installation, and optional mastery.
4. Do not duplicate or reinterpret the canonical workflow here.
5. Do not route to presentation creation unless Gabriel separately requests a
   slide deck.

Codex-specific note: use the available PDF skill for textual extraction, complete
page rendering, and visual inspection. Use the shared non-autologging learning
instructions if Gabriel opts into mastery.
