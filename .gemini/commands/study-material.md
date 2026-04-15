---
name: study_material
description: Reads a PDF/PPTX/vault markdown file, generates comprehensive study material, then runs an interactive drill with KG logging and review-session persistence.
---

# Agent Skill: Study Material Generator & Interactive Drill

Produce a study artifact from a source document, then run adaptive one-question-at-a-time drilling with crash-safe logging and cumulative review tracking.

All §1 directives apply. All §7 session-end hooks are mandatory (preflight, `record-answer`, heartbeat, concept extraction, post-session hook).

## Triggering

Use when user requests study material or drilling from a specific file (`.pdf`, `.pptx`, or vault `.md`). If source is vault `.md`, treat `##` sections as chunks → Phase 1 Step 2.

## Phase 1 — Generate Study Material

### Step 0: Pre-Flight (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && ./src/preflight.sh "<inferred topic>"
```

Read `data/Sessions/learner_context.json` to calibrate emphasis and discrimination.

### Step 0.5: RAG Decision Point (Interactive)

Immediately after Pre-Flight, check the first 5 lines of the source document:
- **If "Generation Mode: [+RAG]" is found:** Skip the interactive prompt. Proceed as if the user said "No" (since the content is already RAG-enriched).
- **If NOT found:** The agent MUST ask the user: **"Got it! Would you like me to enrich our study material with a RAG search?"**
    - **If Yes:** Proceed through all steps, including the mandatory Step 3 RAG-Backfill for Reports.
    - **If No:** Skip Step 3 (RAG Enrichment & Backfill) entirely.

### Step 1: Exhaustive Extraction Loop (Chunked)

Mandatory anti-laziness rules — all three must hold:
1. Never process the entire source in a single pass.
2. Must enumerate all chunks BEFORE processing any chunk.
3. Must verify all chunks were processed BEFORE merging.

#### 1a — Enumerate

Read full source, produce chunk manifest:
```
CHUNK MANIFEST — Total chunks: N
[ ] Chunk 1: pages 1-3 / slides 1-7 / "## Heading A"
...
[ ] Chunk N: ...
```

Do not begin extraction until manifest is complete.

#### 1b — Iterate

For each chunk in order: mark `[processing]` → extract every concept → assign `TU-XX` labels → mark `[done]`: `Chunk K/N complete`. Never skip or batch chunks.

#### 1c — Verify

```
EXTRACTION COMPLETE — Chunks processed: N / N
```

If any chunk was skipped or batched, go back and process individually.

#### 1d — Merge

Group by Teaching Unit, deduplicate, finalize concept map. Derive Title Case topic name.
**CRITICAL MANDATE: Do NOT distill, consolidate, or summarize the extracted concepts. You MUST maintain a 1:1 mapping of extracted concepts to final questions. Total representative coverage is mandatory.**

### Step 2: Complexity Classification

Assign each concept: `recall` | `spatial` | `discrimination` | `mechanism` | `integration` | `visual`.

Rules: default to retrieval-style prompts (not MC). Reserve MC primarily for `discrimination`. Preserve source fidelity.

Write to `data/Sessions/concept_map_<topic_slug>_<YYYYMMDD>.json`:
```json
{
  "teaching_units": [
    {"unit_id": "TU-01", "title": "...", "concepts": [
      {"id": "Q1", "claim": "...", "complexity": "...", "question_type": "retrieval|mc|vignette|short-answer"}
    ]}
  ]
}
```

### Step 3: RAG Enrichment & Backfill (Hard Requirement for Reports)

RAG is additive, not primary. Use only for thin mechanism/integration units:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "<teaching unit title>" --no-learner --no-frontier
```

**RAG-Backfill Mandate:** If RAG is executed, the resulting output MUST be summarized comprehensively and woven back into the source `Reports/<Topic>.md` file. 
- **Placement:** Integrate content into the relevant sections (Anatomy, Pathophysiology, Trials) rather than appending at the bottom.
- **Citation Standard (Hard Requirement):** You MUST map all internal retrieval markers (e.g., `[P1]`) to their actual source metadata. Every piece of RAG-derived content must be followed by an inline citation containing the **Textbook Title, Edition, and Page Number** (e.g., `(Youmans & Winn 8th Ed, p. 757)`). 
- **Prohibited:** Never use raw markers like `[P1]` or `[Source 1]` in the final report.
- **Verification:** Ensure the report remains a cohesive narrative, not a disjointed list of facts, while maintaining 1:1 parity between RAG findings and these precise citations.

### Step 4: Write Study Document

Write to `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/<Topic Title>.md`

**CRITICAL MANDATE: The final document MUST include a question for EVERY single concept extracted in Phase 1. The total number of questions will dynamically match the total number of extracted concepts (maintaining a strict 1:1 mapping). Do not summarize, consolidate, or omit any Teaching Units or concepts to save space.**

**EXECUTION MANDATE: You MUST use the `write_file` tool to generate the complete markdown document directly. NEVER write a Python/Bash script to automate or bypass this step. You must generate the full text of the document natively, ensuring every question has its corresponding `answer` (from the JSON schema) placed inside the `<details>` block.**

**FORMATTING MANDATE: NEVER use an H1 heading (`#`) at the top of the file. The filename acts as the title in Obsidian. Using an H1 creates annoying duplicate titles.**

Required: source metadata (start file directly with this), complexity mix, `## Concept Summary`, `## Questions` with per-question tags/refs, answer blocks in `<details>`. MC questions include distractor rationale. RAG enrichments attributed.

### Step 5: Notify User

Return counts (questions, units, source span, complexity mix). Offer: 1. Start drilling, 2. Take offline, 3. Both.

## Phase 2 — Interactive Drill

### Drill Pre-Flight (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py doc_status "Study Material/<Title>.md"
ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Review Sessions/<Title> Review.md" 2>/dev/null
```

`new` → start TU-01. `returning` → recap, prioritize missed concepts first.

### Core Loop

**Session timestamp (set once at drill start, reuse for all exchanges):**
```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```
Initialize a turn counter at 0. Increment before each `record-answer` call.

One question at a time: ask → wait → evaluate → respond:
- correct: brief confirm + enrichment
- partial: targeted probe
- incorrect: Socratic redirect, then reveal on second miss
- skip/IDK: immediate explanation

Tag confidence silently (`high|low`) from language cues.

**Per-answer memory logging (silent, after each drill answer is evaluated):**
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/memory_orchestrator.py record-answer \
  --session-ts "$SESSION_TS" --turn <N> --skill "study-material" \
  --topic "<topic>" --concept "<Q# concept being tested>" \
  --question "<the question text from the study doc>" \
  --answer "<user's answer, verbatim or close paraphrase>" \
  --correct <0|1|2> \
  [--correction "<your correction/explanation if incorrect>"] \
  [--error-type "<type>"] [--misconception "<specific wrong belief>"] \
  [--root-cause "<why>"] [--remediation "<what should fix it>"] \
  [--teaching-approach "<drill-recall|drill-discrimination|drill-mechanism|drill-integration>"] \
  [--depth <N>] [--domain "<domain>"] [--response-confidence "high|low"]
```

### Ordering

Default: recall → spatial/discrimination → mechanism/integration. If 2+ misses in same TU, insert 1-2 more. Revisit IDK/skip after first pass.

### Heartbeats

Every 3 user turns (silent). Visible checkpoint around ~12 questions.

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
./src/heartbeat.sh \
  --doc "Study Material/<Title>.md" --doc-type "study-material" \
  --covered "<Q IDs attempted>" --understood "<Q IDs correct>" \
  --missed '[{"concept":"<Q ID>","error_type":"<type>","misconception":"<brief>"}]' \
  --coverage-pct <attempted/total*100> --total <total_questions> \
  --topics "<teaching-unit topics>" --depth 2
```

### Session-End Summary

Return: attempted/correct/partial/incorrect/skipped, strongest areas, focus areas with specific concepts, calibration highlights, next recommendation.

Offer: 1. Save to Anki, 2. Review weak areas, 3. Another file, 4. End.

### Post-Summary (Silent)

Run final `heartbeat.sh` with `--obsidian-write` and full `--gap-details`. Outcome: pass >= 80%, partial 50-79%, fail < 50%.

### Review Session File

`Review Sessions/<Title> Review.md` is a living file. Always: append session block, refresh counters, regenerate `## Concept Map Status` + `## Progress Over Sessions`, update INDEX.

### Finalization

Per §7: concept extraction → universal post-session hook.

### Cleanup (Scoped)

```bash
rm -f data/Sessions/learner_context.json data/Sessions/transform_directives.json \
  data/Sessions/retrieval_gap.json data/Sessions/scratch_context.md \
  data/Sessions/transform_output.md data/Sessions/case_log_sync.txt \
  data/Sessions/concept_map_*.json data/Sessions/session_digest_*.md
```

## Resume Logic

If continuing prior topic, load matching Study Material, run drill pre-flight, continue without regeneration unless asked.

## Anki Handoff

On "Save to Anki": compile transcript, prioritize incorrect/skipped, include enrichment nuggets, invoke `/anki-sync`.

## Context Compression

At ~12 turns, follow §4 compression protocol.

## Initialization

On trigger with valid file path, start Phase 1. If no file path, ask.
