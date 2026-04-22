"""Pull Anki review stats and fold them back into concept_mastery.

This closes the learning loop: once a card is created by the real-time
integration, its subsequent review history in Anki (ease factor, interval,
lapses, maturity) becomes another data source for the KG. If Gabriel
steadily fails a card in Anki, the underlying concept is reopened as a
weakness in the KG and the study agents see it before the next session.

Complementary to ``kg_anki.sync_anki`` — that method logs raw signals and
records V2 review events. This module does a tighter join: for every
``learning_exchanges`` row that carries an ``anki_note_id`` we look up the
current review stats and update the ``concept_mastery`` row for the
concept directly.

Run manually or from the universal post-session hook.
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from src.anki_sync.anki_client import AnkiClient  # noqa: E402


ANKI_URL_DEFAULT = "http://localhost:8765"
MATURE_INTERVAL_DAYS = 21


@dataclass
class StatsSyncResult:
    ok: bool
    reason: str
    notes_examined: int = 0
    concepts_updated: int = 0
    concepts_reopened: int = 0
    exchanges_scanned: int = 0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_linked_exchanges(conn) -> list[dict]:
    """Return every exchange with a non-NULL anki_note_id, joined to its concept."""
    rows = conn.execute(
        """SELECT le.exchange_id, le.anki_note_id, le.topic_id, le.concept_text, le.domain,
                  le.answer_correct, le.error_type, le.session_ts
           FROM learning_exchanges le
           WHERE le.anki_note_id IS NOT NULL"""
    ).fetchall()
    return [dict(r) for r in rows]


def _group_note_to_concepts(exchanges: list[dict]) -> dict[int, list[dict]]:
    """Return anki_note_id -> list of exchange rows."""
    out: dict[int, list[dict]] = {}
    for row in exchanges:
        note_id = int(row["anki_note_id"] or 0)
        if note_id <= 0:
            continue
        out.setdefault(note_id, []).append(row)
    return out


def _fetch_card_stats_for_notes(client: AnkiClient, note_ids: list[int]) -> dict[int, dict]:
    """For each note_id, find its cards and aggregate review stats.

    Returns note_id -> {interval, ease_factor, lapses, reps, mature, due_ts}.
    """
    stats: dict[int, dict] = {}
    if not note_ids:
        return stats

    # Build a single findCards query per batch.
    query = " OR ".join(f"nid:{nid}" for nid in note_ids)
    try:
        card_ids = client.find_cards(query)
    except Exception as exc:  # noqa: BLE001
        print(f"[anki_stats_sync] find_cards failed: {exc}", file=sys.stderr)
        return stats
    if not card_ids:
        return stats

    card_details = client.cards_info(card_ids)
    by_note: dict[int, list[dict]] = {}
    for card in card_details:
        nid = int(card.get("note") or 0)
        if nid:
            by_note.setdefault(nid, []).append(card)

    now = _utc_now()
    for nid, cards in by_note.items():
        intervals = [int(c.get("interval") or 0) for c in cards]
        factors = [int(c.get("factor") or 0) for c in cards]
        reps_sum = sum(int(c.get("reps") or 0) for c in cards)
        lapses_sum = sum(int(c.get("lapses") or 0) for c in cards)
        # Only factors > 0 count — new cards have factor 0.
        active_factors = [f for f in factors if f > 0]
        ease_factor = (sum(active_factors) / len(active_factors) / 1000.0) if active_factors else 2.5
        max_interval = max(intervals) if intervals else 0
        mature = max_interval >= MATURE_INTERVAL_DAYS
        due_ts = (now + timedelta(days=max_interval)).isoformat() if max_interval > 0 else None
        stats[nid] = {
            "interval_days": max_interval,
            "ease_factor": round(ease_factor, 3),
            "reps": reps_sum,
            "lapses": lapses_sum,
            "mature": mature,
            "due_ts": due_ts,
            "card_count": len(cards),
        }
    return stats


def _update_concept_mastery(conn, concept_text: str, topic_id: int | None, payload: dict) -> bool:
    """Update concept_mastery with Anki-derived SRS fields.

    Only updates if a row exists (we don't want to invent mastery entries
    from card stats alone). Returns True on update.
    """
    if not concept_text:
        return False
    row = conn.execute(
        """SELECT concept_id, status, times_missed
           FROM concept_mastery
           WHERE concept_text = ?
             AND (topic_id = ? OR ? IS NULL)
           LIMIT 1""",
        (concept_text, topic_id, topic_id),
    ).fetchone()
    if not row:
        return False

    ease = float(payload.get("ease_factor") or 2.5)
    interval = float(payload.get("interval_days") or 0)
    lapses = int(payload.get("lapses") or 0)
    due_ts = payload.get("due_ts")

    with conn:
        conn.execute(
            """UPDATE concept_mastery
               SET review_interval_days = ?,
                   ease_factor = ?,
                   next_review_due = COALESCE(?, next_review_due)
               WHERE concept_id = ?""",
            (interval, ease, due_ts, row["concept_id"]),
        )
    return True


def _should_reopen(payload: dict) -> bool:
    """A card with low ease or chronic lapses is a live weakness signal."""
    ease = float(payload.get("ease_factor") or 2.5)
    lapses = int(payload.get("lapses") or 0)
    return ease < 2.0 or lapses >= 3


def sync_stats(
    *,
    anki_url: str = ANKI_URL_DEFAULT,
    db_path: Path | None = None,
) -> StatsSyncResult:
    """Main entry: pull stats for every linked exchange and fold into mastery."""
    import sqlite3

    if db_path is None:
        from kg_constants import DATA_DIR
        db_path = DATA_DIR / "knowledge_graph.db"

    client = AnkiClient(anki_url)
    ok, err = client.check_connection()
    if not ok:
        return StatsSyncResult(ok=False, reason=f"anki_unavailable: {err}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        exchanges = _load_linked_exchanges(conn)
        if not exchanges:
            return StatsSyncResult(ok=True, reason="no_linked_exchanges")

        note_to_exchanges = _group_note_to_concepts(exchanges)
        note_ids = list(note_to_exchanges.keys())

        # Anki's findCards with OR can be long; chunk to avoid query limits.
        stats: dict[int, dict] = {}
        for i in range(0, len(note_ids), 50):
            chunk = note_ids[i : i + 50]
            stats.update(_fetch_card_stats_for_notes(client, chunk))

        updated = 0
        reopened = 0
        for note_id, payload in stats.items():
            for ex in note_to_exchanges.get(note_id, []):
                if _update_concept_mastery(conn, ex["concept_text"], ex["topic_id"], payload):
                    updated += 1
                if _should_reopen(payload):
                    try:
                        with conn:
                            conn.execute(
                                """UPDATE concept_mastery
                                   SET status = 'unknown',
                                       times_missed = times_missed + 1
                                   WHERE concept_text = ?
                                     AND (topic_id = ? OR ? IS NULL)""",
                                (ex["concept_text"], ex["topic_id"], ex["topic_id"]),
                            )
                        reopened += 1
                    except Exception:  # noqa: BLE001
                        pass

        return StatsSyncResult(
            ok=True,
            reason="synced",
            notes_examined=len(stats),
            concepts_updated=updated,
            concepts_reopened=reopened,
            exchanges_scanned=len(exchanges),
        )
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Sync Anki review stats into concept_mastery")
    parser.add_argument("--anki-url", default=ANKI_URL_DEFAULT)
    args = parser.parse_args(argv)

    result = sync_stats(anki_url=args.anki_url)
    print(json.dumps(result.__dict__, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
