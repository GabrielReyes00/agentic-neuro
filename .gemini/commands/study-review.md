---
name: study_review
description: Socratic review from an existing Study Material note — memory-enabled, doc-anchored.
---

# Study Review

Gemini runtime wrapper for `/study-review`. The canonical contract lives in `.agents/shared/commands/study-review.md`; follow it for all workflow and behavior. This file adds only Gemini-specific runtime constraints.

## Gemini Runtime Constraints

- Grade every answer starting with exactly one of: `Correct`, `Partial`, or `Not quite`.
- After every evaluated answer, run `study_memory.py log-answer` silently per the shared contract. Do not skip this step.
- Do not call Anki directly per turn.
