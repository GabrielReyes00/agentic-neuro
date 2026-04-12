#!/usr/bin/env python3
"""One-time migration: recompute stability_factor, difficulty, and confidence
from signal_events history.

Replays each topic's signal history chronologically with the new
stability-aware decay model to produce meaningful confidence values.

Usage:
    python3 scripts/recompute_confidence.py              # dry-run
    python3 scripts/recompute_confidence.py --apply       # apply changes
    python3 scripts/recompute_confidence.py --verbose     # show per-topic details
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge_graph.db"

# Must match knowledge_graph.py definitions exactly.
SIGNAL_DELTAS: dict[str, float] = {
    "query": 0.03,
    "lecture_received": 0.08,
    "card_created": 0.05,
    "correct_recall": 0.12,
    "partial_recall": 0.04,
    "incorrect_recall": -0.10,
    "weakness_identified": -0.15,
    "anki_review": 0.0,
}

SIGNAL_QUALITY_WEIGHTS: dict[str, float] = {
    "correct_recall": 1.0,
    "drill": 0.8,
    "anki_review": 0.6,
    "study_session": 0.5,
    "lecture_received": 0.4,
    "partial_recall": 0.3,
    "socratic_response": 0.5,
    "card_created": 0.2,
    "query": 0.1,
    "deepening_query": 0.15,
    "incorrect_recall": 0.0,
    "weakness_identified": 0.0,
}


def compute_stability(encounter_count: int, signal_quality_sum: float,
                       signal_type_count: int) -> float:
    encounter_bonus = math.log2(1 + encounter_count)
    diversity_bonus = min(1.0, signal_type_count * 0.25)
    raw = 1.0 + encounter_bonus + signal_quality_sum + diversity_bonus
    return max(1.0, min(10.0, raw))


def compute_difficulty(correct_count: int, incorrect_count: int) -> float:
    total = correct_count + incorrect_count + 2
    error_rate = (incorrect_count + 1) / total
    return max(0.1, min(1.0, error_rate))


def parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        ts_str = ts_str.strip()
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def replay_confidence(events: list[dict], stability: float, depth: int,
                       now: datetime) -> float:
    """Replay signal events chronologically to compute current confidence.

    For each event: decay from previous timestamp, then apply delta.
    After the last event, decay to now.
    """
    conf = 0.0
    prev_ts = None

    for ev in events:
        ev_ts = parse_ts(ev["timestamp"])
        if ev_ts is None:
            continue

        # Apply decay from previous event to this one
        if prev_ts is not None:
            hours = (ev_ts - prev_ts).total_seconds() / 3600
            if hours > 0:
                ev_depth = ev.get("depth_at_event") or 1
                half_life = 48 * (2 ** max(0, ev_depth - 1)) * stability
                conf = conf * (0.5 ** (hours / half_life))

        # Apply signal delta
        stored_delta = ev.get("confidence_delta")
        sig_type = ev["signal_type"]

        if sig_type == "study_session":
            # Reconstruct delta from metadata (log_study_session stores 0.0
            # in confidence_delta and applies its own computed delta separately)
            meta = ev.get("_meta", {})
            n_understood = len(meta.get("understood", []))
            n_gaps = len(meta.get("gaps", []))
            total = n_understood + n_gaps
            if total == 0:
                delta = 0.02
            elif n_gaps == 0:
                delta = 0.06 + min(0.04, n_understood * 0.01)
            elif n_understood == 0:
                delta = -0.03 - min(0.04, n_gaps * 0.01)
            else:
                ratio = n_understood / total
                delta = (ratio * 0.08) - ((1 - ratio) * 0.04)
        elif stored_delta is not None and stored_delta != 0.0:
            delta = stored_delta
        else:
            delta = SIGNAL_DELTAS.get(sig_type, 0.0)

        conf = max(0.0, min(1.0, conf + delta))
        prev_ts = ev_ts

    # Apply decay from last event to now
    if prev_ts is not None:
        hours = (now - prev_ts).total_seconds() / 3600
        if hours > 0:
            half_life = 48 * (2 ** max(0, depth - 1)) * stability
            conf = conf * (0.5 ** (hours / half_life))

    return max(0.0, min(1.0, conf))


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute confidence with stability model")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument("--verbose", action="store_true", help="Show per-topic details")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Ensure columns exist
    for col_sql in [
        "ALTER TABLE topics ADD COLUMN stability_factor REAL DEFAULT 1.0",
        "ALTER TABLE topics ADD COLUMN difficulty REAL DEFAULT 0.5",
    ]:
        try:
            conn.execute(col_sql)
            conn.commit()
        except Exception:
            pass

    now = datetime.now(timezone.utc)

    # Get all studied topics
    topics = conn.execute(
        "SELECT topic_id, display_name, confidence, depth, encounter_count "
        "FROM topics WHERE encounter_count > 0 ORDER BY encounter_count DESC"
    ).fetchall()

    print(f"Topics with encounters: {len(topics)}")
    print(f"{'=' * 70}")

    # Pre-state summary
    confs = [t["confidence"] for t in topics]
    avg_pre = sum(confs) / len(confs) if confs else 0
    max_pre = max(confs) if confs else 0
    print(f"PRE-STATE:  avg={avg_pre:.4f}  max={max_pre:.4f}")
    print()

    results: list[dict] = []

    for topic in topics:
        tid = topic["topic_id"]

        # Get all signals for this topic, chronological
        events = conn.execute(
            "SELECT signal_type, timestamp, depth_at_event, confidence_delta, metadata "
            "FROM signal_events WHERE topic_id = ? ORDER BY timestamp ASC",
            (tid,),
        ).fetchall()

        # Compute stability and difficulty from signal distribution
        sig_counts: dict[str, int] = {}
        correct = 0
        incorrect = 0
        for ev in events:
            st = ev["signal_type"]
            sig_counts[st] = sig_counts.get(st, 0) + 1
            if st in ("correct_recall", "drill"):
                correct += 1
            elif st in ("incorrect_recall", "weakness_identified"):
                incorrect += 1

        quality_sum = sum(
            SIGNAL_QUALITY_WEIGHTS.get(st, 0.0) * cnt
            for st, cnt in sig_counts.items()
        )

        stability = compute_stability(topic["encounter_count"], quality_sum, len(sig_counts))
        difficulty = compute_difficulty(correct, incorrect)

        # Replay confidence from signal history (parse metadata for study_session delta reconstruction)
        ev_dicts = []
        for e in events:
            d = dict(e)
            try:
                d["_meta"] = json.loads(d.get("metadata") or "{}")
            except Exception:
                d["_meta"] = {}
            ev_dicts.append(d)
        new_conf = replay_confidence(ev_dicts, stability, topic["depth"], now)

        results.append({
            "topic_id": tid,
            "display_name": topic["display_name"],
            "old_confidence": topic["confidence"],
            "new_confidence": new_conf,
            "stability_factor": stability,
            "difficulty": difficulty,
            "encounter_count": topic["encounter_count"],
            "depth": topic["depth"],
        })

        if args.verbose:
            print(f"  [{tid:3d}] enc={topic['encounter_count']:2d} d={topic['depth']} "
                  f"stab={stability:.2f} diff={difficulty:.2f} "
                  f"conf {topic['confidence']:.4f} -> {new_conf:.4f}  "
                  f"| {topic['display_name'][:50]}")

    # Post-state summary
    new_confs = [r["new_confidence"] for r in results]
    avg_post = sum(new_confs) / len(new_confs) if new_confs else 0
    max_post = max(new_confs) if new_confs else 0
    min_post = min(new_confs) if new_confs else 0
    variance = (sum(c * c for c in new_confs) / len(new_confs) - avg_post ** 2) if new_confs else 0
    stddev = variance ** 0.5

    print()
    print(f"POST-STATE: avg={avg_post:.4f}  min={min_post:.4f}  max={max_post:.4f}  stddev={stddev:.4f}")
    print()

    # Bucket distribution
    buckets = {"0.00": 0, "0.00-0.05": 0, "0.05-0.10": 0, "0.10-0.20": 0,
               "0.20-0.30": 0, "0.30-0.50": 0, "0.50+": 0}
    for c in new_confs:
        if c == 0:
            buckets["0.00"] += 1
        elif c < 0.05:
            buckets["0.00-0.05"] += 1
        elif c < 0.10:
            buckets["0.05-0.10"] += 1
        elif c < 0.20:
            buckets["0.10-0.20"] += 1
        elif c < 0.30:
            buckets["0.20-0.30"] += 1
        elif c < 0.50:
            buckets["0.30-0.50"] += 1
        else:
            buckets["0.50+"] += 1

    print("Confidence distribution:")
    for bucket, count in buckets.items():
        bar = "#" * count
        print(f"  {bucket:>10}: {count:3d} {bar}")

    # Encounter correlation
    high_enc = [r for r in results if r["encounter_count"] >= 5]
    low_enc = [r for r in results if r["encounter_count"] < 5]
    if high_enc and low_enc:
        avg_high = sum(r["new_confidence"] for r in high_enc) / len(high_enc)
        avg_low = sum(r["new_confidence"] for r in low_enc) / len(low_enc)
        print(f"\nEncounter correlation:")
        print(f"  5+ encounters ({len(high_enc)} topics): avg conf = {avg_high:.4f}")
        print(f"  1-4 encounters ({len(low_enc)} topics): avg conf = {avg_low:.4f}")
        print(f"  Ratio: {avg_high / avg_low:.1f}x" if avg_low > 0 else "")

    # Stability distribution
    stabs = [r["stability_factor"] for r in results]
    print(f"\nStability factor: min={min(stabs):.2f}  max={max(stabs):.2f}  "
          f"avg={sum(stabs) / len(stabs):.2f}")

    if not args.apply:
        print(f"\n{'=' * 70}")
        print("DRY RUN -- no changes written. Use --apply to commit.")
        return

    # Backup
    backup_path = DB_PATH.with_suffix(".db.pre_stability_backup")
    shutil.copy2(DB_PATH, backup_path)
    print(f"\nBackup saved: {backup_path}")

    # Apply
    for r in results:
        conn.execute(
            "UPDATE topics SET confidence = ?, stability_factor = ?, difficulty = ?, "
            "       last_decay_ts = ? WHERE topic_id = ?",
            (r["new_confidence"], r["stability_factor"], r["difficulty"],
             now.isoformat(), r["topic_id"]),
        )
    conn.commit()
    conn.close()

    print(f"Applied: {len(results)} topics updated.")
    print(f"Backup at: {backup_path}")


if __name__ == "__main__":
    main()
