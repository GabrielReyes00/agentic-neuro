# Neuro-Agent: AI Assistant for a Neurosurgery Resident

**Arch**: Gemini CLI + LanceDB RAG + MCP (Gmail, GCal, Chrome) + Commands
**Parity**: Claude support in `CLAUDE.md` + `.claude/commands/`. Gemini must be self-contained here; do not assume it reads Claude instructions.

## §1 Universal Directives

1. No bare "Done" — surface meaningful output or a clarifying question.
2. No persistence without explicit user request, except memory writes mandated by an active learning command after the user has engaged that workflow.
3. No email sending without explicit user approval.
4. No reasoning tags (`<thought>`, XML wrappers).
5. Scripts are tools, not reasoners — Gemini performs reasoning.
6. Silent/background steps in command workflows are mandatory execution, not optional.
7. Scoped cleanup only in `data/Sessions/` — no broad wildcards.
8. No emojis anywhere.
9. No numeric confidence self-rating — infer confidence silently from language.
10. Vault metadata belongs at the bottom YAML block, never top.
11. Never use H1 (`#`) in vault files. The filename is the Obsidian title; start with the first meaningful body content.
12. No alias wikilinks in table cells — `[[target|alias]]` breaks tables. Use `[[target]]` only inside table rows.

## §2 Gemini CLI Rules

Gemini 2.x requires strict sequential tool invocation: one call, wait, then next. Shell `&&` chaining inside a single call is fine. No parallel tool calls.

Use explicit branch targets in command workflows: `If X -> skip to Step N` / `If not X -> continue`. Avoid prose-only branching when the workflow needs deterministic control flow.

Commands longer than 2 minutes should surface timeout and use the documented fallback. First-call retrieval latency around 30-45 seconds is expected.

Default model: `gemini-3-flash-preview`.
Use `gemini-3.1-pro` for `/intern-bootcamp`, `/rag-workflow`, `/study-session`, `/generate-report`, `/intraoperative-guide`, `/study-material`, and `/anki-sync`.

After editing `.toml` descriptors: `/commands reload`.

## §3 Shell Prefix

All shell commands:

```bash
RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate"
eval "$RUN" && <command>
```

## §4 Context Compression

Trigger at about 12 turns, after a long pause + "continue", or significant topic shift. Ask before compressing. On approval, produce a digest and write `data/Sessions/session_digest_YYYYMMDD.md`. Never compress silently.

This repo configures a Gemini `BeforeAgent` hook in `.gemini/settings.json` to run `src/precompact_memory_inject.py` before each turn. The hook injects compact active-session memory as `additionalContext` when recent memory exists. If Gemini prompts to trust project hooks, approve this repo's hook before relying on automatic memory injection.

## §5 Obsidian & Storage

Vault root: `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/`

| Folder | Writer | Purpose |
|---|---|---|
| `Reports/` | `/generate-report` | Research reports |
| `Operative Guides/` | `/intraoperative-guide` | Surgical walkthroughs |
| `Study Material/` | `/study-material` | Concept maps + question banks |
| `Review Sessions/` | All learning skills | Session logs |
| `Concepts/` | Agent | ACGME concept stubs with Dataview inline fields, KG-edge sections, and Encounter History |
| `Error Atlas/` | Agent | Disambiguation pages for misconception pairs |
| `Dashboard.md` + `ACGME Readiness.md` | Post-session hook | Regenerated knowledge surfaces |
| `ACGME Canvases/` | Post-session hook | One `.canvas` per ACGME milestone |

Naming rules:
- Standalone session: `Review Sessions/<Topic Title>.md` — Title Case, spaces, topic-derived.
- Doc-anchored review: `Review Sessions/<Title> Review.md` — upsert, never fork.
- Study Material: `Study Material/<Title>.md` — no date suffix.
- Never create date-prefixed filenames, underscore filenames, all-lowercase session filenames, or skill-prefixed session filenames.

Before writing to `Reports/`, `Operative Guides/`, `Study Material/`, or `Review Sessions/`: ensure `INDEX.md` exists and scan existing vault files for valid wikilinks.

## §6 Long-Term Memory Contract

The durable memory backend is shared across agents:
- SQLite: `data/knowledge_graph.db`
- LanceDB semantic memory: `episodic_memory`
- SQLite FTS: `memory_fts`
- Stable CLI: `src/memory_orchestrator.py`
- Post-session consolidation: `src/universal_post_session_hook.py`

### Active Answer Memory

When Gemini asks a question and the user answers, run the atomic active-answer logger silently:

```bash
python3 src/memory_orchestrator.py record-answer \
  --session-ts "$SESSION_TS" --turn <N> --skill "<command or ad-hoc>" \
  --topic "<topic>" --concept "<specific concept tested>" \
  --question "<your question, verbatim>" \
  --answer "<user's answer, verbatim or close paraphrase>" \
  --correct <0|1|2> \
  [--correction "<your correction/explanation if incorrect>"] \
  [--error-type "<type>"] [--misconception "<specific wrong belief>"] \
  [--root-cause "<why>"] [--remediation "<what should fix it>"] \
  [--teaching-approach "<approach used>"] [--depth <N>] [--domain "<domain>"] \
  [--response-confidence "high|low"]
```

Correctness routing: correct with no hints = `2`; right direction but incomplete = `1`; wrong or misconception = `0`.

Set `SESSION_TS` once per session:

```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```

### Passive Teaching

Passive capture is not globally automatic. If Gemini explains without testing, use `log_study` only when the command workflow or user request requires saving. For explicit passive memory capture, enable the session first:

```bash
python3 src/memory_orchestrator.py session --session-ts "TS" --skill "S" --topic "T" --enabled --scope study_session
python3 src/memory_orchestrator.py record-passive --session-ts "TS" --turn N --skill "S" --topic "T" --content "..."
```

### Prior Context

At the start of a learning interaction on a topic:

```bash
python3 src/memory_orchestrator.py guidance "query" [--topic "T"] [--skill "S"]
python3 src/knowledge_graph.py last_session_narrative --skill "<command or ad-hoc>" --topic "<topic>"
```

Apply prior misconceptions, next-session strategy, confusable pairs, and transfer opportunities before asking new questions.

### Post-Session Consolidation

At session end, run the universal post-session hook after heartbeat/review writes:

```bash
python3 src/universal_post_session_hook.py --skill "<command>" --topics "<topics>" --vault-writes "<files>" --report-out /tmp/post_session_hook_report.json
```

Check the report JSON. Do not claim completion on failure. The hook applies decay, regenerates dashboard/readiness/canvases, syncs concept files, consolidates episodic memory into summaries, embeds memory rows into LanceDB, and runs vault sync.

## §7 Learning Telemetry

`gap_details` schema:

```json
[{"concept":"...","error_type":"...","error_process":"...","misconception":"...","root_cause":"...","remediation":"..."}]
```

`error_process` values: `mechanism_gap` | `context_misapplication` | `prerequisite_absent` | `numerical_anchor` | `classification_mismatch` | `temporal_confusion` | `anatomical_ambiguity`.

Error types: `numerical_recall` | `conceptual_confusion` | `cross_contamination` | `application_failure` | `reasoning_gap` | `omission`.

When logging a clear confusion pair, update `data/confusion_matrix.json`, run `python3 src/knowledge_graph.py generate_error_atlas`, and upsert `Error Atlas/INDEX.md`.

Use context-qualified topic names. Avoid broad labels like `vasospasm` or `ICP management`; prefer `vasospasm prophylaxis after aneurysmal SAH`.

## §8 Capability Router

Default: answer directly from model knowledge.

For non-slash queries, run:

```bash
python3 src/gemini_query_gate.py "query" --hydrate-context
```

Routes: `direct` | `rag-workflow` | `<command>` | `calendar`. `rag-transform` is internal-only.

Always intercept:
- Anki/flashcards -> `/anki-sync`
- Textbook inventory -> `/list-textbooks`
- Inbox/email -> `/inbox-workflow`
- Gaps/dashboard/ACGME -> `/knowledge-map`
- Study plan -> `/study-session`
- Calendar/scheduling -> GCal MCP

Explicit invocation only:
- Textbook lookup -> `/rag-workflow`
- Drill/sim -> `/intern-bootcamp`
- Operative walkthrough -> `/intraoperative-guide`
- Study material from file -> `/study-material`
- Research report -> `/generate-report`

## §9 Session-End Protocol

Learning commands complete only after all relevant steps succeed:
1. Heartbeat completion + session narrative
2. Review session file write/update
3. Concept extraction when applicable
4. Universal post-session hook

If user exits abruptly, finalize with available data.

Log narrative:

```bash
python3 src/knowledge_graph.py log_session_narrative \
  --skill "<command>" --topics "<topics>" \
  --summary "<1-2 sentence recap>" \
  --strategy "<actionable forward directive>" \
  --teaching-failures '[{"concept":"...","attempted":"...","why_failed":"..."}]' \
  --key-confusions '[{"concept_a":"...","concept_b":"...","disambiguation_axis":"..."}]' \
  --turns <N>
```

`--strategy` must be a complete actionable sentence.

## §10 Command Reference

```bash
# Routing
python3 src/gemini_query_gate.py "query" --hydrate-context

# Memory
python3 src/memory_orchestrator.py record-answer --session-ts "TS" --turn N --skill "S" --topic "T" --concept "C" --question "Q" --answer "A" --correct 0|1|2
python3 src/memory_orchestrator.py guidance "query" [--topic "T"] [--skill "S"]
python3 src/memory_orchestrator.py doctor
python3 src/memory_orchestrator.py reindex-fts

# Preflight + Heartbeat
./src/preflight.sh "query" [--doc "..." --skill "..."]
./src/heartbeat.sh --session-mode --skill "..." --slug "..." --topics "..." --turn-num N --status "..." [...]

# Retrieval
python3 src/lance_retriever.py compare "query" [--visual] | compare_multi "q1" "q2" | list_textbooks

# Knowledge Graph
python3 src/knowledge_graph.py context "query" --output data/Sessions/learner_context.json
python3 src/knowledge_graph.py log_study --topics "..." --understood "..." [--gaps/--gap-details] --depth N
python3 src/knowledge_graph.py log_session_narrative --skill "..." --topics "..." --summary "..." --strategy "..."
python3 src/knowledge_graph.py study_plan [--hours N] [--rotation "D"] [--focus "T"]
python3 src/knowledge_graph.py recall "query" [--topic "T"] [--errors-only] [--days N] [--max N] [--compact] [--sqlite-only] [--output path]
python3 src/knowledge_graph.py memory_doctor

# Anki
python3 src/anki_sync_cli.py filter_novelty | validate_final_cards | dispatch
```
