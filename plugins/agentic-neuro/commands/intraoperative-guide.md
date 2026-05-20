---
description: Generate a deep-research neurosurgical operative rehearsal guide targeting 85% resident mastery — Coverage Matrix decomposition, structured source-card RAG, coverage ledger, budgeted knowledge map, dedicated map-completeness and expert-completeness reviewer subagents, verdict-chain audit, targeted gap-repair escalation, verified Obsidian wikilinks, and Mastery Objectives.
argument-hint: [procedure]
---

# Intraoperative Guide

The user invoked `/intraoperative-guide` with: $ARGUMENTS

Read and follow `.agents/shared/commands/intraoperative-guide.md`. That file is the orchestrator for a modular deep-research workflow with context-budget controls and structured artifact handoffs; reload the referenced decomposition, crosslink, research, knowledge-map, **map-completeness review (separate subagent)**, synthesis, **expert completeness review (separate subagent)**, gap-repair, and finalization modules at their checkpoints instead of trying to hold the whole workflow in context from the start.

Use `.agents/shared/commands/learning-session-contract.md` for the module map. Use `memory-operations.md`, `memory-retrieval.md`, `review-artifacts.md`, `anki-session-workflow.md`, and `anki-card-quality.md` for shared memory, artifact, and Anki rules.

Do not write the real guide until:

1. Decomposition has produced a Coverage Matrix anchoring the 85% resident-mastery depth target.
2. The operative knowledge map has been approved by the map-completeness reviewer subagent (`MAP_APPROVED` verdict written to `data/Sessions/<Title>/verdicts/`).
3. The expert completeness reviewer subagent — separate from the writer — has returned `APPROVED` with its own fresh attending-defense questions answered.
4. The finalize module has verified the full verdict chain.

Then write to `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/<Title>.md`, validate it with `src/operative_guide_validator.py`, and revise until the validator passes. The validator is structural and wikilink-aware; the subagent reviewers are the semantic completeness gates. Route any generated Anki cards to `Neurosurgery::Procedures::<Title>`.
