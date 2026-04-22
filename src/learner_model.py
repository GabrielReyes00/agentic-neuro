#!/usr/bin/env python3
"""Adaptive learner model helpers.

This module layers a lightweight 1PL IRT calibration on top of the existing
learner_concept_state mastery model. It is intentionally dependency-free and
recomputable from learning_exchanges.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kg_constants import DATA_DIR

DEFAULT_DB_PATH = DATA_DIR / "knowledge_graph.db"


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DEFAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _clamp(value: float, low: float = 0.01, high: float = 0.99) -> float:
    return max(low, min(high, value))


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def logit(p: float) -> float:
    p = _clamp(p)
    return math.log(p / (1.0 - p))


def difficulty_band(mastery_prob: float | None, difficulty: float | None = None) -> str:
    mastery = float(mastery_prob if mastery_prob is not None else 0.0)
    diff = float(difficulty if difficulty is not None else 0.5)
    if mastery <= 0.05:
        return "cold_start"
    if mastery < 0.35:
        return "remediate"
    if mastery <= 0.75:
        return "zpd"
    if diff >= 0.65:
        return "stretch"
    return "consolidate"


def _item_difficulty(row: sqlite3.Row) -> float:
    diff = float(row["difficulty"] if "difficulty" in row.keys() and row["difficulty"] is not None else 0.5)
    return logit(_clamp(diff, 0.05, 0.95))


def _score_answer(answer_correct: int) -> float:
    if int(answer_correct) >= 2:
        return 1.0
    if int(answer_correct) == 1:
        return 0.55
    return 0.0


def estimate_mastery(
    conn: sqlite3.Connection,
    *,
    topic: str = "",
    concept: str = "",
) -> dict[str, Any]:
    concept_l = (concept or "").strip().lower()
    topic_l = (topic or "").strip().lower()
    params: list[Any] = []
    where = ["1=1"]
    if concept_l:
        where.append("LOWER(lcs.concept_text) = ?")
        params.append(concept_l)
    if topic_l:
        where.append("(LOWER(t.display_name) LIKE ? OR LOWER(t.canonical_name) LIKE ?)")
        params.extend([f"%{topic_l}%", f"%{topic_l}%"])

    row = conn.execute(
        f"""SELECT lcs.*, t.display_name AS topic_display
            FROM learner_concept_state lcs
            LEFT JOIN topics t ON lcs.topic_id = t.topic_id
            WHERE {' AND '.join(where)}
            ORDER BY lcs.last_updated DESC
            LIMIT 1""",
        params,
    ).fetchone()
    if row:
        mastery = float(row["mastery_prob"] or 0.0)
        return {
            "ok": True,
            "cold_start": False,
            "topic": row["topic_display"] or topic,
            "concept": row["concept_text"],
            "mastery_prob": round(mastery, 4),
            "irt_theta": round(float(row["irt_theta"] or logit(_clamp(mastery))), 4),
            "irt_standard_error": round(float(row["irt_standard_error"] or 1.0), 4),
            "difficulty": round(float(row["difficulty"] or 0.5), 4),
            "difficulty_band": row["difficulty_band"] or difficulty_band(mastery, row["difficulty"]),
            "observations": int(row["irt_observation_count"] or 0),
        }

    topic_mean = conn.execute(
        """SELECT AVG(lcs.mastery_prob) AS mastery, AVG(lcs.difficulty) AS difficulty,
                  COUNT(*) AS n
           FROM learner_concept_state lcs
           LEFT JOIN topics t ON lcs.topic_id = t.topic_id
           WHERE (? = '' OR LOWER(t.display_name) LIKE ? OR LOWER(t.canonical_name) LIKE ?)""",
        (topic_l, f"%{topic_l}%", f"%{topic_l}%"),
    ).fetchone()
    n = int(topic_mean["n"] or 0) if topic_mean else 0
    mastery = float(topic_mean["mastery"] if topic_mean and topic_mean["mastery"] is not None else 0.35)
    diff = float(topic_mean["difficulty"] if topic_mean and topic_mean["difficulty"] is not None else 0.5)
    return {
        "ok": True,
        "cold_start": True,
        "topic": topic,
        "concept": concept,
        "mastery_prob": round(mastery, 4),
        "irt_theta": round(logit(_clamp(mastery)), 4),
        "irt_standard_error": 1.5 if n == 0 else 1.1,
        "difficulty": round(diff, 4),
        "difficulty_band": "cold_start" if n == 0 else difficulty_band(mastery, diff),
        "observations": n,
    }


def _recompute_state_row(conn: sqlite3.Connection, state_id: int) -> dict[str, Any]:
    state = conn.execute(
        "SELECT * FROM learner_concept_state WHERE state_id = ?",
        (state_id,),
    ).fetchone()
    if not state:
        return {"ok": False, "error": "state not found", "state_id": state_id}

    rows = conn.execute(
        """SELECT le.answer_correct, le.mastery_prob_before, le.mastery_prob_after,
                  COALESCE(le.difficulty_band, '') AS exchange_band
           FROM learning_exchanges le
           WHERE le.topic_id = ? AND LOWER(le.concept_text) = LOWER(?)
           ORDER BY le.session_ts ASC, le.turn_number ASC, le.exchange_id ASC""",
        (state["topic_id"], state["concept_text"]),
    ).fetchall()
    theta = logit(float(state["mastery_prob"] or 0.35))
    info = 0.0
    for idx, row in enumerate(rows, start=1):
        b = _item_difficulty(state)
        p = sigmoid(theta - b)
        observed = _score_answer(int(row["answer_correct"]))
        lr = 0.45 / math.sqrt(idx + 1)
        theta += lr * (observed - p)
        info += max(0.01, p * (1.0 - p))
    mastery = sigmoid(theta)
    se = 1.0 / math.sqrt(info + 1.0)
    band = difficulty_band(mastery, state["difficulty"])
    last_delta = float(state["last_mastery_delta"] or 0.0)
    with conn:
        conn.execute(
            """UPDATE learner_concept_state
               SET irt_theta = ?, irt_standard_error = ?,
                   irt_observation_count = ?, difficulty_band = ?,
                   last_mastery_delta = ?, last_updated = ?
               WHERE state_id = ?""",
            (
                theta,
                se,
                len(rows),
                band,
                last_delta,
                datetime.now(timezone.utc).isoformat(),
                state_id,
            ),
        )
    return {
        "ok": True,
        "state_id": state_id,
        "concept": state["concept_text"],
        "irt_theta": round(theta, 4),
        "irt_standard_error": round(se, 4),
        "observations": len(rows),
        "difficulty_band": band,
    }


def update_after_exchange(conn: sqlite3.Connection, exchange_id: int) -> dict[str, Any]:
    exchange = conn.execute(
        """SELECT le.*, lcs.state_id, lcs.mastery_prob, lcs.difficulty,
                  lcs.difficulty_band AS state_band
           FROM learning_exchanges le
           LEFT JOIN learner_concept_state lcs
             ON lcs.topic_id = le.topic_id
            AND LOWER(lcs.concept_text) = LOWER(le.concept_text)
           WHERE le.exchange_id = ?""",
        (exchange_id,),
    ).fetchone()
    if not exchange:
        return {"ok": False, "error": "exchange not found", "exchange_id": exchange_id}
    state_id = int(exchange["state_id"] or 0)
    if state_id <= 0:
        return {"ok": False, "error": "learner state not found", "exchange_id": exchange_id}

    mastery_after = float(exchange["mastery_prob"] or 0.0)
    mastery_before = exchange["mastery_prob_before"]
    if mastery_before is None:
        mastery_before = mastery_after
    delta = mastery_after - float(mastery_before)
    band = difficulty_band(mastery_after, exchange["difficulty"])
    with conn:
        conn.execute(
            """UPDATE learning_exchanges
               SET mastery_prob_before = COALESCE(mastery_prob_before, ?),
                   mastery_prob_after = ?,
                   difficulty_band = COALESCE(NULLIF(difficulty_band, ''), ?)
               WHERE exchange_id = ?""",
            (float(mastery_before), mastery_after, band, exchange_id),
        )
        conn.execute(
            """UPDATE learner_concept_state
               SET last_mastery_delta = ?, difficulty_band = ?
               WHERE state_id = ?""",
            (delta, band, state_id),
        )
    recomputed = _recompute_state_row(conn, state_id)
    return {"ok": True, "exchange_id": exchange_id, "mastery_delta": round(delta, 4), **recomputed}


def recompute_learner_model(
    conn: sqlite3.Connection,
    *,
    session_ts: str = "",
    limit: int = 500,
) -> dict[str, Any]:
    params: list[Any] = []
    where = "1=1"
    if session_ts:
        where = "le.session_ts = ?"
        params.append(session_ts)
    rows = conn.execute(
        f"""SELECT DISTINCT lcs.state_id
            FROM learner_concept_state lcs
            JOIN learning_exchanges le
              ON le.topic_id = lcs.topic_id
             AND LOWER(le.concept_text) = LOWER(lcs.concept_text)
            WHERE {where}
            ORDER BY lcs.last_updated DESC
            LIMIT ?""",
        (*params, limit),
    ).fetchall()
    updated = 0
    for row in rows:
        result = _recompute_state_row(conn, int(row["state_id"]))
        if result.get("ok"):
            updated += 1
    return {"ok": True, "states_updated": updated}


def next_item(
    conn: sqlite3.Connection,
    *,
    mode: str = "zpd",
    topic: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    topic_l = (topic or "").strip().lower()
    rows = conn.execute(
        """SELECT lcs.*, t.display_name AS topic_display
           FROM learner_concept_state lcs
           LEFT JOIN topics t ON lcs.topic_id = t.topic_id
           WHERE (? = '' OR LOWER(t.display_name) LIKE ? OR LOWER(t.canonical_name) LIKE ?)
           ORDER BY COALESCE(lcs.next_review_due, lcs.last_updated) ASC
           LIMIT 200""",
        (topic_l, f"%{topic_l}%", f"%{topic_l}%"),
    ).fetchall()
    scored: list[dict[str, Any]] = []
    for row in rows:
        mastery = float(row["mastery_prob"] or 0.0)
        se = float(row["irt_standard_error"] or 1.0)
        diff = float(row["difficulty"] or 0.5)
        band = row["difficulty_band"] or difficulty_band(mastery, diff)
        if mode == "remediate":
            score = (1.0 - mastery) * 0.7 + diff * 0.2 + se * 0.1
        elif mode == "eig":
            p = sigmoid(float(row["irt_theta"] or logit(_clamp(mastery))) - logit(_clamp(diff, 0.05, 0.95)))
            score = p * (1.0 - p) + min(se, 2.0) * 0.15
        else:
            score = 1.0 - abs(mastery - 0.58) + min(se, 1.5) * 0.1
        scored.append({
            "topic": row["topic_display"] or "",
            "concept": row["concept_text"],
            "mastery_prob": round(mastery, 4),
            "difficulty": round(diff, 4),
            "difficulty_band": band,
            "irt_standard_error": round(se, 4),
            "score": round(score, 4),
        })
    scored.sort(key=lambda r: r["score"], reverse=True)
    return {"ok": True, "mode": mode, "items": scored[:limit], "count": len(scored[:limit])}


def _main() -> int:
    parser = argparse.ArgumentParser(description="Adaptive learner model")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sub = parser.add_subparsers(dest="command", required=True)
    p_est = sub.add_parser("estimate-mastery")
    p_est.add_argument("--topic", default="")
    p_est.add_argument("--concept", default="")
    p_next = sub.add_parser("next-item")
    p_next.add_argument("--mode", default="zpd", choices=["eig", "zpd", "remediate"])
    p_next.add_argument("--topic", default="")
    p_next.add_argument("--limit", type=int, default=5)
    p_up = sub.add_parser("update-after-exchange")
    p_up.add_argument("--exchange-id", type=int, required=True)
    p_re = sub.add_parser("recompute")
    p_re.add_argument("--session-ts", default="")
    args = parser.parse_args()

    conn = _connect(args.db)
    try:
        if args.command == "estimate-mastery":
            data = estimate_mastery(conn, topic=args.topic, concept=args.concept)
        elif args.command == "next-item":
            data = next_item(conn, mode=args.mode, topic=args.topic, limit=args.limit)
        elif args.command == "update-after-exchange":
            data = update_after_exchange(conn, args.exchange_id)
        else:
            data = recompute_learner_model(conn, session_ts=args.session_ts)
        print(json.dumps(data, indent=2))
        return 0 if data.get("ok") else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(_main())
