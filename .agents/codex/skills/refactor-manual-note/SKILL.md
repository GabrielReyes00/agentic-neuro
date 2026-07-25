---
name: refactor-manual-note
description: Use when Gabriel asks for /refactor-manual-note, or to refactor / clean up / polish / format a raw manual study note (grand rounds, lecture, clinical discussion) into an active-recall-friendly Obsidian note. Rewrites the source note in place using subject-first hierarchy, selective visual curation, Mermaid/wikilink render guardrails, discrimination tables, and bottom YAML. Follows the shared agent-agnostic command contract.
---

# Refactor Manual Note

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/refactor-manual-note.md`

When this skill triggers:

1. Read `.agents/shared/commands/refactor-manual-note.md`.
2. Follow that shared contract for structure, selective visual curation, render guardrails, wikilink rules, and bottom YAML.
3. Refactor the source note in place — overwrite the file at its existing path; do not create a new file, rename, or add a `(Refactored)` suffix.
4. Do not duplicate or reinterpret the canonical command here.
5. If the shared command conflicts with general agent posture, the shared command wins for `/refactor-manual-note`.
