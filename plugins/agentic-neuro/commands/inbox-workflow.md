---
description: Triage email and draft replies with approval before any external mutation.
argument-hint: [inbox-request]
---

# Inbox Workflow

The user invoked `/inbox-workflow` with: $ARGUMENTS

Resolve the plugin root from this command file. Read `resources/AGENTS.md`,
`resources/.agents/shared/runtime/inbox-workflow.json`, and
`resources/.agents/shared/commands/workflow-runtime.md`, then the entry
contracts: `resources/.agents/shared/commands/inbox-workflow.md`. These are generated mirrors of the canonical
`.agents/shared/commands/` contracts. Load later contracts only after a declared
transition.
