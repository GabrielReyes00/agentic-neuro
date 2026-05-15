---
description: Generate a deep-research neurosurgical operative rehearsal guide with decomposition, serial RAG, operative knowledge map, verified Obsidian wikilinks, expert review, gap repair, readable formatting, and Mastery Objectives.
argument-hint: [procedure]
---

# Intraoperative Guide

The user invoked `/intraoperative-guide` with: $ARGUMENTS

Read and follow `.agents/shared/commands/intraoperative-guide.md`. That file is the orchestrator for a modular deep-research workflow; reload the referenced decomposition, crosslink, research, operative knowledge-map, synthesis, review, gap-repair, and finalization modules at their checkpoints instead of trying to hold the whole workflow in context from the start.

Use `.agents/shared/commands/learning-session-contract.md` for shared memory and artifact rules.

Do not write the real guide until the operative knowledge map has been reviewed, verified wikilinks are selected, and expert completeness review approves it. Then write to `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/<Title>.md`, validate it with `src/operative_guide_validator.py`, and revise until the validator passes. The validator is structural and wikilink-aware; expert review is the semantic completeness gate. Route any generated Anki cards to `Neurosurgery::Procedures::<Title>`.
