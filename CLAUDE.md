# Neuro-Agent: Claude Profile

**Arch**: Claude Code + LanceDB RAG + MCP (Gmail, GCal) + Skills

## §1 Shared Rules & Context

This profile is intentionally not self-contained. Before acting in this repo, read `AGENTS.md`; this file only adds Claude-specific runtime notes.
All agents share the startup recall contract (`startup-recall`; Raw `summary` is for dashboard/audits only) and the `service-log` debrief route through `brain-dump` defined in `AGENTS.md`.
All agents also share the vault intelligence contract in `.agents/shared/commands/vault-intelligence.md` for supplemental Obsidian context; it enriches learner-memory recall and does not replace `study_memory.py`.

Please read and follow `AGENTS.md` for:
- User Profile & Learner Posture (cognitive friction, progressive reveal)
- Universal Directives & Shared Workflow Authority (canonical contracts)
- Memory Contract & Capability Router (Tiers/Routes)
- Vault Targets & skill write rules
- Session-End Protocol & Data Locations
- Shared Protocols (Naming Conventions, Cross-Reference Discovery, INDEX.md Indexes)

## §2 Claude-Specific Environment & Subagents

### Subagent Model Routing

Always specify `model:`, never default to Opus:
| Task | Model |
|---|---|
| RAG transform, research, concept chunking, card drafting, email drafting, voice calibration, procedure synthesis, weakness lecture | **sonnet** |
| Email categorization, claim extraction, image enrichment | **haiku** |

### Environment Setup

- **Obsidian CLI**: `/Applications/Obsidian.app/Contents/MacOS/obsidian` (alias: `OBS`)
- **Vaults**: `agentic-neuro` (primary) | `Peripheral Nerve` (read-only) | `Personal Reflections` (read-only, never write without request)
- **Context compression**: At 12+ turns in Socratic study sessions, notify the user and offer a digest before continuing. Never compress silently.
