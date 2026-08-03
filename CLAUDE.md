# Claude Runtime Profile

Read `AGENTS.md` first. It owns user posture, routing, safety, system boundaries,
and the `service-log` → `shift-debrief` route. This file contains only
Claude-specific execution notes.

- Start learning sessions with `startup-recall`; raw `summary` is for dashboards
  and audits only.
- Use `.agents/shared/commands/vault-intelligence.md` for supplemental Obsidian
  context and `.agents/shared/commands/rag-routing.md` for every textbook
  retrieval. Do not redefine either policy here.
- Shared contracts decide when independent review is required. Use a separate
  subagent when available; pass compact named artifacts rather than the full
  conversation. Model choice should fit the task and current runtime—do not
  preserve a stale hard-coded model table.
- Primary Obsidian vault: `agentic-neuro`. Treat `Peripheral Nerve` and
  `Personal Reflections` as read-only unless Gabriel explicitly asks otherwise.
- At 12 or more Socratic turns, offer a digest before context compression.

Slash-command files under `.claude/commands/` are generated adapters. Repair
policy in the shared contract or registry, then run
`python3 src/sync_agent_adapters.py`; do not hand-maintain wrapper behavior.
