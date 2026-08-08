---
description: Alias a service-rotation debrief to the Shift Debrief workflow.
argument-hint: [de-identified-service-lessons]
---

# Service Log

The user invoked `/service-log` with: $ARGUMENTS

Resolve the plugin root from this command file. Read `resources/AGENTS.md`,
`resources/.agents/shared/runtime/service-log.json`, and
`resources/.agents/shared/commands/workflow-runtime.md`, then the entry
contracts: `resources/.agents/shared/commands/service-log.md`, `resources/.agents/shared/commands/shift-debrief.md`. These are generated mirrors of the canonical
`.agents/shared/commands/` contracts. Load later contracts only after a declared
transition.
