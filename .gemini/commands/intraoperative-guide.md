---
name: intraoperative_guide
description: Deep-research neurosurgical operative rehearsal guide with decomposition, serial RAG, operative knowledge map, verified Obsidian wikilinks, expert review, gap repair, readable formatting, and Mastery Objectives.
---

# Intraoperative Guide

Read and follow `.agents/shared/commands/intraoperative-guide.md`. It is a modular deep-research orchestrator; reload the referenced decomposition, crosslink, research, operative knowledge-map, synthesis, expert review, gap-repair, and finalization modules when each checkpoint is reached.

Do not write the final guide until the operative knowledge map has been reviewed, verified wikilinks are selected, and expert completeness review approves it. Validate the final guide with `src/operative_guide_validator.py`. Route any generated Anki cards to `Neurosurgery::Procedures::<Operative Guide Title>`.
