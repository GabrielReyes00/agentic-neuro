---
description: Refactor a manual Obsidian note in place with optional answering, expansion, verification, distillation, and visualization.
argument-hint: [note-path] [answer] [expand] [verify] [distill] [visualize] [audience=...] [depth=...] [focus=...]
---

# Refactor Manual Note

The user invoked `/refactor-manual-note` with: $ARGUMENTS

Resolve the plugin root from this command file. Read `resources/AGENTS.md`,
`resources/.agents/shared/runtime/refactor-manual-note.json`, and
`resources/.agents/shared/commands/workflow-runtime.md`, then the entry
contracts: `resources/.agents/shared/commands/refactor-manual-note.md`. These are generated mirrors of the canonical
`.agents/shared/commands/` contracts. Load later contracts only after a declared
transition.
