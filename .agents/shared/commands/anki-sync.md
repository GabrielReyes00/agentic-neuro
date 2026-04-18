# Anki Sync

Use when the user asks to make flashcards, save to Anki, create cards, sync cards, or add material to a deck. The agent reasons and drafts; Python handles DB/API/image processing.

## Hard Gates

| Step | Output | Stop condition |
|---|---|---|
| Capture | `current_session_verbatim.txt` | source under 200 chars |
| Deck | `current_topic.json` | deck unresolved |
| Claims | `current_claims.json` | no claims |
| Novelty | `novel_claims.json` | no novel facts |
| Cards | `final_cards.json` | blind validation missing |
| Validation | `validate_final_cards` | CLI validation fails |
| Dispatch | AnkiConnect | unavailable |
| Wrap | KG/vault/post-hook | failures surfaced |

## Schema

Cards use `claim_id`, `card_type` (`cloze` or `qa`), `cloze_text`, `answer_text`, `front`, and `back`. Cloze cards have exactly one `{{c1::...}}`. Invalid aliases such as `type`, `question`, or `answer` are rejected.

`final_cards.json` includes `cards`, per-card `blind_validation`, and `validation_report` with `cards_drafted` and `cards_refined`.

## Workflow

1. Create `data/Sessions/anki_sync_runs`.
2. Write source text to `data/Sessions/current_session_verbatim.txt`.
3. Resolve existing deck path or new subdeck under `Agentic Neurosurgery Review`.
4. Pull confusable pairs for the topic when available:

```bash
python3 src/knowledge_graph.py confusable_pairs --topic "<topic>" > data/Sessions/anki_sync_runs/confusable_pairs.json
```

5. Extract atomic standalone claims chunk-by-chunk. Enumerate chunks first, process each in order, verify `Chunks processed: N / N`, then write `current_claims.json`.
6. Run novelty filter:

```bash
python3 src/anki_sync_cli.py filter_novelty
```

7. Draft one card per novel claim. Cloze for single associations; QA for reasoning or multi-part concepts.
8. Blind-validate every card by hiding the answer and checking whether the prompt uniquely yields the answer.
9. Run:

```bash
python3 src/anki_sync_cli.py validate_final_cards
```

10. Enrich images where useful: assess image type, search/download candidates, visually validate thumbnails, score relevance/accuracy/clarity/quality, accept average >= 3.5, then write selections.
11. Process images and dispatch:

```bash
python3 src/anki_sync_cli.py process_selected_images
python3 src/anki_sync_cli.py dispatch
```

If AnkiConnect fails, tell the user to open Anki and confirm the add-on is installed.

## Finish

Report created cards, image count, text-only count, duplicates, failures, and deck. Silently log study topics, sync Anki if possible, write `Review Sessions/<Deck Topic Title>.md`, refresh index, run post-session hook, and remove only `current_session_verbatim.txt` plus `data/Sessions/anki_sync_runs`.
