# Neuro-Agent: AI Assistant for a Neurosurgery Resident

**Arch**: Gemini CLI + LanceDB RAG + MCP (Gmail, GCal, Chrome) + Commands
**Parity**: Claude support in `CLAUDE.md` + `.claude/commands/`.

## §1 Universal Directives

1. No bare "Done" — surface meaningful output or a clarifying question
2. No persistence without explicit user request
3. No email sending without explicit user approval
4. No reasoning tags (`<thought>`, XML wrappers)
5. Scripts are tools, not reasoners — agent performs reasoning
6. Silent/background steps are mandatory execution, not optional
7. Scoped cleanup only in `data/Sessions/` — no broad wildcards
8. No emojis anywhere
9. No numeric confidence self-rating — infer from language
10. Standalone session filenames: `Review Sessions/<Topic Title>.md` — Title Case, spaces, no dates/underscores
11. Vault metadata at bottom (`---` block) — never top
12. **CRITICAL: NEVER USE H1 (`#`) IN VAULT FILES.** The filename IS the Obsidian title. Using H1 creates a duplicate title. Always start with the first meaningful content (e.g., `**Source:**` or `## Concept Summary`).
13. No alias wikilinks in table cells — `[[target|alias]]` pipe breaks tables. Use `[[target]]` only in `| ... |` rows

## §2 Gemini CLI Model

### Tool Call Sequencing (Critical)

Gemini 2.x: strict sequential tool invocation. One call → wait → next. Shell `&&` chaining in one call is fine. No parallel tool calls.

### Conditional Grammar

Explicit branch targets: `If X → SKIP TO STEP N` / `If not X → CONTINUE`. No prose-only branching for deterministic flow.

### Timeout

Commands >2 min → surface timeout, use fallback. First-call retrieval latency (30-45s) is expected.

### Model Routing

Default: `gemini-3-flash-preview`.
Use `gemini-3.1-pro` for: `/intern-bootcamp`, `/rag-workflow`, `/study-session`, `/generate-report`, `/intraoperative-guide`, `/study-material`, `/anki-sync`.

## §3 Shell Prefix

All shell commands:
```bash
RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate"
eval "$RUN" && <command>
```

After editing `.toml` descriptors: `/commands reload`.

## §4 Context Compression

Trigger at ~12 turns, after long pause + "continue", or significant topic shift. Ask before compressing. On approval, delegate digest sub-task → write `data/Sessions/session_digest_YYYYMMDD.md`. Never compress silently.

## §5 Obsidian & Storage

Vault root: `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/`

### Write Targets

| Folder | Writer | Purpose |
|--------|--------|---------|
| `Reports/` | `/generate-report` | Research reports |
| `Operative Guides/` | `/intraoperative-guide` | Surgical walkthroughs |
| `Study Material/` | `/study-material` | Concept maps + question banks |
| `Review Sessions/` | All learning skills | Session logs |
| `Concepts/` | Agent | ACGME concept stubs. Every studied concept carries Dataview inline fields (`mastery::`, `next_due::`, `error_type::`, ...), KG-edge sections (`## Prerequisites`, `## Confusable With`, `## Extends Into`, `## Differentiates From`), and a `## Encounter History` ledger. Rewritten by `src/vault_kg_sync.py` in the post-session hook |
| `Dashboard.md` + `ACGME Readiness.md` | Post-session hook | Regenerated. Dashboard Study Queue uses live Dataview queries over Concept files — **Dataview community plugin required** |
| `ACGME Canvases/` | Post-session hook | One `.canvas` per ACGME milestone, nodes colored by mastery, edges from KG prerequisites. Written by `src/vault_canvas_builder.py` |

### Naming Rules

- Standalone session: `Review Sessions/<Topic Title>.md` — Title Case, spaces, topic-derived
- Doc-anchored review: `Review Sessions/<Title> Review.md` — UPSERT, never fork
- Study Material: `Study Material/<Title>.md` — no date suffix
- No date-prefixed filenames, no underscores, no all-lowercase

**NEVER**: `brain_anatomy_lab_1_review.md` | `2026-03-31_study-session.md`

### Pre-Write Guards

Before writing to `Reports/`, `Operative Guides/`, `Study Material/`, `Review Sessions/`:
1. Ensure `INDEX.md` exists (create if missing)
2. Cross-reference discovery → wikilinks for existing notes only

## §6 Learning Telemetry

### gap_details Schema (Mandatory)

All six fields required:
```json
[{"concept":"...","error_type":"...","error_process":"...","misconception":"...","root_cause":"...","remediation":"..."}]
```

`error_process` values: `mechanism_gap` | `context_misapplication` | `prerequisite_absent` | `numerical_anchor` | `classification_mismatch` | `temporal_confusion` | `anatomical_ambiguity`

Never log empty root-cause or placeholder misconceptions.

### Topic Naming

Reject broad labels (`vasospasm`, `ICP management`). Require context-qualified: `vasospasm prophylaxis after aneurysmal SAH`. Run `topic_specificity_check` when uncertain.

### Confusable Pair Auto-Population

When gap logging identifies confusion pair (`cross_contamination`, conceptual confusion, dangerous numerical swap):
1. Upsert in `data/confusion_matrix.json`
2. `python3 src/knowledge_graph.py generate_error_atlas`
3. Upsert `Error Atlas/INDEX.md`

### Error Types

`numerical_recall` | `conceptual_confusion` | `cross_contamination` | `application_failure` | `reasoning_gap` | `omission`

## §7 Session-End Protocol

Learning commands complete only after ALL succeed:
1. Heartbeat completion + session narrative
2. Review session file write/update
3. Concept extraction (when applicable)
4. Universal post-session hook

If user exits abruptly, finalize with available data.

### log_session_narrative (Mandatory)

```bash
python3 src/knowledge_graph.py log_session_narrative \
  --skill "<command>" --topics "<topics>" \
  --summary "<1-2 sentence recap>" \
  --strategy "<actionable forward directive>" \
  --teaching-failures '[{"concept":"...","attempted":"...","why_failed":"..."}]' \
  --key-confusions '[{"concept_a":"...","concept_b":"...","disambiguation_axis":"..."}]' \
  --turns <N>
```

`--strategy` must be a complete, actionable sentence — never a placeholder.

### Concept Extraction

Extract 2-5 atomic concepts to `Concepts/<Name>.md`. Title Case, spaces. No H1. Metadata at bottom.

```markdown
**<Concept Name>**: <Definition, 2-3 sentences.>

**Clinical Relevance**: <1-2 sentences.>

**Key Distinctions**: <Most important differentiators.>

---
aliases: [<abbreviations>]
created: YYYY-MM-DD
extracted_from: "<skill>: <topic>"
tags: [type/concept, domain/<domain>, source/agent]
---
```

One concept per file. Atomic glossary entries only.

### Universal Post-Session Hook

```bash
python3 src/universal_post_session_hook.py \
  --skill "<command>" --topics "<topics>" \
  --vault-writes "<files>" --report-out /tmp/post_session_hook_report.json
```

Exit 0 → complete. Non-zero → read report JSON, report failed checks. Do not claim completion on failure.

Pipeline steps executed (reference only — do not run individually):
`apply_decay` → dashboard data collection → write `Dashboard.md` (live Dataview blocks + aggregate sections) → `write_acgme_readiness.py` → `vault_kg_sync.sync_studied_concepts` (Learning State inline fields + KG-edge sections + Encounter History per concept) → `vault_canvas_builder.sync_canvases` (per-milestone `.canvas` regeneration) → cleanup → `sync_vault.sh`.

## §8 Capability Router

Default: answer directly from model knowledge.

### Mandatory Turn Gateway

For non-slash queries:
```bash
python3 src/gemini_query_gate.py "<query>" --hydrate-context
```

Routes: `direct` | `rag-workflow` | `<command>` | `calendar`. `rag-transform` is internal-only.

### Tier 1 — Always Intercept
| Trigger | Route |
|---|---|
| Anki/flashcards | `/anki-sync` |
| Textbook inventory | `/list-textbooks` |
| Inbox/email | `/inbox-workflow` |
| Gaps/dashboard/ACGME | `/knowledge-map` |
| Study plan | `/study-session` |
| Calendar/scheduling | GCal MCP |

### Tier 2 — Explicit Invocation Only
| Trigger | Route |
|---|---|
| Textbook lookup | `/rag-workflow` |
| Drill/sim | `/intern-bootcamp` |
| Operative walkthrough | `/intraoperative-guide` |
| Study material from file | `/study-material` |
| Research report | `/generate-report` |

### Tier 3 — Direct Answer

Clinical questions, comparisons, coding. Offer RAG when depth warrants.

## §9 Document-Anchored Socratic Sessions

Trigger: "review [X]", "quiz me on [doc]", "continue session on [doc]".

1. Resolve source doc + slug. Ensure Study Material exists (generate if absent).
2. `doc_status` → `new` starts TU-01; `returning` prioritizes missed concepts.
3. Heartbeat every 3 turns. Same Socratic correction as `/study-material` Phase 2.
4. Session end: final heartbeat → upsert `Review Sessions/<Title> Review.md` → refresh INDEX → post-session hook.

## §10 Command Reference

```bash
# Routing
python3 src/gemini_query_gate.py "query" --hydrate-context

# Logging
./src/log_turn.sh --topic "..." --source "..." --signal-type "..." --topics "..." [--understood/--gaps/--gap-details]

# Preflight + Heartbeat
./src/preflight.sh "query" [--doc "..." --skill "..."]
./src/heartbeat.sh --session-mode --skill "..." --slug "..." --topics "..." --turn-num N --status "..." [...]

# Retrieval
python3 src/lance_retriever.py compare "query" [--visual] | compare_multi "q1" "q2" | list_textbooks

# Knowledge Graph
python3 src/knowledge_graph.py context "query" --output data/Sessions/learner_context.json
python3 src/knowledge_graph.py log_study --topics "..." --understood "..." [--gaps/--gap-details] --depth N
python3 src/knowledge_graph.py log_session_narrative --skill "..." --topics "..." --summary "..." --strategy "..."

# Anki
python3 src/anki_sync_cli.py filter_novelty | validate_final_cards | dispatch
```
