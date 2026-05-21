---
description: Generate an encyclopedic citation-dense neurosurgical reference report in the Obsidian vault.
argument-hint: [topic]
---

# Generate Report

The user invoked `/generate-report` with: $ARGUMENTS

Read and follow `.agents/shared/commands/generate-report.md`.

Use the report modules referenced by the shared command: query-aware research plan, source cards, coverage ledger, synthesis map, and finalize. Rewrite the user's request into focused retrieval queries before search. Write the report to `Reports/<Title>.md`, include `## Mastery Objectives`, validate the target report with `src/report_validator.py --coverage-ledger`, and log the report anchor to memory per the shared command.
