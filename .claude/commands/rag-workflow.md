---
name: rag_workflow
description: RAG Knowledge Workflow — full retrieval, transform, and learning pipeline. Automatically loaded for clinical/mechanistic questions. Contains Step 0-5, Gym protocol, spaced verification, search architecture, and cache details.
---

# RAG Knowledge Workflow

This file contains the full RAG pipeline instructions. It is loaded automatically when the Capability Router detects a clinical/mechanistic question.

**Pipeline: Assess → Retrieve → Transform → Gap Check → Present**

Complex queries decompose into atomic sub-queries for independent retrieval, then merge. Transform subagent synthesizes in isolated context. Main agent never reads raw passages.

**Tone**: Expert cognitive coach for PGY-1–PGY-3. High-level, zero fluff. Surgical schemas and mental models over rote enumeration. Challenge the *why*.

### Step 0: Learner Context Pre-Flight

**Run before every RAG query, bootcamp, and intraop guide.** Silent — do not narrate.

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py context "query" --output data/Sessions/learner_context.json
```

Returns JSON with per-topic state, adaptive guidance, cross-capability patterns, suggested depth, remediation directives, transfer candidates.

**Adaptation rules** (from context JSON):
| Field | Action |
|---|---|
| `adaptive_guidance` says skip foundations | Go straight to mechanisms/decision-making |
| `error_count_30d` > 0 | Target the specific gap, not generic re-teaching |
| `"studied_not_tested"` pattern | Offer bootcamp scenario after response |
| `"tested_not_studied"` pattern | Note foundational gaps may exist |
| `"knowledge_application_gap"` | Frame around application, not knowledge |
| `"anki_struggling"` | Re-anchor concept, not just repetition |
| `"never_encountered"` topic | Start from first principles |
| `suggested_depth` ≥ 2 | Target higher-order reasoning |
| `remediation_directives` present | Shape Gym questions per `recommended_mode` + `framing_hint` |
| `transfer_candidates` present | Design Gym/bootcamp to test concept in novel context (Channel 4) |

### Step 1: Assess Query Complexity

- **Simple** (single concept) → single `compare` call
- **Complex** (multi-faceted/comparison/3+ axes) → decompose into 2-3 sub-queries via `compare_multi`

Complexity signals: "compare/vs/contrast/differentiate", multiple distinct concepts joined by "and", 3+ clinical axes. Cap: 3 sub-queries max. When in doubt, single well-crafted query.

### Step 2: Retrieve

Output one status line with detected template before retrieval.

**Frontier search gating**: Skip for pure anatomy/pathophys/mechanisms. Include for treatment protocols, recent evidence, guidelines, outcomes.

```bash
# Simple (with frontier)
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/frontier_search.py "query" && python3 src/lance_retriever.py compare "query"

# Simple (no frontier — foundational)
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/lance_retriever.py compare "query"

# Complex (decomposed)
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/frontier_search.py "query" && python3 src/lance_retriever.py compare_multi "sq1" "sq2" "sq3"
```

`compare_multi` loads models once, runs sub-queries sequentially, merges with 220-char dedup, caps at 20 passages → `scratch_context.md`. `compare` writes to `data/Sessions/scratch_context.md`.

### Step 3: Transform (Subagent)

Detect template from query:

| Template | Triggers |
|---|---|
| `neuro-scaffold` | Default — Anchor→Build→Compress→Gym |
| `board-exam` | "board review", "high yield", "test me" |
| `quick-ref` | "quick", "brief", "short" |
| `socratic-drill` | "tutor me", "drill me", "guide me through" |
| `textbook-chapter` | "teach me", "deep dive", "explain like a textbook" |

Spawn `general-purpose` subagent:

> Read `/Users/gabrielreyes/agentic-neuro/.claude/commands/rag-transform.md` for full instructions.
> **QUERY**: {query} | **TEMPLATE**: {template}
> **CONTEXT_PATH**: `/Users/gabrielreyes/agentic-neuro/data/Sessions/scratch_context.md`
> **LEARNER_CONTEXT_PATH**: `/Users/gabrielreyes/agentic-neuro/data/Sessions/learner_context.json`
> Read both files, apply template with learner-aware personalization, write to `/Users/gabrielreyes/agentic-neuro/data/Sessions/transform_output.md`.

### Step 3.5: Gap Check

1. Read `data/Sessions/retrieval_gap.json`
2. `has_gap: false` → Step 4
3. `has_gap: true` → run ONE follow-up: `python3 src/lance_retriever.py compare "{gap_query}" --append` → re-invoke Transform with: *"FOLLOW-UP pass. Previous synthesis at `transform_output.md`. New context appended for: {gap_reason}. Integrate."* — **hard cap: one follow-up**
4. If `web_search_candidate: true`, carry `web_search_reason` to Step 3.75

### Step 3.75: Web Evidence Gap Flag (User-Gated)

Fire only when local RAG + gap-fill are insufficient (~10-20% of queries). **Never for foundational anatomy/pathophys.** Never stall waiting for web evidence.

Triggers: major query axis has zero passages + empty frontier | evidence likely outdated (>5yr) | query asks about current guidelines/trials/devices | Transform flagged unresolved gap.

**After synthesis** (always deliver what you have first), append:
> **Evidence gap detected:** [gap]. Local textbooks and PMC didn't cover [what]. A search on **[source]** for **"[query]"** would help. Proceed as-is, or check?

Source routing: protocols/guidelines → UpToDate, AANS.org, CNS.org | dosing → UpToDate, MDCalc | devices → manufacturer sites | operative technique → NeurosurgeryAtlas.com | scoring → MDCalc

If Gabriel pastes a finding → integrate with `[Web: Source]` tag. If proceeds → continue as-is.

### Step 4: Present

1. **Read ONLY** `data/Sessions/transform_output.md` — **NEVER** `scratch_context.md`
2. Output synthesis
3. Handle Gym/Socratic/clarification follow-up directly (synthesis is in context at ~3-5K tokens)

**Recall Bridge**: Prepend retrieval question only if genuine connection to prior topic. Prefer overdue concepts from `concepts_due_for_review` (spaced verification). Omit if no connection — never force.

### Follow-Up Context Protocol

When the user asks a follow-up question about a synthesis already delivered in the current conversation:

1. **Do NOT re-read `transform_output.md`** — the full synthesis is already in conversation context
2. **If context window is getting large** (12+ turns or agent signals compression needed):
   ```bash
   cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/lance_retriever.py digest
   ```
   This produces `data/Sessions/synthesis_digest.md` (~500-800 tokens) preserving all clinical facts, thresholds, the Compress mental model, and the Gym question. Read the digest instead of the full synthesis for follow-up context.
3. **For Gym responses**: Answer directly from conversation context — no file reads needed.
4. **For "tell me more about X" follow-ups**: If X was covered in the synthesis, answer from context. If X needs new retrieval, run a fresh `compare` query — do NOT append to the old scratch_context.

### Gym Follow-Up Protocol

- **Correct** → confirm mechanism → TRANSFER scenario (same mechanism, different context)
- **Partially correct** → acknowledge right parts → re-anchor with narrower question
- **Incorrect** → do NOT give answer → guiding question isolating the gap, cite source

**Immediately run Step 5 after any Gym response.** Do not narrate.

### Spaced Verification Protocol

Concepts decay. Knowledge graph tracks last confirmation + spaced interval (`base * (1 + 0.3 * times_confirmed)^1.5`; base=3d with errors, 7d clean). Overdue concepts appear in `learner_context()`. **User should never feel artificially quizzed** — verification woven invisibly:

**Channel 1 — Gym Enrichment**: `same_topic_review_due` → incorporate overdue concept into Gym question, testing it in context of new material.

**Channel 2 — Recall Bridge**: `concepts_due_for_review` from other topics → if genuine connection to current query, use as Recall Bridge. Must feel like "connecting the dots", not a pop quiz.

**Channel 3 — Bootcamp Seeding**: Overdue concepts in same domain as scenario → design scenario requiring those concepts.

**Channel 4 — Transfer Challenge**: `transfer_candidates` (confirmed 2+ times, never cross-validated) in related domain → test in new context without telling user. Log outcome:
```bash
# Success:
python3 src/knowledge_graph.py log_transfer --concept "X" --topic "Y" --context "Z" --success
# Failure (omit --success → flips to "unknown" with error_type "application_failure"):
python3 src/knowledge_graph.py log_transfer --concept "X" --topic "Y" --context "Z"
```

**Verification logging**: correct → `log_study --understood "concept"` (resets interval, increments `times_confirmed`). Wrong → `log_study --gaps "concept"` or `--gap-details` (flips to "unknown"). Aggressive: one correct resets, one failure flips.

### Step 5: Log Learning Signal

**After Gym interaction or topic change.** Captures per-concept mastery. Do not narrate.

```bash
# Simple form
python3 src/knowledge_graph.py log_study --topics "t1,t2" --understood "concept A,concept B" --gaps "missed concept" --depth 2

# Rich form (preferred when error cause is identifiable)
python3 src/knowledge_graph.py log_study --topics "t1" --understood "A,B" --gap-details '[{"concept":"nimodipine 60mg q4h","error_type":"cross_contamination","misconception":"confused with methylprednisolone 30mg/kg","remediation":"re-anchored to trial data"}]' --depth 2
```

**Error types**: `numerical_recall` (forgot values) | `conceptual_confusion` (confused related concepts) | `cross_contamination` (wrong subspecialty protocol) | `application_failure` (knows fact, can't apply) | `reasoning_gap` (missing causal step) | `omission` (never encountered)

**Mastery assessment**: `--understood` = positive evidence only (correct Gym, accurate reasoning). `--gaps` = concepts missed. Silence = log neither (don't assume from silence).

**Concept specificity**: Be precise. Good: `"Fisher grade 3 highest vasospasm risk"`. Bad: `"vasospasm"` (topic name, not concept).

**Concept dictionary is persistent**: gap→demonstrated = flip to "known", `times_confirmed`++. known→missed = flip to "unknown", `times_missed`++. Error context preserved for Step 0 pre-flight.

**Meta-cognitive patterns** (recurring cross-topic patterns):
```bash
python3 src/knowledge_graph.py log_pattern --type "cross_contamination_prone" --description "..." --evidence "..."
```
Types: `strong_mechanistic_learner`, `cross_contamination_prone`, `numerical_recall_weak`, `visual_spatial_strength`, `application_transfer_gap`

### Post-Interaction Routing

After logging gaps with a clear `error_type`, offer ONE targeted remediation (highest `times_missed` or just-logged gap). User must opt in.

| Error Type | Offer |
|---|---|
| `numerical_recall` | Rapid-fire numbers quiz |
| `conceptual_confusion` | Causal chain walkthrough |
| `cross_contamination` | Disambiguation table |
| `application_failure` | Bootcamp scenario |
| `reasoning_gap` | Scaffolded walkthrough |

Routing: `drill`/`socratic` → RAG with template override | `disambiguation` → confusion_matrix.json comparison | `scenario` → focused bootcamp | `scaffold` → RAG with `textbook-chapter`

### Search Architecture

LanceDB (`neurosurgery_v4.lance`) — 46,714 rows, 22 books.

- **Embeddings**: BAAI/bge-m3 1024-dim (dense + sparse) via FlagEmbedding
- **Reranker**: cross-encoder/ms-marco-MiniLM-L-6-v2 (~22MB, sigmoid scoring)
- **Indexing**: IVF-PQ on dense vectors + 5 FTS indexes (child_text, heading, section_path, table_markdown, caption_text)
- **Retrieval**: Dense ANN + FTS fused via RRF (k=60)
- **Parent-child**: Each row stores `child_text` (~512 tok, retrieval) and `parent_text` (~2048 tok, context delivery)
- **Pre-filter**: Reference/bibliography chunks stripped before reranking
- **Defaults**: `min_similarity=0.35`, `max_per_source=10`, `n_results=35`, `min_sources=3`
- **Adaptive Context Distillation**: Multi-axis queries auto-decomposed → cross-encoder scores passages per axis → budget allocation per axis with source diversity → child_text for supplementary, parent_text for primary matches. Cuts scratch_context.md by ~50-60%. Bypass with `--no-distill`.
- **Learner-Aware Reranking**: Reads `learner_context.json` (from Step 0 pre-flight) → gap concepts get +0.05 tiebreaker, confirmed concepts get -0.03. Never filters — only breaks ties. Bypass with `--no-learner`.
- **Retrieval Coverage Signal**: Writes `data/Sessions/retrieval_coverage.json` after each query — per-source passage counts, per-axis coverage strength.
- **Flags**: `--visual` (image extraction) | `--append` (multi-query merge, 220-char dedup, 20 passage cap) | `--force-refresh` (backward compat) | `--no-distill` (bypass axis distillation) | `--no-learner` (bypass KG rerank modifier)
- **Status output**: `OK {n} passages | {s} sources | {ms}ms`

### Cache Architecture

No disk cache needed — LanceDB IVF-PQ queries are fast enough without caching.

| Cache | Lifecycle | Notes |
|---|---|---|
| LanceDB connection + table | Process lifetime | Singleton, opened once |
| BGE-M3 embedding model | Process lifetime | ~4s first load, then instant |
| MiniLM-L6 reranker | Process lifetime | ~1s first load, then instant |
| Frontier cache (`frontier_cache.md`) | 10-min TTL | Written by frontier_search.py, read by lance_retriever.py |

`clear_cache` is a no-op. `--force-refresh` accepted for backward compatibility.

Latencies: fresh cold ~12-15s (includes model load) | fresh warm ~6-10s | `compare_multi` 3-query ~20-30s | gap pass +6-10s
