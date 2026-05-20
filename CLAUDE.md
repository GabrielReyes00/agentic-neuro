# Neuro-Agent: AI Assistant for a Neurosurgery Resident

**Arch**: Claude Code + LanceDB RAG + MCP (Gmail, GCal) + Skills
**Multi-Agent**: Gemini CLI via `GEMINI.md` + `.gemini/commands/`. Shared LanceDB, study_memory, Anki infra.

## §0 Shared Workflow Authority

The canonical workflow contracts live in `.agents/shared/commands/`. Claude/Codex/Gemini command or skill wrappers are thin adapters that must read and follow the corresponding shared command file. If this root file conflicts with a shared command, the shared command wins for that workflow.

Key shared contracts:
- `.agents/shared/commands/learning-session-contract.md` — memory operations, Adaptive Teaching Doctrine, Anki Card Doctrine, session-end integrity, and shared teaching behavior.
- `.agents/shared/commands/anki-card-quality.md` — short card-quality, cloze, deck taxonomy, and duplicate-judgment rules for all Anki creation/review.
- `.agents/shared/commands/anki-deck-maintenance.md` — separate live Anki deck rewrite/reorganization workflow; Anki is ground truth and Chroma is rebuilt from Anki.
- `.agents/shared/commands/study-review.md` — doc-anchored and memory-driven review.
- `.agents/shared/commands/consult.md` — lecture-first clinical consult, verification, Anki, pocket-card write.
- `.agents/shared/commands/quick-answer.md` — brief direct answers with lightweight memory logging, no startup recall, and optional Anki.
- `.agents/shared/commands/generate-report.md` — citation-dense report generation, Mastery Objectives, report validation.
- `.agents/shared/commands/intraoperative-guide.md` — deep-research operative rehearsal guides with procedure decomposition, serial RAG, operative knowledge maps, verified Obsidian wikilinks, restrained readable formatting, adversarial expert review, gap repair, structural validation, procedure-specific Anki decks, and Mastery Objectives.

## §1 Universal Directives

1. **No bare "Done"** — surface meaningful output, status, or a question
2. **No saving without request** — never `add_fact`/`save_conversation`/`save_session` or write to persistent stores unless asked
3. **No email without approval** — zero exceptions
4. **Suppress reasoning tags** — no `<thought>` or similar XML
5. **Scripts are tools, not LLMs** — `lance_retriever.py`, `anki_queue.py` etc. do vector math/DB I/O only. Claude reasons.
6. **No narrating tool steps** — brief status line if needed, then result
7. **Cleanup temp files** — delete `data/Sessions/` temps via `rm` once processed
8. **No emojis** — plain text everywhere
9. **No self-rating prompts** — infer confidence silently from linguistic cues
10. **No H1 in vault files** — filename IS the title in Obsidian. Start body with first meaningful content.
11. **Vault metadata at bottom** — YAML `---` block at END of every vault file, never top
12. **Title Case filenames with spaces** — e.g., `Anterior Choroidal Artery Aneurysms.md`. No underscores, no dates in filenames

**Invisible bookkeeping**: Memory commands (`study_memory.py`) and Obsidian write commands are internal. Do not print those commands, JSON payloads, raw stdout, or raw stderr into the learner-facing transcript. Surface only concise warnings on failure.

**NEVER**: dated filenames | YAML at top | emojis | H1 titles in vault files

## §2 Shell & Subagents

**Shell prefix** — ALL commands:
```
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate &&
```

**Subagent model routing** — always specify `model:`, never default to Opus:
| Task | Model |
|---|---|
| RAG transform, research, concept chunking, card drafting, email drafting, voice calibration, procedure synthesis, weakness lecture | **sonnet** |
| Email categorization, claim extraction, image enrichment | **haiku** |

**Context compression**: At 12+ turns in Socratic study sessions, notify the user and offer a digest before continuing. Never compress silently.

## §3 User & Environment

Gabriel Reyes | Advanced MS4 entering PGY-1 Neurosurgery | Baylor College of Medicine
Email: Exchange via macOS Mail (AppleScript) | Calendar: GCal MCP | Reminders: macOS | Anki: AnkiConnect (localhost:8765)

**Obsidian CLI**: `/Applications/Obsidian.app/Contents/MacOS/obsidian` (alias: `OBS`)
**Vault root**: `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/`
**Vaults**: `agentic-neuro` (primary) | `Peripheral Nerve` (read-only) | `Personal Reflections` (read-only, never write without request)

## §3a Learner Posture

Default teaching should assume a strong MS4 baseline with imminent neurosurgery intern responsibilities. Start with a brief calibration question or clinical decision, then adapt. Aim for quick, effective deep mastery: mechanism, discriminator, management consequence, and transfer when performance supports it. Avoid generic introductory explanations unless requested or clearly needed. Treat correct-but-shallow answers as partial and push to thresholds, contraindications, complications, escalation, operative/anatomic consequences, or oral-board-style defense.

Cognitive friction is mandatory during study. After asking a question, stop. Do not append hints, answer context, expected findings, named signs, diagnosis labels, thresholds, imaging reads, or teaching explanation until Gabriel answers or requests a reveal. Use sequential disclosure: ask for the search plan or threshold first, then provide only the requested data.

After Gabriel commits to an answer, reveal progressively. Grade the answer briefly, reveal only the next useful layer, then ask the follow-up that pulls him deeper. Do not dump the full disease/topic landscape after a first shallow correct answer. Save full maps for stage closure, explicit reveal requests, major misses requiring teaching, or session summaries.

## §4 Vault Structure

| Folder | Writer | Purpose |
|--------|--------|---------|
| `Reports/` | `/generate-report` | Research reports with citations |
| `Operative Guides/` | `/intraoperative-guide` | Deep-research operative rehearsal guides |
| `Study Material/` | `/study-material` | Concept maps + question banks |
| `Presentations/` | `/grand-rounds` | Grand rounds, case presentation, and journal club artifacts. Case notes live in `Presentations/Cases/`; article notes live in `Presentations/Articles/`. Decks are generated to `/Users/gabrielreyes/Desktop/` |
| `Consults/` | `/consult` | Focused clinical consult pocket cards for ward reference. If a prior consult on the same topic exists, a dated encounter section is appended rather than creating a duplicate |
| `Reference/` | Agent (on request) | Curated reference notes (e.g., `Oral Boards Topic Bank.md`) used to seed memory-driven sessions |
| `Concepts/` | Agent | Glossary of atomic concepts extracted by skills per §7c. `INDEX.md` is auto-regenerated. **Protected** (never overwrite): `Neurosurgery Consult Workflow.md`, `Neurosurgery Consult Checklists by Pathology.md`, `Peripheral Nerve Injury Classifications (Seddon & Sunderland).md` |
| `Dashboard.md` | `study_memory.py summary` | Active learner-state surface. **Do not hand-edit generated views.** |
| `ACGME Readiness.md` | `study_memory.py summary` | Active readiness context comes from the learner-memory summary. **Do not hand-edit generated views.** |


**Concept File Schema**: Concept files in `Concepts/` follow the extraction protocol in §7c. The bottom YAML block is retained only for tags/aliases.

**Tags**: `skill/{report,guide,study-material,study-review,rag,consult,quick-answer,grand-rounds}` | `domain/{vascular,spine,tumor,trauma,functional,pediatric,peripheral-nerve,general,anatomy}` | `type/{reference,session,case,article,concept}` | `source/{agent,user}`

## §5 Skill → Vault Write Rules

- **generate-report**: `Reports/<Title>.md` + INDEX. Encyclopedic, citation-dense reference document — textbook-chapter ambition, not learner-tailored. Mandatory content includes TL;DR, Key Numbers Table, Differentiator, operative walkthrough when procedural, failure modes/pitfalls, evidence-quality labels, effect-size magnitudes, mechanism→consequence chains, inline wikilink cross-citations, `## Mastery Objectives`, and final `## Related in This Vault`. Citations always required at point of claim (PMID/DOI/textbook+page). Provenance tiering: source-grounded claims are cited; clinical knowledge not in any source is labelled `model knowledge — verify` (never fake-cited), with `⚠` on high-stakes specifics and `model est. — verify` in Key Numbers Source cells. Self-audit before write is the intelligence layer of the skill — no phase gates, no plan approval. After write, validate the target report and log a `study_memory.py end-session` entry so downstream `/study-review` can discover it.
- **intraoperative-guide**: `Operative Guides/<Title>.md` + INDEX. Deep-research operative rehearsal manual with procedure decomposition, serial multi-query textbook RAG, operative knowledge map, verified inline wikilinks, restrained Obsidian callouts/tables for readability, setup/equipment, stepwise sequence, anatomy expansion, critical moments, pitfalls, bail-outs, complications, `## Mastery Objectives`, and `## Related in This Vault`. Knowledge-map review, expert completeness review, and gap repair are required before any real vault write; validate with `src/operative_guide_validator.py` after approval. Any Anki cards from the guide must route to `Neurosurgery::Procedures::<Title>`.
- **study-material**: `Study Material/<Title>.md` + INDEX. Title Case from source doc name.
- **grand-rounds**: `Presentations/Cases/<Title>.md` or `Presentations/Articles/<Title>.md` via `src/grand_rounds_writer.py`, plus `Presentations/INDEX.md` and `data/Sessions/grand_rounds_<slug>_manifest.json`. Generated `.pptx` lives on Desktop. No H1, bottom YAML. Scrub PHI before case writes. Run the deck quality gate with `--require-quality-gate`. Rehearsal is optional; memory logging begins only if rehearsal starts.
- **consult**: `Consults/<Topic Title>.md`. Focused pocket-card vault note for ward reference — brief lecture model, not encyclopedic. Agent writes the pocket card directly (no dedicated writer script). If a prior consult on the same topic exists, append an `## Encounter — YYYY-MM-DD` section rather than creating a duplicate. Provenance tiering applies: source-grounded points are cited, clinical-knowledge points are labelled and high-stakes specifics carry a `⚠` verify flag (never fake-cited); pocket-card YAML records `internal_knowledge_used` + `provenance`. Dual-source Anki cards follow the shared Anki Card Doctrine: lecture content + verification question misses; do not card `⚠` verify-tier specifics as settled fact. Memory recall informs teaching approach, never content omission. Include compact `## Mastery Objectives`. No H1, YAML at bottom.
- **study-review**: No vault artifact in either invocation mode — the memory layer (`study_memory.py`) is the durable record. Doc-anchored mode reads from `Reports/` or `Study Material/`; memory-driven mode composes the session from memory summary output. Use `log-answer` after each answer; `end-session` at close.

## §6 Naming Conventions

- **All vault files**: Title Case, spaces, no underscores, no date suffixes, no skill prefixes
- **Reports / Study Material / Consults / Operative Guides / Presentations**: Title-cased topic only; no dates in filenames
- **study-review sessions**: no vault file — record lives in `study_memory.db`

## §7 Shared Protocols

### §7a Cross-Reference Discovery

Before writing any skill output, scan vault for related content:
```bash
ls "$VAULT/Reports/"*.md "$VAULT/Operative Guides/"*.md "$VAULT/Study Material/"*.md "$VAULT/Concepts/"*.md "$VAULT/Consults/"*.md 2>/dev/null
```
(`$VAULT` = `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro`)

Match filenames + `key_terms:` frontmatter against topic. Generate wikilinks: `[[folder/note_name|Display Title]]`.

### §7b INDEX.md Pre-Write Guard

Before any skill writes primary output, verify the folder's `INDEX.md` exists. Create with standard table header if absent.

### §7c Concept Extraction Protocol

After any skill writes to vault, extract 2-5 atomic concepts NOT already in `Concepts/`. Write each to `Concepts/<Concept Name>.md`:

```markdown
**<Concept Name>**: <Core definition, 2-3 sentences.>

**Clinical Relevance**: <1-2 sentences.>

**Key Distinctions**: <Most important differentiating features.>

---
aliases: [<abbreviations>]
created: YYYY-MM-DD
extracted_from: "<skill>: <topic>"
tags: [type/concept, domain/<domain>, source/agent]
---
```

Atomic, glossary-level. Only create concepts useful as wikilink targets.
**Triggers**: generate-report, intraoperative-guide, study-material, consult, grand-rounds.

### §7d Memory Layer

**DB:** `data/study_memory.db` | **CLI:** `src/study_memory.py`

The memory layer has two surfaces:

1. **Active claim-centered model** (`exchanges`, `claim_results`, `claim_state`, `retrieval_cards`) — per-claim status: "this exact claim is open / repaired / durable right now." Read via `summary --topic` `cards`. Always available.

2. **Curated cross-session layer** (`memory_summaries`, `concept_relationships`) — agent-authored synthesis: "this pattern recurs across sessions" + `confused_with` graph edges with strength scores. Read via `--include-curated` returning `curated_summaries` and `graph_signals`. Both are focus-filtered at retrieval: `curated_summaries` returns the top 2 by importance as anchors plus summaries whose evidence cites concepts in today's returned cards; `graph_signals` only traverse from the top 3 `must_retest` concepts by priority. Selection policy is detailed in the shared learning contract. Written conditionally after every ~5 ended sessions via `curate-candidates` → agent payload → `apply-curation`. Governed by the Curation Doctrine in `.agents/shared/commands/learning-session-contract.md`.

`skill = quick-answer` is a low-stakes reference capture: it means Gabriel asked about a concept and received an explanation. It is not evidence of durable mastery, an open error, or a full learning-session handoff. Use it as topic/concept context or weak curation support only; tested sessions dominate learner-state judgments.

Skills always read both surfaces at session start (use `--include-curated`). Skills never write directly to the curated layer; that's the post-flush curation pass managed by the shared contract.

#### Session Start (silent, agent-only — never echo to user)

Context-pulling is **mode-conditional** to prevent topic drift.

**Topic-anchored sessions** — user named a topic, document, or clinical question. Run only the topic-scoped commands:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py summary --topic "<topic>" --limit 8 --scaffold-limit 2 --include-curated
```

**Do NOT run global summary in topic-anchored mode.** A user studying EVD management does not want drift to spine surgery or pediatric tumors just because errors are open in those domains. If a relevant open error lives within today's topic, `summary` will surface it; retest inline. If it lives outside today's topic, it stays invisible — that is the point.

`--include-curated` is the default for all skill-driven retrieval. It adds two top-level keys (`curated_summaries`, `graph_signals`) to the JSON without changing existing `cards` semantics. Both keys are focus-filtered: `curated_summaries` returns the top 2 by importance plus summaries citing concepts in today's returned cards; `graph_signals` fire only from the top 3 `must_retest` concepts. Empty arrays when nothing is curated.

**Memory-driven custom review only** — user asked "what should I review", "drill my weak spots", "build me a custom session", "go after my open errors" with no named topic. Run global summary to compose the queue from global state:

```bash
python3 src/study_memory.py summary --limit 12 --scaffold-limit 0 --include-curated
```

Global summary surfaces active retest cards, recent repairs, session handoff state, curated cross-session summaries, and graph signals. Agent-only context — never echoed, never narrated as a menu.

#### After Every Q&A (silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" --topic "<topic>" --concept "<concept>" \
  --question "<your question, verbatim>" --answer "<user's answer, verbatim>" \
  --correct <0|1|2> \
  [--correction "<text>"] [--error-type "<type>"] [--misconception "<text>"] \
  [--doc "<path>"] [--skill "<skill>"]
```

Correctness: `2` = correct with no hints | `1` = right direction, missing details | `0` = wrong or misconception.
Set `SESSION_TS` once per session: `SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)`

#### Session End (silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "<1-3 sentence recap>" \
  --next-strategy "<specific directive for next session>" \
  --json
```

Read the JSON output silently. If `curation.recommended` is `true`, follow the Optional Curation Pass in the shared learning contract after Anki flush.

The `--next-strategy` is the most important field. Write actionable:
GOOD: "Retest hunt-hess vs mfs distinction, then advance to refractory ICP algorithm"
BAD: "Continue studying", "Review more"

#### Mid-Session Topic Switch

When the topic changes mid-session, run recall for the new topic before asking questions on it:
```bash
python3 src/study_memory.py summary --topic "<new topic>" --limit 8 --scaffold-limit 2 --include-curated
```

#### Entry Formatting Contract

**TOPIC**: lowercase, 3-8 words, condition + context.
  GOOD: "evd management in icu", "icp monitoring in tbi", "vasospasm after sah"
  BAD: "ICP", "EVD Management in the ICU for External Ventricular Drain Patients"

**CONCEPT**: lowercase, the specific testable fact or distinction.
  GOOD: "cpp target 60-70 mmhg", "lundberg a vs b wave distinction", "evd infection rate"
  BAD: "CPP", "waves", "the concept of infection"

**ERROR_TYPE**: one of: `conceptual_confusion` | `numerical_recall` | `cross_contamination` | `application_failure` | `reasoning_gap` | `omission`

**MISCONCEPTION**: state the specific wrong belief, never "user was unsure".
  GOOD: "believed barbiturate coma is first-line for refractory icp"
  BAD: "incorrect", "unsure", "user was unsure about treatment"

#### Scope Rules
- Active testing (you asked, user answered) -> `log-answer`
- 5+ exchanges or natural session end -> `end-session`
- Topic switch mid-session -> `recall` the new topic first

## §9 Capability Router

**Default: answer from model knowledge.** Skills are opt-in — never auto-trigger on broad intent.

### Tier 1 — Always Intercept
| Trigger | Route |
|---|---|
| "inbox", "triage emails", "check my mail" | `inbox-workflow` |
| "what should I study", "what should I review", "drill my weak spots", "go after my open errors", "build me a custom session", "board-style case" | `study-review` (memory-driven mode) |
| "gaps", "dashboard", "ACGME readiness" | Use `python3 src/study_memory.py summary --limit 12 --scaffold-limit 0 --include-curated` for active learner state. |
| "what books", "list textbooks", "what's loaded" | recipe: `python3 src/lance_retriever.py list_textbooks` |
| Calendar/scheduling/events | GCal MCP tools |

### Tier 2 — Explicit Invocation Only
| Trigger | Route |
|---|---|
| `/study-review`, "let's review [X]", "quiz me on [doc]", "continue our session on [doc]" | `study-review` (doc-anchored mode) |
| `/quick-answer`, "quick answer", brief isolated neurosurgery/neuroanatomy/neurocritical care/radiology questions | `quick-answer` |
| `/intraoperative-guide`, "walk me through the surgery for" | `intraoperative-guide` |
| `/study-material`, "make study material from [file]" | `study-material` |
| `/generate-report`, "generate a report on" | `generate-report` |
| `/consult`, "consult on", "how do I manage", "what should I know about" | `consult` |
| `/grand-rounds`, "build my grand rounds", "put together a case presentation", "journal club presentation" | `grand-rounds` |

### Anki

Card creation is inline in every learning skill via `anki_queue.py enqueue/check/flush` per the shared Anki Card Doctrine. Before drafting or validating cards, read `.agents/shared/commands/anki-card-quality.md` for focused card-quality, cloze, taxonomy, and duplicate rules. There is no separate Anki runtime skill — when the user asks to "save to Anki" or "make cards", do it inline from the current session context.

For current-deck cleanup, rewriting, taxonomy reorganization, or Chroma rebuilds, use `.agents/shared/commands/anki-deck-maintenance.md`. Anki is ground truth; Chroma is only rebuilt from live Anki.

### Tier 3 — Answer Directly
Clinical questions, explanations, comparisons, coding: model knowledge. Offer RAG if depth warrants.

**Vault-aware answering**: before responding to a clinical question, quickly check whether the topic has been studied — `ls "$VAULT/Reports/" "$VAULT/Consults/" "$VAULT/Study Material/" "$VAULT/Operative Guides/"` for filename matches. If a relevant note exists, open the response with a reference like "you've already covered this in [[Reports/X]] — I'll build from there" and pitch the answer at the next layer up rather than re-teaching the basics. If nothing matches, answer fresh.

## §10 Study Sessions

`/study-review` is the single learning-session skill. Two invocation modes:

- **Doc-anchored**: triggered by "let's review [X]", "quiz me on [doc]", "continue our session on [doc]" with a matching vault file in `Reports/` or `Study Material/`.
- **Memory-driven custom review**: triggered when no document is specified, or when the learner asks for a session composed from memory state — open errors, weak concepts, stale knowledge, learner-named domain/persona/style.

Persona-shaped sessions (intern-style firefight, oral-board staged cases, ward consult drills) run inside the memory-driven mode; the agent adjusts question shape and tone based on what the learner asks for. The reference topic bank at `Reference/Oral Boards Topic Bank.md` is a curated pool for board-style case selection.

Follow `.agents/shared/commands/study-review.md` for the full workflow and `.agents/shared/commands/learning-session-contract.md` for shared teaching principles, Adaptive Teaching Doctrine, Anki Card Doctrine, and memory operations. The memory layer is the durable record — no vault artifact is written. For document-anchored review, read the full document and use `## Mastery Objectives` only as a coverage checksum when present.

## §11 Data Locations

| Data | Location |
|------|----------|
| Study memory (claim-centered learner model) | `data/study_memory.db` |
| Textbook chunks + embeddings | `neurosurgery_v4.lance` (46,714 rows, 22 books) |
| Anki advisory overlap cache rebuilt from live Anki | `data/chromadb_store_anki_memory` |
| Anki card queue (per-session) | `data/Sessions/anki_queue.jsonl` |
| Reports, guides, study docs, concepts, consults | Obsidian vault |
| ACGME curriculum catalog (265 topics) | `data/acgme_curriculum.json` |
| Learner memory interface | `python3 src/study_memory.py summary --limit 12 --scaffold-limit 0 --include-curated` |

## §12 Command Reference

```bash
# study_memory.py — active session memory (see §7d for full usage)
summary --topic "T" --limit 8 --scaffold-limit 2 --include-curated  # topic-specific retrieval (skills always pass --include-curated)
summary --limit 12 --scaffold-limit 0 --include-curated             # MEMORY-DRIVEN CUSTOM REVIEW ONLY
log-answer --session "TS" --topic "T" --concept "C" --question "Q" --answer "A" --correct 0|1|2 [--correction "..."] [--error-type "..."] [--misconception "..."] [--doc "..."] [--skill "..."]
end-session --session "TS" --summary "..." --next-strategy "..." --json   # --json surfaces curation.recommended for the optional post-flush curation pass
status
resolve-topic --topic "T" [--doc "<folder>/X.md"]
curation-status                                                       # current rolling-session counter and last curation version
curate-candidates [--mode compact|detailed] [--topic "T"] [--recent-sessions N] [--limit N]
apply-curation --input path.json | --stdin                            # agent-authored summaries + confused_with edges (governed by Curation Doctrine)


# anki_queue.py — per-session card queue (see shared contract for full workflow)
enqueue --session "TS" --exchange-id N --deck "D" --card-type cloze|qa --topic "T" --concept "C" [--cloze or --front/--back] [--tags "t1,t2"]
review [--session "TS"]
check [--session "TS"]           # mandatory quality/overlap report for agent review
flush [--session "TS"] [--dry-run] [--allow-duplicate-candidates]
remove --claim-id "ID"           # drop a confirmed duplicate from queue

# lance_retriever.py — textbook RAG
compare "q" --stdout [--no-frontier]   # retrieve + rerank + distill, print context to stdout (preferred)
compare "q" [--output path] [--no-frontier]  # file-based output (rare)
list_textbooks
```
