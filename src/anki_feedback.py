"""Bounded Anki review-history overlay for Neuro-Agent startup recall.

Live Anki is the source of truth for review metadata. This module converts
that metadata into a compact advisory profile for teaching design; it does not
write learner state and does not override `study_memory.py` claim_state.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ANKI_URL = "http://localhost:8765"
CHROMADB_PATH = "data/anki_vector_cache.db"
COLLECTION_NAME = "anki_claim_memory"

RECENT_REVIEW_DAYS = 7
RECENT_AGAIN_DAYS = 3
FRESH_NEW_DAYS = 3
STALE_NEW_DAYS = 7
MATURE_INTERVAL_DAYS = 60
MATURE_LAST_SEEN_DAYS = 90
SLOW_RESPONSE_MS = 15_000
NORMAL_PROFILE_CHAR_CAP = 1_500
MAX_ATOMIC_FOCUS = 5
MAX_ATOMIC_SCAFFOLDS = 3
MAX_ATOMIC_PRIMES = 3
MAX_ATOMS_PER_CONCEPT = 2
SEMANTIC_DIRECT_DISTANCE_MAX = 0.55
SEMANTIC_TOP_RANK_DISTANCE_MAX = 0.80
SEMANTIC_ANCHORED_DISTANCE_MAX = 1.05
SEMANTIC_TOP_RANK_LIMIT = 8

CATEGORY_ORDER = {
    "leech": 0,
    "active_lapse": 1,
    "shaky_success": 2,
    "stale_new": 3,
    "mature_stale": 4,
    "transition_new": 5,
    "recent_success": 6,
    "fresh_new": 7,
    "stable": 8,
}


@dataclass(frozen=True)
class CardMapping:
    topic: str
    concept: str
    inventory_concept_id: str
    mapping_quality: str
    mapping_source: str
    source_workflow: str


@dataclass(frozen=True)
class CardLifecycle:
    category: str
    subtype: str
    reps: int
    lapses: int
    interval_days: int
    previous_interval_days: int
    response_time_s: float
    created_days_ago: float | None
    last_seen_days_ago: float | None
    last_button: str


def invoke(action: str, timeout: float = 3.0, **params: Any) -> Any:
    payload = {"action": action, "version": 6, "params": params}
    req = urllib.request.Request(
        ANKI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res = json.loads(response.read().decode("utf-8"))
            if res.get("error"):
                raise RuntimeError(str(res["error"]))
            return res.get("result")
    except Exception as exc:  # noqa: BLE001 - connection status is surfaced compactly.
        raise ConnectionError(f"Cannot connect to AnkiConnect: {exc}") from exc


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _slug(text: str) -> str:
    text = html.unescape(str(text or "")).lower()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _display_from_slug(text: str) -> str:
    return re.sub(r"[-_]+", " ", str(text or "")).strip().title()


def _strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", str(text or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _safe_float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _age_days(timestamp_ms: int | float | None, now_ms: int) -> float | None:
    if not timestamp_ms:
        return None
    try:
        return max(0.0, (now_ms - float(timestamp_ms)) / 86_400_000)
    except Exception:
        return None


def _creation_days(card: dict[str, Any], now_ms: int) -> float | None:
    for key in ("cardId", "card_id", "note"):
        value = _safe_int(card.get(key), 0)
        if value > 1_000_000_000_000:
            return _age_days(value, now_ms)
    return None


def _review_timestamp(review: dict[str, Any]) -> int:
    return _safe_int(review.get("id"), 0)


def _latest_review(reviews: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not reviews:
        return None
    return max(reviews, key=_review_timestamp)


def _button_name(ease: int) -> str:
    return {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}.get(ease, "")


def _is_new_card(card: dict[str, Any], reviews: list[dict[str, Any]]) -> bool:
    card_type = _safe_int(card.get("type"), -1)
    queue = _safe_int(card.get("queue"), -99)
    reps = _safe_int(card.get("reps"), 0)
    return card_type == 0 or queue == 0 or (not reviews and reps == 0)


def _is_relearning_after_lapse(card: dict[str, Any]) -> bool:
    card_type = _safe_int(card.get("type"), -1)
    queue = _safe_int(card.get("queue"), -99)
    lapses = _safe_int(card.get("lapses"), 0)
    return lapses > 0 and (card_type == 3 or queue in (1, 3))


def _correct_streak(reviews: list[dict[str, Any]]) -> int:
    streak = 0
    for review in sorted(reviews, key=_review_timestamp, reverse=True):
        ease = _safe_int(review.get("ease"), 0)
        if ease in (2, 3, 4):
            streak += 1
        else:
            break
    return streak


def _tags(card: dict[str, Any]) -> list[str]:
    raw = card.get("tags", [])
    if isinstance(raw, str):
        return [tag for tag in re.split(r"[\s,]+", raw) if tag]
    if isinstance(raw, list):
        return [str(tag) for tag in raw if str(tag)]
    return []


def classify_card_lifecycle(
    card: dict[str, Any],
    reviews: list[dict[str, Any]] | None = None,
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Classify one live Anki card into the startup-recall lifecycle taxonomy."""
    reviews = reviews or []
    now_ms = now_ms if now_ms is not None else _now_ms()
    latest = _latest_review(reviews)
    latest_age = _age_days(_review_timestamp(latest), now_ms) if latest else None
    ease = _safe_int(latest.get("ease"), 0) if latest else 0
    response_ms = _safe_int(latest.get("time"), 0) if latest else 0
    interval = _safe_int(card.get("interval"), _safe_int(card.get("ivl"), 0))
    if latest:
        interval = max(interval, _safe_int(latest.get("ivl"), 0))
    previous_interval = _safe_int(latest.get("lastIvl"), 0) if latest else 0
    reps = _safe_int(card.get("reps"), len(reviews))
    lapses = _safe_int(card.get("lapses"), 0)
    created_days = _creation_days(card, now_ms)
    lower_tags = {tag.lower() for tag in _tags(card)}
    has_leech_tag = any("leech" in tag for tag in lower_tags)
    recent_again = bool(ease == 1 and latest_age is not None and latest_age <= RECENT_AGAIN_DAYS)

    subtype = ""
    if lapses >= 4 or has_leech_tag:
        category = "leech"
        subtype = "chronic_leech" if lapses >= 4 else "tagged_leech"
    elif recent_again or _is_relearning_after_lapse(card):
        category = "active_lapse"
        subtype = "mature_lapse" if previous_interval >= MATURE_INTERVAL_DAYS else "recent_again"
    elif _is_new_card(card, reviews):
        if created_days is not None and created_days < FRESH_NEW_DAYS:
            category = "fresh_new"
        elif created_days is not None and created_days > STALE_NEW_DAYS:
            category = "stale_new"
        else:
            category = "transition_new"
    elif ease in (2, 3, 4):
        streak = _correct_streak(reviews)
        if ease == 2 or response_ms >= SLOW_RESPONSE_MS or (lapses > 0 and streak <= 1):
            category = "shaky_success"
            subtype = "hard_or_slow"
        elif latest_age is not None and latest_age <= RECENT_REVIEW_DAYS:
            category = "recent_success"
        elif interval >= MATURE_INTERVAL_DAYS and latest_age is not None and latest_age >= MATURE_LAST_SEEN_DAYS:
            category = "mature_stale"
        else:
            category = "stable"
    elif interval >= MATURE_INTERVAL_DAYS and latest_age is not None and latest_age >= MATURE_LAST_SEEN_DAYS:
        category = "mature_stale"
    else:
        category = "stable"

    lifecycle = CardLifecycle(
        category=category,
        subtype=subtype,
        reps=reps,
        lapses=lapses,
        interval_days=interval,
        previous_interval_days=previous_interval,
        response_time_s=round(response_ms / 1000.0, 1),
        created_days_ago=round(created_days, 1) if created_days is not None else None,
        last_seen_days_ago=round(latest_age, 1) if latest_age is not None else None,
        last_button=_button_name(ease),
    )
    return {
        "category": lifecycle.category,
        "subtype": lifecycle.subtype,
        "reps": lifecycle.reps,
        "lapses": lifecycle.lapses,
        "interval_days": lifecycle.interval_days,
        "previous_interval_days": lifecycle.previous_interval_days,
        "response_time_s": lifecycle.response_time_s,
        "created_days_ago": lifecycle.created_days_ago,
        "last_seen_days_ago": lifecycle.last_seen_days_ago,
        "last_button": lifecycle.last_button,
    }


def _load_chroma_collection() -> Any | None:
    # Return path to the custom SQLite vector cache DB
    return CHROMADB_PATH


def _chroma_metadata_for_card(card: dict[str, Any], chroma_collection: Any | None) -> dict[str, Any]:
    if chroma_collection is None:
        return {}

    # If it is the pre-fetched cache dictionary
    if isinstance(chroma_collection, dict):
        note_id = card.get("note")
        card_id = card.get("cardId")
        candidates = []
        if note_id:
            candidates.append(("note_id", _safe_int(note_id)))
            candidates.append(("claim_id", str(note_id)[-12:]))
        if card_id:
            candidates.append(("card_id", _safe_int(card_id)))

        for key, value in candidates:
            if (key, value) in chroma_collection:
                return dict(chroma_collection[(key, value)] or {})
        return {}

    # If it is a string database path, we do not query single-card metadata on the fly
    if isinstance(chroma_collection, str):
        return {}

    # Otherwise, it's a mocked database object in tests; run get() on it directly
    note_id = card.get("note")
    card_id = card.get("cardId")
    candidates = []
    if note_id:
        candidates.append(("note_id", _safe_int(note_id)))
        candidates.append(("claim_id", str(note_id)[-12:]))
    if card_id:
        candidates.append(("card_id", _safe_int(card_id)))

    for key, value in candidates:
        try:
            res = chroma_collection.get(where={key: value})
            metadatas = res.get("metadatas") if isinstance(res, dict) else []
            if metadatas:
                return dict(metadatas[0] or {})
        except Exception:
            continue
    return {}


def _resolve_source_workflow(tags: list[str], deck_name: str) -> str:
    lower = {tag.lower() for tag in tags}
    for value in ("brain-dump", "study-review", "quick-answer", "consult", "intraoperative-guide"):
        if value in lower:
            return value
    if "brain dumps" in deck_name.lower():
        return "brain-dump"
    return "live_anki"


def _prefetch_chroma_metadata(cards: list[dict[str, Any]], chroma_collection: Any | None) -> dict[tuple[str, Any], dict[str, Any]]:
    # If the collection is a mocked object (like in tests)
    if chroma_collection is not None and not isinstance(chroma_collection, str):
        note_ids = []
        claim_ids = []
        card_ids = []
        for card in cards:
            note_id = card.get("note")
            card_id = card.get("cardId")
            if note_id:
                note_ids.append(_safe_int(note_id))
                claim_ids.append(str(note_id)[-12:])
            if card_id:
                card_ids.append(_safe_int(card_id))
        meta_map = {}
        for nid in note_ids:
            try:
                res = chroma_collection.get(where={"note_id": nid})
                metadatas = res.get("metadatas") if isinstance(res, dict) else []
                if metadatas:
                    meta_map[("note_id", nid)] = metadatas[0]
            except Exception:
                pass
        for cid in card_ids:
            try:
                res = chroma_collection.get(where={"card_id": cid})
                metadatas = res.get("metadatas") if isinstance(res, dict) else []
                if metadatas:
                    meta_map[("card_id", cid)] = metadatas[0]
            except Exception:
                pass
        return meta_map

    db_path = chroma_collection or CHROMADB_PATH
    if not cards or not Path(db_path).exists():
        return {}

    card_ids = []
    note_ids = []
    for card in cards:
        cid = card.get("cardId")
        nid = card.get("note")
        if cid:
            card_ids.append(int(cid))
        if nid:
            note_ids.append(int(nid))

    if not card_ids and not note_ids:
        return {}

    meta_map = {}
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        where_clauses = []
        params = []
        if card_ids:
            placeholders_cid = ",".join("?" for _ in card_ids)
            where_clauses.append(f"card_id IN ({placeholders_cid})")
            params.extend(card_ids)
        if note_ids:
            placeholders_nid = ",".join("?" for _ in note_ids)
            where_clauses.append(f"json_extract(metadata, '$.note_id') IN ({placeholders_nid})")
            params.extend(note_ids)
            
        sql = "SELECT card_id, metadata FROM card_vectors WHERE " + " OR ".join(where_clauses)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        for cid, meta_str in rows:
            meta = json.loads(meta_str)
            if cid is not None:
                meta_map[("card_id", int(cid))] = meta
            if "note_id" in meta:
                meta_map[("note_id", int(meta["note_id"]))] = meta
                meta_map[("claim_id", str(meta["note_id"])[-12:])] = meta
        conn.close()
    except Exception:
        pass
    return meta_map


def _resolve_card_mapping(card_detail: dict[str, Any], chroma_collection: Any | None = None) -> CardMapping:
    note_id = card_detail.get("note")
    deck_name = str(card_detail.get("deckName", ""))
    deck_parts = [part for part in deck_name.split("::") if part]
    tags = _tags(card_detail)

    topic = "General"
    concept = "General"
    inventory_concept_id = ""
    mapping_source = "fallback_deck"
    mapping_quality = "low"

    if len(deck_parts) >= 2:
        topic = deck_parts[1]
    if len(deck_parts) >= 3:
        concept = deck_parts[-1]

    meta = _chroma_metadata_for_card(card_detail, chroma_collection)
    if meta:
        chroma_topic = str(meta.get("topic", "") or "")
        chroma_concept = str(meta.get("concept", "") or "")
        if chroma_topic and chroma_topic != "live_anki":
            topic = chroma_topic
            mapping_source = "chroma"
            mapping_quality = "medium"
        if chroma_concept:
            concept = chroma_concept
            mapping_source = "chroma"
            mapping_quality = "medium"
        if not chroma_concept and meta.get("claim_id") == str(note_id)[-12:]:
            mapping_quality = max(mapping_quality, "low")

    for tag in tags:
        lower = tag.lower()
        if lower.startswith("topic/"):
            topic = _display_from_slug(tag.split("/", 1)[1])
            mapping_source = "explicit_tag"
            mapping_quality = "high"
        elif lower.startswith("domain/") and mapping_source == "fallback_deck":
            topic = _display_from_slug(tag.split("/", 1)[1])
        elif lower.startswith("concept/"):
            concept = _display_from_slug(tag.split("/", 1)[1])
            mapping_source = "explicit_tag"
            mapping_quality = "high"
        elif lower.startswith("inv/"):
            inventory_concept_id = tag.split("/", 1)[1].strip()
            mapping_source = "explicit_tag"
            mapping_quality = "high"

    source_workflow = _resolve_source_workflow(tags, deck_name)
    return CardMapping(
        topic=topic or "General",
        concept=concept or topic or "General",
        inventory_concept_id=inventory_concept_id,
        mapping_quality=mapping_quality,
        mapping_source=mapping_source,
        source_workflow=source_workflow,
    )


def _resolve_card_concept_and_topic(card_detail: dict[str, Any], chroma_collection: Any) -> tuple[str, str]:
    """Compatibility wrapper for older tests and ad hoc callers."""
    mapping = _resolve_card_mapping(card_detail, chroma_collection)
    return mapping.topic, mapping.concept


def _find_cards(query: str) -> list[int]:
    try:
        result = invoke("findCards", query=query)
    except ConnectionError:
        raise
    except Exception:
        return []
    if not isinstance(result, list):
        return []
    return [_safe_int(card_id) for card_id in result if _safe_int(card_id)]


def _find_cards_multi(queries: list[str]) -> list[list[int]]:
    if not queries:
        return []
    actions = [{"action": "findCards", "params": {"query": q}} for q in queries]
    try:
        results = invoke("multi", actions=actions)
    except ConnectionError:
        raise
    except Exception:
        return [[] for _ in queries]
    if not isinstance(results, list):
        return [[] for _ in queries]
    out = []
    for res in results:
        if isinstance(res, list):
            out.append([_safe_int(cid) for cid in res if _safe_int(cid)])
        else:
            out.append([])
    return out


def _cards_info(card_ids: list[int]) -> list[dict[str, Any]]:
    if not card_ids:
        return []
    try:
        result = invoke("cardsInfo", cards=card_ids)
    except ConnectionError:
        raise
    except Exception:
        return []
    if isinstance(result, list):
        return [card for card in result if isinstance(card, dict)]
    return []


def _reviews_for_cards(card_ids: list[int]) -> dict[str, list[dict[str, Any]]]:
    if not card_ids:
        return {}
    try:
        result = invoke("getReviewsOfCards", cards=card_ids)
    except ConnectionError:
        raise
    except Exception:
        return {}
    if not isinstance(result, dict):
        return {}
    return {
        str(key): [review for review in value if isinstance(review, dict)]
        for key, value in result.items()
        if isinstance(value, list)
    }


def _profile_terms(
    topic: str,
    resolved_topic: str,
    doc_path: str,
    context: str,
    planning_concepts: list[str] | None,
) -> list[str]:
    raw_terms = [topic, resolved_topic, Path(doc_path).stem if doc_path else "", context]
    raw_terms.extend(planning_concepts or [])
    seen: set[str] = set()
    terms: list[str] = []
    for term in raw_terms:
        cleaned = re.sub(r"[-_]+", " ", str(term or "")).strip()
        slug = _slug(cleaned)
        if cleaned and slug and slug not in seen:
            seen.add(slug)
            terms.append(cleaned)
    return terms[:12]


def _term_slugs(terms: list[str], *, include_tokens: bool = True) -> set[str]:
    stopwords = {
        "and",
        "the",
        "for",
        "with",
        "management",
        "critical",
        "care",
        "review",
        "topic",
        "general",
        "emergency",
        "emergencies",
        "acute",
        "chronic",
        "syndrome",
        "syndromes",
        "algorithm",
        "algorithms",
        "protocol",
        "protocols",
        "approach",
        "approaches",
    }
    slugs: set[str] = set()
    for term in terms:
        slug = _slug(term)
        if slug:
            slugs.add(slug)
        if include_tokens:
            for token in slug.split("-"):
                if len(token) >= 3 and token not in stopwords:
                    slugs.add(token)
    return slugs


def _explicit_search_queries(terms: list[str]) -> list[str]:
    queries: list[str] = []
    for term in terms[:6]:
        slug = _slug(term)
        if not slug:
            continue
        queries.append(f"deck:Neurosurgery* tag:topic/{slug}")
        queries.append(f"deck:Neurosurgery* tag:concept/{slug}")
        queries.append(f'deck:Neurosurgery* "{term}"')
    return queries


def _semantic_candidate_hits(chroma_collection: Any | None, terms: list[str], *, limit: int = 60) -> dict[int, dict[str, Any]]:
    # If the collection is a mocked object (like in tests)
    if chroma_collection is not None and not isinstance(chroma_collection, str):
        query = " ".join(terms[:8])
        try:
            result = chroma_collection.query(
                query_texts=[query],
                n_results=limit,
                include=["metadatas", "distances"],
            )
        except Exception:
            return {}
        metadatas = (result.get("metadatas") or [[]])[0] if isinstance(result, dict) else []
        distances = (result.get("distances") or [[]])[0] if isinstance(result, dict) else []
        hits = {}
        def remember(card_id: int, hit: dict[str, Any]) -> None:
            if not card_id:
                return
            existing = hits.get(card_id)
            existing_distance = _safe_float_or_none(existing.get("distance")) if existing else None
            new_distance = _safe_float_or_none(hit.get("distance"))
            if (
                existing is None
                or (new_distance is not None and (existing_distance is None or new_distance < existing_distance))
                or _safe_int(hit.get("rank"), 999) < _safe_int(existing.get("rank"), 999)
            ):
                hits[card_id] = hit
        for rank, meta in enumerate(metadatas, start=1):
            if not isinstance(meta, dict):
                continue
            distance = _safe_float_or_none(distances[rank - 1] if rank - 1 < len(distances) else None)
            hit = {
                "rank": rank,
                "distance": round(distance, 4) if distance is not None else None,
            }
            card_id = _safe_int(meta.get("card_id"), 0)
            if card_id:
                remember(card_id, hit)
        return hits

    db_path = chroma_collection or CHROMADB_PATH
    if not terms or not Path(db_path).exists():
        return {}
    query = " ".join(terms[:8])
    hits: dict[int, dict[str, Any]] = {}
    note_hits: dict[int, dict[str, Any]] = {}

    import sqlite3
    import numpy as np
    try:
        # 1. Check or load query embedding from cache
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS query_embeddings (
                query TEXT PRIMARY KEY,
                vector BLOB NOT NULL,
                timestamp REAL NOT NULL
            );
        """)
        conn.commit()

        cursor.execute("SELECT vector FROM query_embeddings WHERE query = ?", (query,))
        row = cursor.fetchone()
        if row:
            q_emb = list(np.frombuffer(row[0], dtype=np.float32))
        else:
            from fastembed import TextEmbedding  # type: ignore
            embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5", cache_dir="data/Sessions/fastembed_cache")
            q_emb = list(embedder.embed([query]))[0]
            vec_bytes = np.array(q_emb, dtype=np.float32).tobytes()
            cursor.execute("""
                INSERT OR REPLACE INTO query_embeddings (query, vector, timestamp)
                VALUES (?, ?, ?);
            """, (query, vec_bytes, time.time()))
            conn.commit()

        q_vec = np.array(q_emb, dtype=np.float32)

        # 2. Fetch vectors and metadata from SQLite
        cursor.execute("SELECT card_id, vector, metadata FROM card_vectors;")
        rows = cursor.fetchall()
        conn.close()

        cids = []
        vectors = []
        metas = []
        for cid, vec_bytes, meta_str in rows:
            cids.append(int(cid))
            vectors.append(np.frombuffer(vec_bytes, dtype=np.float32))
            metas.append(json.loads(meta_str))

        # 3. Compute exact cosine similarity via dot product (vectors are already normalized)
        vectors_matrix = np.array(vectors)
        scores = np.dot(vectors_matrix, q_vec)

        # 4. Sort and select top hits
        top_indices = np.argsort(scores)[::-1][:limit]

        def remember(card_id: int, hit: dict[str, Any]) -> None:
            if not card_id:
                return
            existing = hits.get(card_id)
            existing_distance = _safe_float_or_none(existing.get("distance")) if existing else None
            new_distance = _safe_float_or_none(hit.get("distance"))
            if (
                existing is None
                or (new_distance is not None and (existing_distance is None or new_distance < existing_distance))
                or _safe_int(hit.get("rank"), 999) < _safe_int(existing.get("rank"), 999)
            ):
                hits[card_id] = hit

        for rank, idx in enumerate(top_indices, start=1):
            cid = cids[idx]
            meta = metas[idx]
            score = float(scores[idx])
            # Cosine similarity to cosine distance (1 - similarity)
            distance = float(max(0.0, min(1.0, 1.0 - score)))
            hit = {
                "rank": rank,
                "distance": round(distance, 4),
            }
            remember(cid, hit)
            note_id = _safe_int(meta.get("note_id"), 0)
            if note_id:
                note_hits[note_id] = hit

        if note_hits:
            note_id_list = sorted(note_hits.keys())
            for idx in range(0, len(note_id_list), 40):
                batch_ids = note_id_list[idx : idx + 40]
                or_query = " OR ".join(f"nid:{nid}" for nid in batch_ids)
                card_ids = _find_cards(or_query)
                if card_ids:
                    cards_info = _cards_info(card_ids)
                    for card in cards_info:
                           card_id = _safe_int(card.get("cardId"))
                           nid = _safe_int(card.get("note"))
                           if nid in note_hits:
                               remember(card_id, note_hits[nid])
    except Exception:
        pass
    return hits


def _semantic_candidate_ids(chroma_collection: Any | None, terms: list[str], *, limit: int = 60) -> set[int]:
    """Compatibility helper for older tests and ad hoc callers."""
    return set(_semantic_candidate_hits(chroma_collection, terms, limit=limit))


def _scope_match_strength(card: dict[str, Any], mapping: CardMapping, terms: list[str]) -> int:
    if not terms:
        return 0
    haystack = " ".join(
        [
            str(card.get("deckName", "")),
            " ".join(_tags(card)),
            mapping.topic,
            mapping.concept,
            _strip_html(card.get("question", "")),
        ]
    ).lower()
    term_slugs = _term_slugs(terms)
    haystack_slug = _slug(haystack)
    haystack_tokens = set(haystack_slug.split("-"))
    best = 0
    for slug in term_slugs:
        if not slug:
            continue
        if "-" in slug:
            if slug in haystack_slug:
                best = max(best, 2)
        elif slug in haystack_tokens:
            best = max(best, 1)
    return best


def _matches_scope(card: dict[str, Any], mapping: CardMapping, terms: list[str]) -> bool:
    return _scope_match_strength(card, mapping, terms) > 0


def _semantic_hit_in_scope(
    card: dict[str, Any],
    mapping: CardMapping,
    terms: list[str],
    hit: dict[str, Any] | None,
) -> bool:
    if not hit:
        return False
    distance = _safe_float_or_none(hit.get("distance"))
    rank = _safe_int(hit.get("rank"), 999)
    anchored = _scope_match_strength(card, mapping, terms) > 0
    if distance is None:
        return anchored
    if distance <= SEMANTIC_DIRECT_DISTANCE_MAX:
        return True
    if rank <= SEMANTIC_TOP_RANK_LIMIT and distance <= SEMANTIC_TOP_RANK_DISTANCE_MAX:
        return True
    return anchored and distance <= SEMANTIC_ANCHORED_DISTANCE_MAX


def _is_service_local(card: dict[str, Any]) -> bool:
    deck = str(card.get("deckName", "")).lower()
    lower_tags = {tag.lower() for tag in _tags(card)}
    if "service" in deck and "brain dumps" not in deck:
        return True
    return any(
        tag.startswith(("service/", "site/"))
        or tag in {"service-learning", "local-convention", "site-local"}
        for tag in lower_tags
    )


def _is_brain_dump(card: dict[str, Any], mapping: CardMapping) -> bool:
    deck = str(card.get("deckName", "")).lower()
    lower_tags = {tag.lower() for tag in _tags(card)}
    return "brain dumps" in deck or mapping.source_workflow == "brain-dump" or "brain-dump" in lower_tags


def _allowed_by_profile(card: dict[str, Any], mapping: CardMapping, profile: str) -> bool:
    normalized = profile or "memory"
    if normalized == "service":
        return _is_service_local(card)
    if _is_service_local(card):
        return False
    if normalized == "doc" and _is_brain_dump(card, mapping):
        return False
    return True


def _compact_metric(value: Any) -> Any:
    if value is None or value == 0 or value == "":
        return None
    return value


def _clean_cloze_text(text: str) -> str:
    return re.sub(r"\{\{c\d+::([^:}]+)(?::[^}]+)?\}\}", r"[\1]", text)


def _field_text(card: dict[str, Any], field_name: str) -> str:
    fields = card.get("fields")
    if not isinstance(fields, dict):
        return ""
    value = fields.get(field_name, "")
    if isinstance(value, dict):
        return _strip_html(str(value.get("value", "")))
    return _strip_html(str(value or ""))


def _trim_fact(text: str, *, limit: int = 128) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _card_fact_snippet(card: dict[str, Any]) -> str:
    cloze_text = _field_text(card, "Text")
    if cloze_text:
        return _trim_fact(_clean_cloze_text(cloze_text))

    front = _field_text(card, "Front")
    back = _field_text(card, "Back")
    if front and back:
        return _trim_fact(f"{front} -> {back}")

    question = _clean_cloze_text(_strip_html(str(card.get("question", ""))))
    answer = _clean_cloze_text(_strip_html(str(card.get("answer", ""))))
    if question and answer:
        answer_tail = answer
        if answer_tail.lower().startswith(question.lower()):
            answer_tail = answer_tail[len(question):].strip(" :;-")
        if answer_tail:
            return _trim_fact(f"{question} -> {answer_tail}")
    if question:
        return _trim_fact(question)
    return _trim_fact(answer or "Anki card")


def _card_metrics(row: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key, dest in (
        ("reps", "reps"),
        ("lapses", "lapses"),
        ("interval_days", "ivl"),
        ("previous_interval_days", "prev_ivl"),
    ):
        value = row.get(key)
        if value is not None and value != 0 and value != "":
            metrics[dest] = _safe_int(value)
    rt = row.get("response_time_s")
    if rt is not None and rt != 0.0:
        metrics["rt_s"] = _safe_float(rt)
    if row.get("last_button"):
        metrics["last"] = row["last_button"]
    age = row.get("created_days_ago")
    if row.get("category") in {"fresh_new", "transition_new", "stale_new"} and age is not None:
        metrics["age_d"] = _safe_float(age)
    return metrics


def _atomic_entry(row: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "fact": _card_fact_snippet(row),
        "state": row.get("category"),
        "concept": row.get("concept"),
    }
    subtype = row.get("subtype")
    if subtype:
        entry["subtype"] = subtype
    metrics = _card_metrics(row)
    if metrics:
        entry["metrics"] = metrics
    if row.get("mapping_quality") and row.get("mapping_quality") != "high":
        entry["map"] = row["mapping_quality"]
    return entry


def _directive_for_category(category: str) -> str:
    return {
        "leech": "deconstruct concept and consider card redesign",
        "active_lapse": "prioritize Socratic repair",
        "shaky_success": "changed-frame check, no basic recall",
        "stale_new": "light recognition prime",
        "mature_stale": "one maintenance check if central",
        "recent_success": "use as transfer scaffold",
        "stable": "macro context only",
        "fresh_new": "avoid direct quiz",
        "transition_new": "use only as premise",
    }.get(category, "advisory only")


def _directive_fact_fragment(value: object) -> str:
    return str(value or "").strip().rstrip(".;:")


def _build_teaching_directives(
    targets: list[dict[str, Any]],
    scaffolds: list[dict[str, Any]],
    primes: list[dict[str, Any]],
    avoid: dict[str, Any],
) -> list[str]:
    directives: list[str] = []
    if targets:
        facts = "; ".join(_directive_fact_fragment(item.get("fact")) for item in targets[:2])
        directives.append(f"After SQLite gaps, use these exact Anki facts for changed-frame probes: {facts}.")
    if scaffolds:
        facts = "; ".join(_directive_fact_fragment(item.get("fact")) for item in scaffolds[:1])
        directives.append(f"Use stable Anki fact as a transfer premise: {facts}.")
    if primes:
        facts = "; ".join(_directive_fact_fragment(item.get("fact")) for item in primes[:1])
        directives.append(f"Lightly prime neglected new Anki fact: {facts}.")
    if avoid.get("count", 0):
        directives.append("Do not directly quiz fresh or transition Anki cards; let Anki handle initial consolidation.")
    if not directives:
        directives.append("No Anki anomaly should change the SQLite-led teaching plan.")
    return directives[:5]


def _enforce_cap(profile: dict[str, Any], max_chars: int, keep_full_rollup: bool = False) -> dict[str, Any]:
    full_rollup = profile.pop("full_concept_rollup", None)
    res = _enforce_cap_inner(profile, max_chars)
    if keep_full_rollup and full_rollup is not None:
        res["full_concept_rollup"] = full_rollup
    return res


def _enforce_cap_inner(profile: dict[str, Any], max_chars: int) -> dict[str, Any]:
    if len(_json_dumps(profile)) <= max_chars:
        return profile

    profile = dict(profile)

    # Pass 2: reduce non-primary surfaces first, preserving atomic focus metrics.
    profile["atomic_scaffolds"] = profile.get("atomic_scaffolds", [])[:2]
    profile["atomic_primes"] = profile.get("atomic_primes", [])[:2]
    profile["concept_rollup"] = profile.get("concept_rollup", [])[:3]

    avoid = dict(profile.get("avoid_direct_quiz", {}) or {})
    avoid["facts"] = avoid.get("facts", [])[:1]
    profile["avoid_direct_quiz"] = avoid
    profile["teaching_directives"] = profile.get("teaching_directives", [])[:3]

    if len(_json_dumps(profile)) <= max_chars:
        return profile

    # Pass 3: reduce atomic lists but keep each selected fact and its metrics.
    profile["atomic_focus"] = profile.get("atomic_focus", [])[:4]
    profile["atomic_scaffolds"] = profile.get("atomic_scaffolds", [])[:1]
    profile["atomic_primes"] = profile.get("atomic_primes", [])[:1]

    if len(_json_dumps(profile)) <= max_chars:
        return profile

    # Pass 4: compact concept_rollup to single-line summaries instead of dropping
    profile["concept_rollup"] = [
        f"{item['concept']}:{item['worst']}({item['cards']})"
        if isinstance(item, dict) and "concept" in item else str(item)
        for item in profile.get("concept_rollup", [])
    ]
    profile["atomic_focus"] = profile.get("atomic_focus", [])[:3]
    profile["atomic_primes"] = profile.get("atomic_primes", [])[:1]
    profile["teaching_directives"] = profile.get("teaching_directives", [])[:1]

    if len(_json_dumps(profile)) <= max_chars:
        return profile

    # Pass 4.5: empty concept_rollup if it still doesn't fit
    profile["concept_rollup"] = []

    if len(_json_dumps(profile)) <= max_chars:
        return profile

    # Pass 5: final fallback keeps exact facts and state; metrics are last to go.
    for key in ("atomic_focus", "atomic_scaffolds"):
        profile[key] = [
            {
                "fact": item.get("fact"),
                "state": item.get("state"),
                "concept": item.get("concept"),
            }
            for item in profile.get(key, [])[:2]
        ]

    return profile


def _row_priority(row: dict[str, Any]) -> tuple[int, int, int, float, str]:
    return (
        CATEGORY_ORDER.get(str(row.get("category")), 99),
        -_safe_int(row.get("lapses")),
        -_safe_int(row.get("previous_interval_days")),
        -_safe_float(row.get("response_time_s")),
        str(row.get("fact", "")),
    )


def _select_atomic_rows(
    rows: list[dict[str, Any]],
    categories: set[str],
    *,
    limit: int,
    max_per_concept: int = MAX_ATOMS_PER_CONCEPT,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    per_concept: Counter[str] = Counter()
    for row in sorted(rows, key=_row_priority):
        if row.get("category") not in categories:
            continue
        concept = str(row.get("concept") or "")
        if per_concept[concept] >= max_per_concept:
            continue
        selected.append(_atomic_entry(row))
        per_concept[concept] += 1
        if len(selected) >= limit:
            break
    return selected


def _concept_rollup(rows: list[dict[str, Any]], *, limit: int = 4) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("concept") or "General")].append(row)
    rollup: list[dict[str, Any]] = []
    for concept, items in grouped.items():
        states = Counter(str(item.get("category")) for item in items)
        worst = min(states, key=lambda state: CATEGORY_ORDER.get(state, 99))
        reps_sum = sum(int(item.get("reps") or 0) for item in items)
        lapses_sum = sum(int(item.get("lapses") or 0) for item in items)
        success_rate = round(max(0.0, float(reps_sum - lapses_sum) / reps_sum), 3) if reps_sum > 0 else 0.0
        inv_ids = sorted({
            str(item.get("inventory_concept_id") or "").strip()
            for item in items
            if str(item.get("inventory_concept_id") or "").strip()
        })
        rollup.append({
            "concept": concept,
            "inventory_concept_id": inv_ids[0] if len(inv_ids) == 1 else "",
            "worst": worst,
            "cards": len(items),
            "states": dict(sorted(states.items())),
            "reviews_count": reps_sum,
            "success_rate": success_rate,
        })
    rollup.sort(key=lambda item: (CATEGORY_ORDER.get(str(item["worst"]), 99), -int(item["cards"]), str(item["concept"])))
    return rollup[:limit]


def _rollup_profile(
    cards: list[dict[str, Any]],
    reviews_by_card: dict[str, list[dict[str, Any]]],
    mappings: dict[int, CardMapping],
    *,
    scope: str,
    now_ms: int,
    max_chars: int,
    keep_full_rollup: bool = False,
) -> dict[str, Any]:
    macro_counts: Counter[str] = Counter()
    mapping_counts: Counter[str] = Counter()
    atomic_rows: list[dict[str, Any]] = []

    for card in cards:
        card_id = _safe_int(card.get("cardId"))
        mapping = mappings[card_id]
        reviews = reviews_by_card.get(str(card_id), [])
        lifecycle = classify_card_lifecycle(card, reviews, now_ms=now_ms)
        category = str(lifecycle["category"])
        macro_counts[category] += 1
        mapping_counts[mapping.mapping_quality] += 1
        enriched_card = dict(card)
        enriched_card.update(lifecycle)
        enriched_card["concept"] = mapping.concept or mapping.topic or "General"
        enriched_card["topic"] = mapping.topic
        enriched_card["inventory_concept_id"] = mapping.inventory_concept_id
        enriched_card["mapping_quality"] = mapping.mapping_quality
        enriched_card["fact"] = _card_fact_snippet(enriched_card)
        atomic_rows.append(enriched_card)

    intervention_categories = {"leech", "active_lapse", "shaky_success", "mature_stale"}
    atomic_focus = _select_atomic_rows(
        atomic_rows,
        intervention_categories,
        limit=MAX_ATOMIC_FOCUS,
    )
    atomic_scaffolds = _select_atomic_rows(
        atomic_rows,
        {"recent_success", "stable"},
        limit=MAX_ATOMIC_SCAFFOLDS,
        max_per_concept=1,
    )
    atomic_primes = _select_atomic_rows(
        atomic_rows,
        {"stale_new"},
        limit=MAX_ATOMIC_PRIMES,
        max_per_concept=1,
    )
    avoid_facts = [
        _atomic_entry(row)["fact"]
        for row in sorted(atomic_rows, key=_row_priority)
        if row.get("category") in {"fresh_new", "transition_new"}
    ][:2]
    avoid_count = macro_counts["fresh_new"] + macro_counts["transition_new"]
    avoid_direct_quiz = {
        "count": avoid_count,
        "facts": avoid_facts,
        "directive": "exclude direct quiz; use only as premise" if avoid_count else "",
    }

    profile = {
        "status": "success",
        "scope": scope,
        "mapping_quality": dict(mapping_counts),
        "cards_examined": len(cards),
        "macro_counts": dict(sorted(macro_counts.items())),
        "atomic_focus": atomic_focus,
        "atomic_scaffolds": atomic_scaffolds,
        "atomic_primes": atomic_primes,
        "concept_rollup": _concept_rollup(atomic_rows),
        "full_concept_rollup": _concept_rollup(atomic_rows, limit=999),
        "avoid_direct_quiz": avoid_direct_quiz,
        "teaching_directives": _build_teaching_directives(
            atomic_focus,
            atomic_scaffolds,
            atomic_primes,
            avoid_direct_quiz,
        ),
    }
    return _enforce_cap(profile, max_chars, keep_full_rollup=keep_full_rollup)


def _build_global_profile(now_ms: int) -> dict[str, Any]:
    card_ids = _find_cards(f"deck:Neurosurgery* rated:{RECENT_REVIEW_DAYS}")
    if not card_ids:
        return {
            "status": "no_reviews",
            "scope": "global_recent",
            "cards_examined": 0,
            "message": f"No Anki reviews found in the last {RECENT_REVIEW_DAYS} days.",
        }
    cards = _cards_info(card_ids[:300])
    reviews = _reviews_for_cards([_safe_int(card.get("cardId")) for card in cards])
    chroma = _load_chroma_collection()
    prefetch_map = _prefetch_chroma_metadata(cards, chroma)
    topics: dict[str, dict[str, Any]] = {}
    for card in cards:
        mapping = _resolve_card_mapping(card, prefetch_map)
        card_reviews = reviews.get(str(card.get("cardId")), [])
        if mapping.topic not in topics:
            topics[mapping.topic] = {"topic": mapping.topic, "reviews": 0, "lapses": 0, "time_ms": 0}
        for review in card_reviews:
            age = _age_days(_review_timestamp(review), now_ms)
            if age is not None and age > RECENT_REVIEW_DAYS:
                continue
            topics[mapping.topic]["reviews"] += 1
            topics[mapping.topic]["time_ms"] += _safe_int(review.get("time"), 0)
            if _safe_int(review.get("ease"), 0) == 1:
                topics[mapping.topic]["lapses"] += 1
    headlines = []
    for stats in topics.values():
        reviews_count = _safe_int(stats.get("reviews"))
        if not reviews_count:
            continue
        headlines.append({
            "topic": stats["topic"],
            "reviews": reviews_count,
            "lapses": _safe_int(stats.get("lapses")),
            "avg_rt_s": round(_safe_int(stats.get("time_ms")) / reviews_count / 1000, 1),
        })
    headlines.sort(key=lambda item: (-_safe_int(item["lapses"]), -_safe_int(item["reviews"]), str(item["topic"])))
    return {
        "status": "success",
        "scope": "global_recent",
        "cards_examined": len(cards),
        "topic_headlines": headlines[:5],
        "teaching_directives": [
            "Use global Anki headlines only for candidate topic selection.",
            "Run topic-scoped startup-recall before teaching from any Anki signal.",
        ],
        "concept_level_overlay": False,
    }


def build_session_anki_profile(
    topic: str,
    resolved_topic: str = "",
    doc_path: str = "",
    context: str = "",
    global_mode: bool = False,
    profile: str = "memory",
    *,
    planning_concepts: list[str] | None = None,
    max_chars: int = NORMAL_PROFILE_CHAR_CAP,
    now_ms: int | None = None,
    keep_full_rollup: bool = False,
) -> dict[str, Any]:
    """Return a compact Anki overlay for startup-recall planning."""
    now_ms = now_ms if now_ms is not None else _now_ms()
    try:
        if global_mode:
            return _build_global_profile(now_ms)

        primary_terms = _profile_terms(topic, resolved_topic, doc_path, context, None)
        planning_terms = _profile_terms("", "", "", "", planning_concepts)
        terms = primary_terms or planning_terms
        if not terms:
            return {"status": "skipped", "reason": "No resolved topic scope for Anki overlay."}

        chroma = _load_chroma_collection()
        candidate_ids: set[int] = set()
        
        # Consolidate explicit search queries into a single batch request
        queries = _explicit_search_queries(primary_terms or terms)
        multi_results = _find_cards_multi(queries)
        for res in multi_results:
            candidate_ids.update(res)

        semantic_hits = _semantic_candidate_hits(chroma, primary_terms or terms)
        candidate_ids.update(semantic_hits)

        if not candidate_ids:
            candidate_ids.update(_find_cards("deck:Neurosurgery*")[:400])
        if not candidate_ids:
            return {"status": "no_cards", "scope": "topic", "cards_examined": 0, "macro_counts": {}}

        cards = _cards_info(sorted(candidate_ids)[:400])
        reviews = _reviews_for_cards([_safe_int(card.get("cardId")) for card in cards])
        scoped_cards: list[dict[str, Any]] = []
        mappings: dict[int, CardMapping] = {}

        prefetch_map = _prefetch_chroma_metadata(cards, chroma)
        for card in cards:
            card_id = _safe_int(card.get("cardId"))
            mapping = _resolve_card_mapping(card, prefetch_map)
            if not _allowed_by_profile(card, mapping, profile):
                continue
            if _matches_scope(card, mapping, primary_terms or terms) or _semantic_hit_in_scope(
                card,
                mapping,
                primary_terms or terms,
                semantic_hits.get(card_id),
            ):
                scoped_cards.append(card)
                mappings[card_id] = mapping

        if not scoped_cards:
            return {
                "status": "no_matches",
                "scope": "topic",
                "cards_examined": 0,
                "macro_counts": {},
                "message": "No Anki cards matched the resolved topic scope.",
            }

        return _rollup_profile(
            scoped_cards,
            reviews,
            mappings,
            scope="topic",
            now_ms=now_ms,
            max_chars=max_chars,
            keep_full_rollup=keep_full_rollup,
        )
    except ConnectionError:
        return {"status": "offline", "message": "AnkiConnect offline, skipping Anki overlay."}


def get_recent_reviews(days: int = 7) -> list[dict[str, Any]]:
    """Compatibility helper: fetch recently reviewed cards and review logs."""
    card_ids = _find_cards(f"rated:{days}")
    if not card_ids:
        return []
    cards = _cards_info(card_ids)
    reviews_dict = _reviews_for_cards(card_ids)
    limit_ms = (_now_ms() - (days * 86_400_000))
    results = []
    for card in cards:
        cid = str(card.get("cardId"))
        recent_reviews = [
            review
            for review in reviews_dict.get(cid, [])
            if _review_timestamp(review) >= limit_ms
        ]
        if recent_reviews:
            results.append({"card": card, "reviews": recent_reviews})
    return results


def build_feedback_summary(days: int = 7) -> dict[str, Any]:
    """Backward-compatible recent-review summary for non-startup callers."""
    try:
        invoke("version", timeout=0.5)
    except Exception:
        return {"status": "offline", "message": "AnkiConnect offline, skipping feedback."}

    recent_data = get_recent_reviews(days)
    if not recent_data:
        return {"status": "no_reviews", "message": f"No reviews found in the last {days} days."}

    chroma_collection = _load_chroma_collection()
    prefetch_map = _prefetch_chroma_metadata([item["card"] for item in recent_data if "card" in item], chroma_collection)
    topic_stats: dict[str, dict[str, float]] = {}
    concept_stats: dict[str, dict[str, Any]] = {}
    lapses: list[dict[str, Any]] = []

    for item in recent_data:
        card = item["card"]
        reviews = item["reviews"]
        topic, concept = _resolve_card_concept_and_topic(card, prefetch_map)
        topic_stats.setdefault(topic, {"total": 0, "correct": 0, "fail": 0, "time_ms": 0})
        concept_stats.setdefault(concept, {"total": 0, "correct": 0, "fail": 0, "topic": topic})

        for review in reviews:
            ease = _safe_int(review.get("ease"), 3)
            time_ms = _safe_int(review.get("time"), 0)
            correct = ease in (2, 3, 4)
            topic_stats[topic]["total"] += 1
            topic_stats[topic]["time_ms"] += time_ms
            concept_stats[concept]["total"] += 1
            if correct:
                topic_stats[topic]["correct"] += 1
                concept_stats[concept]["correct"] += 1
            else:
                topic_stats[topic]["fail"] += 1
                concept_stats[concept]["fail"] += 1
            if _safe_int(review.get("type"), 1) == 1 and ease == 1:
                question = _strip_html(card.get("question", ""))
                lapses.append({
                    "concept": concept,
                    "topic": topic,
                    "question": question[:120] + ("..." if len(question) > 120 else ""),
                    "interval_before": _safe_int(review.get("lastIvl"), 0),
                    "time_taken_s": time_ms / 1000.0,
                })

    formatted_topics = {}
    for topic, stats in topic_stats.items():
        total = stats["total"]
        pct = (stats["correct"] / total * 100) if total else 0
        formatted_topics[topic] = {
            "total_reviews": int(total),
            "success_rate_pct": round(pct, 1),
            "avg_time_s": round(stats["time_ms"] / total / 1000.0, 1) if total else 0,
            "fails": int(stats["fail"]),
        }

    formatted_concepts = {}
    for concept, stats in concept_stats.items():
        total = stats["total"]
        pct = (stats["correct"] / total * 100) if total else 0
        formatted_concepts[concept] = {
            "topic": stats["topic"],
            "total_reviews": int(total),
            "success_rate_pct": round(pct, 1),
            "fails": int(stats["fail"]),
        }

    return {
        "status": "success",
        "days_audited": days,
        "total_reviews_evaluated": sum(t["total_reviews"] for t in formatted_topics.values()),
        "topics": formatted_topics,
        "concepts": formatted_concepts,
        "lapses": lapses[:8],
    }


def generate_markdown_summary(feedback: dict[str, Any]) -> str:
    """Generate a compact markdown view for manual inspection."""
    if feedback.get("status") != "success":
        return f"> [!NOTE]\n> {feedback.get('message', 'No Anki review data available.')}\n"

    md = ["### Recent Anki Reviews Feedback (Last 7 Days)"]
    md.append(
        f"Evaluated **{feedback['total_reviews_evaluated']} reviews** "
        f"across **{len(feedback['topics'])} topics**."
    )
    md.append("\n| Topic | Reviews | Success Rate | Avg Response Time | Fails |")
    md.append("| :--- | :---: | :---: | :---: | :---: |")
    for topic, stats in sorted(feedback["topics"].items(), key=lambda x: x[1]["success_rate_pct"]):
        md.append(
            f"| **{topic}** | {stats['total_reviews']} | {stats['success_rate_pct']}% | "
            f"{stats['avg_time_s']}s | {stats['fails']} |"
        )
    if feedback.get("lapses"):
        md.append("\n> [!WARNING]")
        md.append("> **Recent Lapses (Forgotten Facts)**:")
        for lapse in feedback["lapses"]:
            md.append(
                f"> * **{lapse['concept']}** ({lapse['topic']}): Forgot card after a "
                f"{lapse['interval_before']}-day interval. Response time: {lapse['time_taken_s']:.1f}s."
            )
            md.append(f">   * Prompt snippet: *{lapse['question']}*")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build compact Anki feedback overlays")
    sub = parser.add_subparsers(dest="command")

    session = sub.add_parser("session-profile")
    session.add_argument("--topic", default="")
    session.add_argument("--resolved-topic", default="")
    session.add_argument("--doc-path", default="")
    session.add_argument("--context", default="")
    session.add_argument("--profile", default="memory")
    session.add_argument("--global", dest="global_mode", action="store_true")
    session.add_argument("--json", action="store_true")

    recent = sub.add_parser("recent-summary")
    recent.add_argument("--days", type=int, default=7)
    recent.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "session-profile":
        payload = build_session_anki_profile(
            topic=args.topic,
            resolved_topic=args.resolved_topic,
            doc_path=args.doc_path,
            context=args.context,
            global_mode=args.global_mode,
            profile=args.profile,
        )
    else:
        payload = build_feedback_summary(getattr(args, "days", 7))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
