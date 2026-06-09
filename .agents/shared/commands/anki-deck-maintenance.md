# Anki Deck Maintenance Contract

Purpose: separate live deck rewriting/reorganization from normal learning-session card creation. This workflow treats Anki as the source of truth and the SQLite vector cache as a rebuildable advisory cache.

Use this only when Gabriel asks to clean, rewrite, reorganize, deduplicate, audit, or rebuild the current Anki deck. Do not run it as part of routine session-end flush, and do not rely on it to clean duplicates that routine sessions should have caught before flush.

## Ground Truth

Anki is the only durable user-visible card store. The SQLite novelty vector database is derived from live Anki and must never veto a card independently of Anki.

Implications:
- Export cards from live Anki before assessing quality.
- Rewrite existing notes in place whenever possible so scheduling/review history is preserved.
- Move existing cards between decks with AnkiConnect `changeDeck`; do not recreate cards for taxonomy cleanup.
- Rebuild the SQLite vector cache from live Anki after approved edits/moves.
- If the vector cache contains concepts not present in Anki, they must not suppress future cards.

## Workflow

1. Export live deck:
```bash
python3 src/anki_deck_tools.py export \
  --query "deck:Neurosurgery*" \
  --output "data/Sessions/anki_live_export.json"
```

2. Agent assessment:
- Read `.agents/shared/commands/anki-card-quality.md`.
- Assess each note for card quality, atomicity, self-containment, wording, deck taxonomy, and duplicate memory trace.
- Produce an explicit edit plan before changing Anki.
- Mark each proposed action as one of: `rewrite_note`, `move_note`, `merge_by_rewrite_then_suspend`, `leave`, `needs_user_decision`.

3. Approved in-place edits:
```bash
python3 src/anki_deck_tools.py update-note \
  --note-id "<note_id>" \
  --fields-json '{"Front":"...","Back":"..."}'
```

For Cloze notes use `{"Text":"..."}`. Do not write cloze explanations into Back Extra unless the user explicitly wants that field populated.

4. Approved deck moves:
```bash
python3 src/anki_deck_tools.py move-note \
  --note-id "<note_id>" \
  --deck "Neurosurgery::<Domain>::<Topic>"
```

5. Re-export and verify:
```bash
python3 src/anki_deck_tools.py export \
  --query "deck:Neurosurgery*" \
  --output "data/Sessions/anki_live_export_after.json"
```

6. Rebuild the SQLite vector cache from final live Anki:
```bash
python3 src/anki_deck_tools.py rebuild-cache --query "deck:Neurosurgery*"
```

## Prohibited

- Do not delete or recreate notes to fix wording or deck taxonomy when in-place update/move is possible.
- Do not use the vector cache as a source of truth for whether a live card exists.
- Do not bulk suspend/delete without an approved note-id list.
- Do not run broad cleanup commands over Anki without an exported plan.

## Completion Criteria

The workflow is complete only when:
- live Anki has been re-exported after edits
- the post-edit export matches the approved plan
- The SQLite vector cache has been rebuilt from the post-edit live Anki export
- the final summary reports note counts, moved notes, updated notes, unresolved decisions, and vector cache rebuild count
