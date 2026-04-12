---
name: anki_sync
description: Pipeline that extracts Anki flashcards from the current session transcript — deduplicates claims, drafts validated cloze/QA cards, enriches every card with a vision-validated image, and syncs to Anki via AnkiConnect. Always invoke this skill when the user wants to create flashcards or save to Anki — phrases like "save to Anki", "make flashcards", "make cards", "create Anki cards", "sync to Anki", "add this to my deck", "save for later study", or "turn this into cards". Do not attempt to answer inline for these requests.
---

# Anki Sync

Converts current session transcript into image-enriched Anki flashcards. You handle all LLM reasoning; Python handles DB/API only.

## Step 1: Capture Transcript

1. `mkdir -p data/Sessions/anki_sync_runs`
2. Write full verbatim conversation to `data/Sessions/current_session_verbatim.txt` via shell redirect (NOT WriteFile).
3. Wrap long lines: `python3 -c "import textwrap; ..."`
4. Read file. If <200 chars, stop: "Transcript too short."

## Step 2: Resolve Subdeck

Ask user: existing subdeck (paste path) or new one (auto-generate name under `Agentic Neurosurgery Review`).
Write to `data/Sessions/anki_sync_runs/current_topic.json`: `{"topic":"...","deck":"..."}`

## Step 3: Claim Extraction (Subagent, `model: "haiku"`)

> Extract factual claims from neurosurgery study session.
>
> **4-Phase extraction** (all must complete before writing):
> **A — Enumerate**: Read transcript, identify chunk boundaries, produce manifest.
> **B — Iterate**: For each chunk: extract atomic standalone claims, assign C001+ IDs. Never skip/batch chunks.
> **C — Verify**: Confirm all chunks processed.
> **D — Merge and Write**: Deduplicate, write to `data/Sessions/anki_sync_runs/current_claims.json`.
>
> Then run: `python3 src/anki_sync_cli.py filter_novelty`
> Read `novel_claims.json`, count novel claims. Return `{total_claims: N, novel_claims: M}`.

If 0 novel claims, stop: "No novel facts found."

## Step 4: Card Drafting (Subagent, `model: "sonnet"`)

> Read `novel_claims.json`. For each claim, draft ONE card:
> - **Cloze** for single factual associations. Exactly one `{{c1::...}}` deletion.
> - **QA** for reasoning/multi-part. Concise `front`/`back`.
>
> **Blind Validation**: For EACH card — hide answer, read only visible prompt. "Can someone guess the EXACT answer?" If too vague, add clinical constraints.
>
> Write to `data/Sessions/anki_sync_runs/final_cards.json`.

## Step 5: Image Enrichment (Subagent, `model: "haiku"`)

> **Phase 1 — Assess**: Classify each card's `image_type` (anatomy_diagram, radiology, histology, surgical_photo, schematic, none). Generate 2-3 specific search queries. Write to `image_search_requests.json`.
> **Phase 2 — Search**: `python3 src/anki_sync_cli.py search_images`. Read `image_candidates.json`. If empty, refine and retry once.
> **Phase 3 — Vision Validate**: `python3 src/anki_sync_cli.py download_thumbnails`. Read manifest, visually inspect thumbnails. Score relevance/accuracy/clarity/quality (1-5). Accept avg >= 3.5.
> **Phase 4 — Write**: `image_selections.json` with all 4 scores. Then `python3 src/anki_sync_cli.py process_selected_images`.

## Step 6: Dispatch

**Before dispatching**: read `current_claims.json` and `current_topic.json` to capture topics for KG logging.

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/anki_sync_cli.py dispatch
```

If connection fails: "AnkiConnect not running. Open Anki and ensure AnkiConnect is installed."

Report: "Created N cards (X with images, Y text-only), D duplicates, F failures in deck ..."

## Step 7: Post-Dispatch (Silent)

1. `log_study` with topics from deck + card content, depth 2, source "anki"
2. `sync_anki 2>/dev/null || true`
3. Write Obsidian session log to `Review Sessions/<Deck Topic Title>.md` — Cards Created table, Topics Reinforced, Notes. Metadata at bottom. Update `Review Sessions/INDEX.md`.
4. Post-Session Hook per CLAUDE.md §8
5. Cleanup: `rm -f data/Sessions/*.json data/Sessions/*.md data/Sessions/*.jsonl && rm -rf data/Sessions/anki_sync_runs`

Do not narrate Steps 7.1-7.5.
