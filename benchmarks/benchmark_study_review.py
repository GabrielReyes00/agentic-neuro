#!/usr/bin/env python3
"""Measure study-review instruction and startup-state context on a safe DB copy."""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import instruction_audit  # noqa: E402
import study_memory  # noqa: E402
from runtime_paths import STUDY_MEMORY_DB  # noqa: E402


def _tokens(text: str) -> int:
    return len(instruction_audit._load_cl100k().encode(text))


def _safe_database(source: Path, target: Path) -> None:
    if not source.is_file():
        return
    source_conn = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def _topic(conn: sqlite3.Connection, requested: str) -> str:
    if requested:
        return requested
    row = conn.execute(
        """SELECT t.canonical_slug, COUNT(cr.id) AS n
             FROM topics t LEFT JOIN claim_results cr ON cr.topic_id = t.id
            GROUP BY t.id ORDER BY n DESC, t.id LIMIT 1"""
    ).fetchone()
    return str(row[0]) if row else "subarachnoid hemorrhage"


def run(*, database: Path, topic: str = "", repeat: int = 7) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="study-review-benchmark-") as tmp:
        copied = Path(tmp) / "study_memory.db"
        _safe_database(database, copied)
        conn = study_memory._get_db(copied)
        try:
            selected_topic = _topic(conn, topic)
            timings: dict[str, list[float]] = {"audit": [], "tutor": []}
            payloads: dict[str, str] = {}
            for profile in ("audit", "tutor"):
                for _ in range(max(1, repeat)):
                    started = time.perf_counter()
                    payloads[profile] = study_memory.startup_recall(
                        conn, topic=selected_topic, profile=profile
                    )
                    timings[profile].append((time.perf_counter() - started) * 1000)
            audit_tokens = _tokens(payloads["audit"])
            tutor_tokens = _tokens(payloads["tutor"])
            tutor_payload = json.loads(payloads["tutor"])
            state = tutor_payload["tutor_state"]
            instruction = instruction_audit.measure()["runtime_startup"]["workflows"]["study-review"]
            result = {
                "schema_version": 1,
                "database_source": str(database),
                "database_was_copied": database.is_file(),
                "topic": selected_topic,
                "instruction_entry": instruction,
                "startup_state": {
                    "audit_tokens": audit_tokens,
                    "tutor_tokens": tutor_tokens,
                    "reduction_tokens": audit_tokens - tutor_tokens,
                    "reduction_pct": round((1 - tutor_tokens / max(1, audit_tokens)) * 100, 1),
                    "audit_median_ms": round(statistics.median(timings["audit"]), 3),
                    "tutor_median_ms": round(statistics.median(timings["tutor"]), 3),
                    "top_level_keys": sorted(tutor_payload),
                    "active_nodes": len(state["knowledge_map"]["active_nodes"]),
                    "omitted_nodes": state["knowledge_map"]["omitted_nodes"],
                    "nearby_nodes": len(state["context_expansion"]["nearby_nodes"]),
                    "maximum_hops": state["context_expansion"]["maximum_hops"],
                },
            }
            checks = {
                "instruction_entry_under_3000": int(instruction["selected_tokens"]) <= 3000,
                "startup_state_smaller_than_audit": tutor_tokens < audit_tokens,
                "active_node_cap": len(state["knowledge_map"]["active_nodes"]) <= 8,
                "one_hop_cap": state["context_expansion"]["maximum_hops"] == 1,
                "bounded_top_level": set(tutor_payload) == {
                    "startup_recall", "tutor_state", "retrieval_guidance"
                },
            }
            result["checks"] = checks
            result["ok"] = all(checks.values())
            return result
        finally:
            conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=STUDY_MEMORY_DB)
    parser.add_argument("--topic", default="")
    parser.add_argument("--repeat", type=int, default=7)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = run(database=args.database, topic=args.topic, repeat=args.repeat)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if (not args.check or result["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
