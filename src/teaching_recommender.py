#!/usr/bin/env python3
"""Teaching approach recommender.

Ranks teaching moves from the procedural policy table using a sparse-aware
backoff ladder and Beta-smoothed outcome estimates.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kg_constants import (
    CANONICAL_TEACHING_APPROACHES,
    DATA_DIR,
    TEACHING_APPROACH_ALIASES,
)

DEFAULT_DB_PATH = DATA_DIR / "knowledge_graph.db"

ERROR_DEFAULTS: dict[str, str] = {
    "numerical_recall": "threshold_drill",
    "conceptual_confusion": "forced_discrimination",
    "cross_contamination": "forced_discrimination",
    "application_failure": "clinical_vignette_transfer",
    "reasoning_gap": "pathophys_derivation",
    "omission": "management_algorithm",
}


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DEFAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _clean(value: str) -> str:
    return " ".join((value or "").strip().lower().replace("-", "_").split())


def canonicalize_approach(conn: sqlite3.Connection | None, approach: str) -> str:
    raw = _clean(approach)
    if not raw:
        return ""
    raw = raw.replace(" ", "_")
    if raw in CANONICAL_TEACHING_APPROACHES:
        return raw
    if raw in TEACHING_APPROACH_ALIASES:
        return TEACHING_APPROACH_ALIASES[raw]
    if conn is not None:
        row = conn.execute(
            "SELECT canonical_approach FROM teaching_approach_aliases WHERE alias = ?",
            (raw,),
        ).fetchone()
        if row:
            return str(row["canonical_approach"])
    return raw


def seed_aliases(conn: sqlite3.Connection) -> int:
    now = datetime.now(timezone.utc).isoformat()
    added = 0
    with conn:
        for alias, canonical in TEACHING_APPROACH_ALIASES.items():
            cur = conn.execute(
                """INSERT OR IGNORE INTO teaching_approach_aliases
                   (alias, canonical_approach, created_ts)
                   VALUES (?, ?, ?)""",
                (_clean(alias).replace(" ", "_"), canonical, now),
            )
            added += int(cur.rowcount or 0)
        for canonical in CANONICAL_TEACHING_APPROACHES:
            cur = conn.execute(
                """INSERT OR IGNORE INTO teaching_approach_aliases
                   (alias, canonical_approach, created_ts)
                   VALUES (?, ?, ?)""",
                (canonical, canonical, now),
            )
            added += int(cur.rowcount or 0)
    return added


def _row_score(row: sqlite3.Row) -> float:
    success = int(row["success_count"] or 0)
    failure = int(row["failure_count"] or 0)
    unknown = int(row["unknown_count"] or 0)
    delta_count = int(row["mastery_delta_count"] or 0)
    delta_mean = (float(row["mastery_delta_sum"] or 0.0) / delta_count) if delta_count else 0.0
    posterior = (success + 1.0) / (success + failure + 2.0)
    evidence = min(0.12, (success + failure + unknown) * 0.015)
    return posterior + delta_mean * 0.75 + evidence


def _query_level(
    conn: sqlite3.Connection,
    *,
    domain: str,
    topic_id: int | None,
    concept_text: str,
    error_type: str,
    difficulty_band: str,
    level: str,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[Any] = []
    if level == "concept_error_band":
        clauses.extend(["LOWER(concept_text) = LOWER(?)", "error_type = ?"])
        params.extend([concept_text, error_type])
        if difficulty_band:
            clauses.append("(difficulty_band = ? OR difficulty_band = '')")
            params.append(difficulty_band)
    elif level == "concept_error":
        clauses.extend(["LOWER(concept_text) = LOWER(?)", "error_type = ?"])
        params.extend([concept_text, error_type])
    elif level == "topic_error":
        clauses.extend(["topic_id IS ?", "error_type = ?"])
        params.extend([topic_id, error_type])
    elif level == "domain_error":
        clauses.extend(["LOWER(domain) = LOWER(?)", "error_type = ?"])
        params.extend([domain, error_type])
    else:
        clauses.append("1=1")
    where = " AND ".join(clauses)
    return conn.execute(
        f"""SELECT *
            FROM teaching_policy_stats
            WHERE {where}
              AND teaching_approach IS NOT NULL
              AND teaching_approach != ''
            ORDER BY updated_ts DESC
            LIMIT 50""",
        params,
    ).fetchall()


def recommend_approach(
    conn: sqlite3.Connection,
    *,
    domain: str = "",
    topic_id: int | None = None,
    concept_text: str = "",
    error_type: str = "",
    difficulty_band: str = "",
) -> dict[str, Any]:
    seed_aliases(conn)
    levels = [
        "concept_error_band",
        "concept_error",
        "topic_error",
        "domain_error",
        "global",
    ]
    for level in levels:
        rows = _query_level(
            conn,
            domain=domain,
            topic_id=topic_id,
            concept_text=concept_text,
            error_type=error_type,
            difficulty_band=difficulty_band,
            level=level,
        )
        candidates: dict[str, dict[str, Any]] = {}
        for row in rows:
            approach = canonicalize_approach(conn, row["teaching_approach"])
            if not approach:
                continue
            score = _row_score(row)
            entry = candidates.setdefault(
                approach,
                {
                    "approach": approach,
                    "score": 0.0,
                    "success_count": 0,
                    "failure_count": 0,
                    "unknown_count": 0,
                    "sparse": True,
                },
            )
            entry["score"] = max(float(entry["score"]), score)
            entry["success_count"] += int(row["success_count"] or 0)
            entry["failure_count"] += int(row["failure_count"] or 0)
            entry["unknown_count"] += int(row["unknown_count"] or 0)
            entry["sparse"] = (entry["success_count"] + entry["failure_count"]) < 3
        if candidates:
            ranked = sorted(candidates.values(), key=lambda c: c["score"], reverse=True)
            best = ranked[0]
            return {
                "ok": True,
                "approach": best["approach"],
                "backoff_level": level,
                "sparse": bool(best["sparse"]),
                "candidates": ranked[:5],
            }

    fallback = ERROR_DEFAULTS.get(error_type, "")
    if not fallback:
        fallback = "pathophys_derivation" if difficulty_band == "remediate" else "clinical_vignette_transfer"
    return {
        "ok": True,
        "approach": fallback,
        "backoff_level": "default",
        "sparse": True,
        "candidates": [{"approach": fallback, "score": 0.5, "sparse": True}],
    }


def update_policy_delta(
    conn: sqlite3.Connection,
    *,
    policy_id: int,
    mastery_delta: float,
    difficulty_band: str,
) -> None:
    if policy_id <= 0:
        return
    with conn:
        conn.execute(
            """UPDATE teaching_policy_stats
               SET mastery_delta_sum = COALESCE(mastery_delta_sum, 0.0) + ?,
                   mastery_delta_count = COALESCE(mastery_delta_count, 0) + 1,
                   last_mastery_delta = ?,
                   difficulty_band = COALESCE(NULLIF(difficulty_band, ''), ?),
                   sparse = CASE
                       WHEN (success_count + failure_count + unknown_count) >= 3 THEN 0
                       ELSE 1
                   END,
                   updated_ts = ?
               WHERE policy_id = ?""",
            (
                float(mastery_delta),
                float(mastery_delta),
                difficulty_band,
                datetime.now(timezone.utc).isoformat(),
                policy_id,
            ),
        )


def refresh_teaching_policy(conn: sqlite3.Connection) -> dict[str, Any]:
    aliases_added = seed_aliases(conn)
    rows = conn.execute(
        "SELECT policy_id, teaching_approach, success_count, failure_count, unknown_count FROM teaching_policy_stats"
    ).fetchall()
    canonicalized = 0
    sparse_updated = 0
    with conn:
        for row in rows:
            canonical = canonicalize_approach(conn, row["teaching_approach"])
            sparse = 1 if (int(row["success_count"] or 0) + int(row["failure_count"] or 0)) < 3 else 0
            conn.execute(
                """UPDATE teaching_policy_stats
                   SET teaching_approach = ?, sparse = ?
                   WHERE policy_id = ?""",
                (canonical, sparse, row["policy_id"]),
            )
            canonicalized += int(canonical != row["teaching_approach"])
            sparse_updated += 1
    return {
        "ok": True,
        "aliases_added": aliases_added,
        "policies_seen": len(rows),
        "canonicalized": canonicalized,
        "sparse_updated": sparse_updated,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Recommend adaptive teaching approaches")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    sub = parser.add_subparsers(dest="command", required=True)
    p_rec = sub.add_parser("recommend-approach")
    p_rec.add_argument("--domain", default="")
    p_rec.add_argument("--topic-id", type=int, default=None)
    p_rec.add_argument("--concept", default="", dest="concept_text")
    p_rec.add_argument("--error-type", default="")
    p_rec.add_argument("--difficulty-band", default="")
    sub.add_parser("refresh")
    args = parser.parse_args()

    conn = connect(args.db)
    try:
        if args.command == "recommend-approach":
            data = recommend_approach(
                conn,
                domain=args.domain,
                topic_id=args.topic_id,
                concept_text=args.concept_text,
                error_type=args.error_type,
                difficulty_band=args.difficulty_band,
            )
        else:
            data = refresh_teaching_policy(conn)
        print(json.dumps(data, indent=2))
        return 0 if data.get("ok") else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(_main())
