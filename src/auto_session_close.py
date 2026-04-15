#!/usr/bin/env python3
"""Auto-consolidate session memory on agent exit.

Fires via AfterAgent (Gemini) and Stop (Claude) hooks. Idempotent — safe to
run even when the post-session hook already ran explicitly. Only acts when
there are recent unembedded exchanges.

What it does:
  1. Finds exchanges from the last LOOKBACK_HOURS with no LanceDB embedding
  2. Writes a minimal session narrative if none exists for the session
     (so next session has strategy/confusion context from preflight)
  3. Embeds unembedded exchanges into LanceDB via consolidate_episodic_memory
  4. Derives confusion pairs from recent confusion-type errors

What it does NOT do:
  - Write vault files (no agent context available)
  - Regenerate Dashboard/ACGME Readiness
  - Override a narrative already written by an explicit session end

Usage (shell):
  python3 src/auto_session_close.py   # reads hook JSON from stdin
"""

from __future__ import annotations

import json
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
from collections.abc import Mapping

from kg_constants import BASE_DIR
sys.path.insert(0, str(BASE_DIR / "src"))

LOOKBACK_HOURS = 4

_CLAUDE_HOOKS = frozenset({
    "Stop", "PreCompact", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Notification",
})


def _hook_event_name(payload: Mapping[str, object]) -> str:
    return str(payload.get("hook_event_name") or payload.get("hookEventName") or "").strip()


def _is_structured_hook(payload: Mapping[str, object]) -> bool:
    """True when invoked by any structured hook (Gemini or Claude)."""
    return bool(_hook_event_name(payload))


def _silent_ok() -> None:
    print(json.dumps({"suppressOutput": True}))


def _find_recent_unembedded(kg, cutoff: str) -> list[sqlite3.Row]:
    """Return distinct (session_ts, skill) rows with unembedded exchanges."""
    return kg.conn.execute(
        """SELECT DISTINCT le.session_ts, le.skill
           FROM learning_exchanges le
           WHERE le.session_ts >= ?
             AND (le.consolidated_at IS NULL OR le.consolidated_at = ''
                  OR le.lance_row_id IS NULL OR le.lance_row_id = '')
           ORDER BY le.session_ts DESC LIMIT 5""",
        (cutoff,),
    ).fetchall()


def _topic_names(kg, session_ts: str) -> list[str]:
    rows = kg.conn.execute(
        """SELECT DISTINCT t.display_name
           FROM learning_exchanges le
           LEFT JOIN topics t ON le.topic_id = t.topic_id
           WHERE le.session_ts = ?
           LIMIT 8""",
        (session_ts,),
    ).fetchall()
    return [r["display_name"] for r in rows if r["display_name"]]


def _narrative_exists(kg, session_ts: str, skill: str) -> bool:
    row = kg.conn.execute(
        """SELECT narrative_id FROM session_narratives
           WHERE session_ts >= ? AND skill = ?
           ORDER BY session_ts DESC LIMIT 1""",
        (session_ts, skill),
    ).fetchone()
    return row is not None


def _write_auto_narrative(kg, session_ts: str, skill: str, topics: list[str]) -> None:
    """Write a minimal session narrative for next-session context."""
    topic_str = ", ".join(topics) if topics else "general"

    error_rows: list[sqlite3.Row] = kg.conn.execute(
        """SELECT concept_text, error_type, misconception
           FROM learning_exchanges
           WHERE session_ts = ? AND answer_correct = 0
           LIMIT 5""",
        (session_ts,),
    ).fetchall()

    partial_rows: list[sqlite3.Row] = kg.conn.execute(
        """SELECT concept_text FROM learning_exchanges
           WHERE session_ts = ? AND answer_correct = 1
           LIMIT 3""",
        (session_ts,),
    ).fetchall()

    total = kg.conn.execute(
        "SELECT COUNT(*) AS n FROM learning_exchanges WHERE session_ts = ?",
        (session_ts,),
    ).fetchone()["n"]

    correct = kg.conn.execute(
        "SELECT COUNT(*) AS n FROM learning_exchanges WHERE session_ts = ? AND answer_correct = 2",
        (session_ts,),
    ).fetchone()["n"]

    summary_parts = [f"Auto-closed session on {topic_str}. {correct}/{total} correct."]
    if error_rows:
        misses = [r["concept_text"] for r in error_rows if r["concept_text"]]
        summary_parts.append(f"Misses: {', '.join(misses[:3])}.")

    strategy_parts = [f"Resume {topic_str}."]
    if error_rows:
        strategy_parts.append("Re-test missed concepts first before advancing.")
    if partial_rows:
        partials = [r["concept_text"] for r in partial_rows if r["concept_text"]]
        strategy_parts.append(f"Repair partial answers on: {', '.join(partials[:2])}.")

    kg.log_session_narrative(
        skill=skill,
        topics=topics if topics else [topic_str],
        summary=" ".join(summary_parts),
        next_session_strategy=" ".join(strategy_parts),
        teaching_failures=[],
        key_confusions=[],
        duration_turns=total,
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    structured = _is_structured_hook(payload)

    try:
        from knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
    except Exception:
        if structured:
            _silent_ok()
        return 0

    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).isoformat()
        unembedded = _find_recent_unembedded(kg, cutoff)

        if not unembedded:
            kg.close()
            if structured:
                _silent_ok()
            return 0

        # Most-recent session is primary target
        session_ts = unembedded[0]["session_ts"]
        skill = unembedded[0]["skill"] or "ad-hoc"
        topics = _topic_names(kg, session_ts)

        # Write minimal narrative only if none exists (don't clobber explicit session end)
        if not _narrative_exists(kg, session_ts, skill):
            _write_auto_narrative(kg, session_ts, skill, topics)

        # Embed all unembedded exchanges (up to 5 sessions) into LanceDB
        kg.consolidate_episodic_memory(limit=5, fallback_skill=skill)

        # Derive confusion pairs from recent confusion-type errors
        kg.derive_session_confusions(session_ts=session_ts, skill=skill)

        kg.close()
    except Exception:
        try:
            kg.close()
        except Exception:
            pass

    if structured:
        _silent_ok()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
