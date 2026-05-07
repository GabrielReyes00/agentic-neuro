#!/usr/bin/env python3
"""One-time migration from old knowledge_graph.db to new study_memory.db."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from study_memory import _get_db, _normalize, DB_PATH


def migrate(source: Path, target: Path, dry_run: bool = False) -> None:
    old = sqlite3.connect(str(source))
    old.row_factory = sqlite3.Row

    new = _get_db(target)

    # Build topic_id -> display_name map
    topic_map: dict[int, str] = {}
    for row in old.execute("SELECT topic_id, display_name FROM topics"):
        topic_map[row["topic_id"]] = row["display_name"]

    # --- Migrate session_narratives -> sessions ---
    sn_count = 0
    for row in old.execute("SELECT * FROM session_narratives ORDER BY session_ts"):
        topics_json = row["topics_json"] or "[]"
        topics_list = json.loads(topics_json)
        # Normalize topic names
        norm_topics = [_normalize(t) for t in topics_list]

        stats = {}
        if row["duration_turns"]:
            stats["total"] = row["duration_turns"]
        if row["session_success_rate"] is not None:
            stats["success_rate"] = row["session_success_rate"]

        if not dry_run:
            new.execute(
                """INSERT OR IGNORE INTO sessions
                   (session_id, started, skill, topics_json, summary,
                    next_strategy, confusions_json, stats_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["session_ts"],
                    row["session_ts"],
                    row["skill"],
                    json.dumps(norm_topics),
                    row["summary"] or "",
                    row["next_session_strategy"] or "",
                    row["key_confusions_json"] or "[]",
                    json.dumps(stats),
                ),
            )
        sn_count += 1

    # --- Migrate learning_exchanges -> exchanges + errors ---
    ex_count = 0
    err_count = 0
    for row in old.execute("SELECT * FROM learning_exchanges ORDER BY exchange_id"):
        topic_name = topic_map.get(row["topic_id"], "unknown")
        norm_topic = _normalize(topic_name)
        norm_concept = _normalize(row["concept_text"] or "")

        if not norm_concept:
            continue

        if not dry_run:
            new.execute(
                """INSERT INTO exchanges
                   (session_id, ts, turn, topic, concept, question, answer,
                    correct, correction, error_type, misconception, skill)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["session_ts"],
                    row["session_ts"],
                    row["turn_number"],
                    norm_topic,
                    norm_concept,
                    row["question_text"] or "",
                    row["answer_text"] or "",
                    row["answer_correct"],
                    row["correction_text"] or "",
                    row["error_type"] or "",
                    row["misconception"] or "",
                    row["skill"] or "",
                ),
            )

            # Create error entries for wrong answers with misconceptions
            if row["answer_correct"] == 0 and row["misconception"]:
                new.execute(
                    """INSERT INTO errors
                       (ts, topic, concept, error_type, misconception, correction)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        row["session_ts"],
                        norm_topic,
                        norm_concept,
                        row["error_type"] or "",
                        row["misconception"],
                        row["correction_text"] or "",
                    ),
                )
                err_count += 1

        ex_count += 1

    # --- Migrate concept_mastery -> concepts ---
    cm_count = 0
    for row in old.execute("SELECT * FROM concept_mastery ORDER BY concept_id"):
        topic_name = topic_map.get(row["topic_id"], "unknown")
        norm_topic = _normalize(topic_name)
        norm_concept = _normalize(row["concept_text"] or "")

        if not norm_concept:
            continue

        right = row["times_confirmed"] or 0
        wrong = row["times_missed"] or 0
        status = row["status"] or "unknown"
        if status not in ("known", "partial", "unknown"):
            status = "known" if right >= 2 and right > wrong else (
                "partial" if right >= 1 else "unknown"
            )

        if not dry_run:
            new.execute(
                """INSERT OR IGNORE INTO concepts
                   (topic, concept, status, times_right, times_wrong,
                    last_error_type, last_misconception, last_tested)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    norm_topic,
                    norm_concept,
                    status,
                    right,
                    wrong,
                    row["error_type"] or "",
                    row["misconception"] or "",
                    row["last_updated"] or "",
                ),
            )
        cm_count += 1

    # --- Migrate document_sessions -> doc_progress ---
    dp_count = 0
    for row in old.execute("SELECT * FROM document_sessions ORDER BY doc_id"):
        if not dry_run:
            new.execute(
                """INSERT OR IGNORE INTO doc_progress
                   (doc_path, session_count, last_studied, concepts_known, concepts_gap)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    row["doc_path"],
                    row["session_count"] or 0,
                    row["last_studied"] or "",
                    row["concepts_understood"] or "[]",
                    row["concepts_missed"] or "[]",
                ),
            )
        dp_count += 1

    if not dry_run:
        new.commit()

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}Migration complete:")
    print(f"  Sessions:   {sn_count}")
    print(f"  Exchanges:  {ex_count}")
    print(f"  Errors:     {err_count}")
    print(f"  Concepts:   {cm_count}")
    print(f"  Doc progress: {dp_count}")
    print(f"  Target DB:  {target}")

    old.close()
    new.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate old KG DB to study_memory.db")
    parser.add_argument("--source", required=True, help="Path to old knowledge_graph.db")
    parser.add_argument("--target", default=str(DB_PATH), help="Path to new study_memory.db")
    parser.add_argument("--dry-run", action="store_true", help="Print counts without writing")
    args = parser.parse_args()

    source = Path(args.source)
    target = Path(args.target)

    if not source.exists():
        print(f"ERROR: source DB not found: {source}")
        sys.exit(1)

    if target.exists() and not args.dry_run:
        print(f"WARNING: target DB already exists: {target}")
        print("Migration will INSERT OR IGNORE (skip duplicates).")

    migrate(source, target, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
