---
description: Answer a bounded bedside task or immediate clinical decision; durable capture is optional.
argument-hint: [clinical-question-or-task]
---

# Consult

The user invoked `/consult` with: $ARGUMENTS

Resolve the plugin root from this command file. Read `resources/AGENTS.md`,
`resources/.agents/shared/runtime/consult.json`, and
`resources/.agents/shared/commands/workflow-runtime.md`, then the entry
contracts: `resources/.agents/shared/commands/consult.md`. These are generated mirrors of the canonical
`.agents/shared/commands/` contracts. Load later contracts only after a declared
transition.
