---
name: inbox-workflow
description: Use when Gabriel invokes /inbox-workflow or asks to triage email and draft replies with approval before any external mutation.
---

# Inbox Workflow

Read `.agents/shared/runtime/inbox-workflow.json` and
`.agents/shared/commands/workflow-runtime.md` completely, then the entry
contracts: `.agents/shared/commands/inbox-workflow.md`. Load later contracts only after a
declared transition. Shared contracts own behavior; do not reinterpret them.
