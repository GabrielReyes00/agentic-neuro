---
name: rag_workflow
description: RAG Knowledge Workflow — full retrieval, transform, and learning pipeline for deep textbook-grounded answers. Invoke via /rag-workflow or when the user explicitly asks to search textbooks, look something up in the database, or says "RAG this". Do NOT auto-trigger on general clinical questions — answer those from model knowledge first.
---

# RAG Knowledge Workflow

**Pipeline: Assess → Retrieve → Transform → Gap Check → Present**

Complex queries decompose into atomic sub-queries for independent retrieval, then merge. Transform subagent synthesizes in isolated context. Main agent never reads raw passages.

**Tone**: Expert cognitive coach for PGY-1-3. Zero fluff. Surgical schemas and mental models. Challenge the *why*.

### Step 0: Pre-Flight (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && ./src/preflight.sh "query"
```

Produces `data/Sessions/learner_context.json` + `data/Sessions/transform_directives.json`. If `case_log_sync.txt` lists new files, run Case Log Proactive Sync per CLAUDE.md §5.

**Session continuity** (silent):
```bash
python3 src/knowledge_graph.py last_session_narrative --skill "rag-workflow" --topic "<query topic>"
```
If the query topic matches a prior session (non-null result):
- Read `next_session_strategy` — shape Gym questions to follow the recommended approach
- Read `key_confusions_json` — re-test previously confused concepts before advancing
- Read `teaching_failures` — avoid repeating failed approaches
- Surface prior gaps in the Adaptation rules below

**Adaptation rules** (from context JSON):
| Field | Action |
|---|---|
| `adaptive_guidance` says skip foundations | Go straight to mechanisms/decision-making |
| `error_count_30d` > 0 | Target the specific gap |
| `"studied_not_tested"` | Offer bootcamp after response |
| `"tested_not_studied"` | Note foundational gaps may exist |
| `"knowledge_application_gap"` | Frame around application |
| `"anki_struggling"` | Re-anchor concept |
| `"never_encountered"` | Start from first principles |
| `suggested_depth` >= 2 | Target higher-order reasoning |
| `remediation_directives` present | Shape Gym per `recommended_mode` + `framing_hint` |
| `transfer_candidates` present | Design Gym to test concept in novel context |

### Step 1: Assess Query Complexity

- **Simple** (single concept) → single `compare` call
- **Complex** (multi-faceted/comparison/3+ axes) → decompose into 2-3 sub-queries via `compare_multi`

Cap: 3 sub-queries max.

### Step 2: Retrieve

Output one status line with detected template before retrieval.

**Frontier search gating**: Skip for pure anatomy/pathophys/mechanisms. Include for treatment protocols, recent evidence, guidelines, outcomes.

```bash
# Simple (with frontier)
python3 src/frontier_search.py "query" && python3 src/lance_retriever.py compare "query"

# Simple (no frontier — foundational)
python3 src/lance_retriever.py compare "query"

# Complex (decomposed)
python3 src/frontier_search.py "query" && python3 src/lance_retriever.py compare_multi "sq1" "sq2" "sq3"
```

### Step 3: Transform (Subagent)

Detect template from query:
| Template | Triggers |
|---|---|
| `neuro-scaffold` | Default |
| `board-exam` | "board review", "high yield", "test me" |
| `quick-ref` | "quick", "brief", "short" |
| `socratic-drill` | "tutor me", "drill me", "guide me through" |
| `textbook-chapter` | "teach me", "deep dive", "explain like a textbook" |

Spawn `general-purpose` subagent (`model: "sonnet"`):
> Read `.claude/commands/rag-transform.md` for full instructions.
> QUERY: {query} | TEMPLATE: {template}
> CONTEXT_PATH: `data/Sessions/scratch_context.md`
> DIRECTIVES_PATH: `data/Sessions/transform_directives.json`
> Read both files, apply template with learner-aware personalization, write to `data/Sessions/transform_output.md`.

### Step 3.5: Gap Check

1. Read `data/Sessions/retrieval_gap.json`
2. `has_gap: false` → Step 4
3. `has_gap: true` → ONE follow-up: `python3 src/lance_retriever.py compare "{gap_query}" --append` → re-invoke Transform as follow-up pass. Hard cap: one follow-up.
4. If `web_search_candidate: true`, carry to Step 3.75

### Step 3.75: Web Evidence Gap Flag (User-Gated)

Fire only when local RAG + gap-fill are insufficient (~10-20% of queries). Never for foundational anatomy/pathophys. **Always deliver synthesis first**, then append:
> **Evidence gap detected:** [gap]. A search on **[source]** for **"[query]"** would help. Proceed as-is, or check?

Source routing: protocols → UpToDate/AANS/CNS | dosing → UpToDate/MDCalc | devices → manufacturer sites | operative technique → NeurosurgeryAtlas.com

### Step 4: Present

1. Read ONLY `data/Sessions/transform_output.md` — NEVER `scratch_context.md`
2. Output synthesis
3. Handle Gym/Socratic/clarification follow-up directly

**Recall Bridge**: Prepend only if genuine connection to prior topic. Prefer overdue concepts from `concepts_due_for_review`. Omit if no connection.

**Follow-up context**: Don't re-read files for follow-ups already in conversation context. For large conversations, run `digest` to get a compact version.

### Gym Follow-Up Protocol

- **Correct** → confirm mechanism → TRANSFER scenario (same mechanism, different context)
- **Partially correct** → acknowledge right parts → narrower re-anchor question
- **Incorrect** → do NOT give answer → guiding question isolating the gap

**Session timestamp (set once at first Gym question, reuse for all exchanges):**
```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```
Initialize a turn counter at 0. Increment before each `record-answer` call.

**After every Gym response, immediately run (silent):**

1. **Atomic per-answer memory log** — route correctness by outcome:
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/memory_orchestrator.py record-answer \
  --session-ts "$SESSION_TS" --turn <N> --skill "rag-workflow" \
  --topic "<topic>" --concept "<specific concept tested>" \
  --question "<your question, verbatim>" \
  --answer "<user's answer, verbatim or close paraphrase>" \
  --correct <0|1|2> \
  [--correction "<your correction/explanation if incorrect>"] \
  [--error-type "<type>"] [--misconception "<specific wrong belief>"] \
  [--root-cause "<why>"] [--remediation "<what should fix it>"] \
  [--teaching-approach "<approach used>"] \
  [--retrieval-sources "<source_book: heading>"] \
  [--depth <N>] [--domain "<domain>"] [--response-confidence "high|low"]
```
Correctness routing: correct with no hints = `--correct 2` | right direction but missing key details = `--correct 1` | wrong answer or misconception = `--correct 0`. Capture the ACTUAL question and answer. For breakthroughs, add `--breakthrough --insight "<what clicked>"`.

2. Crash-safe heartbeat (session-mode, `--skill "rag-workflow"`, `--obsidian-write`)

### Spaced Verification Protocol

Concepts decay. Overdue concepts appear in `learner_context()`. User should never feel quizzed — verification woven invisibly:

- **Channel 1 — Gym Enrichment**: `same_topic_review_due` → incorporate into Gym question
- **Channel 2 — Recall Bridge**: `concepts_due_for_review` → connect to current query if genuine
- **Channel 3 — Bootcamp Seeding**: Overdue concepts in same domain → design scenario requiring them
- **Channel 4 — Transfer Challenge**: `transfer_candidates` → test in new context. Log via `log_transfer`.

Verification logging: correct → `log_study --understood` (resets interval). Wrong → `log_study --gaps` (flips to "unknown").

### Step 5: Session End (Silent)

**Session routing**: Doc-anchored sessions follow CLAUDE.md §10. Standalone sessions:

1. Final heartbeat: `heartbeat.sh --session-mode --status "complete" --obsidian-write`
2. Write full session log to `Review Sessions/<topic-slug>.md` via Write tool:
   - Content: Query, Key Insights, Gym Performance table, Gaps Identified, Related in This Vault
   - Metadata at bottom: date, skill, query, template, topic, tags
3. Concept Extraction per CLAUDE.md §7c
4. Post-Session Hook per CLAUDE.md §8
5. Cleanup: `rm -f data/Sessions/*.json data/Sessions/scratch_context.md data/Sessions/transform_output.md data/Sessions/*.jsonl`

### Post-Interaction Routing

After logging gaps with a clear `error_type`, offer ONE targeted remediation (highest `times_missed`):

| Error Type | Offer |
|---|---|
| `numerical_recall` | Rapid-fire numbers quiz |
| `conceptual_confusion` | Causal chain walkthrough |
| `cross_contamination` | Disambiguation table |
| `application_failure` | Bootcamp scenario |
| `reasoning_gap` | Scaffolded walkthrough |
