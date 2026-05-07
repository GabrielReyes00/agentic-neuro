# Knowledge Map

Use for progress, dashboard, gaps, studied topics, and learning-state questions. Route "what should I study today" to `study-session`.

## Core Commands

```bash
python3 src/study_memory.py status
python3 src/study_memory.py status --topic "<topic>"
python3 src/study_memory.py recall --topic "<topic>"
```

## Rendering

**Status** (no topic): overall counts, top weak concepts with error types and misconceptions, recent sessions with summaries.

**Status** (with topic): focused view of that topic's concepts, gaps, errors, and session history.

**Recall** (with topic): full context including last session strategy, known/gap/error breakdown, recent exchanges, and doc progress.

### Dashboard

When the user asks for a dashboard, gaps, or "what should I study":

1. Run `status` for the overview.
2. Run `recall` on the weakest topic (most open errors or lowest mastery).
3. Present: coverage summary, weakest areas with specific misconceptions, open errors to retest, recent session summaries, and recommended next session topic with rationale.

### Gaps

Group by:
- Open errors (specific misconceptions needing retesting).
- Weak concepts (multiple misses, low mastery).
- Topics with no recent sessions.

Offer to start `study-session` on the weakest area.

## Dashboard Write

After dashboard or gap rendering, silently update:

`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Dashboard.md`

Rules: use real data from `status` and `recall`, no stale carryover, no H1, no emojis, tables for data, Obsidian callouts for prose. Include overview, weak concepts, open errors, recent sessions, and recommended next focus.
