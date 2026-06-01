#!/usr/bin/env python3
"""Lean Anki card queue.

This script handles deterministic queue mechanics. Agents own card-quality
judgment via `.agents/shared/commands/anki-card-quality.md`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from difflib import SequenceMatcher
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
BATCH_DUPLICATE_THRESHOLD = 0.84
COLLECTION_NAME = "anki_claim_memory"
MAX_PROMPT_WORDS = 35
MAX_QA_BACK_WORDS = 45

_FEEDBACK_RE = re.compile(
    r"\b("
    r"correct interpretation|correct core distinction|strong operational handoff|"
    r"key discriminator is\s+(correct|strong)|for .+?, the key discriminator is"
    r")\b",
    re.IGNORECASE,
)


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


def _strip_cloze(text: str) -> str:
    text = re.sub(r"\{\{c\d+::(.*?)(::.*?)?\}\}", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _word_count(text: str) -> int:
    return len(_strip_cloze(text).split())


def _normalize_claim_text(text: str) -> str:
    text = _strip_cloze(text).lower()
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "#", text)
    text = re.sub(r"[^a-z0-9#]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _claim_text_for_entry(entry: dict) -> str:
    """Build the text used for advisory overlap checks.

    Basic cards need the answer included so two differently worded questions
    testing the same threshold/action collide more reliably. Cloze cards keep
    the visible prompt as the primary claim because cloze deletions already
    encode the target facts.
    """
    front = _card_text(entry)
    if entry.get("card_type") == "qa":
        answer = _answer_text(entry)
        text = f"{front} -> {answer}" if answer else front
    else:
        text = front

    concept = entry.get("concept", "")
    if concept:
        text = f"{concept}: {text}"
    return text[:420]


def _quality_warnings(entry: dict) -> list[str]:
    warnings: list[str] = []
    text = _card_text(entry)
    answer = _answer_text(entry)
    if _word_count(text) > MAX_PROMPT_WORDS:
        warnings.append(f"prompt_over_{MAX_PROMPT_WORDS}_words")
    if entry.get("card_type") == "qa" and _word_count(answer) > MAX_QA_BACK_WORDS:
        warnings.append(f"qa_back_over_{MAX_QA_BACK_WORDS}_words")
    if _FEEDBACK_RE.search(_strip_cloze(text)):
        warnings.append("feedback_derived_prompt")
    return warnings


def _batch_duplicate_details(
    entries: list[dict],
    store: NoveltyStore,
    threshold: float = BATCH_DUPLICATE_THRESHOLD,
) -> list[dict]:
    """Return same-batch overlap candidates for agent review."""
    if not entries:
        return []

    duplicate_details: list[dict] = []
    kept_entries: list[dict] = []
    kept_embedding_indices: list[int] = []

    embeddings: list[list[float]] | None = None
    try:
        raw_embeddings = store._embed([_claim_text_for_entry(e) for e in entries])
        embeddings = []
        for vec in raw_embeddings:
            norm = sum(float(x) * float(x) for x in vec) ** 0.5 or 1.0
            embeddings.append([float(x) / norm for x in vec])
        if len(embeddings) != len(entries):
            raise ValueError("embedding count mismatch")
    except Exception:
        embeddings = None

    for idx, entry in enumerate(entries):
        text = _claim_text_for_entry(entry)
        normalized = _normalize_claim_text(text)
        duplicate: dict | None = None

        for kept_idx, kept in enumerate(kept_entries):
            kept_text = _claim_text_for_entry(kept)
            kept_normalized = _normalize_claim_text(kept_text)
            lexical = SequenceMatcher(None, normalized, kept_normalized).ratio()
            semantic = 0.0
            if embeddings is not None:
                kept_embedding_idx = kept_embedding_indices[kept_idx]
                semantic = sum(
                    a * b for a, b in zip(embeddings[idx], embeddings[kept_embedding_idx])
                )
            score = max(lexical, semantic)
            if score >= threshold:
                duplicate = {
                    "queued_card": _card_text(entry),
                    "matched_queued_card": _card_text(kept),
                    "similarity": round(score, 4),
                    "claim_id": entry.get("claim_id", _claim_id(_card_text(entry))),
                }
                break

        if duplicate:
            duplicate_details.append(duplicate)
            continue

        kept_entries.append(entry)
        kept_embedding_indices.append(idx)

    return duplicate_details


# ── enqueue ─────────────────────────────────────────────────────────

_DECK_RE = re.compile(r"^Neurosurgery::.+::.+$")
BRAIN_DUMP_DECK = "Neurosurgery::Brain Dumps"


def _validate_enqueue(
    text: str,
    deck: str,
    card_type: str,
    answer: str = "",
    tags: str = "",
) -> list[str]:
    """Return mechanical problems. Agentic quality judgment happens later."""
    problems: list[str] = []
    if len(text.split()) < 4:
        problems.append(f"Card text too short ({len(text.split())} words, min 4)")
    parsed_tags = {tag.strip() for tag in tags.split(",") if tag.strip()}
    if deck != BRAIN_DUMP_DECK and not _DECK_RE.match(deck):
        problems.append(
            f"Deck must be Neurosurgery::<Domain>::<Topic> or {BRAIN_DUMP_DECK}, got: '{deck}'"
        )
    if deck == BRAIN_DUMP_DECK and "brain-dump" not in parsed_tags:
        problems.append("Cards in Neurosurgery::Brain Dumps must include the brain-dump tag")
    if "brain-dump" in parsed_tags and deck != BRAIN_DUMP_DECK:
        problems.append("Cards tagged brain-dump must use the Neurosurgery::Brain Dumps deck")
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

    answer_text = answer if card_type == "cloze" else back
    problems = _validate_enqueue(text, deck, card_type, answer_text, tags)
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


# ── check (advisory pre-flight) ────────────────────────────────────

def check(
    session: str | None = None,
    queue_path: Path = QUEUE_PATH,
) -> dict:
    """Surface quality warnings and overlap candidates for agent review.

    This command never decides what should flush. Chroma is an advisory index
    rebuilt from live Anki, not a source of truth.
    """
    all_entries = _read_queue(queue_path)
    if session:
        to_check = [e for e in all_entries if e.get("session_ts") == session]
    else:
        to_check = all_entries

    if not to_check:
        print(json.dumps({"queue_size": 0, "duplicate_candidates": [], "quality_warnings": []}))
        return {"queue_size": 0, "duplicate_candidates": [], "quality_warnings": []}

    claims = []
    for e in to_check:
        text = _card_text(e)
        cid = e.get("claim_id", _claim_id(text))
        claims.append(ClaimModel(
            claim_id=cid,
            topic=e.get("topic", ""),
            concept=e.get("concept", ""),
            card_type=e.get("card_type", ""),
            claim_text=_claim_text_for_entry(e),
        ))

    store = NoveltyStore(CHROMADB_PATH, COLLECTION_NAME, EMBEDDING_MODEL)
    _, decisions = store.filter_novel_claims(claims, NOVELTY_THRESHOLD)
    batch_dup_details = _batch_duplicate_details(to_check, store)

    duplicate_candidates = []
    for d, e in zip(decisions, to_check):
        if not d.is_novel:
            duplicate_candidates.append({
                "source": "anki_chroma_cache",
                "queued_card": _card_text(e),
                "matched_existing": d.matched_text,
                "similarity": round(d.max_similarity, 4),
                "claim_id": d.claim_id,
            })
    for detail in batch_dup_details:
        detail["source"] = "same_queue_batch"
        duplicate_candidates.append(detail)

    quality_warnings = []
    for e in to_check:
        warnings = _quality_warnings(e)
        if warnings:
            quality_warnings.append({
                "claim_id": e.get("claim_id", _claim_id(_card_text(e))),
                "card": _card_text(e),
                "warnings": warnings,
            })

    # Programmatic check for missed/partial exchanges in SQLite missing from the queue
    db_path = Path("data/study_memory.db")
    if db_path.exists() and session:
        import sqlite3
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT DISTINCT e.id, c.display_name AS concept
                   FROM exchanges e
                   JOIN claim_results cr ON e.id = cr.exchange_id
                   JOIN concepts c ON e.concept_id = c.id
                   WHERE e.session_id = ? AND cr.score < 2""",
                [session],
            ).fetchall()

            enqueued_exchanges = {int(e["exchange_id"]) for e in to_check if e.get("exchange_id") is not None}

            for r in rows:
                ex_id = int(r["id"])
                if ex_id not in enqueued_exchanges:
                    quality_warnings.append({
                        "claim_id": f"missed_exchange_{ex_id}",
                        "card": f"Exchange {ex_id} (concept: '{r['concept']}') was logged with score < 2 but has NO enqueued card.",
                        "warnings": ["uncarded_missed_exchange"],
                    })
            conn.close()
        except Exception:
            pass

    result = {
        "queue_size": len(to_check),
        "duplicate_candidates": duplicate_candidates,
        "duplicates": duplicate_candidates,
        "quality_warnings": quality_warnings,
    }
    print(json.dumps(result, indent=2))
    return result


# ── flush ───────────────────────────────────────────────────────────

def flush(
    session: str | None = None,
    dry_run: bool = False,
    allow_duplicate_candidates: bool = False,
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

    preflight = check(session=session, queue_path=queue_path)
    duplicate_candidates = preflight.get("duplicate_candidates", [])
    if duplicate_candidates and not allow_duplicate_candidates:
        result = {
            "error": "duplicate_candidates_require_agent_review",
            "queue_size": len(to_flush),
            "duplicate_candidates": duplicate_candidates,
            "message": (
                "Run anki_queue.py check, remove true duplicates, or rerun flush "
                "with --allow-duplicate-candidates only after judging all candidates false positives."
            ),
        }
        print(json.dumps(result, indent=2))
        return result

    drafts = []
    for e in to_flush:
        text = _card_text(e)
        cid = e.get("claim_id", _claim_id(text))

        drafts.append(CardDraft(
            claim_id=cid,
            card_type=e["card_type"],
            cloze_text=e.get("cloze_text", ""),
            answer_text=e.get("answer_text", ""),
            front=e.get("front", ""),
            back=e.get("back", ""),
        ))

    if dry_run:
        metrics = {
            "queue_size": len(to_flush),
            "would_dispatch": len(drafts),
            "duplicate_candidate_count": len(duplicate_candidates),
            "dry_run": True,
        }
        print(json.dumps(metrics, indent=2))
        return metrics

    created = 0
    duplicate = 0
    failed = 0
    decks_touched: set[str] = set()
    errors: list[str] = []

    for draft, entry in zip(drafts, to_flush):
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

    _write_queue(queue_path, remaining)

    metrics = {
        "queue_size": len(to_flush),
        "created": created,
        "duplicate": duplicate,
        "duplicate_candidate_count": len(duplicate_candidates),
        "duplicate_gate": "overridden" if duplicate_candidates else "clear",
        "failed": failed,
        "decks_touched": sorted(decks_touched),
    }
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
    p_flush.add_argument(
        "--allow-duplicate-candidates",
        action="store_true",
        help="Proceed only after an agent has reviewed check output and judged candidates false positives.",
    )

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
        result = flush(
            session=args.session,
            dry_run=args.dry_run,
            allow_duplicate_candidates=args.allow_duplicate_candidates,
        )
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
