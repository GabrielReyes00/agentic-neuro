---
description: Audit or reorganize the live neurosurgery Anki deck with approval before mutation.
argument-hint: [audit|rewrite|move|deduplicate|rebuild-cache]
---

# Anki Maintenance

The user invoked `/anki-maintenance` with: $ARGUMENTS

Resolve the plugin root from this command file. Read `resources/AGENTS.md`,
`resources/.agents/shared/runtime/anki-maintenance.json`, and
`resources/.agents/shared/commands/workflow-runtime.md`, then the entry
contracts: `resources/.agents/shared/commands/anki-deck-maintenance.md`. These are generated mirrors of the canonical
`.agents/shared/commands/` contracts. Load later contracts only after a declared
transition.
