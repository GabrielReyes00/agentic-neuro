# Neuro-Agent: AI Assistant for a Neurosurgery Resident

**Status**: Active | **Arch**: Claude Code + LanceDB RAG + MCP (Gmail, GCal, Chrome) + Skills
**Multi-Agent**: Python backend is agent-agnostic. Gemini CLI support via `GEMINI.md` + `.gemini/commands/`. Both agents share the same LanceDB, knowledge graph, and Anki infrastructure.

## Universal Directives

1. **No bare "Done"/"Executed"** — always surface meaningful output, status, or a question
2. **No saving without explicit request** — never call `add_fact`, `save_conversation`, `save_session`, or write to any persistent store unless asked. "This seems important" is not a trigger
3. **No email without explicit approval** — hard constraint, zero exceptions
4. **Suppress reasoning tags** — never output `<thought>` or similar XML tags
5. **Scripts are tools, not LLMs** — `lance_retriever.py`, `anki_sync_cli.py`, etc. do vector math/DB I/O/API calls only. Claude is the sole reasoning engine
6. **No narrating tool steps** — single brief status line if needed, then final result
7. **Immediate Intermediate Cleanup** — all temporary files in `data/Sessions/` (JSONs, MDs, logs) MUST be deleted via `rm` as soon as their data is processed into the database or written to the final Obsidian destination. No lingering "scratchpad" files after a turn finishes.
8. **No emojis** — never use emojis in any output: Obsidian files, Anki cards, session logs, terminal messages, or user-facing text. Plain text only.
9. **No self-rating prompts** — never ask the user to rate their own confidence or understanding on a numeric scale. The agent silently infers confidence from linguistic cues (hedging, qualifiers, declarative tone).
10. **Standalone session filenames are topic-only** — `Review Sessions/<topic-slug>.md`, never dates or skill prefixes in the filename. The date goes in YAML frontmatter.

## Shell Prefix

> **ALL commands MUST use this prefix.** The CLI may run from `~`, not the project dir.

```
RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate"
```

All commands below assume `$RUN &&` prepended. Written inline as the full prefix where shown.

## Context Compression Checkpoints

Triggers: bootcamp/Socratic session hits 12+ turns | "continue" after pause | new major topic in long session.

Protocol:
1. Notify: *"We're ~12 turns in — want a session digest before we continue?"*
2. On approval: spawn `general-purpose` subagent → produce digest (scenario summary, diagnoses, teaching points, error patterns, open threads)
3. Write to `data/Sessions/session_digest_YYYYMMDD.md` with `## SESSION DIGEST (compressed)` header — reference forward, never re-dump
4. **Never compress silently** — always notify and await approval

## Subagent Model Routing

All subagent spawns MUST specify an explicit `model:` parameter to avoid defaulting to Opus. Route by task complexity:

| Subagent Task | Model | Rationale |
|---|---|---|
| RAG transform synthesis | **sonnet** | Pedagogical synthesis — needs reasoning but not Opus-level |
| Research agents (generate-report) | **sonnet** | Web search + structured summarization |
| Concept chunking (study-material) | **sonnet** | Classification + pedagogical structuring |
| Card drafting + validation (anki-sync) | **sonnet** | Requires blind validation reasoning |
| Email drafting (inbox-workflow) | **sonnet** | User-facing tone quality |
| Voice calibration (inbox-workflow) | **sonnet** | Nuanced voice analysis |
| Procedure synthesis (intraoperative) | **sonnet** | Surgical content quality |
| Weakness lecture (intern-bootcamp) | **sonnet** | High-stakes educational content |
| Email categorization (inbox-workflow) | **haiku** | Structured classification — simple |
| Claim extraction (anki-sync) | **haiku** | SVO triple extraction — mechanical |
| Image enrichment (anki-sync) | **haiku** | Search query generation — simple |

Inbox subagent gate: delegate all email fetching/reading/classification to a `general-purpose` subagent → returns structured JSON only. Raw email bodies never enter main context.

## User Profile

Gabriel Reyes | PGY-1 Neurosurgery | Baylor College of Medicine
- Email: Exchange via macOS Mail (AppleScript) | Calendar: GCal MCP | Reminders: macOS | Anki: AnkiConnect (localhost:8765)

## Obsidian CLI

**Binary**: `/Applications/Obsidian.app/Contents/MacOS/obsidian`
**Alias for commands**: `OBS="/Applications/Obsidian.app/Contents/MacOS/obsidian"`

**Vault root**: `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/`

**Vaults**:
- `agentic-neuro` — primary vault, the human-readable interface layer over the machine brain
- `Peripheral Nerve` — user-written clinical/anatomical notes (read for context)
- `Personal Reflections` — user journal/rotation notes (read for context, never write without request)

**Usage pattern**: `$OBS vault="agentic-neuro" <command> [options]`

Key commands: `read`, `write`, `append`, `search`, `list`, `open`, `aliases`, `backlinks`

### agentic-neuro Vault Structure

| Folder | Written By | Purpose |
|--------|-----------|---------|
| `Reports/` | `/generate-report` | Comprehensive research reports with citations |
| `Operative Guides/` | `/intraoperative-guide` | Step-by-step surgical walkthroughs |
| `Study Material/` | `/study-material` or doc-anchored session | Structured concept maps + question banks (1:1 with source docs) |
| `Review Sessions/` | All learning skills | **One file per Study Material doc** (`<slug>_review.md`) — living, updated each session |
| `Case Log/` | User only (real cases) | Clinical case documentation. Agent reads for context, never writes |
| `Concepts/` | Agent generated | Curriculum concept stubs for all 265 ACGME topics; auto-updates for studied topics after every session. Protected notes (Consult Workflow, Consult Checklists, Peripheral Nerve Classifications) are never overwritten. |
| `Error Atlas/` | Agent generated | One clinical disambiguation page per misconception pair. Auto-grows via Confusion Matrix Auto-Population Protocol (step 5). INDEX.md tracks all pairs. |
| `_Templates/` | — | Templater templates for user-authored notes |
| `_System/` | — | Vault schema documentation |
| `Dashboard.md` | `/knowledge-map` | Knowledge graph surface — gaps, review queue, domain progress |
| `ACGME Readiness.md` | Agent generated | PGY-year-filtered curriculum coverage view. Regenerated after every session via Universal Post-Session Hook. Used by `/study-session` Step 0 for domain recommendations. |

### Tag Taxonomy

| Category | Tags |
|----------|------|
| Skill origin | `skill/report`, `skill/guide`, `skill/study-material`, `skill/bootcamp`, `skill/study-session`, `skill/rag` |
| Domain | `domain/vascular`, `domain/spine`, `domain/tumor`, `domain/trauma`, `domain/functional`, `domain/pediatric`, `domain/peripheral-nerve`, `domain/general`, `domain/anatomy` |
| Note type | `type/reference`, `type/session`, `type/case`, `type/concept` |
| Source | `source/agent`, `source/user` |

### Skill → Vault Write Rules

- **generate-report**: Writes to `Reports/<slug>.md` + updates `Reports/INDEX.md`. Cross-references vault content via `ls` before writing. Appends `## Related in This Vault` with wikilinks.
- **intraoperative-guide**: Writes to `Operative Guides/<slug>.md` + updates `Operative Guides/INDEX.md`. Same cross-reference discovery and Related section.
- **study-material**: Writes to `Study Material/<slug>_<date>.md` + updates `Study Material/INDEX.md`.
- **intern-bootcamp / study-session / rag-workflow** (standalone, not doc-anchored):
    1. **Real-Time Log**: For every significant response/answer from the user, use `knowledge_graph.py log_event` to immediately record the activity signal AND `log_study` for concept mastery. Use fine-grained topic names (specificity level 2-3) and include `root_cause` + `error_process` in all gap_details.
    2. **Crash-Safe Heartbeat**: Use `heartbeat.sh --session-mode` to write incremental checkpoints to `Review Sessions/<topic-slug>.md` after every ~3 interactions. If the session exits unexpectedly, the vault retains progress.
    3. **Session-End Write**: Finalize the session file via `heartbeat.sh --session-mode --status "complete" --next-strategy "..." --narrative-summary "..."`, which automatically calls `log_session_narrative`. Then replace checkpoint content with the full session log format via the Write tool.
    4. **Post-Session Hook**: Silently run the Universal Post-Session Hook (concept extraction + Dashboard update).
- **Doc-anchored sessions** (any skill directed at a specific vault document):
    1. **One Review Session file per Study Material doc** — named `Review Sessions/<slug>_review.md`. UPSERT (append new session entry) on every session. Never create a new file.
    2. **Heartbeat** — `src/heartbeat.sh` every 3 user turns (silent).
    3. **Session-end** — final heartbeat + upsert `<slug>_review.md`.
- **Case Log Proactive Sync**: At the start of any learning skill (rag, study, bootcamp, study-material), the agent MUST check `Case Log/` for new user files:
    1. **Scan**: `ls` the Case Log folder and compare against `data/Sessions/case_log_sync.txt` (produced by `preflight.sh`, which queries `signal_events` for `source='case_log'`).
    2. **Log**: For each new case log, read the template fields and use `knowledge_graph.py log_event --topic "<Procedure>" --source "case_log" --signal-type "clinical_case" --depth 2 --category "<domain>"` to record the procedure. For each gap listed in "Anatomical / Technical Gaps Identified", use `knowledge_graph.py add_topic --name "<gap>" --category "<domain>" --source "case-log" --priority 2`.
    3. **Notify**: "Synced [N] new cases (e.g., [Procedure]) from your Case Log. Ready to integrate these into our session."
- **knowledge-map**: Silently triggered after any learning skill via the Universal Post-Session Hook to update `Dashboard.md`.

### Naming Conventions — Hard Stops

**Standalone session files** (study-session, rag-workflow, intern-bootcamp, anki-sync): Named `<topic-slug>.md` in `Review Sessions/`. No dates, no skill prefixes. The topic slug is lowercase, underscores, derived from the dominant topic (e.g., `pcoma_fetal_variant.md`, `cross_cover_herniation.md`, `sah_management_cards.md`).

**Doc-anchored review files** (study-material): Named `<slug>_review.md` in `Review Sessions/`. One living file per Study Material doc, appended over time.

**NEVER:**
- `YYYY-MM-DD_study-session.md` (no topic, has date)
- `YYYY-MM-DD_intern-bootcamp.md` (no topic, has date)
- `YYYY-MM-DD_rag.md` (no topic, has date)
- Emojis anywhere in any vault file
- `skill: skill/study-session` in frontmatter (use bare string `skill: "study-session"`)

### Confusion Matrix Auto-Population Protocol

When logging gaps with `error_type`, check whether a confusable pair should be added to `data/confusion_matrix.json`:

**Trigger conditions:**
- `cross_contamination`: user applied concept B's rule to concept A's context. Append pair with both concepts.
- `conceptual_confusion`: user confused two specific concepts in `gap_details`. Append pair with `disambiguation_axis` derived from the correction delivered.
- `numerical_recall` on clinically dangerous thresholds (e.g., mannitol 0.5 vs 1.0 g/kg): append pair with `disambiguation_axis = "correct value vs common incorrect value"`.

**Protocol:**
1. Read `data/confusion_matrix.json`
2. Check whether a pair for concept_a + concept_b already exists (case-insensitive substring match in both directions)
3. If not, append: `{"concept_a": "...", "concept_b": "...", "disambiguation_axis": "...", "source": "auto-<skill>", "first_added": "YYYY-MM-DD"}`
4. Write back to `data/confusion_matrix.json`
5. Generate and write the Error Atlas entry for the new pair:
   a. Run: `cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py generate_error_atlas`
   b. Find the entry matching the new pair (match by concept_a/concept_b substring)
   c. Write to `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Error Atlas/<ShortA> vs <ShortB>.md` using the standard Error Atlas format (frontmatter + disambiguation axis + clinical comparison table + Drill This Pair section)
   d. Upsert the row in `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Error Atlas/INDEX.md` — add the new pair to the table, increment `total_pairs` in frontmatter

All interactive learning skills (study-session, rag-workflow, intern-bootcamp, study-material) MUST check this protocol when logging gap-details with an identifiable error_type.

### Universal Post-Session Hook

**After EVERY learning skill's session-end sequence** (Obsidian write complete, KG logging complete), the agent MUST silently run this hook:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py apply_decay && \
echo "=== DASHBOARD DATA ===" && \
python3 src/knowledge_graph.py dashboard && \
echo "=== GAPS ===" && \
python3 src/knowledge_graph.py gaps --top 5 && \
echo "=== REVIEW_QUEUE ===" && \
python3 src/knowledge_graph.py review_queue --n 5 && \
echo "=== COGNITIVE_PATTERNS ===" && \
python3 src/knowledge_graph.py cognitive_patterns && \
echo "=== CALIBRATION ===" && \
python3 src/knowledge_graph.py calibration_profile
```

Then regenerate `Dashboard.md` using the knowledge-map skill's template (see knowledge-map.md § Obsidian Dashboard Write). Include a `## What Changed (Last Session)` section:

```markdown
## What Changed (Last Session)
- **Skill**: <skill that just ran>
- **Topics Touched**: <topics from session>
- **Concepts Added**: N new concepts to KG / N new Concepts/ notes created
- **Gaps Logged**: <N new gap entries with error types>
- **Vault Writes**: <list of files created/updated>
- **Next Priority**: <top gap concept based on current KG state>
```

After the Dashboard.md write, run the ACGME Readiness and concept stub updates:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py acgme_readiness > /tmp/acgme_data.json && \
python3 src/knowledge_graph.py export_concept_stubs --only-studied > /tmp/stubs_studied.json
```

Then:
- Run `python3 scripts/write_acgme_readiness.py --json /tmp/acgme_data.json` to rewrite `ACGME Readiness.md`
- Read `/tmp/stubs_studied.json` and rewrite each studied concept stub in `Concepts/` (rich format). Do NOT overwrite the three protected notes: `Neurosurgery Consult Workflow.md`, `Neurosurgery Consult Checklists by Pathology.md`, `Peripheral Nerve Injury Classifications (Seddon & Sunderland).md`
- Delete `/tmp/acgme_data.json` and `/tmp/stubs_studied.json` per the Immediate Intermediate Cleanup directive

**Skills that trigger this hook**: study-session, study-material, rag-workflow, intern-bootcamp, generate-report, intraoperative-guide, anki-sync. Each skill file explicitly references this hook at its session-end.

Do not narrate the Dashboard update or ACGME Readiness/stub updates to the user.

### Concept Extraction Protocol

After any skill writes its primary output to the vault (Reports, Operative Guides, Study Material), the agent MUST extract 2-5 atomic concepts that are:
- Named clinical entities (syndromes, classifications, procedures, structures, danger zones)
- NOT already in `Concepts/` (check via `ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/"*.md 2>/dev/null`)
- Important enough to be referenced across multiple topics

Write each to `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/<Concept Name>.md`:

```markdown
---
aliases: [<common abbreviations or alternate names>]
created: YYYY-MM-DD
extracted_from: "<skill>: <topic or procedure>"
tags:
  - type/concept
  - domain/<domain>
  - source/agent
---

**<Concept Name>**: <Core definition, 2-3 sentences.>

**Clinical Relevance**: <1-2 sentences connecting to practice.>

**Key Distinctions**: <Most important differentiating features from confusable entities.>
```

Keep atomic — one concept per file. These are glossary entries, not reports. Only create concepts that would be useful as wikilink targets.

**Skills that trigger concept extraction**: generate-report (already does this), rag-workflow (already does this), intraoperative-guide (new), study-material (new), intern-bootcamp (new).

### INDEX.md Pre-Write Guard

Before any skill writes its primary output, check for the relevant INDEX.md (`Reports/INDEX.md`, `Operative Guides/INDEX.md`, `Study Material/INDEX.md`, `Review Sessions/INDEX.md`). If absent, create it with the standard table header before writing the output file.

### Cross-Reference Discovery

Before writing any skill output to vault, check for cross-reference candidates:
```bash
ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Review Sessions/"*.md 2>/dev/null
```
Match filenames against the current topic via keyword overlap. For richer matching, also check `key_terms:` from YAML frontmatter of candidate files. Generate wikilinks: `[[folder/note_name|Display Title]]`.

### What Lives Where

| Data | Location | Why |
|------|----------|-----|
| Topic confidence, depth, encounters | `knowledge_graph.db` (`topics`) | Machine-queryable |
| Per-topic clinical context + specificity level | `knowledge_graph.db` (`topics.clinical_context`, `.specificity_level`) | Enforces fine-grained naming |
| Spaced review schedule (topic-level Ebbinghaus) | `knowledge_graph.db` (`topics.last_decay_ts`) | Algorithmic decay model |
| Per-concept SM-2 SRS schedule | `knowledge_graph.db` (`concept_mastery.next_review_due`, `.ease_factor`, `.review_interval_days`) | SM-2 per-concept spaced repetition |
| Concept status: unknown / known / due | `knowledge_graph.db` (`concept_mastery.status`) | 'due' = was known but past review date |
| Root cause + error process per concept gap | `knowledge_graph.db` (`concept_mastery.root_cause`, `.error_process`) | Process-level causal chain for adaptive teaching |
| Teaching notes per concept | `knowledge_graph.db` (`concept_mastery.teaching_notes`) | Auto-populated on unknown→known transition; persists effective approach |
| Concept partial mastery score | `knowledge_graph.db` (`concept_mastery.concept_confidence`) | Continuous 0–1 score independent of binary status; decays on miss |
| Calibration signals | `knowledge_graph.db` | Structured, feeds adaptive teaching |
| Concept relationships: prerequisites + confusable pairs | `knowledge_graph.db` (`concept_relationships`) | Supersedes external confusion_matrix.json; queryable graph; auto-seeded via `seed_prerequisites` |
| Session narratives + next_session_strategy + ZPD | `knowledge_graph.db` (`session_narratives`) | Forward-looking teaching intelligence; `session_success_rate` + `strategy_outcome` for ZPD loop; `topic_fingerprint` for overlap-based retrieval (Round 3) |
| Error patterns | `knowledge_graph.db` + `confusion_matrix.json` (legacy, migrated to `concept_relationships`) | Cross-referenced |
| Topic clinical adjacency (blind spot detection) | `knowledge_graph.db` (`topic_adjacency`) | Surfaces never-studied curriculum topics adjacent to current query — unknown unknowns |
| Misconception cognitive clusters | Derived from `concept_mastery.root_cause` via `misconception_clusters` | Groups errors by cognitive theme: mechanism/context/threshold/anatomy/etc |
| Domain learning velocity + stagnation alerts | Derived from `signal_events.confidence_delta` via `learning_velocity` | Injected into `learner_context` when a domain shows no confidence growth over 5+ signals (Round 3) |
| ZPD difficulty target | `data/Sessions/difficulty_target.json` (preflight output) | Real-time ZPD status: too_easy / optimal / too_hard |
| **Document-level coverage, concept progress** | `knowledge_graph.db` (`document_sessions`) | Queryable via `doc_status` / `log_doc_progress` |
| Textbook chunks + embeddings | `neurosurgery_v4.lance` | Vector search |
| Anki card dedup | `chromadb_store_anki_memory` | Dedup only |
| Reports, guides, study docs | **Obsidian vault** | Human-readable, browsable, wikilinked |
| **Doc-anchored review logs** | **Obsidian vault** (`Review Sessions/<slug>_review.md`) | One living file per Study Material doc — human-browsable cumulative record |
| Standalone session logs | **Obsidian vault** (`Review Sessions/<topic-slug>.md`) | Topic-named for non-doc-anchored sessions (bootcamp, RAG, etc.) — crash-safe via heartbeat checkpoints |
| Clinical cases | **Obsidian vault** (`Case Log/`) | User-authored only — agent reads for context |
| Reference concepts | **Obsidian vault** (`Concepts/`) | Agent-generated — automated atomic concept glossary |

## Capability Router

**Default: Answer directly using model knowledge.** The LLM's built-in training is the first-line response for clinical questions, quick overviews, explanations, and general conversation. Skills are **opt-in enhancements** invoked by explicit trigger phrases or slash commands — never auto-triggered on broad intent.

> **Rule of thumb**: If the user asks a question the model can answer from training data, just answer it. Only invoke a skill when the user explicitly requests the deeper tooling OR uses a slash command.

### Tier 1 — Always Intercept (tool-dependent, model knowledge cannot fulfill)

| Trigger | Route | Why |
|---|---|---|
| "save to Anki", "make cards", "flashcards", "sync to Anki" | **`anki-sync`** | Needs AnkiConnect pipeline |
| "what books", "inventory", "what's loaded", "list textbooks" | **`list-textbooks`** | Needs DB query |
| "inbox", "triage emails", "check my mail", "process inbox" | **`inbox-workflow`** | Needs email access |
| "gaps", "knowledge map", "weaknesses", "dashboard", "milestones", "ACGME" | **`knowledge-map`** | Needs knowledge graph DB |
| "what should I study", "study session", "study plan" | **`study-session`** | Needs knowledge graph DB |
| Calendar/scheduling/events | **`gcal` MCP tools** | Needs calendar API |

### Tier 2 — Explicit Invocation Only (use slash command or specific trigger phrases)

| Trigger | Route | Persona |
|---|---|---|
| `/rag-workflow`, "search my textbooks for", "look this up in the database", "what do my textbooks say about", "RAG this" | **`rag-workflow`** | Expert cognitive coach — Socratic, mechanistic |
| `/intern-bootcamp`, "drill me", "run a scenario", "night float sim", "bootcamp", "cross-cover sim", "pager sim" | **`intern-bootcamp`** | Per skill directives |
| `/intraoperative-guide`, "operative walkthrough for", "walk me through the surgery for" | **`intraoperative-guide`** | Senior fellow — precise, anatomical |
| `/study-material`, "make study material from [file]", "quiz me on this file", "prep me for [file]" | **`study-material`** | Study coach — encouraging, honest |
| `/generate-report`, "generate a report on", "research report on", "comprehensive review of" | **`generate-report`** | Research architect — comprehensive, evidence-based |

### Case Log → CLI Bridge (Obsidian-as-library, CLI-as-tutor)

| Trigger | Route |
|---|---|
| "review the [X] case log", "let's go over my [X] case", "Socratic review of [case]" | **`rag-workflow`** — read the specified Case Log file, use its content as context for a Socratic review session |
| "make cards from [X] case log", "Anki cards for the [X] case takeaways" | **`anki-sync`** — read the Case Log's Key Takeaways, generate targeted flashcards |
| "extract gaps from [X] case", "update knowledge-map from [case]" | **`knowledge-map`** — read the Case Log's Gaps section, log them to knowledge graph |
| "anatomical review for [X] case", "review the approach from [case]" | **`rag-workflow`** — read the Case Log's Procedure/Approach, run RAG retrieval on the anatomy |

### Tier 3 — Default (no skill needed)

| Intent | Route |
|---|---|
| Clinical question ("why does X happen", "explain Y", "compare A vs B", "what is the mechanism of") | **Answer directly from model knowledge.** Offer to go deeper with RAG if the topic warrants it: *"Want me to search the textbooks for more detail?"* |
| "walk me through" (non-surgical context), general overviews, quick factual questions | **Answer directly.** |
| Coding/debugging/dev | **Default agent behavior** |

---

## Document-Anchored Socratic Sessions

Triggered when the user directs learning at a specific vault document (Report, Operative Guide, or Study Material). The agent owns the full lifecycle — generation, session continuity, and progress tracking — with zero user overhead.

### Trigger Phrases
"let's review [X report/guide]", "Socratic session on [document]", "quiz me on [document]", "continue our session on [document]", "pick up where we left off on [document]", "review the [topic] report/guide/material", "drill me on [topic] from my notes"

### Pre-Flight (Silent — run before every doc-anchored session)

**1. Identify source document.** Derive `<slug>` from the filename stem (strip extension). If ambiguous, ask once.

**2. Check for Study Material.**
```bash
ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/"<slug>*.md 2>/dev/null
```
- **Found** → use the most recent file as the canonical Study Material doc. Read it to get the TU-XX / Q# question bank.
- **Not found** → silently generate it by invoking the `study-material` skill on the source document.

**3. Check `doc_status`.**
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py doc_status "Study Material/<slug>_<date>.md"
```
- `status: "new"` → fresh start. Greet naturally. Begin drill from TU-01.
- `status: "returning"` → open with a brief, specific recap of progress and missed concepts.

**4. Check Review Session doc.**
```bash
ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Review Sessions/"<slug>_review.md 2>/dev/null
```
Read if it exists. Create at session end if absent.

### Drill Session (uses study-material Phase 2 engine)

- Use the Study Material's TU-XX and Q# IDs as the structured curriculum.
- Question ordering: revisit `concepts_missed` from `doc_status` first, then continue forward from last covered position.
- Adapt difficulty: if `coverage_pct >= 80%`, shift to harder cross-application questions rather than repeating covered ground.
- Socratic correction rules: same as study-material Phase 2 (no answer reveal on first miss; guiding question; reveal on second miss).

### Heartbeat Logging (Silent — every 3 user turns)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
./src/heartbeat.sh --doc "Study Material/<slug>_<date>.md" --doc-type "<type>" \
  --covered "<Q IDs>" --understood "<correct Q IDs>" \
  --missed '[{"concept":"<Q ID>","error_type":"<type>","misconception":"<brief>"}]' \
  --coverage-pct <N> --total <total> --topics "<topics>" --depth 3
```

### Session End

1. Final heartbeat (complete state for this session)
2. Upsert `Review Sessions/<slug>_review.md` — append new session block, do NOT create a new file
3. Update `Review Sessions/INDEX.md`
4. Silently trigger `/knowledge-map`

### Review Session Document Format (`Review Sessions/<slug>_review.md`)

This file is created once and appended after every session. It is the human-readable counterpart to `doc_status`.

```markdown
---
title: "Review Sessions: <Topic Name>"
source_document: "<Reports|Operative Guides>/<slug>.md"
study_material: "Study Material/<slug>_<date>.md"
total_topics: <N TUs>
total_questions: <N Qs>
last_studied: YYYY-MM-DD
session_count: <N>
coverage_pct: <cumulative %>
tags:
  - type/session
  - skill/study-material
  - domain/<domain>
  - source/agent
---

# Review Sessions: <Topic Name>

## Concept Map Status
| Topic | Questions | Cumulative Score | Status |
|-------|-----------|-----------------|--------|
| [TU-01]: <Title> | Q1-Q6 | 5/6 (83%) | Strong |
| [TU-02]: <Title> | Q7-Q12 | 3/6 (50%) | Needs work |

---

## Session Log

### Session 1 — YYYY-MM-DD
**Coverage**: TU-01 + TU-02 (Q1-Q12) | **Score**: 8/12 (67%)
**Understood**: [TU-01] <concept A>, <concept B>; [TU-02] <concept C>
**Gaps**:
- [TU-02] <concept D> (Q9) — conceptual_confusion — <brief misconception>
```

**Rules:**
- Never create a new `<slug>_review.md` — always append a new `### Session N` block.
- `session_count` and `coverage_pct` in frontmatter are updated on every append.
- `## Concept Map Status` table is regenerated from current `doc_status` on every append.
- `## Progress Over Sessions` table is regenerated on every append — shows cumulative trajectory (Session, Date, Coverage, Score, Key Gaps) constructed from all `### Session N` blocks.
- CORRECTED concepts from prior sessions are called out explicitly — progress visibility matters.

---

## RAG Knowledge Workflow

**Full pipeline in skill files** — invoked via `/rag-workflow` or explicit textbook search requests.

**Quick reference**: Assess → Retrieve (`lance_retriever.py compare`) → Transform (subagent reads `scratch_context.md`, writes `transform_output.md`) → Gap Check → Present (read ONLY `transform_output.md`).

---

## Knowledge & Memory Policy

**All saves user-gated. No automatic accumulation.**
- Never `add_fact`/`save_conversation`/`save_session` without explicit request
- Anki cards only on explicit request

**Stores**: LanceDB (`neurosurgery_v4.lance` — 46,714 rows, 22 books) | Anki ChromaDB (`chromadb_store_anki_memory` — dedup only) | Knowledge Graph (`knowledge_graph.db` — SQLite, auto-grows via RAG/bootcamp hooks, includes cognitive pattern detection + calibration profiles) | Session files (`data/Sessions/` — ephemeral, overwritten per query) | Confusion matrix (`confusion_matrix.json` — auto-grows on `cross_contamination` errors) | Obsidian vault (`~/Documents/Obsidian/agentic-neuro/`)

## Command Reference

All commands require the shell prefix. Showing subcommands only:

```bash
# lance_retriever.py
search "query"
compare "query" [--force-refresh] [--visual] [--append] [--output path] [--no-distill] [--no-learner] [--no-frontier]
compare_multi "sq1" "sq2" ["sq3"] [--no-distill] [--no-learner] [--no-frontier]
digest [--input path] [--output path]
prepare_directives "query" [--output path]
audit_citations [--transform path] [--manifest path]
attrition_report [--log path] [--last-n N]
list_textbooks
clear_cache

# frontier_search.py
"query"                                     # writes to frontier_cache.md

# knowledge_graph.py
status | dashboard | activity [--n 30]
gaps [--rotation "X"] [--top N]
fine_grained_gaps [--top N] [--domain "X"]  # concept-level gaps with root_cause + error_process
topics [--domain "X"] [--only-studied] [--sort confidence] [--limit N]
topic_detail "topic"
topic_specificity_check "topic name"         # validate topic name granularity (level 1-3)
add_topic --name "X" --category "Y" [--source "Z"] [--priority N]
context "query" --output data/Sessions/learner_context.json
log_study --topics "t" --understood "c" --gaps "c" [--gap-details 'JSON'] --depth N
log_bootcamp --topics "t" --weaknesses "w" --module "m" --outcome "o" [--calibration 'JSON']
log_pattern --type "T" --description "D" --evidence "E"
log_transfer --concept "X" --topic "Y" --context "Z" [--success]
log_session_narrative --skill "X" --topics "t" --summary "..." --strategy "..." [--teaching-failures 'JSON'] [--key-confusions 'JSON'] [--turns N]
last_session_narrative [--skill "X"] [--topic "X"]   # retrieve most recent teaching narrative
review_queue [--n N] [--domain "X"]
concept_review_queue [--n N] [--domain "X"]          # SM-2 SRS scheduled concepts (use this, not review_queue)
transfer_candidates [--n N]
cognitive_patterns
calibration_profile
confusable_pairs [--topic "X"]
blocking_gaps --topic "X"                            # gaps with unmet prerequisite concepts
concept_chain --concept "X" [--topic "X"]            # full prerequisite + extension chain
add_concept_relationship --a "X" --b "Y" --type prerequisite_of|confusable_with|extends|differentiates_from [--notes "..."]
milestone_report
sync_anki
backfill --telemetry data/Sessions/search_telemetry.jsonl
apply_decay                                          # decays topic confidence AND marks overdue known concepts as 'due'
migrate_confusion_matrix                             # one-time: migrate confusion_matrix.json → concept_relationships table
log_event --topic "T" --source "S" --signal-type "ST" [--depth N] [--category "C"]
load_curriculum --file data/curriculum_skeleton.json
doc_status "Study Material/<slug>_<date>.md"
log_doc_progress --doc "..." --doc-type "..." --covered "Q1,Q2" --understood "Q1" --missed '[...]' --coverage-pct 25 --total-concepts 12

# Iteration 2: Prerequisite Intelligence
seed_prerequisites                                   # auto-seed prerequisite + confusable edges from gap co-occurrence

# Iteration 3: ZPD + Learning Velocity
difficulty_target                                    # ZPD recommendation from last 5 sessions (too_easy/optimal/too_hard)
learning_velocity [--domain "X"] [--n N]            # per-domain confidence change rate — detects stagnation

# Iteration 4: Blind Spot Detection
unknown_unknowns --topic "X" [--n N]                # adjacent curriculum topics NEVER studied (blind spots near current query)
misconception_clusters                               # group root_cause descriptions by cognitive theme (mechanism/context/threshold/anatomy/etc)
seed_topic_adjacency                                 # one-time: seed topic_adjacency table from curriculum subdomain groupings
backfill_specificity                                 # backfill specificity_level + clinical_context for existing 671 topics

# Round 3: Stagnation + fingerprint + SM-2 coupling
backfill_topic_fingerprints                          # backfill topic_fingerprint for existing session_narratives (idempotent)

# Utility scripts
src/preflight.sh "query" [--doc "Study Material/slug.md"] [--skill "X"]   # 8 steps: apply_decay (step 0) + context + directives + case log scan + doc_status + last_session_narrative + concept_review_queue + difficulty_target
src/heartbeat.sh --doc "..." --covered "..." --understood "..." --missed '[...]' --coverage-pct N --total N --topics "..." --depth N [--obsidian-write --topic-name "..." --slug "..." --session-num N --score "..." --skill "..." --domain "..." --understood-detail "..." --gaps-detail "..."]   # doc-anchored: log_doc_progress + log_study + optional <slug>_review.md
src/heartbeat.sh --session-mode --skill "..." --slug "..." --topics "..." --depth N --domain "..." [--understood "..." --gaps "..." --gap-details '...'] --turn-num N --status "in-progress|complete" [--narrative-summary "..." --next-strategy "..." --narrative-failures 'JSON'] [--session-success-rate N.NN] [--obsidian-write --topic-name "..." --understood-detail "..." --gaps-detail "..." --score "..."]   # session mode: log_study + log_session_narrative (at complete) + optional <topic-slug>.md
```

### gap_details Schema (MANDATORY for all learning skills)

Every gap logged must include all six fields. `root_cause` and `error_process` are new required fields as of the KG Redesign Phase.

```json
[{
  "concept": "ICP targets in newly diagnosed high-grade glioma",
  "error_type": "application_failure",
  "error_process": "context_misapplication",
  "misconception": "applied TBI ICP threshold (>20 mmHg) to brain tumor patient",
  "root_cause": "did not distinguish vasogenic (tumor) from cytotoxic (TBI) cerebral edema; management targets derive from edema mechanism, not diagnosis alone",
  "remediation": "teach edema type first, derive ICP targets from pathophysiology"
}]
```

**`error_process` controlled vocabulary** (required, pick one):
- `mechanism_gap` — does not understand the biological mechanism; teach pathophysiology before management
- `context_misapplication` — correct rule applied to wrong clinical context; drill context-switching scenarios
- `prerequisite_absent` — missing foundational concept required here; address prerequisite first
- `numerical_anchor` — anchored on wrong memorized value; spaced recall of correct threshold
- `classification_mismatch` — applied wrong grading/classification system; side-by-side comparison
- `temporal_confusion` — incorrect timing/sequencing; timeline visualization
- `anatomical_ambiguity` — confused adjacent structures; anatomical review

**NEVER log**: `"misconception": "user was unsure"` or `"root_cause": ""` — these are empty signals.

### Topic Naming Convention (ENFORCED)

Topic names MUST be specific enough to distinguish clinical sub-contexts. Run `topic_specificity_check` when uncertain.

**Specificity levels**:
- Level 1 (coarse, REJECTED): "ICP management", "vasospasm", "EVD placement"
- Level 2 (contextual, acceptable): "ICP management in brain tumors"
- Level 3 (precise, preferred): "ICP management in newly diagnosed high-grade glioma", "EVD placement indications in subarachnoid hemorrhage grade III-IV"

**Anti-patterns** — NEVER create topics named like these:
- Single noun: "vasospasm", "herniation", "craniotomy"
- Generic action: "ICP management", "blood pressure control", "anticoagulation"
- Disease only: "TBI management", "SAH management"

**Correct examples**:
- "ICP management in traumatic brain injury (severe)"
- "vasospasm prophylaxis after aneurysmal SAH"
- "EVD management in the setting of elevated ICP post-SAH"
- "anticoagulation reversal in anticoagulant-associated ICH"

### Session-End Sequence (All Learning Skills)

At the end of every session the agent MUST call `log_session_narrative` with the forward-looking teaching strategy. This is the most important call — it persists teaching intelligence across sessions.

```bash
python3 src/knowledge_graph.py log_session_narrative \
  --skill "<skill>" \
  --topics "<comma-separated topics>" \
  --summary "<1-2 sentence session recap>" \
  --strategy "<forward directive for the NEXT session — what approach to use, what to start with, what this learner needs>" \
  --teaching-failures '[{"concept":"...","attempted":"...","why_failed":"..."}]' \
  --key-confusions '[{"concept_a":"...","concept_b":"...","disambiguation_axis":"..."}]' \
  --turns <N>
```

The `--strategy` value must be a complete, actionable sentence, not a placeholder. Example:
> "Start with vasogenic vs. cytotoxic edema distinction before covering ICP management targets in brain tumor patients. Learner anchors on TBI numbers. Use the tumor endothelial barrier breakdown model as the mechanism hook before presenting management thresholds."

Or via heartbeat at `--status complete`:
```bash
./src/heartbeat.sh --session-mode --status "complete" \
  --narrative-summary "..." \
  --next-strategy "..." \
  --narrative-failures '[...]' \
  ...
```

**Embeddings**: `BAAI/bge-m3` 1024-dim via FlagEmbedding. MPS/CPU auto-detected.
**Reranker**: `cross-encoder/ms-marco-MiniLM-L-6-v2` via CrossEncoder. ~22MB, sigmoid scoring.
**Medical NER**: SciSpacy `en_ner_bc5cdr_md` — CHEMICAL/DISEASE entity extraction for entity-aware filtering. Regex fallback if unavailable.
**Post-retrieval pipeline**: RRF fusion → CE rerank → Entity-aware filtering → Parent-child expansion → Adaptive distillation → Entity-enriched gap-fill → Concurrent frontier search.
