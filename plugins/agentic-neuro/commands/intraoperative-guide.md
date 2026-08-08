---
description: Create and independently review a source-grounded operative rehearsal guide.
argument-hint: [procedure]
---

# Intraoperative Guide

The user invoked `/intraoperative-guide` with: $ARGUMENTS

Resolve the plugin root from this command file. Read `resources/AGENTS.md`,
`resources/.agents/shared/runtime/intraoperative-guide.json`, and
`resources/.agents/shared/commands/workflow-runtime.md`, then the entry
contracts: `resources/.agents/shared/commands/intraoperative-guide.md`, `resources/.agents/shared/commands/intraoperative-guide-decomposition.md`. These are generated mirrors of the canonical
`.agents/shared/commands/` contracts. Load later contracts only after a declared
transition.
