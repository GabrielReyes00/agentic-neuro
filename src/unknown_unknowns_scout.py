#!/usr/bin/env python3
"""Surface likely prerequisite blind spots from recent misses."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from kg_constants import DATA_DIR, SESSIONS_DIR

DEFAULT_DB_PATH = DATA_DIR / "knowledge_graph.db"
DEFAULT_PROBE_PATH = SESSIONS_DIR / "proactive_probe.json"


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DEFAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _memory_hash(*parts: object) -> str:
    import hashlib

    payload = "|".join(str(p or "").strip().lower() for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def surface_unknown_unknowns(
    conn: sqlite3.Connection,
    *,
    limit: int = 5,
    recent_days: int = 30,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=recent_days)).isoformat()
    rows = conn.execute(
        """SELECT le.exchange_id, le.topic_id, le.concept_text AS missed_concept,
                  le.error_type, le.answer_correct, le.session_ts,
                  t.display_name AS topic_text,
                  cr.rel_id, cr.concept_a AS prerequisite_text,
                  cr.strength, cr.notes,
                  lcs.mastery_prob, lcs.difficulty, lcs.irt_standard_error
           FROM learning_exchanges le
           JOIN concept_relationships cr
             ON LOWER(cr.concept_b) = LOWER(le.concept_text)
            AND cr.relationship = 'prerequisite_of'
           LEFT JOIN topics t ON le.topic_id = t.topic_id
           LEFT JOIN learner_concept_state lcs
             ON lcs.topic_id = le.topic_id
            AND LOWER(lcs.concept_text) = LOWER(cr.concept_a)
           WHERE le.answer_correct < 2
             AND le.session_ts >= ?
           ORDER BY le.session_ts DESC, le.exchange_id DESC
           LIMIT 100""",
        (cutoff,),
    ).fetchall()

    queued = 0
    probes: list[dict[str, Any]] = []
    with conn:
        for row in rows:
            prereq_mastery = row["mastery_prob"]
            mastery = float(prereq_mastery if prereq_mastery is not None else 0.15)
            difficulty = float(row["difficulty"] if row["difficulty"] is not None else 0.6)
            se = float(row["irt_standard_error"] if row["irt_standard_error"] is not None else 1.0)
            severity = (1.0 - mastery) * 0.55 + difficulty * 0.25 + min(se, 1.5) * 0.1
            severity += float(row["strength"] or 0.5) * 0.1
            if int(row["answer_correct"] or 0) == 0:
                severity += 0.1
            priority = round(min(1.0, severity), 4)
            dedupe = _memory_hash("probe", row["topic_id"], row["prerequisite_text"], row["missed_concept"])
            payload = {
                "missed_concept": row["missed_concept"],
                "error_type": row["error_type"] or "",
                "prerequisite_mastery_prob": mastery,
                "relationship_strength": float(row["strength"] or 0.5),
                "source_exchange_id": row["exchange_id"],
            }
            cur = conn.execute(
                """INSERT OR IGNORE INTO probe_queue
                   (created_ts, due_ts, priority, status, source, topic_id,
                    topic_text, concept_text, prerequisite_text, relationship_id,
                    reason, payload_json, evidence_exchange_ids, dedupe_key)
                   VALUES (?, ?, ?, 'pending', 'unknown_unknowns_scout', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    now.isoformat(),
                    now.isoformat(),
                    priority,
                    row["topic_id"],
                    row["topic_text"] or "",
                    row["missed_concept"],
                    row["prerequisite_text"],
                    row["rel_id"],
                    f"Recent miss on {row['missed_concept']} may reflect prerequisite gap: {row['prerequisite_text']}.",
                    json.dumps(payload, sort_keys=True),
                    json.dumps([row["exchange_id"]]),
                    dedupe,
                ),
            )
            if cur.rowcount:
                queued += 1
            probes.append({
                "topic": row["topic_text"] or "",
                "concept": row["missed_concept"],
                "prerequisite": row["prerequisite_text"],
                "priority": priority,
                "source_exchange_id": row["exchange_id"],
            })
            if len(probes) >= limit:
                break
    return {"ok": True, "queued": queued, "probes": probes[:limit]}


def pop_probe(
    conn: sqlite3.Connection,
    *,
    output_path: str | Path | None = DEFAULT_PROBE_PATH,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        """SELECT *
           FROM probe_queue
           WHERE status = 'pending'
             AND (due_ts IS NULL OR due_ts <= ?)
           ORDER BY priority DESC, created_ts ASC
           LIMIT 1""",
        (now,),
    ).fetchone()
    if not row:
        data = {"ok": True, "status": "none"}
    else:
        with conn:
            conn.execute(
                "UPDATE probe_queue SET status = 'popped', popped_ts = ? WHERE probe_id = ?",
                (now, row["probe_id"]),
            )
        payload = {}
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        data = {
            "ok": True,
            "status": "popped",
            "probe_id": row["probe_id"],
            "topic": row["topic_text"],
            "concept": row["concept_text"],
            "prerequisite": row["prerequisite_text"],
            "priority": row["priority"],
            "reason": row["reason"],
            "payload": payload,
        }
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def _main() -> int:
    parser = argparse.ArgumentParser(description="Unknown-unknown prerequisite scout")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sub = parser.add_subparsers(dest="command", required=True)
    p_surf = sub.add_parser("surface")
    p_surf.add_argument("--limit", type=int, default=5)
    p_surf.add_argument("--recent-days", type=int, default=30)
    p_pop = sub.add_parser("pop")
    p_pop.add_argument("--output", default=str(DEFAULT_PROBE_PATH))
    args = parser.parse_args()

    conn = connect(args.db)
    try:
        if args.command == "surface":
            data = surface_unknown_unknowns(conn, limit=args.limit, recent_days=args.recent_days)
        else:
            data = pop_probe(conn, output_path=args.output)
        print(json.dumps(data, indent=2))
        return 0 if data.get("ok") else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(_main())
