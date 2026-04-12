---
name: anki_sync
description: Convert session or file content into validated neurosurgery Anki cards, enrich with vision-checked images, and sync through AnkiConnect. Use for flashcard/save-to-Anki requests.
---

# Anki Sync Command

Build cards from source material with strict schema validation, blind prompt checks, image enrichment, and post-sync telemetry. Shell prefix per §3.

## Hard Gates (Do Not Skip)

| Step | Output | Stop condition |
|---|---|---|
| 1 | `current_session_verbatim.txt` | source text <200 chars |
| 2 | `current_topic.json` | deck path unresolved |
| 4 | `current_claims.json` | missing/empty claims |
| 5 | `novel_claims.json` | empty → stop (no novel facts) |
| 6 | `final_cards.json` | blind validation not completed |
| 6.5 | `validation_audit.json` | `validate_final_cards` fails |
| 8 | dispatch | AnkiConnect unavailable |
| 9 | KG + vault + cleanup | never skip |

## Card Schema (Exact Contract)

Fields: `claim_id`, `card_type` (`"cloze"` or `"qa"`), `cloze_text` (cloze only, exactly one `{{c1::...}}`), `answer_text` (cloze), `front`/`back` (qa). Invalid aliases (`type`, `question`, `answer`) are rejected.

`final_cards.json` must include: `cards` with per-card `blind_validation`, `validation_report` with `cards_drafted`/`cards_refined`. No emojis. Plain text + `<b>`/`<i>` only.

## Step 1: Capture Source

1. `mkdir -p data/Sessions/anki_sync_runs`
2. Copy file content or write transcript via shell heredoc (not file-write tool) to `data/Sessions/current_session_verbatim.txt`
3. Wrap long lines. Abort if <200 chars.

## Step 2: Resolve Deck

Ask user: existing path or new subdeck. Write `{"topic":"...","deck":"..."}` to `data/Sessions/anki_sync_runs/current_topic.json`.

## Step 3: Pull Confusable Pairs

```bash
python3 src/knowledge_graph.py confusable_pairs --topic "<subdeck label>" > data/Sessions/anki_sync_runs/confusable_pairs.json
```

## Step 4: Extract Claims (Sub-task, Chunked)

Anti-laziness rules — all three must hold:
1. Never read source in a single pass
2. Enumerate all chunks BEFORE extracting
3. Verify all chunks processed BEFORE writing

Delegate with enforced loop:

**4a Enumerate**: Read source, identify section boundaries, produce manifest:
```
CHUNK MANIFEST — Total chunks: N
[ ] Chunk 1: lines 1-80 / "Topic: ..."
...
```

**4b Iterate**: Per chunk in order: `[processing]` → extract atomic claims → assign `C001+` IDs → `[done]`: `Chunk K/N`. Never skip or batch.

**4c Verify**: `EXTRACTION COMPLETE — Chunks processed: N / N`. Process any skipped chunks individually.

**4d Write**: Merge, deduplicate, write to `data/Sessions/anki_sync_runs/current_claims.json`. Use confusable-pair file to sharpen phrasing.

## Step 5: Novelty Filter

```bash
python3 src/anki_sync_cli.py filter_novelty
```

Read `novel_claims.json`; abort if empty.

## Step 6: Draft Cards + Blind Validation (Sub-task)

Draft one card per claim (batch 10-15 for large sets). Enforce schema exactly. For each card: hide answer → evaluate if prompt uniquely yields exact answer → refine until pass. Write `final_cards.json` with per-card `blind_validation` and `validation_report`.

## Step 6.5: CLI Validation Gate

```bash
python3 src/anki_sync_cli.py validate_final_cards
```

Do not continue unless this passes. Anti-gaming: if `cards_refined = 0` for >3 cards, validation is treated as skipped.

## Step 7: Image Enrichment (Sub-task)

1. **Assess**: From `final_cards.json`, produce `image_search_requests.json`
2. **Search/download**: `search_images` → `download_thumbnails`
3. **Vision validate**: Inspect pixels, score relevance/accuracy/clarity/quality (1-5), accept avg >= 3.5
4. **Write**: `image_selections.json` with `claim_id`, URLs, attribution, scores, `validated_by_vision`

## Step 8: Process & Dispatch

```bash
python3 src/anki_sync_cli.py validate_final_cards && \
python3 src/anki_sync_cli.py process_selected_images && \
python3 src/anki_sync_cli.py dispatch
```

Report: created, with-images, text-only, duplicates, failures, deck.

## Step 9: Post-Dispatch (Silent)

1. `log_study` with topics + card concepts, depth 2, source "anki"
2. `sync_anki 2>/dev/null || true`
3. Write `Review Sessions/<Deck Topic Title>.md` + refresh INDEX
4. Universal post-session hook per §7
5. `rm -f data/Sessions/current_session_verbatim.txt && rm -rf data/Sessions/anki_sync_runs`

Do not narrate step 9 unless failures occur.
