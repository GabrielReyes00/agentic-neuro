---
name: intraoperative_guide
description: Deep-research neurosurgical operative rehearsal guide targeting 85% resident mastery — Coverage Matrix decomposition, structured source-card RAG, coverage ledger, budgeted knowledge map, dedicated map-completeness and expert-completeness reviewer subagents, verdict-chain audit, targeted gap-repair escalation, verified Obsidian wikilinks, and Mastery Objectives.
---

# Intraoperative Guide

Read and follow `.agents/shared/commands/intraoperative-guide.md`. It is a modular deep-research orchestrator with context-budget controls and structured artifact handoffs; reload the referenced decomposition, crosslink, research, knowledge-map, **map-completeness review (separate subagent)**, synthesis, **expert completeness review (separate subagent)**, gap-repair, and finalization modules when each checkpoint is reached.

Do not write the final guide until:

1. The decomposition has produced a Coverage Matrix anchoring the 85% resident-mastery depth target.
2. The operative knowledge map has been approved by the dedicated map-completeness reviewer subagent (`MAP_APPROVED` verdict written to `data/Sessions/<Title>/verdicts/`).
3. The expert completeness reviewer subagent — separate from the writer — has returned `APPROVED` with its own fresh attending-defense questions answered.
4. Every required verdict JSON exists under `data/Sessions/<Title>/verdicts/` and the finalize module has verified the chain.

Validate the final guide with `src/operative_guide_validator.py`. Route any generated Anki cards to `Neurosurgery::Procedures::<Operative Guide Title>`.
