# Neuro-Agent: Gemini CLI Profile

**Arch**: Gemini CLI + LanceDB RAG + MCP (Gmail, GCal, Chrome) + Commands

## §1 Shared Rules & Context

This profile is intentionally not self-contained. Before acting in this repo, read `AGENTS.md`; this file only adds Gemini-specific runtime notes.
All agents share the startup recall contract (`startup-recall`; Raw `summary` is for dashboard/audits only) and the `service-log` debrief route through `brain-dump` defined in `AGENTS.md`.

Please read and follow `AGENTS.md` for:
- User Profile & Learner Posture (cognitive friction, progressive reveal)
- Universal Directives & Shared Workflow Authority (canonical contracts)
- Memory Contract & Capability Router (Tiers/Routes)
- Vault Targets & skill write rules
- Session-End Protocol & Data Locations
- Shared Protocols (Naming Conventions, Cross-Reference Discovery, INDEX.md Indexes)

## §2 Gemini CLI Rules

### No Inline Python / Heredoc Dumps (HARD RULE)

The Gemini CLI echoes the full body of every shell tool call in the transcript. Multi-line `python3 -c "..."`, `python3 <<EOF`, `bash -c "<long block>"`, and inline heredocs therefore dump 20+ lines of code at Gabriel every time. Do not use them.

Instead:
1. **Prefer existing tooling.** `src/` has scripts for recurring operations (study_memory, lance_retriever, anki_queue, etc.). Use them.
2. **If ad-hoc Python is truly required**, write the script once with the `write_file` tool to `data/Sessions/tmp_<short_name>.py`, then run it with a single-line `python3 data/Sessions/tmp_<short_name>.py`, then delete it.
3. **Never narrate what you are about to run.** Just call the tool. If the prior attempt failed, one short sentence describing the *outcome* is enough.
4. **Do not restate tool output.** If a command succeeded, a one-line summary ("Created 9 subdecks") is the whole report.

Violations of this rule are the #1 source of transcript noise in Gemini sessions. Treat it as load-bearing.

### Command Execution & Performance

- Batch independent tool calls in a single turn for speed; serialize only when one call depends on another's output. Exception: run local RAG retrieval (`lance_retriever.py compare`) serially — the local embedding stack contends and stalls if multiple retrieval calls run at once. Shell `&&` chaining inside a single call is fine.
- Use explicit branch targets in command workflows: `If X -> skip to Step N` / `If not X -> continue`. Avoid prose-only branching when the workflow needs deterministic control flow.
- Commands longer than 2 minutes should surface timeout and use the documented fallback. First-call retrieval latency around 30-45 seconds is expected.
- After editing `.toml` descriptors: `/commands reload`.
