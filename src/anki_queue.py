#!/usr/bin/env python3
"""Lean Anki card queue: enqueue, review, and flush to AnkiConnect with dedup."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from anki_sync.anki_client import AnkiClient, AnkiDispatchResult
from anki_sync.novelty import NoveltyStore
from anki_sync.schemas import CardDraft, ClaimModel

QUEUE_PATH = Path("data/Sessions/anki_queue.jsonl")
CHROMADB_PATH = "data/chromadb_store_anki_memory"
ANKI_URL = "http://localhost:8765"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
NOVELTY_THRESHOLD = 0.70
COLLECTION_NAME = "anki_claim_memory"


def _claim_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_queue(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def _write_queue(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _card_text(entry: dict) -> str:
    if entry.get("card_type") == "cloze":
        return entry.get("cloze_text", "")
    return entry.get("front", "")


def _answer_text(entry: dict) -> str:
    if entry.get("card_type") == "cloze":
        return entry.get("answer_text", "")
    return entry.get("back", "")


# ── enqueue ─────────────────────────────────────────────────────────

_DECK_RE = re.compile(r"^Neurosurgery::.+::.+$")


def _validate_enqueue(text: str, deck: str, card_type: str) -> list[str]:
    """Return list of problems. Empty = valid."""
    problems: list[str] = []
    if len(text.split()) < 4:
        problems.append(f"Card text too short ({len(text.split())} words, min 4)")
    if not _DECK_RE.match(deck):
        problems.append(
            f"Deck must be Neurosurgery::<Domain>::<Topic>, got: '{deck}'"
        )
    if card_type == "cloze" and "{{c1::" not in text:
        problems.append("Cloze card missing {{c1::...}} blank")
    return problems


def enqueue(
    session: str,
    exchange_id: int,
    deck: str,
    card_type: str,
    cloze: str = "",
    answer: str = "",
    front: str = "",
    back: str = "",
    tags: str = "",
    topic: str = "",
    concept: str = "",
    queue_path: Path = QUEUE_PATH,
) -> bool:
    text = cloze if card_type == "cloze" else front

    problems = _validate_enqueue(text, deck, card_type)
    if problems:
        print("VALIDATION ERROR -- fix and retry:\n  " + "\n  ".join(problems),
              file=sys.stderr)
        return False

    cid = _claim_id(text)

    try:
        draft = CardDraft(
            claim_id=cid,
            card_type=card_type,
            cloze_text=cloze,
            answer_text=answer,
            front=front,
            back=back,
        )
    except Exception as exc:
        print(f"VALIDATION ERROR -- fix and retry:\n  {exc}", file=sys.stderr)
        return False

    entry = {
        "enqueued_at": _now_iso(),
        "session_ts": session,
        "exchange_id": exchange_id,
        "deck": deck,
        "card_type": draft.card_type,
        "claim_id": cid,
        "topic": topic,
        "concept": concept,
        "tags": [t.strip() for t in tags.split(",") if t.strip()] if tags else [],
    }
    if card_type == "cloze":
        entry["cloze_text"] = draft.cloze_text
        entry["answer_text"] = draft.answer_text
    else:
        entry["front"] = draft.front
        entry["back"] = draft.back

    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"OK card_id={cid}")
    return True


# ── review ──────────────────────────────────────────────────────────

def review(session: str | None = None, queue_path: Path = QUEUE_PATH) -> list[dict]:
    entries = _read_queue(queue_path)
    if session:
        entries = [e for e in entries if e.get("session_ts") == session]

    if not entries:
        print("Queue is empty.")
        return entries

    decks = set()
    for i, e in enumerate(entries, 1):
        deck = e.get("deck", "?")
        decks.add(deck)
        ctype = e.get("card_type", "?")
        text = _card_text(e)[:80]
        ans = _answer_text(e)[:60]
        print(f"  [{i}] {ctype:5s} | {deck}")
        print(f"        {text}")
        print(f"        -> {ans}")

    print(f"\n{len(entries)} card(s), {len(decks)} deck(s)")
    return entries


# ── check (novelty pre-flight) ─────────────────────────────────────

def check(
    session: str | None = None,
    queue_path: Path = QUEUE_PATH,
) -> dict:
    """Run novelty check and surface duplicate pairs for agent review."""
    all_entries = _read_queue(queue_path)
    if session:
        to_check = [e for e in all_entries if e.get("session_ts") == session]
    else:
        to_check = all_entries

    if not to_check:
        print(json.dumps({"queue_size": 0, "novel": 0, "duplicates": []}))
        return {"queue_size": 0, "novel": 0, "duplicates": []}

    claims = []
    for e in to_check:
        text = _card_text(e)
        cid = e.get("claim_id", _claim_id(text))
        claims.append(ClaimModel(
            claim_id=cid,
            topic=e.get("topic", ""),
            concept=e.get("concept", ""),
            card_type=e.get("card_type", ""),
            claim_text=text[:420],
        ))

    store = NoveltyStore(CHROMADB_PATH, COLLECTION_NAME, EMBEDDING_MODEL)
    _, decisions = store.filter_novel_claims(claims, NOVELTY_THRESHOLD)

    novel_count = sum(1 for d in decisions if d.is_novel)
    duplicates = []
    for d, e in zip(decisions, to_check):
        if not d.is_novel:
            duplicates.append({
                "queued_card": _card_text(e),
                "matched_existing": d.matched_text,
                "similarity": round(d.max_similarity, 4),
                "claim_id": d.claim_id,
            })

    result = {
        "queue_size": len(to_check),
        "novel": novel_count,
        "duplicates": duplicates,
    }
    print(json.dumps(result, indent=2))
    return result


# ── flush ───────────────────────────────────────────────────────────

def flush(
    session: str | None = None,
    dry_run: bool = False,
    queue_path: Path = QUEUE_PATH,
) -> dict:
    all_entries = _read_queue(queue_path)
    if session:
        to_flush = [e for e in all_entries if e.get("session_ts") == session]
        remaining = [e for e in all_entries if e.get("session_ts") != session]
    else:
        to_flush = all_entries
        remaining = []

    if not to_flush:
        print(json.dumps({"queue_size": 0}))
        return {"queue_size": 0}

    if not dry_run:
        client = AnkiClient(ANKI_URL)
        ok, err = client.check_connection()
        if not ok:
            print(f"AnkiConnect unavailable: {err}", file=sys.stderr)
            print(json.dumps({"error": f"AnkiConnect unavailable: {err}"}))
            return {"error": err}

    claims = []
    drafts = []
    for e in to_flush:
        text = _card_text(e)
        cid = e.get("claim_id", _claim_id(text))

        claims.append(ClaimModel(
            claim_id=cid,
            topic=e.get("topic", ""),
            concept=e.get("concept", ""),
            card_type=e.get("card_type", ""),
            claim_text=text[:420],
        ))
        drafts.append(CardDraft(
            claim_id=cid,
            card_type=e["card_type"],
            cloze_text=e.get("cloze_text", ""),
            answer_text=e.get("answer_text", ""),
            front=e.get("front", ""),
            back=e.get("back", ""),
        ))

    store = NoveltyStore(CHROMADB_PATH, COLLECTION_NAME, EMBEDDING_MODEL)
    novel_claims, decisions = store.filter_novel_claims(claims, NOVELTY_THRESHOLD)
    novel_ids = {c.claim_id for c in novel_claims}

    novel_drafts = [d for d in drafts if d.claim_id in novel_ids]
    novel_entries = [e for e in to_flush if e.get("claim_id", "") in novel_ids]
    filtered_count = len(to_flush) - len(novel_drafts)

    # Build duplicate details for agent review
    dup_details = []
    for d, e in zip(decisions, to_flush):
        if not d.is_novel:
            dup_details.append({
                "queued_card": _card_text(e),
                "matched_existing": d.matched_text,
                "similarity": round(d.max_similarity, 4),
            })

    if dry_run:
        metrics = {
            "queue_size": len(to_flush),
            "novel": len(novel_drafts),
            "filtered_duplicate": filtered_count,
            "dry_run": True,
        }
        if dup_details:
            metrics["duplicate_details"] = dup_details
        print(json.dumps(metrics, indent=2))
        return metrics

    created = 0
    duplicate = 0
    failed = 0
    decks_touched: set[str] = set()
    errors: list[str] = []

    for draft, entry in zip(novel_drafts, novel_entries):
        deck = entry.get("deck", "Neurosurgery::General::Session")
        tags = entry.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        tags = ["Neuro-Agent", "study-review"] + tags

        try:
            client.ensure_deck(deck)
            result: AnkiDispatchResult = client.add_card(draft, deck, tags)
            if result.status == "created":
                created += 1
                decks_touched.add(deck)
            elif result.status == "duplicate":
                duplicate += 1
            else:
                failed += 1
                if result.error:
                    errors.append(result.error)
        except Exception as e:
            failed += 1
            errors.append(str(e))

    if novel_claims:
        store.persist_claims(novel_claims, {"source": "anki_queue"})

    _write_queue(queue_path, remaining)

    metrics = {
        "queue_size": len(to_flush),
        "created": created,
        "duplicate": duplicate,
        "novel_filtered": filtered_count,
        "failed": failed,
        "decks_touched": sorted(decks_touched),
    }
    if dup_details:
        metrics["filtered_details"] = dup_details
    if errors:
        metrics["errors"] = errors

    print(json.dumps(metrics, indent=2))
    return metrics


# ── CLI ─────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Anki card queue")
    sub = parser.add_subparsers(dest="command", required=True)

    p_enq = sub.add_parser("enqueue")
    p_enq.add_argument("--session", required=True)
    p_enq.add_argument("--exchange-id", type=int, required=True)
    p_enq.add_argument("--deck", required=True)
    p_enq.add_argument("--card-type", choices=["cloze", "qa"], required=True)
    p_enq.add_argument("--cloze", default="")
    p_enq.add_argument("--answer", default="")
    p_enq.add_argument("--front", default="")
    p_enq.add_argument("--back", default="")
    p_enq.add_argument("--tags", default="")
    p_enq.add_argument("--topic", default="")
    p_enq.add_argument("--concept", default="")

    p_rev = sub.add_parser("review")
    p_rev.add_argument("--session", default=None)

    p_check = sub.add_parser("check")
    p_check.add_argument("--session", default=None)

    p_flush = sub.add_parser("flush")
    p_flush.add_argument("--session", default=None)
    p_flush.add_argument("--dry-run", action="store_true")

    p_remove = sub.add_parser("remove")
    p_remove.add_argument("--claim-id", required=True,
                          help="Remove a specific card by claim_id (from check output)")

    args = parser.parse_args(argv)

    if args.command == "enqueue":
        ok = enqueue(
            session=args.session,
            exchange_id=args.exchange_id,
            deck=args.deck,
            card_type=args.card_type,
            cloze=args.cloze,
            answer=args.answer,
            front=args.front,
            back=args.back,
            tags=args.tags,
            topic=args.topic,
            concept=args.concept,
        )
        return 0 if ok else 1

    if args.command == "review":
        review(session=args.session)
        return 0

    if args.command == "check":
        check(session=args.session)
        return 0

    if args.command == "flush":
        result = flush(session=args.session, dry_run=args.dry_run)
        return 1 if "error" in result else 0

    if args.command == "remove":
        entries = _read_queue(QUEUE_PATH)
        before = len(entries)
        entries = [e for e in entries if e.get("claim_id") != args.claim_id]
        _write_queue(QUEUE_PATH, entries)
        removed = before - len(entries)
        print(f"Removed {removed} card(s) with claim_id={args.claim_id}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
