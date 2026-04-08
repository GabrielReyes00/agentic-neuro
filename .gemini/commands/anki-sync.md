---
name: anki_sync
description: Pipeline that extracts Anki flashcards from the current session — deduplicates claims, targets confusable pairs, drafts validated cards, enriches with vision-validated images, and syncs to Anki via AnkiConnect. Always invoke when the user wants to create flashcards or save to Anki.
---

# Anki Sync Command

Converts the current session into high-yield, image-enriched Anki flashcards.

> **ALL shell commands MUST use this prefix:**
> `RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate" && eval "$RUN" && <command>`

## MANDATORY STEP GATE

This pipeline has hard STOP conditions between steps. Do NOT proceed to the next step until the current step's output file exists and is non-empty.

| Step | Input | Output file | STOP if... |
|------|-------|-------------|-----------|
| 1 | Conversation | `current_session_verbatim.txt` | File < 200 chars — abort with message |
| 2 | User response | `current_topic.json` | Deck path not confirmed — wait for user |
| 3 | Topic | `confusable_pairs.json` | (no stop — failures non-fatal) |
| 4 | Verbatim transcript | `current_claims.json` | File missing or empty claims array |
| 5 | Claims | `novel_claims.json` | Empty — "No novel facts found" — abort |
| **6** | Novel claims | **`final_cards.json`** | **MUST complete blind validation before writing — see below** |
| **6.5** | `final_cards.json` | `validation_audit.json` | `python3 src/anki_sync_cli.py validate_final_cards` fails |
| 7 | Final cards | `image_selections.json` | (soft stop — text-only if no images pass) |
| 8 | Selections | Anki dispatch | AnkiConnect unreachable — report error |
| 9 | Cards | KG + Obsidian + cleanup | Never skip these — mandatory |

### Step 6 Validation Gate (CRITICAL)

The sub-task for Step 6 MUST perform blind validation on EVERY card before writing `final_cards.json`. This validation is non-optional:

1. Sub-task drafts a card
2. Sub-task HIDES the answer and reads only the visible prompt
3. Sub-task asks: "Can someone guess the EXACT hidden answer from this prompt alone?"
4. If NO (too vague): **rewrite the card** with more clinical specificity
5. Repeat until YES
6. Only then include the card in `final_cards.json`

A card written to `final_cards.json` without completing blind validation is a pipeline error.

`final_cards.json` MUST include:
- Per-card `blind_validation` object:
  - `prompt_visible` (string)
  - `self_guess` (string)
  - `exact_match` (must be `true`)
  - `revision_count` (integer, `>= 0`)
- Top-level `validation_report` object:
  - `cards_drafted` (integer)
  - `cards_refined` (integer)

If `cards_refined = 0` for any session with more than 3 cards, validation is treated as skipped and the CLI gate fails.

## CardDraft Schema Reference (MUST MATCH EXACTLY)

The Python `anki_sync_cli.py` validates cards with Pydantic. Wrong field names cause immediate rejection.

**Exact field names** (case-sensitive, no alternatives):

| Field | Required For | Description |
|-------|-------------|-------------|
| `claim_id` | all | e.g. "C001" |
| `card_type` | all | `"cloze"` or `"qa"` — NOT `"type"`, NOT `"card_kind"` |
| `cloze_text` | cloze only | Must contain exactly one `{{c1::...}}` deletion |
| `answer_text` | cloze only | The hidden answer text (required even though it's in the cloze) |
| `front` | qa only | The question side — NOT `"question"` |
| `back` | qa only | The answer side — NOT `"answer"` |

**Common errors that WILL crash the pipeline:**
- Using `"type"` instead of `"card_type"` → Pydantic validation error
- Using `"question"/"answer"` instead of `"front"/"back"` → missing required fields
- Omitting `answer_text` on cloze cards → validation error
- Including `front`/`back` on cloze cards or `cloze_text` on QA cards → set unused fields to `""`

**Valid cloze example:**
```json
{"claim_id": "C001", "card_type": "cloze", "cloze_text": "The calcium channel blocker used for vasospasm prophylaxis after SAH is {{c1::nimodipine}}", "answer_text": "nimodipine", "front": "", "back": ""}
```

**Valid QA example:**
```json
{"claim_id": "C002", "card_type": "qa", "cloze_text": "", "answer_text": "", "front": "What triad results from AChA occlusion?", "back": "Contralateral hemiparesis, hemisensory loss, and homonymous hemianopia (posterior limb internal capsule infarction)"}
```

**No emojis in any card text.** Plain text with `<b>bold</b>` / `<i>italics</i>` only — never markdown formatting.

## Step 1: Capture Input (File or Transcript)

Determine the source material. If the user provided a file path (e.g., "make cards from [filepath]"), read that file directly. Otherwise, capture the full verbatim conversation.

1. Ensure dir exists: `mkdir -p /Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs`
2. **If using current session chat:** Write the full session transcript to `/Users/gabrielreyes/agentic-neuro/data/Sessions/current_session_verbatim.txt` using shell redirect (NOT the file write tool — avoids dumping to terminal):
   ```bash
   cat > /Users/gabrielreyes/agentic-neuro/data/Sessions/current_session_verbatim.txt << 'TRANSCRIPT_EOF'
   [full transcript here]
   TRANSCRIPT_EOF
   ```
   **If a file path was provided:** Copy its contents to `/Users/gabrielreyes/agentic-neuro/data/Sessions/current_session_verbatim.txt`.
3. Wrap long lines:
   ```bash
   cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 -c "import textwrap; p = 'data/Sessions/current_session_verbatim.txt'; content = open(p).read(); wrapped = '\n'.join(['\n'.join(textwrap.wrap(line, width=150, break_long_words=False, replace_whitespace=False)) if len(line) > 150 else line for line in content.split('\n')]); open(p, 'w').write(wrapped)"
   ```
4. Read the file. If fewer than 200 characters, **stop**: "The source material is too short to extract meaningful cards."

## Step 2: Resolve Subdeck

Ask the user:

> "Would you like to add these cards to an **existing subdeck** or **create a new one**?
> - **Existing** -> paste the full deck path (e.g., `Agentic Neurosurgery Review::Intern Bootcamp`)
> - **New** -> I'll generate an appropriate subdeck name; just confirm the root deck (default: `Agentic Neurosurgery Review`)"

Resolve the full deck path. Write to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/current_topic.json`:
```json
{"topic": "<subdeck label>", "deck": "<full deck path>"}
```

## Step 3: Confusable Pairs Query

Fetch known conceptual errors for this topic from the Knowledge Graph:
```bash
RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate" && eval "$RUN" && python3 src/knowledge_graph.py confusable_pairs --topic "<subdeck label>" > data/Sessions/anki_sync_runs/confusable_pairs.json
```

## Step 4: Claim Extraction (SECTION-BY-SECTION LOOP via Generalist)

Use the `generalist` tool:

> "Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/current_session_verbatim.txt`. Extract atomic factual claims as Subject-Verb-Object (SVO) triples. Merge overlapping facts, discard conversational filler. Each `claim_text` must be standalone. IDs: `C001`, `C002`, etc.
>
> **CRITICAL: EXHAUSTIVE EXTRACTION VIA CHUNKING REQUIRED.** To prevent generation fatigue, do NOT process the entire file at once. Process the file in chunks (e.g., 2-3 paragraphs or 1-2 headings at a time). For *each chunk*, extract EVERY testable nuance: every drug, dose, threshold, anatomical relationship, pathophysiological mechanism, clinical pearl, differential point, and procedural detail. 
> A dense clinical report or session should yield 50+ distinct claims. Do NOT stop early or summarize multiple facts into one claim.
>
> Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/confusable_pairs.json`. This file influences *HOW* claims are phrased, NOT *which* claims are extracted. If a claim relates to a confusable pair, phrase the `claim_text` to explicitly contrast those concepts.
>
> Compile all extracted claims across all chunks and write to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/current_claims.json`:
> `{"claims": [{"claim_id": "C001", "subject": "...", "verb": "...", "object": "...", "claim_text": "..."}]}`"

## Step 5: Novelty Filtering

```bash
RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate" && eval "$RUN" && python3 src/anki_sync_cli.py filter_novelty
```
Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/novel_claims.json`. If empty, **stop**: "No novel facts found; all concepts are already in the Anki database."

## Step 6: Card Drafting & Validation (BATCHED via Generalist)

Use the `generalist` tool:

> "Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/novel_claims.json`. For each claim, draft ONE card. 
> **CRITICAL: BATCH YOUR DRAFTING.** If there are more than 15 claims, draft them in batches of 10-15 cards at a time to ensure high quality and prevent timeouts, appending them to `final_cards.json`.
>
> **STRICT SCHEMA ENFORCEMENT:**
> - `card_type` MUST be EXACTLY lowercase `"cloze"` or `"qa"`. NEVER uppercase `"QA"`.
> - **Cloze cards** MUST have exactly one `{{c1::...}}` deletion in `cloze_text` AND MUST populate the `answer_text` field with the exact hidden text. `front` and `back` MUST be `""`.
> - **QA cards** MUST populate `front` and `back`. `cloze_text` and `answer_text` MUST be `""`.
> - Use `<b>bold</b>` / `<i>italics</i>` — NEVER markdown (`**bold**`). All text fields valid JSON, newlines escaped as `\n`.
> - If a claim relates to known confusable pairs, force discrimination between those concepts.
>
> **Blind Validation — For EACH card:**
> Hide the answer. Read ONLY the visible prompt. Can someone guess the EXACT hidden answer and nothing else? If too vague, add clinical constraints.
> - BAD: `'The treatment for SAH is {{c1::nimodipine}}'`
> - GOOD: `'The calcium channel blocker used for vasospasm prophylaxis after SAH is {{c1::nimodipine}}'`
>
> Write to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/final_cards.json`:
> `{"cards": [{"claim_id": "C001", "card_type": "cloze", "category": "...", "cloze_text": "...", "answer_text": "...", "front": "", "back": "", "blind_validation": {"prompt_visible": "...", "self_guess": "...", "exact_match": true, "revision_count": 1}}], "validation_report": {"cards_drafted": 12, "cards_refined": 5}}`
>
> **Return**: `{cards_drafted: N, cards_refined: N}`"

### Step 6.5: Validation Gate (CLI-Enforced)

Run:
```bash
RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate" && eval "$RUN" && python3 src/anki_sync_cli.py validate_final_cards
```

This is a hard gate. If it fails, do not continue to image enrichment or dispatch.

## Step 7: Image Enrichment (BATCHED via Generalist)

Use the `generalist` tool:

> "You are an image enrichment agent for neurosurgery Anki flashcards. Find, validate, and select a contextual image for every card.
>
> **Shell prefix:** `RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate" && eval "$RUN" && <command>`
>
> ### Phase 1: Assess & Query Generation
>
> Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/final_cards.json`. For each card, classify `image_type`:
> - `"anatomy_diagram"` — labeled structures, cross-sections, nerve/vessel maps
> - `"radiology"` — CT, MRI, X-ray, angiogram
> - `"histology"` — microscopic tissue, pathology slides
> - `"surgical_photo"` — intraoperative views, approaches
> - `"schematic"` — flowcharts, pathways, classification tables
> - `"none"` — ONLY for pure pharmacology numbers or abstract definitions. **Bias toward finding an image.**
>
> Generate EXACTLY ONE highly specific search query per card. Disambiguate aggressively — use medical anchors, avoid broad terms. For vascular/aneurysm topics, include vessel names and anatomical relationships.
> - Good: `"Circle of Willis anatomy diagram labeled arteries"`, `"posterior communicating artery fetal variant anatomy"`
> - Bad: `"brain blood vessels"`, `"anatomy"`
>
> Write to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/image_search_requests.json`:
> `[{"claim_id": "C001", "image_type": "anatomy_diagram", "search_queries": ["Circle of Willis anatomy diagram labeled arteries"]}]`
> Skip cards with `image_type: "none"`.
>
> ### Phase 2: Search & Download
>
> 1. Run the search script (this fetches candidates using your queries):
> ```bash
> RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate" && eval "$RUN" && python3 src/anki_sync_cli.py search_images
> ```
> 2. Run the batch thumbnail downloader (this fetches up to 3 thumbnails per card):
> ```bash
> RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate" && eval "$RUN" && python3 src/anki_sync_cli.py download_thumbnails
> ```
> Read `/tmp/anki_thumbs/manifest.json` to see what was downloaded.
>
> ### Phase 3: Batched Vision Validation & Selection
>
> **CRITICAL: BATCH YOUR VALIDATION.** If there are >15 cards, validate them in batches of 10-15 at a time, appending passing selections to `image_selections.json` to prevent timeouts.
>
> For each card in your current batch:
> 1. **Short-circuit inspection (NO CHEATING):** You MUST use the `read_file` tool to physically look at the pixels of candidate `_1.jpg` from `data/Sessions/anki_sync_runs/anki_thumbs/`. Do NOT rely on text metadata to guess the image contents.
> 2. Score it 1-5 for: **RELEVANCE** (right structure/concept?), **ACCURACY** (labels correct?), **CLARITY** (readable at ~500px?), **QUALITY** (professional, no watermarks?).
> 3. **If average >= 3.5**: ACCEPT IT IMMEDIATELY. Do NOT waste time inspecting `_2.jpg` or `_3.jpg`.
> 4. **If it fails**: Try `_2.jpg`, then `_3.jpg`.
> 5. **Fallback:** You may ONLY fall back to scoring the image purely on the title/description text found in `image_candidates.json` if the `read_file` tool explicitly returns a file read error, corruption error, or times out.
> 6. If NO candidate passes, skip the card (it will be text-only).
>
> ### Phase 4: Write Selections
>
> **CRITICAL SCHEMA FOR FLASH:** You MUST include the `image_url` and `source_url` (found in `image_candidates.json`) for every selection. Do NOT use local file paths in these fields. 
>
> Write/Append passing selections to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/image_selections.json` using this EXACT structure:
> ```json
> [
>   {
>     "claim_id": "C001",
>     "image_url": "https://upload.wikimedia.org/path/to/image.jpg",
>     "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
>     "attribution": "Author Name | Wikimedia Commons, CC BY-SA 4.0",
>     "placement": "back",
>     "alt_text": "Anatomic diagram of the AChA",
>     "validated_by_vision": true,
>     "validation_scores": {
>       "relevance": 5,
>       "accuracy": 4,
>       "clarity": 4,
>       "quality": 4
>     },
>     "validation_notes": "I visually inspected the image using read_file. I saw a clearly labeled ICA and the origin of the AChA branching distally to the PComA, which directly supports the claim."
>   }
> ]
> ```
> **ALL 4 scores required.** `validated_by_vision` must be `true` unless you used the text fallback.
>
> **Return**: `{cards_with_images: N, text_only: M, total: N+M}`"

## Step 8: Process & Dispatch

```bash
RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate" && eval "$RUN" && python3 src/anki_sync_cli.py validate_final_cards && python3 src/anki_sync_cli.py process_selected_images && python3 src/anki_sync_cli.py dispatch
```

**If connection fails**: "AnkiConnect is not running. Please open the Anki desktop app and ensure AnkiConnect is installed, then try again."

Report final counts: "Created N cards (X with images, Y text-only), D duplicates, F failures in deck ..."

## Step 9: Knowledge Graph + Obsidian Integration (Silent)

After successful dispatch, run these operations:

### 9a. Log card creation to knowledge graph

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py log_study \
  --topics "<comma-separated topics from deck name and card content>" \
  --understood "<comma-separated card front concepts>" \
  --depth 2 --source "anki"
```

Derive topics from the deck path (e.g., `Agentic Neurosurgery Review::SAH Management` -> topic = "SAH management"). Use the `claim_text` fields captured before dispatch as the understood concepts.

### 9b. Sync Anki retention stats (if Anki is open)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py sync_anki 2>/dev/null || true
```

This pulls current retention stats for all cards. Failures are non-fatal.

### 9c. Write Obsidian session log

Write to: `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Review Sessions/<deck-slug>.md`

Where `<deck-slug>` is derived from the subdeck name (e.g., `sah_management_cards.md`).

```markdown
---
date: YYYY-MM-DD
skill: "anki-sync"
deck: "<full deck path>"
cards_created: N
topic: "<primary topic>"
tags:
  - type/session
  - skill/anki-sync
  - domain/<domain>
  - source/agent
---
# Anki Sync — <Topic>

## Cards Created
| Card Front | Type | Topic | Image |
|---|---|---|---|
| <cloze/front text truncated to 80 chars> | cloze/QA | <topic> | yes/no |

## Topics Reinforced
- <topic 1>: N cards
- <topic 2>: N cards

## Notes
<dispatch summary: failures, deduplicated claims count, image enrichment stats>
```

Update `Review Sessions/INDEX.md` (create if absent).

### 9d. Post-Session Hook

Run the Universal Post-Session Hook (see GEMINI.md) to update Dashboard.md.

### 9e. Cleanup (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
rm -f data/Sessions/*.json data/Sessions/*.md data/Sessions/*.jsonl && rm -rf data/Sessions/anki_sync_runs
```

Do not narrate Steps 9a-9e to the user.
