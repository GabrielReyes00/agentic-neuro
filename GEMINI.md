# Gemini CLI Runtime Profile

Read `AGENTS.md` first. It owns user posture, routing, safety, system boundaries,
and the `service-log` → `shift-debrief` route. This file contains only Gemini
CLI execution notes.

- Start learning sessions with `startup-recall`; raw `summary` is for dashboards
  and audits only.
- Use `.agents/shared/commands/vault-intelligence.md` for supplemental Obsidian
  context and `.agents/shared/commands/rag-routing.md` for every textbook
  retrieval. Do not redefine either policy here.
- Gemini echoes shell bodies into the transcript. Prefer existing `src/` tools;
  never use multiline inline Python, `python3 -c`, or heredoc program dumps. If
  ad-hoc code is essential, create one narrowly named temporary script under
  `data/Sessions/`, run it once, and remove only that file.
- Batch independent work; serialize dependent work. Use one Mini-RAG batch or
  full-RAG batch rather than concurrent model-loading processes.
- Do not narrate routine commands or repeat raw output. Report the result,
  relevant path/count, or actionable failure.
- After generated `.toml` command adapters change, run `/commands reload`.

Files under `.gemini/commands/` are generated adapters. Repair policy in the
shared contract or registry, then run `python3 src/sync_agent_adapters.py`; do
not hand-maintain wrapper behavior.
