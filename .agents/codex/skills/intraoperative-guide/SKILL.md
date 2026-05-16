---
name: intraoperative-guide
description: Use when Gabriel asks for /intraoperative-guide, intraoperative guide, operative guide, or the related workflow; follows the shared agent-agnostic command contract. Deep-research operative rehearsal guide with procedure decomposition, structured source-card RAG, coverage ledger, budgeted operative knowledge map, verified Obsidian wikilinks, expert review, targeted gap repair, readable formatting, and Mastery Objectives.
---

# Intraoperative Guide

This Codex skill is a thin adapter. The source of truth is:

`.agents/shared/commands/intraoperative-guide.md`

When this skill triggers:

1. Read `.agents/shared/commands/intraoperative-guide.md`.
2. Treat the shared contract as a modular deep-research orchestrator with context-budget controls and structured artifact handoffs. Reload its referenced decomposition, crosslink, research, operative knowledge-map, synthesis, expert review, gap-repair, and finalization modules when each checkpoint is reached.
3. Do not write a real vault guide until the operative knowledge map has been reviewed and expert completeness review approves the draft.
4. Follow the shared contract for workflow, behavior, artifacts, and capture.
5. Do not duplicate or reinterpret the canonical command here.
6. If the shared command conflicts with general agent posture, the shared command wins for `/intraoperative-guide`.

Codex-specific note: there is no Gemini/Claude autologging hook in this runtime unless one is explicitly configured. Use the shared contract's non-autologging instructions when answer or transfer capture is required.
