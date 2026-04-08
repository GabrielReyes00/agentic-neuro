---
name: anki_sync
description: Pipeline that extracts Anki flashcards from the current session transcript — deduplicates claims, drafts validated cloze/QA cards, enriches every card with a vision-validated image, and syncs to Anki via AnkiConnect. Always invoke this skill when the user wants to create flashcards or save to Anki — phrases like "save to Anki", "make flashcards", "make cards", "create Anki cards", "sync to Anki", "add this to my deck", "save for later study", or "turn this into cards". Do not attempt to answer inline for these requests.
---

# Anki Sync Command

Converts the current session transcript into image-enriched Anki flashcards. You handle all LLM reasoning; Python handles DB/API operations only.

> **ALL shell commands MUST use:** `cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate &&`

## Step 1: Capture Transcript

Capture the full verbatim conversation and write it to disk.

1. Ensure dir exists: `mkdir -p /Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs`
2. Write via **Shell tool with quiet redirect** (NOT WriteFile — avoids dumping to terminal):
   ```
   cat > /Users/gabrielreyes/agentic-neuro/data/Sessions/current_session_verbatim.txt << 'TRANSCRIPT_EOF'
   [full transcript here]
   TRANSCRIPT_EOF
   ```
3. Wrap long lines:
   ```
   python3 -c "import textwrap; p = '/Users/gabrielreyes/agentic-neuro/data/Sessions/current_session_verbatim.txt'; content = open(p).read(); wrapped = '\n'.join(['\n'.join(textwrap.wrap(line, width=150, break_long_words=False, replace_whitespace=False)) if len(line) > 150 else line for line in content.split('\n')]); open(p, 'w').write(wrapped)"
   ```
4. Read the file. If fewer than 200 characters, **stop**: "The session transcript is too short to extract meaningful cards."

## Step 2: Resolve Subdeck

Ask the user:

> "Would you like to add these cards to an **existing subdeck** or **create a new one**?
> - **Existing** → paste the full deck path (e.g., `Agentic Neurosurgery Review::Intern Bootcamp`)
> - **New** → I'll generate an appropriate subdeck name; just confirm the root deck (default: `Agentic Neurosurgery Review`)"

Resolve the full deck path and write to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/current_topic.json`:
```json
{"topic": "<subdeck label>", "deck": "<full deck path>"}
```

## Step 3: Claim Extraction & Novelty Filtering (Subagent)

Spawn a `general-purpose` subagent (use `model: "haiku"`):

> You are extracting factual claims from a neurosurgery study session for Anki flashcard creation.
>
> 1. Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/current_session_verbatim.txt`.
>
> 2. Extract atomic factual claims as Subject-Verb-Object (SVO) triples.
>    - Merge overlapping facts — zero duplicates. Discard conversational filler and non-technical content.
>    - Each `claim_text` must be standalone (understandable without context). IDs: `C001`, `C002`, etc.
>    - **EXHAUSTIVE EXTRACTION REQUIRED.** A typical 20-minute study session contains 25-50+ distinct factual claims. If you find yourself stopping around 10, you are almost certainly under-extracting. Go back through the transcript section by section and look for facts you missed. Every drug, dose, threshold, anatomical relationship, pathophysiological mechanism, clinical pearl, differential point, and procedural detail is a separate claim. Do NOT stop early or summarize multiple facts into one claim.
>
>    Write to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/current_claims.json`:
>    ```json
>    {"claims": [{"claim_id": "C001", "subject": "...", "verb": "...", "object": "...", "claim_text": "..."}]}
>    ```
>
> 3. Run novelty filtering:
>    ```
>    cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/anki_sync_cli.py filter_novelty
>    ```
>
> 4. Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/novel_claims.json` and count novel claims.
>
> **Return**: `{total_claims: N, novel_claims: M}`

If `novel_claims` is 0, **stop**: "No novel facts found; all concepts are already in the Anki database."

## Step 4: Card Drafting & Validation (Subagent)

Spawn a `general-purpose` subagent (use `model: "sonnet"`):

> You are drafting and validating Anki flashcards from novel neurosurgery claims.
>
> 1. Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/novel_claims.json`.
>
> 2. For each claim, draft ONE card:
>    - **Cloze** for single factual associations (drugs, landmarks, thresholds, definitions). Exactly one `{{c1::...}}` deletion.
>    - **QA** for reasoning or multi-part answers (pathophysiology, differentials, procedures). Concise `front`/`back`.
>    - All text fields must be valid JSON strings. Newlines escaped as `\n`.
>
> 3. **Blind Validation** — For EACH card:
>    - Hide the answer. Read ONLY the visible prompt.
>    - Ask: "Can someone guess the EXACT hidden answer and nothing else?"
>    - If too vague, add clinical constraints until only one answer is possible.
>    - Example: ❌ `"The treatment for SAH is {{c1::nimodipine}}"` → ✅ `"The calcium channel blocker used for vasospasm prophylaxis after SAH is {{c1::nimodipine}}"`
>
> Write validated cards to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/final_cards.json`:
> ```json
> {"cards": [{"claim_id": "C001", "card_type": "cloze", "cloze_text": "...", "answer_text": "...", "front": "", "back": ""}]}
> ```
>
> **Return**: `{cards_drafted: N, cards_refined: N}`

## Step 5: Image Enrichment (Subagent)

Spawn a `general-purpose` subagent (use `model: "haiku"`):

> You are an image enrichment agent for neurosurgery Anki flashcards. Find, validate, and select a contextual image for every card.
>
> **Shell prefix:** `cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate &&`
>
> ### Phase 1: Assess
>
> Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/final_cards.json`.
>
> For EACH card, classify `image_type`:
> - `"anatomy_diagram"` — labeled structures, cross-sections, nerve/vessel maps
> - `"radiology"` — CT, MRI, X-ray, angiogram
> - `"histology"` — microscopic tissue, pathology slides
> - `"surgical_photo"` — intraoperative views, approaches
> - `"schematic"` — flowcharts, pathways, classification tables
> - `"none"` — ONLY for pure pharmacology numbers or abstract definitions. **Bias toward finding an image.**
>
> Generate 2-3 specific search queries per card. Be descriptive and disambiguate aggressively:
> - Good: `"Circle of Willis anatomy diagram labeled arteries"`, `"CT head epidural hematoma lens shaped"`
> - Bad: `"brain blood vessels"`, `"anatomy"`
>
> Write to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/image_search_requests.json`:
> ```json
> [{"claim_id": "C001", "image_type": "anatomy_diagram", "search_queries": ["query1", "query2"]}]
> ```
> Skip cards with `image_type: "none"`.
>
> ### Phase 2: Search
>
> ```
> cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/anki_sync_cli.py search_images
> ```
> Smart routing: Wikimedia for anatomy/schematic types, Open-i for radiology/histology/surgical types, automatic fallback if < 2 candidates. Treat `openi_unavailable` as expected degradation.
>
> Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/image_candidates.json`. If a card has no candidates, refine queries with stronger medical anchors and re-run `search_images` once.
>
> ### Phase 3: Vision Validation
>
> Run the batch thumbnail downloader (handles pacing and retries internally):
> ```
> cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/anki_sync_cli.py download_thumbnails
> ```
> This downloads up to 3 thumbnails per card to `/tmp/anki_thumbs/{claim_id}_1.jpg`, `_2.jpg`, `_3.jpg` and writes a manifest to `/tmp/anki_thumbs/manifest.json`.
>
> Read the manifest, then for EACH card, use the Read tool on its thumbnail files to visually inspect them. Score each on 1-5:
> - **RELEVANCE**: depicts the right structure/concept?
> - **ACCURACY**: labels correct?
> - **CLARITY**: readable at ~500px?
> - **QUALITY**: professional, not watermarked?
>
> Accept if average >= 3.5. Select the best passing candidate.
>
> If NO candidate passes: refine queries, re-run `search_images`, then `download_thumbnails`, and validate once more. **One retry only** — then mark as no image.
>
> ### Phase 4: Write Selections & Process
>
> Write `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/image_selections.json`:
> ```json
> [
>   {
>     "claim_id": "C001",
>     "image_url": "https://direct-image-url...",
>     "source_url": "https://wikimedia-page-url...",
>     "attribution": "Author | Wikimedia Commons, CC-BY-SA 4.0",
>     "placement": "back",
>     "alt_text": "Brief description",
>     "validated_by_vision": true,
>     "validation_scores": {"relevance": 4, "accuracy": 4, "clarity": 4, "quality": 4},
>     "validation_notes": "Why this image was selected."
>   }
> ]
> ```
> **ALL 4 scores required** — pipeline rejects selections missing any. Omit claims with no passing image.
>
> Run batch processing:
> ```
> cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/anki_sync_cli.py process_selected_images
> ```
>
> **Return**: `{cards_enriched: N, text_only: M, total: N+M}`

## Step 6: Dispatch to Anki

**Before dispatching**, read `data/Sessions/anki_sync_runs/current_claims.json` and `data/Sessions/anki_sync_runs/current_topic.json` to capture topics and concepts for KG logging (these files are deleted after dispatch).

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/anki_sync_cli.py dispatch
```

This stores images in Anki's `collection.media`, injects `<img>` HTML into card fields, and persists claims to ChromaDB for future deduplication.

**If connection fails**: "AnkiConnect is not running. Please open the Anki desktop app and ensure AnkiConnect is installed, then try again."

Report final counts: "Created N cards (X with images, Y text-only), D duplicates, F failures in deck ..."

## Step 7: Knowledge Graph + Obsidian Integration (Silent)

After successful dispatch, run three operations:

### 7a. Log card creation to knowledge graph

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py log_study \
  --topics "<comma-separated topics from deck name and card content>" \
  --understood "<comma-separated card front concepts>" \
  --depth 2 --source "anki"
```

Derive topics from the deck path (e.g., `Agentic Neurosurgery Review::SAH Management` -> topic = "SAH management"). Use the `claim_text` fields captured before dispatch as the understood concepts.

### 7b. Sync Anki retention stats (if Anki is open)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py sync_anki 2>/dev/null || true
```

This pulls current retention stats for all cards. Failures are non-fatal.

### 7c. Write Obsidian session log

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

### 7d. Post-Session Hook

Run the Universal Post-Session Hook (see shared-system.md) to update Dashboard.md.

### 7e. Cleanup

```bash
rm -f data/Sessions/*.json data/Sessions/*.md data/Sessions/*.jsonl && rm -rf data/Sessions/anki_sync_runs
```

Do not narrate Steps 7a-7e to the user.
