"""Real-time Anki card creation wired into the memory layer.

Design
------
Every call to ``memory_orchestrator.py record-answer`` enqueues a CARD
CANDIDATE (one JSON line in ``data/Sessions/anki_queue.jsonl``). The enqueue
is trivially fast — no LLM, no network. At natural flush points (every 3
turns via heartbeat, and at session end via the post-session hook) the
queue is flushed:

  queue candidates -> suppression filter -> Gemini 3 Flash batch synthesis
    -> CardDraft validation -> ChromaDB novelty filter (Anki memory store)
    -> AnkiConnect dispatch -> ChromaDB persist -> KG backlink
    -> queue file cleared

The ChromaDB store (``chromadb_store_anki_memory``, collection
``neurosurgery_memory_v1``) is the same store the legacy ``anki-sync``
skill uses. Every successfully-created card persists its claim text here,
so subsequent sessions will not re-card semantically equivalent facts.

Deck convention
---------------
``Neurosurgery::<Domain Title>::<Topic Title>``. The domain
umbrella matches the KG's ``domain`` tag (vascular, spine, tumor, trauma,
functional, pediatric, peripheral-nerve, general, anatomy). AnkiConnect
``createDeck`` is idempotent, so the umbrella and subdeck are created on
first use and reused thereafter.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

# --- Path bootstrap so this module works both as `python3 src/anki_realtime.py`
#     and as `python3 -m src.anki_realtime`.
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from kg_constants import DATA_DIR, SESSIONS_DIR  # noqa: E402

DEFAULT_DB_PATH = DATA_DIR / "knowledge_graph.db"
from src.anki_sync.schemas import CardDraft, ClaimModel  # noqa: E402
from src.anki_sync.anki_client import AnkiClient  # noqa: E402
from src.anki_gemini_synth import synthesize_cards  # noqa: E402


QUEUE_PATH = SESSIONS_DIR / "anki_queue.jsonl"
FLUSH_LOG_PATH = SESSIONS_DIR / "anki_flush_log.jsonl"
ROOT_DECK = "Neurosurgery"

ANKI_URL_DEFAULT = "http://localhost:8765"

# ChromaDB store settings (identical to anki_sync_cli.py so dedup is shared).
CHROMA_PATH = str(DATA_DIR / "chromadb_store_anki_memory")
CHROMA_COLLECTION = "neurosurgery_memory_v1"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
NOVELTY_THRESHOLD = 0.88


# ---------------------------------------------------------------------------
# Suppression — avoid carding routine correct answers on shallow depth
# ---------------------------------------------------------------------------


def _should_suppress(candidate: dict) -> bool:
    correct = int(candidate.get("correct") or 0)
    depth = int(candidate.get("depth") or 1)
    error_type = (candidate.get("error_type") or "").strip()
    breakthrough = bool(candidate.get("breakthrough"))

    if breakthrough:
        return False
    # Always card partial and incorrect answers — those are teaching moments.
    if correct < 2:
        return False
    # Correct answer at high depth is still worth reinforcing.
    if depth >= 3:
        return False
    # Correct answer with a declared error_type means the agent flagged a
    # subtle issue (calibration, minor omission). Keep it.
    if error_type:
        return False

    # Routine correct at shallow depth with no error signal: skip.
    return True


def _validate_candidate(candidate: dict) -> bool:
    question = (candidate.get("question") or "").strip()
    answer = (candidate.get("answer") or "").strip()
    concept = (candidate.get("concept") or "").strip()
    if len(question) < 10 or len(answer) < 2 or not concept:
        return False
    return True


# ---------------------------------------------------------------------------
# Deck name resolution
# ---------------------------------------------------------------------------

_DOMAIN_TITLES = {
    "vascular": "Vascular",
    "spine": "Spine",
    "tumor": "Tumor",
    "trauma": "Trauma",
    "functional": "Functional",
    "pediatric": "Pediatric",
    "peripheral-nerve": "Peripheral Nerve",
    "peripheral_nerve": "Peripheral Nerve",
    "general": "General",
    "anatomy": "Anatomy",
}


def _title_case(text: str) -> str:
    """Title-case a phrase while preserving acronyms and existing capitalization.

    - All-uppercase tokens (MCA, SAH, ACGME) stay all-uppercase.
    - Tokens already containing an internal uppercase (e.g. "ICP") are left as-is.
    - Pure-lowercase tokens are capitalized.
    """
    out = []
    for token in text.split():
        if not token:
            continue
        if token.isupper():
            out.append(token)
        elif any(c.isupper() for c in token[1:]):
            out.append(token)
        else:
            out.append(token.capitalize())
    return " ".join(out)


def _sanitize_deck_segment(text: str) -> str:
    import re
    clean = re.sub(r"[^A-Za-z0-9\s\-&]", " ", (text or "").replace("::", " "))
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:60] or "General"


# Tokens stripped during topic normalization. Stopwords are low-signal;
# session modifiers are the names/ages/scenarios that would otherwise
# fragment a topic into dozens of near-duplicate decks.
_TOPIC_STOPWORDS = frozenset({
    "a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or",
    "the", "to", "with",
    "case", "patient", "pt", "review", "session", "scenario",
})
_SESSION_MODIFIER_PATTERNS = (
    r"\bin\s+(?:a|an|the)?\s*\d+[- ]?(?:year|yo|y\.o\.|yr)[- ]?old[^,.;]*",
    r"\b\d+[- ]?(?:year|yo|yr)[- ]?old\b",
    r"\b(?:adolescent|elderly|young|adult|male|female|infant|newborn|geriatric|pregnant)\b",
    r"\bin\s+(?:a|an|the)?\s*(?:case|patient|scenario|context|setting)\b",
    r"\bcase\s*#?\s*\d+\b",
)


def _strip_session_modifiers(text: str) -> str:
    import re
    out = text
    for pat in _SESSION_MODIFIER_PATTERNS:
        out = re.sub(pat, " ", out, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip(" -")


def _topic_tokens(text: str) -> frozenset[str]:
    import re
    t = text.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return frozenset(w for w in t.split() if w not in _TOPIC_STOPWORDS and len(w) > 1)


def _canonicalize_topic(proposed: str, existing: list[str]) -> str:
    """Either reuse an existing sibling topic (if close enough) or return a
    broadened version of ``proposed`` suitable as a new subdeck name.

    Reuse rule: a sibling is reused when token IoU >= 0.5 OR one side's
    tokens are >= 80% contained in the other — high enough that "SAH
    management" reuses "SAH and Vasospasm Management" but "SAH rebleeding"
    stays separate from "SAH grading scales".

    Broadening rule: if no sibling matches, session modifiers (ages,
    "in a patient", "case 3", etc.) are stripped so the new deck covers
    future related cards.
    """
    stripped_proposed = _strip_session_modifiers(proposed) or proposed
    proposed_tokens = _topic_tokens(stripped_proposed)
    if not proposed_tokens:
        return _title_case(stripped_proposed or "Session")

    best_name: str | None = None
    best_score = 0.0
    for sibling in existing or []:
        if not sibling:
            continue
        sibling_tokens = _topic_tokens(sibling)
        if not sibling_tokens:
            continue
        inter = proposed_tokens & sibling_tokens
        if not inter:
            continue
        iou = len(inter) / len(proposed_tokens | sibling_tokens)
        subset = len(inter) / min(len(proposed_tokens), len(sibling_tokens))
        if iou >= 0.5 or subset >= 0.8:
            score = max(iou, subset * 0.9)
            if score > best_score or (score == best_score and best_name and sibling < best_name):
                best_score = score
                best_name = sibling
    if best_name:
        return best_name
    return _title_case(stripped_proposed)


def resolve_deck_name(
    topic: str,
    domain: str,
    existing_subtopics: list[str] | None = None,
) -> str:
    """Build the AnkiConnect deck name for a (topic, domain) pair.

    Returns ``Neurosurgery::<Umbrella>::<Topic>``. When
    ``existing_subtopics`` is provided (the list of topic segments already
    present under this domain in Anki), the topic is canonicalized against
    it — existing decks are reused when a close match exists, and new
    decks are given broadened names that can accommodate future cards.
    """
    domain_clean = (domain or "").strip().lower()
    umbrella = _DOMAIN_TITLES.get(domain_clean, _title_case(domain_clean) or "General")
    umbrella_clean = _sanitize_deck_segment(umbrella)
    proposed = topic or "Session"
    if existing_subtopics:
        canonical = _canonicalize_topic(proposed, existing_subtopics)
    else:
        canonical = _title_case(_strip_session_modifiers(proposed) or proposed)
    topic_clean = _sanitize_deck_segment(canonical)
    return f"{ROOT_DECK}::{umbrella_clean}::{topic_clean}"


def _list_existing_subtopics(client: "AnkiClient") -> dict[str, list[str]]:
    """Return {<Domain Title>: [<topic segment>, ...]} for all existing
    ``Neurosurgery::*::*`` decks. Safe on failure — returns empty mapping.
    """
    out: dict[str, list[str]] = {}
    try:
        for deck in client.list_decks():
            if not deck.startswith(f"{ROOT_DECK}::"):
                continue
            parts = deck.split("::")
            if len(parts) != 3:
                continue
            out.setdefault(parts[1], []).append(parts[2])
    except Exception:  # noqa: BLE001
        return {}
    return out


# ---------------------------------------------------------------------------
# Queue I/O
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def enqueue_candidate(
    *,
    session_ts: str,
    exchange_id: int,
    skill: str,
    topic: str,
    concept: str,
    question: str,
    answer: str,
    correction: str = "",
    correct: int = 1,
    error_type: str = "",
    misconception: str = "",
    root_cause: str = "",
    teaching_approach: str = "",
    depth: int = 1,
    domain: str = "",
    breakthrough: bool = False,
    queue_path: Path = QUEUE_PATH,
) -> bool:
    """Append one candidate to the Anki queue. Non-blocking, best-effort.

    Returns True if the candidate was written, False if suppressed or invalid.
    Never raises — enqueue must never break a live learning session.
    """
    candidate = {
        "enqueued_at": _utc_now_iso(),
        "session_ts": session_ts,
        "exchange_id": int(exchange_id) if exchange_id else 0,
        "skill": skill or "",
        "topic": topic or "",
        "concept": concept or "",
        "question": question or "",
        "answer": answer or "",
        "correction": correction or "",
        "correct": int(correct) if correct is not None else 1,
        "error_type": error_type or "",
        "misconception": misconception or "",
        "root_cause": root_cause or "",
        "teaching_approach": teaching_approach or "",
        "depth": int(depth) if depth else 1,
        "domain": (domain or "general").lower(),
        "breakthrough": bool(breakthrough),
    }
    if not _validate_candidate(candidate):
        return False
    if _should_suppress(candidate):
        return False
    try:
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        with queue_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(candidate, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"[anki_realtime] enqueue failed: {exc}", file=sys.stderr)
        return False
    return True


def _read_queue(queue_path: Path) -> list[dict]:
    if not queue_path.exists():
        return []
    out: list[dict] = []
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _write_queue(queue_path: Path, rows: list[dict]) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        if queue_path.exists():
            queue_path.unlink()
        return
    queue_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )


def _append_flush_log(entry: dict) -> None:
    try:
        FLUSH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with FLUSH_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# KG backlink
# ---------------------------------------------------------------------------


def _backlink_note_ids(mapping: dict[int, int], db_path: Path = DEFAULT_DB_PATH) -> int:
    """Write anki_note_id back onto learning_exchanges rows.

    Returns the number of rows actually updated (exchange IDs that existed).
    Silent on failure.
    """
    if not mapping:
        return 0
    updated = 0
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            with conn:
                for exchange_id, note_id in mapping.items():
                    cur = conn.execute(
                        """UPDATE learning_exchanges
                           SET anki_note_id = ?, anki_queued_at = COALESCE(anki_queued_at, ?)
                           WHERE exchange_id = ?""",
                        (int(note_id), _utc_now_iso(), int(exchange_id)),
                    )
                    updated += cur.rowcount or 0
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"[anki_realtime] KG backlink failed: {exc}", file=sys.stderr)
    return updated


# ---------------------------------------------------------------------------
# Flush
# ---------------------------------------------------------------------------


def _claim_from_card(card: CardDraft, candidate: dict) -> ClaimModel:
    """Build a ClaimModel row for ChromaDB dedup.

    The stored ``claim_text`` is the cloze text with the c-tag braces removed
    — that's the semantic payload the Anki memory novelty filter compares
    against in future sessions.
    """
    import re
    stripped = re.sub(r"\{\{c\d+::([^}]*)\}\}", r"\1", card.cloze_text).strip()
    text = (stripped or card.answer_text or candidate.get("concept") or "")[:420]
    subject = (candidate.get("concept") or "concept")[:200]
    verb = (candidate.get("error_type") or "teaches")[:120]
    obj = (candidate.get("misconception") or candidate.get("topic") or "fact")[:260]
    claim_id = card.claim_id[:16]
    if len(text) < 8:
        text = f"{subject} — {obj}"
    return ClaimModel(
        claim_id=claim_id,
        subject=subject or "concept",
        verb=verb or "teaches",
        object=obj or "fact",
        claim_text=text,
    )


def flush_queue(
    *,
    dry_run: bool = False,
    queue_path: Path = QUEUE_PATH,
    db_path: Path = DEFAULT_DB_PATH,
    anki_url: str = ANKI_URL_DEFAULT,
    gemini_model: str | None = None,
    max_batch: int = 8,
    skip_anki: bool = False,
) -> dict:
    """Drain the queue: synthesize cards, dedup, dispatch to Anki, backlink KG.

    Returns a metrics dict. Safe to call with no queue (returns zero metrics).
    """
    candidates = _read_queue(queue_path)
    metrics = {
        "queue_size": len(candidates),
        "suppressed": 0,
        "synthesized": 0,
        "deduped": 0,
        "created": 0,
        "duplicates": 0,
        "failed": 0,
        "backlinked": 0,
        "decks_touched": [],
        "errors": [],
    }
    if not candidates:
        return metrics

    # Final suppression pass (in case older queue rows predate the filter).
    kept: list[dict] = []
    for c in candidates:
        if _validate_candidate(c) and not _should_suppress(c):
            kept.append(c)
        else:
            metrics["suppressed"] += 1
    if not kept:
        _write_queue(queue_path, [])
        return metrics

    # Group by (domain, topic) so each Gemini batch is coherent. Cap batch size.
    groups: dict[tuple[str, str], list[dict]] = {}
    for c in kept:
        key = ((c.get("domain") or "general").lower(), (c.get("topic") or "").strip())
        groups.setdefault(key, []).append(c)

    from src.anki_sync.novelty import NoveltyStore

    novelty_store: NoveltyStore | None = None
    try:
        if not dry_run and not skip_anki:
            novelty_store = NoveltyStore(
                db_path=CHROMA_PATH,
                collection_name=CHROMA_COLLECTION,
                embedding_model=EMBEDDING_MODEL,
            )
    except Exception as exc:  # noqa: BLE001
        metrics["errors"].append(f"novelty_store_init: {exc}")
        novelty_store = None

    client: AnkiClient | None = None
    if not dry_run and not skip_anki:
        client = AnkiClient(anki_url)
        ok, err = client.check_connection()
        if not ok:
            metrics["errors"].append(f"anki_unavailable: {err}")
            # Leave the queue intact so the next flush retries.
            return metrics
        try:
            client.ensure_models()
        except Exception as exc:  # noqa: BLE001
            metrics["errors"].append(f"ensure_models: {exc}")
            return metrics

    exchange_note_map: dict[int, int] = {}
    deck_set: set[str] = set()
    batched_cards: list[tuple[CardDraft, dict, ClaimModel, str]] = []

    # Snapshot existing Neurosurgery::*::* deck siblings once so every
    # candidate in this flush canonicalizes against the same world. For
    # dry-run / skip-anki paths, we skip the snapshot and fall back to the
    # stateless broadening rule.
    existing_subtopics: dict[str, list[str]] = {}
    if client:
        existing_subtopics = _list_existing_subtopics(client)

    for (domain, topic), group in groups.items():
        # Further slice into max_batch chunks to keep Gemini calls bounded.
        for i in range(0, len(group), max_batch):
            sub = group[i : i + max_batch]
            # Candidate projection for Gemini — strip fields it does not need.
            gemini_input = [
                {
                    "exchange_id": c.get("exchange_id"),
                    "topic": c.get("topic"),
                    "concept": c.get("concept"),
                    "question": c.get("question"),
                    "answer": c.get("answer"),
                    "correction": c.get("correction"),
                    "correct": c.get("correct"),
                    "error_type": c.get("error_type"),
                    "misconception": c.get("misconception"),
                    "root_cause": c.get("root_cause"),
                    "depth": c.get("depth"),
                    "domain": c.get("domain"),
                    "breakthrough": c.get("breakthrough"),
                }
                for c in sub
            ]
            try:
                drafts = synthesize_cards(
                    gemini_input,
                    model=gemini_model or None,
                ) if gemini_model else synthesize_cards(gemini_input)
            except Exception as exc:  # noqa: BLE001
                metrics["errors"].append(f"synthesize_cards: {exc}")
                continue
            metrics["synthesized"] += len(drafts)
            if not drafts:
                continue

            # Each draft gets associated with the first sub-candidate whose
            # concept text is a substring of the cloze or answer — otherwise
            # the first candidate in the sub-batch.
            for draft in drafts:
                owner = _match_owner(draft, sub) or sub[0]
                claim = _claim_from_card(draft, owner)
                domain_raw = (owner.get("domain") or "").strip().lower()
                umbrella_title = _DOMAIN_TITLES.get(domain_raw, _title_case(domain_raw) or "General")
                siblings = existing_subtopics.get(umbrella_title, []) if existing_subtopics else []
                deck_name = resolve_deck_name(
                    owner.get("topic", ""),
                    owner.get("domain", ""),
                    existing_subtopics=siblings,
                )
                deck_set.add(deck_name)
                batched_cards.append((draft, owner, claim, deck_name))

    if dry_run:
        metrics["decks_touched"] = sorted(deck_set)
        metrics["prepared"] = len(batched_cards)
        return metrics

    # Novelty filter (semantic dedup against prior Anki claims). Failure
    # here is non-fatal — we'd rather create a possibly-duplicate card
    # than lose the exchange.
    if novelty_store and batched_cards:
        try:
            all_claims = [c for _d, _o, c, _dn in batched_cards]
            novel_claims, decisions = novelty_store.filter_novel_claims(
                claims=all_claims,
                threshold=NOVELTY_THRESHOLD,
            )
            novel_ids = {c.claim_id for c in novel_claims}
            deduped_batch: list[tuple[CardDraft, dict, ClaimModel, str]] = []
            for draft, owner, claim, deck_name in batched_cards:
                if claim.claim_id in novel_ids:
                    deduped_batch.append((draft, owner, claim, deck_name))
                else:
                    metrics["deduped"] += 1
            batched_cards = deduped_batch
        except Exception as exc:  # noqa: BLE001
            metrics["errors"].append(f"novelty_filter: {exc}")
            novelty_store = None  # skip persist as well

    if not batched_cards:
        _write_queue(queue_path, [])
        metrics["decks_touched"] = sorted(deck_set)
        return metrics

    # Ensure every touched deck exists.
    if client:
        for deck_name in deck_set:
            try:
                client.ensure_deck(deck_name)
            except Exception as exc:  # noqa: BLE001
                metrics["errors"].append(f"ensure_deck({deck_name}): {exc}")

    # Dispatch in parallel.
    persisted_claims: list[ClaimModel] = []
    if client:
        def _dispatch_one(bundle):
            draft, owner, claim, deck_name = bundle
            tags = _tags_for(owner)
            res = client.add_card(draft, deck_name, tags=tags)
            return bundle, res

        with ThreadPoolExecutor(max_workers=4) as pool:
            for bundle, res in pool.map(_dispatch_one, batched_cards):
                draft, owner, claim, deck_name = bundle
                if res.status == "created":
                    metrics["created"] += 1
                    persisted_claims.append(claim)
                    if res.note_id and owner.get("exchange_id"):
                        exchange_note_map[int(owner["exchange_id"])] = int(res.note_id)
                elif res.status == "duplicate":
                    metrics["duplicates"] += 1
                    persisted_claims.append(claim)
                else:
                    metrics["failed"] += 1
                    metrics["errors"].append(
                        f"dispatch({claim.claim_id}): {res.error[:120]}"
                    )

    if novelty_store and persisted_claims:
        try:
            novelty_store.persist_claims(
                persisted_claims,
                metadata={"source": "anki_realtime"},
            )
        except Exception as exc:  # noqa: BLE001
            metrics["errors"].append(f"persist_claims: {exc}")

    if exchange_note_map:
        metrics["backlinked"] = _backlink_note_ids(exchange_note_map, db_path=db_path)

    metrics["decks_touched"] = sorted(deck_set)

    # Clear queue only if we did real work. If every batch failed to
    # synthesize AND nothing was created, retain the queue for retry.
    drained = metrics["created"] + metrics["duplicates"] + metrics["deduped"]
    if drained > 0 or metrics["synthesized"] > 0:
        _write_queue(queue_path, [])
    _append_flush_log({"ts": _utc_now_iso(), **metrics})
    return metrics


def _match_owner(draft: CardDraft, candidates: list[dict]) -> dict | None:
    """Heuristic link from a generated card back to the exchange it came from."""
    haystack = (draft.cloze_text + " " + draft.answer_text).lower()
    best = None
    best_score = 0
    for c in candidates:
        concept = (c.get("concept") or "").lower().strip()
        if not concept:
            continue
        if concept in haystack:
            score = len(concept)
            if score > best_score:
                best = c
                best_score = score
    return best


def _tags_for(candidate: dict) -> list[str]:
    tags: list[str] = ["neuro-agent", "realtime"]
    domain = (candidate.get("domain") or "").lower().strip()
    if domain:
        tags.append(f"domain/{domain}")
    skill = (candidate.get("skill") or "").lower().strip()
    if skill:
        tags.append(f"skill/{skill}")
    err = (candidate.get("error_type") or "").lower().strip()
    if err:
        tags.append(f"error_type/{err}")
    if candidate.get("breakthrough"):
        tags.append("breakthrough")
    session_ts = (candidate.get("session_ts") or "")[:10]
    if session_ts:
        tags.append(f"session/{session_ts}")
    exchange_id = candidate.get("exchange_id")
    if exchange_id:
        tags.append(f"exchange/{exchange_id}")
    return tags


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Real-time Anki queue flush")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_flush = sub.add_parser("flush", help="Flush the pending Anki queue")
    p_flush.add_argument("--dry-run", action="store_true")
    p_flush.add_argument("--skip-anki", action="store_true", help="Skip AnkiConnect + novelty store (synthesis only)")
    p_flush.add_argument("--queue-path", default=str(QUEUE_PATH))
    p_flush.add_argument("--anki-url", default=ANKI_URL_DEFAULT)
    p_flush.add_argument("--max-batch", type=int, default=8)
    p_flush.add_argument("--gemini-model", default=None)

    p_status = sub.add_parser("status", help="Show pending queue size")
    p_status.add_argument("--queue-path", default=str(QUEUE_PATH))

    p_enq = sub.add_parser("enqueue", help="(Manual) enqueue a single candidate; primarily for tests")
    p_enq.add_argument("--session-ts", required=True)
    p_enq.add_argument("--exchange-id", type=int, required=True)
    p_enq.add_argument("--skill", default="manual")
    p_enq.add_argument("--topic", required=True)
    p_enq.add_argument("--concept", required=True)
    p_enq.add_argument("--question", required=True)
    p_enq.add_argument("--answer", required=True)
    p_enq.add_argument("--correction", default="")
    p_enq.add_argument("--correct", type=int, default=1)
    p_enq.add_argument("--error-type", default="", dest="error_type")
    p_enq.add_argument("--misconception", default="")
    p_enq.add_argument("--depth", type=int, default=2)
    p_enq.add_argument("--domain", default="general")
    p_enq.add_argument("--breakthrough", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "status":
        rows = _read_queue(Path(args.queue_path))
        print(json.dumps({"pending": len(rows), "queue_path": str(args.queue_path)}, indent=2))
        return 0

    if args.cmd == "enqueue":
        ok = enqueue_candidate(
            session_ts=args.session_ts,
            exchange_id=args.exchange_id,
            skill=args.skill,
            topic=args.topic,
            concept=args.concept,
            question=args.question,
            answer=args.answer,
            correction=args.correction,
            correct=args.correct,
            error_type=args.error_type,
            misconception=args.misconception,
            depth=args.depth,
            domain=args.domain,
            breakthrough=args.breakthrough,
        )
        print(json.dumps({"ok": ok}, indent=2))
        return 0

    if args.cmd == "flush":
        metrics = flush_queue(
            dry_run=args.dry_run,
            skip_anki=args.skip_anki,
            queue_path=Path(args.queue_path),
            anki_url=args.anki_url,
            max_batch=args.max_batch,
            gemini_model=args.gemini_model,
        )
        print(json.dumps(metrics, indent=2))
        return 0 if not metrics.get("errors") or metrics.get("created", 0) > 0 else 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
