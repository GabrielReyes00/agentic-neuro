---
name: generate-report
description: Use when Gabriel asks for /generate-report, generate report, or the related workflow. Encyclopedic, citation-dense neurosurgical reference report — textbook-chapter ambition, structured source-card research, coverage ledger, synthesis map, validator gate, vault write. Follows the shared agent-agnostic command contract.
---

# Generate Report

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/generate-report.md`

When this skill triggers:

1. Read `.agents/shared/commands/generate-report.md`.
2. Follow that shared contract and its referenced report modules for workflow, behavior, artifacts, and capture.
3. Do not duplicate or reinterpret the canonical command here.
4. If the shared command conflicts with general agent posture, the shared command wins for `/generate-report`.

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Use the shared contract's non-autologging instructions when answer or transfer capture is required.
