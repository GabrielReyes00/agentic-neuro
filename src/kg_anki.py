#!/usr/bin/env python3
"""Anki integration mixin for KnowledgeGraph."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from collections.abc import Mapping


class KnowledgeGraphAnkiMixin:
    """AnkiConnect snapshot and card-creation signal behavior."""

    # ------------------------------------------------------------------
    # Phase 4 — Anki Integration
    # ------------------------------------------------------------------

    def _anki_request(
        self,
        url: str,
        action: str,
        params: Mapping[str, object] | None = None,
    ) -> object:
        """Send a request to AnkiConnect and return the result."""
        payload: dict[str, object] = {"action": action, "version": 6}
        if params:
            payload["params"] = dict(params)
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res.get("result")

    def sync_anki(self, url: str = "http://localhost:8765") -> dict[str, object]:
        """Pull Anki review data via AnkiConnect and snapshot into the knowledge graph."""
        try:
            # 1. Test connection
            try:
                self._anki_request(url, "version")
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                return {"status": "unavailable", "reason": str(exc)}

            # 2. Find cards in Neuro-related decks
            card_ids = self._anki_request(url, "findCards", {"query": "deck:Neuro*"})
            if not isinstance(card_ids, list):
                card_ids = []
            if not card_ids:
                card_ids = self._anki_request(url, "findCards", {"query": "deck:*"})
                if not isinstance(card_ids, list):
                    card_ids = []
            if not card_ids:
                return {"status": "synced", "cards": 0, "matched": 0, "unmatched": 0, "snapshot_id": None}

            # 3. Fetch card info in batches of 50
            all_cards: list[dict[str, object]] = []
            for i in range(0, len(card_ids), 50):
                batch = card_ids[i : i + 50]
                batch_info = self._anki_request(url, "cardsInfo", {"cards": batch})
                if isinstance(batch_info, list):
                    all_cards.extend(item for item in batch_info if isinstance(item, dict))

            # 4. Create snapshot
            now = datetime.now(timezone.utc).isoformat()
            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO anki_sync_snapshots (synced_at, total_cards, total_reviews, metadata)
                       VALUES (?, ?, 0, '{}')""",
                    (now, len(all_cards)),
                )
                snapshot_id = cur.lastrowid

            # 5. Get previous snapshot's note IDs to avoid duplicate signal logging
            prev_note_ids: set[int] = set()
            prev_snap = self.conn.execute(
                "SELECT snapshot_id FROM anki_sync_snapshots WHERE snapshot_id < ? ORDER BY snapshot_id DESC LIMIT 1",
                (snapshot_id,),
            ).fetchone()
            if prev_snap:
                rows = self.conn.execute(
                    "SELECT anki_note_id FROM anki_card_stats WHERE snapshot_id = ?",
                    (prev_snap["snapshot_id"],),
                ).fetchall()
                prev_note_ids = {int(r["anki_note_id"] or 0) for r in rows}

            # 6. Process each card
            matched = 0
            unmatched = 0

            for card in all_cards:
                note_id = int(card.get("note") or 0)
                deck_name = str(card.get("deckName") or "")
                interval = int(card.get("interval") or 0)
                factor = int(card.get("factor") or 2500)
                reps = int(card.get("reps") or 0)
                lapses = int(card.get("lapses") or 0)

                # Extract first field value (card front text)
                fields = card.get("fields", {})
                card_front = ""
                if isinstance(fields, dict) and fields:
                    first_field = next(iter(fields.values()), {})
                    if isinstance(first_field, dict):
                        card_front = str(first_field.get("value") or "")[:200]
                    else:
                        card_front = str(first_field)[:200]

                ease_factor = factor / 1000.0

                # Topic matching
                matched_topic_id = None
                if card_front:
                    normalized = self._normalize_topic(card_front)
                    topic = self._find_topic(normalized)
                    if topic:
                        matched_topic_id = topic["topic_id"]
                        matched += 1

                        # Log signal only for cards not in the previous snapshot
                        if note_id not in prev_note_ids:
                            if ease_factor >= 2.5 and interval >= 21:
                                self.log_signal(
                                    topic_name=card_front,
                                    source="anki",
                                    signal_type="anki_review",
                                    metadata={"confidence_delta": 0.03},
                                )
                            elif ease_factor < 2.0 or lapses >= 3:
                                self.log_signal(
                                    topic_name=card_front,
                                    source="anki",
                                    signal_type="anki_review",
                                    metadata={"confidence_delta": -0.05},
                                )
                            # Otherwise: normal retention, no change
                    else:
                        unmatched += 1
                else:
                    unmatched += 1

                # Insert card stat row
                with self.conn:
                    self.conn.execute(
                        """INSERT INTO anki_card_stats
                           (snapshot_id, anki_note_id, deck_name, card_front,
                            interval_days, ease_factor, reps, lapses, matched_topic_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (snapshot_id, note_id, deck_name, card_front,
                         interval, ease_factor, reps, lapses, matched_topic_id),
                    )

            return {
                "status": "synced",
                "cards": len(all_cards),
                "matched": matched,
                "unmatched": unmatched,
                "snapshot_id": snapshot_id,
            }

        except Exception as exc:
            return {"status": "unavailable", "reason": f"sync_anki error: {exc}"}

    def log_anki_creation(
        self,
        topic: str,
        card_count: int,
        claim_texts: list[str] | None = None,
    ) -> None:
        """Log knowledge graph signals when new Anki cards are created.

        Called from anki_sync_cli.py after card dispatch.
        """
        try:
            if claim_texts:
                for claim in claim_texts:
                    self.log_signal(
                        topic_name=claim,
                        source="anki",
                        signal_type="card_created",
                        depth_at_event=2,
                    )
            else:
                self.log_signal(
                    topic_name=topic,
                    source="anki",
                    signal_type="card_created",
                    depth_at_event=2,
                )
        except Exception as exc:
            print(f"[knowledge_graph] log_anki_creation error: {exc}", file=sys.stderr)
