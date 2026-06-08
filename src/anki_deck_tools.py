#!/usr/bin/env python3
"""Deck maintenance tools for live Anki as source of truth.

Normal study sessions should use `anki_queue.py` through enqueue/review/check/
flush. This script is for the separate deck rewrite/reorganization workflow:
export live cards, apply approved in-place edits/moves, then rebuild Chroma
from the final Anki state.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

from anki_sync.anki_client import AnkiClient
from anki_sync.novelty import NoveltyStore
from anki_sync.schemas import ClaimModel

ANKI_URL = "http://localhost:8765"
CHROMADB_PATH = "data/chromadb_store_anki_memory"
COLLECTION_NAME = "anki_claim_memory"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_QUERY = "deck:Neurosurgery*"


def _strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _field_value(fields: dict, name: str) -> str:
    value = fields.get(name, "")
    if isinstance(value, dict):
        return str(value.get("value", ""))
    return str(value)


def _note_prompt(note: dict) -> str:
    fields = note.get("fields") or {}
    if note.get("modelName") == "Cloze":
        return _field_value(fields, "Text")
    return _field_value(fields, "Front")


def _note_answer(note: dict) -> str:
    fields = note.get("fields") or {}
    if note.get("modelName") == "Cloze":
        return _field_value(fields, "Back Extra") or _field_value(fields, "Extra")
    return _field_value(fields, "Back")


def _claim_text(note: dict) -> str:
    prompt = _strip_html(_note_prompt(note))
    answer = _strip_html(_note_answer(note))
    if note.get("modelName") == "Basic" and answer:
        return f"{prompt} -> {answer}"[:420]
    return prompt[:420]


def _slug_display(value: str) -> str:
    value = re.sub(r"[-_]+", " ", str(value or "")).strip()
    return value.title()


def _note_topic_concept(note: dict) -> tuple[str, str, str]:
    tags = [str(tag) for tag in note.get("tags", []) if str(tag)]
    decks = [str(deck) for deck in note.get("decks", []) if str(deck)]
    deck_parts = decks[0].split("::") if decks else []
    topic = ""
    concept = ""
    source_workflow = "live_anki"

    if len(deck_parts) >= 2:
        topic = deck_parts[1]
    if len(deck_parts) >= 3:
        concept = deck_parts[-1]
    if any(tag.lower() == "brain-dump" for tag in tags) or any("Brain Dumps" in deck for deck in decks):
        source_workflow = "brain-dump"
    for tag in tags:
        lower = tag.lower()
        if lower.startswith("topic/"):
            topic = _slug_display(tag.split("/", 1)[1])
        elif lower.startswith("domain/") and not topic:
            topic = _slug_display(tag.split("/", 1)[1])
        elif lower.startswith("concept/"):
            concept = _slug_display(tag.split("/", 1)[1])
        elif lower in {"study-review", "quick-answer", "consult", "intraoperative-guide"}:
            source_workflow = lower

    return topic or "live_anki", concept, source_workflow


def _export_notes(client: AnkiClient, query: str) -> dict:
    card_ids = client.find_cards(query)
    cards = client.cards_info(card_ids, batch_size=100)
    note_ids = sorted({int(c["note"]) for c in cards if c.get("note") is not None})
    notes = client.notes_info(note_ids, batch_size=100)

    cards_by_note: dict[int, list[dict]] = {}
    for card in cards:
        note_id = int(card.get("note"))
        cards_by_note.setdefault(note_id, []).append(card)

    rows = []
    for note in notes:
        note_id = int(note["noteId"])
        fields = note.get("fields") or {}
        simple_fields = {
            name: _field_value(fields, name)
            for name in fields
        }
        note_cards = cards_by_note.get(note_id, [])
        rows.append({
            "noteId": note_id,
            "modelName": note.get("modelName", ""),
            "tags": note.get("tags", []),
            "fields": simple_fields,
            "decks": sorted({c.get("deckName", "") for c in note_cards}),
            "cardIds": [int(c["cardId"]) for c in note_cards if c.get("cardId")],
            "claim_text": _claim_text(note),
        })

    return {
        "query": query,
        "card_count": len(cards),
        "note_count": len(rows),
        "notes": rows,
    }


def export(query: str, output: Path | None) -> dict:
    client = AnkiClient(ANKI_URL)
    data = _export_notes(client, query)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "query": query,
        "cards": data["card_count"],
        "notes": data["note_count"],
        "output": str(output) if output else "",
    }, indent=2))
    return data


def rebuild_chroma(query: str, dry_run: bool = False) -> dict:
    client = AnkiClient(ANKI_URL)
    data = _export_notes(client, query)
    claims = []
    metadatas = []
    for note in data["notes"]:
        if not note.get("claim_text"):
            continue
        topic, concept, source_workflow = _note_topic_concept(note)
        claims.append(
            ClaimModel(
                claim_id=str(note["noteId"])[-12:],
                topic=topic,
                concept=concept,
                card_type="cloze" if note["modelName"] == "Cloze" else "qa",
                claim_text=note["claim_text"],
            )
        )
        card_ids = [int(card_id) for card_id in note.get("cardIds", []) if card_id]
        metadatas.append({
            "source": "live_anki_rebuild",
            "source_workflow": source_workflow,
            "note_id": int(note["noteId"]),
            "card_id": card_ids[0] if card_ids else 0,
            "deck": " | ".join(str(deck) for deck in note.get("decks", [])),
            "tags": " ".join(str(tag) for tag in note.get("tags", [])),
        })

    if not dry_run:
        store = NoveltyStore(CHROMADB_PATH, COLLECTION_NAME, EMBEDDING_MODEL)
        store.replace_claims(claims, metadatas)

    result = {
        "query": query,
        "anki_notes": data["note_count"],
        "claims": len(claims),
        "dry_run": dry_run,
        "source_of_truth": "anki",
    }
    print(json.dumps(result, indent=2))
    return result


def update_note(note_id: int, fields_json: str) -> dict:
    fields = json.loads(fields_json)
    if not isinstance(fields, dict) or not all(isinstance(k, str) for k in fields):
        raise ValueError("--fields-json must be an object of field names to values")
    client = AnkiClient(ANKI_URL)
    client.update_note_fields(note_id, {k: str(v) for k, v in fields.items()})
    result = {"updated_note": int(note_id), "fields": sorted(fields)}
    print(json.dumps(result, indent=2))
    return result


def move_note(note_id: int, deck: str) -> dict:
    client = AnkiClient(ANKI_URL)
    cards = client.notes_info([note_id])
    if not cards:
        raise RuntimeError(f"Note not found: {note_id}")
    card_ids = [int(c) for c in cards[0].get("cards", [])]
    client.change_deck(card_ids, deck)
    result = {"moved_note": int(note_id), "cards": card_ids, "deck": deck}
    print(json.dumps(result, indent=2))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live Anki deck maintenance tools")
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export")
    p_export.add_argument("--query", default=DEFAULT_QUERY)
    p_export.add_argument("--output", type=Path, default=None)

    p_rebuild = sub.add_parser("rebuild-chroma")
    p_rebuild.add_argument("--query", default=DEFAULT_QUERY)
    p_rebuild.add_argument("--dry-run", action="store_true")

    p_update = sub.add_parser("update-note")
    p_update.add_argument("--note-id", type=int, required=True)
    p_update.add_argument("--fields-json", required=True)

    p_move = sub.add_parser("move-note")
    p_move.add_argument("--note-id", type=int, required=True)
    p_move.add_argument("--deck", required=True)

    args = parser.parse_args(argv)

    if args.command == "export":
        export(args.query, args.output)
        return 0
    if args.command == "rebuild-chroma":
        rebuild_chroma(args.query, args.dry_run)
        return 0
    if args.command == "update-note":
        update_note(args.note_id, args.fields_json)
        return 0
    if args.command == "move-note":
        move_note(args.note_id, args.deck)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
