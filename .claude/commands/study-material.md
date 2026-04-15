---
name: study_material
description: Reads a PDF or PPTX file, extracts content, generates a comprehensive study document with mixed question types, then runs an interactive drill session with feedback and knowledge graph logging. Invoke via /study-material or when the user explicitly requests file-based study material — "make study material from [file]", "quiz me on this file", "prep me for [file]", "test me on these slides". For general study questions not tied to a specific file, answer from model knowledge instead.
---

# Study Material Generator & Interactive Drill

Read a user-provided file (PDF/PPTX/vault .md), extract content, generate a study document with questions matched to content complexity, then drill the user interactively with feedback and KG logging.

## Critical Anti-Patterns

1. **NEVER generate ad-hoc scenarios or simulations.** This is NOT intern-bootcamp. Use the structured TU-XX / Q# question bank only.
2. **NEVER ask for numeric self-ratings.** Tag confidence silently from linguistic cues.
3. **NEVER create `YYYY-MM-DD_study-session.md`.** Doc-anchored sessions use `<Title> Review.md`.
4. **NEVER log shallow gap-details.** Every entry MUST have specific `misconception` and `remediation` (per CLAUDE.md §11).

---

## Phase 1: Generate Study Material

### Step 0 — Pre-Flight (Silent)

Infer topic from filename. Run preflight:
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && ./src/preflight.sh "<inferred topic>"
```
Read `data/Sessions/learner_context.json`. If new case log files, sync per CLAUDE.md §5.

### Step 1 — Extract Content

**Derive topic name** from filename: strip dates, "edited", "AM/PM", version numbers, extensions. Convert to Title Case with spaces. Example: `"Lab 1 - Gross anatomy brain structures_3-24-26 (AM edited).pptx"` → `Brain Anatomy Lab 1`. This is `<Topic Title>` for all outputs.

**PPTX**: Extract per-slide: number, title, body, speaker notes, image descriptions.
**PDF**: Extract per-page: number, headers, body, figure captions, table contents.
**Vault .md**: Read directly. Treat `##` headings as slides, bullets as body. Skip to Step 2.

Write extraction to `data/Sessions/slide_extraction_<slug>_<YYYYMMDD>.json`.

### Step 2 — Concept Chunking & Classification (Subagent)

Spawn `general-purpose` subagent (`model: "sonnet"`):

> Read `data/Sessions/slide_extraction_<slug>_<YYYYMMDD>.json`.
>
> **MANDATORY 4-PHASE EXTRACTION:**
>
> **Phase A — Enumerate**: Divide into logical chunks. Produce chunk manifest before extracting.
> **Phase B — Iterate**: For each chunk in order: mark processing, extract every concept, assign TU-XX labels, mark done. Never skip or batch chunks.
> **Phase C — Verify**: Confirm `Chunks processed: N / N`. Re-process any skipped.
> **Phase D — Classify and Merge**: Group by Teaching Unit, classify each concept:
>
> | Content Pattern | Complexity | Question Type |
> |---|---|---|
> | Named structure, definition, single fact | `recall` | Short answer / fill-in-the-blank |
> | Spatial relationship, pathway course | `spatial` | Anatomical relationship |
> | Two confusable structures/conditions | `discrimination` | MC with close distractors |
> | Causal chain, mechanism | `mechanism` | Two-step reasoning |
> | Requires combining anatomy + physiology + clinical | `integration` | Clinical vignette |
> | Labeled diagram or imaging central | `visual` | Image-reference question |
>
> **Critical**: Do NOT default to MC. MC is ONLY for `discrimination` where close distractors are the teaching tool.
>
> Write to `data/Sessions/concept_map_<slug>_<YYYYMMDD>.json` with `teaching_units[]`, `total_concepts`, `complexity_distribution`.

### Step 3 — RAG Enrichment (Supplemental Only)

RAG supplements slide content — it does NOT replace it. Only run for `mechanism`/`integration` TUs or thin content (<30 words/concept).

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/lance_retriever.py compare "<TU title>" --no-learner --no-frontier
```

RAG content used ONLY for answer explanations, clinical pearls, and integration questions. Slide-sourced ≥70% of each explanation.

### Step 4 — Generate Study Document

Write to: `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/<Topic Title>.md`

**CRITICAL MANDATE: The final document MUST include a question for EVERY single concept extracted in Phase 1. The total number of questions will dynamically match the total number of extracted concepts (maintaining a strict 1:1 mapping). Do not summarize, consolidate, or omit any Teaching Units or concepts to save space.**

**EXECUTION MANDATE: You MUST use the native file writing tool to generate the complete markdown document directly. NEVER write a Python/Bash script to automate or bypass this step. You must generate the full text of the document natively, ensuring every question has its corresponding `answer` (from the JSON schema) placed inside the `<details>` block.**

**FORMATTING MANDATE: NEVER use an H1 heading (`#`) at the top of the file. The filename acts as the title in Obsidian. Using an H1 creates annoying duplicate titles.**

Structure:
```markdown
**Source**: <filename> | **Generated**: <date> | **Total Questions**: <N>
**Complexity Mix**: <R>R / <S>S / <D>D / <M>M / <I>I / <V>V

---

## Concept Summary

### <TU Title> (Slides X-Y)
- [Dense testable bullets — distilled, not transcript]

---

## Questions

### Q1 [recall] (Slides 4-6) — TU-01
**Question text**
<details><summary>Answer</summary>
[Answer + Explanation (primarily from slides, RAG-enriched if applicable with attribution)]
**Slide reference**: Slides 4-6
</details>

---

### Q2 [discrimination] (Slides 8-9) — TU-03
**MC question**
- A) ...  B) ...  C) ...  D) ...
<details><summary>Answer</summary>
**Answer** + **Why each distractor is wrong**
**Slide reference**: Slides 8-9
</details>
```

Every question: tagged with complexity, slide ref, TU ID. Every MC: "why each distractor is wrong." RAG enrichment always labeled/attributed. `<details>` tags for self-testing.

### Step 5 — Notify User

> **Study material generated**: <N> questions from <M> slides across <K> TUs.
> Written to `Obsidian → agentic-neuro/Study Material/<Topic Title>.md`
> **Complexity breakdown**: ...
> **What would you like to do?**
> 1. **Start drilling** — interactive Q&A session
> 2. **Take it offline** — review on your own
> 3. **Both** — drill now, finish offline later

---

## Phase 2: Interactive Drill

### Drill Pre-Flight (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py doc_status "Study Material/<Topic Title>.md"
ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Review Sessions/<Topic Title> Review.md" 2>/dev/null
```

- `"new"` → begin TU-01
- `"returning"` → recap, then reorder: missed concepts first, continue forward

### Drill Engine

**Session timestamp (set once at drill start, reuse for all exchanges):**
```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```
Initialize a turn counter at 0. Increment before each `record-answer` call.

**Tone**: Study coach — encouraging, honest, direct. Never punitive.
**One question at a time. Wait for answer. Never show answer preemptively.**

| Outcome | Response |
|---|---|
| Correct | Brief confirm + enrichment nugget. Move on. |
| Partially correct | Acknowledge right, isolate missing with follow-up probe. No reveal. |
| Incorrect | No reveal. Socratic redirect targeting the misconception. |
| Incorrect after redirect | Full answer + explanation. Frame as learning moment. |
| "I don't know" / skip | Respected. Full explanation. Circle back later. |

**Silent confidence tagging**: `high` (declarative, no hedging) vs `low` ("I think", "maybe", hedging).

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
Capture the ACTUAL question and ACTUAL answer. For breakthroughs, add `--breakthrough --insight "<what clicked>"`.

**Ordering**: recall → spatial/discrimination → mechanism/integration. Visual interspersed.
**Adaptive**: 2+ wrong in same TU → insert 1-2 additional questions from different angle.

### Mid-Session Checkpoint (Every ~12 Questions)

Pause with Strong/Needs Work summary. Offer: keep going | focus weak areas | pause.

Silently run `log_doc_progress` heartbeat at every checkpoint.

### Session-End Summary

Present: questions attempted, correct/partial/incorrect/skipped, strongest areas, focus areas with specific gaps, calibration check, recommendation.

Offer: Save to Anki | Review weak areas | Another file | End session.

### Session-End Logging (Silent)

Use `heartbeat.sh` with `--obsidian-write` for atomic KG + Obsidian write:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
./src/heartbeat.sh \
  --doc "Study Material/<Topic Title>.md" --doc-type "study-material" \
  --covered "<Q IDs>" --understood "<correct Q IDs>" \
  --missed '[{"concept":"<Q>","error_type":"<type>","misconception":"<specific>"}]' \
  --coverage-pct <N> --total <N> --topics "<topics>" --depth 2 \
  --gaps "<incorrect concepts>" --gap-details '<JSON per CLAUDE.md §11>' \
  --obsidian-write --topic-name "<Topic Name>" --slug "<Title>" \
  --session-num <N> --score "<N/N (pct%)>" --skill "study-material" --domain "<domain>" \
  --understood-detail "<detail>" --gaps-detail "<detail per TU>"
```

For `--gaps-detail`, separate entries with `|`. Each must describe the specific incorrect mental model.

**After heartbeat**: Update `## Concept Map Status` table in review file. Update `Study Material/INDEX.md` if newly created.

**Error type mapping**: confused structures → `cross_contamination` | forgot fact → `numerical_recall`/`conceptual_confusion` | knew but couldn't apply → `application_failure` | skipped causal step → `reasoning_gap`

If calibration data notable (>=3 miscalibrated signals): `log_bootcamp` with `--calibration` array.

### Post-Session (Silent)

1. Concept Extraction per CLAUDE.md §7c
2. Post-Session Hook per CLAUDE.md §8
3. Regenerate `## Progress Over Sessions` table in review file

---

## Resuming a Previous Document

"drill me on brain anatomy lab 1" → check `Study Material/` for match. If found, start Phase 2 directly.

## Anki Handoff

If user selects "Save to Anki": compile session transcript, prefix with `### CRITICAL: STUDY MATERIAL DRILL SESSION. GENERATE CARDS ONLY FOR INCORRECTLY ANSWERED AND SKIPPED QUESTIONS ###`, trigger `anki-sync` with scoped transcript. Use `model: "sonnet"`.

## Initialization

On trigger, immediately begin Phase 1. First user-visible output is Step 5 notification. If no file path, ask for one.
