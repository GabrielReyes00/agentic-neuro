"""Typed study-review lifecycle and learner-stage context.

This module keeps session-envelope validation and integrity checks separate from
the large compatibility ledger.  Callers inject recall/close functions, which
avoids a circular dependency while leaving SQLite as the sole durable authority.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable


def learner_profile_get(conn: sqlite3.Connection) -> dict[str, object]:
    row = conn.execute("SELECT * FROM learner_profile WHERE id = 1").fetchone()
    if row is None:
        return {
            "current_pgy": None,
            "active_service": "",
            "expected_responsibilities": [],
            "domain_expectations": {},
        }

    def parsed(value: str, fallback: object) -> object:
        try:
            return json.loads(value or "")
        except (TypeError, ValueError):
            return fallback

    return {
        "current_pgy": row["current_pgy"],
        "active_service": row["active_service"] or "",
        "expected_responsibilities": parsed(row["expected_responsibilities_json"], []),
        "domain_expectations": parsed(row["domain_expectations_json"], {}),
        "updated_at": row["updated_at"] or "",
        "interpretation": (
            "PGY and service set expected responsibility only; observed, concept-specific "
            "performance sets scaffolding and mastery."
        ),
    }


def learner_profile_upsert(
    conn: sqlite3.Connection, payload: dict[str, object]
) -> dict[str, object]:
    pgy = payload.get("current_pgy")
    if pgy is not None and (not isinstance(pgy, int) or not 1 <= pgy <= 7):
        raise ValueError("current_pgy must be an integer from 1 through 7")
    responsibilities = payload.get("expected_responsibilities", [])
    domains = payload.get("domain_expectations", {})
    if not isinstance(responsibilities, list):
        raise ValueError("expected_responsibilities must be a list")
    if not isinstance(domains, dict):
        raise ValueError("domain_expectations must be an object")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO learner_profile
           (id, current_pgy, active_service, expected_responsibilities_json,
            domain_expectations_json, updated_at)
           VALUES (1, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             current_pgy=COALESCE(excluded.current_pgy, learner_profile.current_pgy),
             active_service=excluded.active_service,
             expected_responsibilities_json=excluded.expected_responsibilities_json,
             domain_expectations_json=excluded.domain_expectations_json,
             updated_at=excluded.updated_at""",
        (
            pgy,
            str(payload.get("active_service") or ""),
            json.dumps(responsibilities, sort_keys=True),
            json.dumps(domains, sort_keys=True),
            now,
        ),
    )
    conn.commit()
    return {"ok": True, **learner_profile_get(conn)}


def set_study_runtime(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    lifecycle_node: str,
    profile: str = "",
    topic_id: int | None = None,
    doc_path: str = "",
    now: str | None = None,
) -> None:
    timestamp = now or datetime.now(timezone.utc).isoformat()
    closed = timestamp if lifecycle_node == "done" else ""
    conn.execute(
        """INSERT INTO study_runtime_sessions
           (session_id, lifecycle_node, profile, topic_id, doc_path,
            tutor_state_version, started_at, updated_at, closed_at)
           VALUES (?, ?, ?, ?, ?, 'tutor_state_v1', ?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET
             lifecycle_node=excluded.lifecycle_node,
             profile=CASE WHEN excluded.profile != '' THEN excluded.profile ELSE study_runtime_sessions.profile END,
             topic_id=COALESCE(excluded.topic_id, study_runtime_sessions.topic_id),
             doc_path=CASE WHEN excluded.doc_path != '' THEN excluded.doc_path ELSE study_runtime_sessions.doc_path END,
             tutor_state_version=excluded.tutor_state_version,
             updated_at=excluded.updated_at,
             closed_at=CASE WHEN excluded.closed_at != '' THEN excluded.closed_at ELSE study_runtime_sessions.closed_at END""",
        (session_id, lifecycle_node, profile, topic_id, doc_path, timestamp, timestamp, closed),
    )


def start_session(
    conn: sqlite3.Connection,
    payload: dict[str, object],
    *,
    startup_recall: Callable[..., str],
) -> dict[str, object]:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("start-session requires session_id")
    mode = str(payload.get("mode") or "topic").strip().lower()
    if mode not in {"document", "topic", "memory"}:
        if mode == "service":
            raise ValueError(
                "service-local teaching is provenance-isolated; use shift-debrief/service-log, "
                "not study-review start-session"
            )
        raise ValueError("start-session mode must be document, topic, or memory")
    if str(payload.get("lens") or "general").strip().lower() == "service":
        raise ValueError("study-review cannot use the service lens; use shift-debrief/service-log")
    topic = str(payload.get("topic") or "").strip()
    doc_path = str(payload.get("doc_path") or "").strip()
    global_mode = mode == "memory" and not topic and not doc_path
    if mode == "document" and not doc_path:
        raise ValueError("document mode requires doc_path")
    if not global_mode and not (topic or doc_path):
        raise ValueError("start-session requires topic or doc_path unless mode=memory")
    return json.loads(startup_recall(
        conn,
        topic=topic,
        doc_path=doc_path,
        global_mode=global_mode,
        context=str(payload.get("context") or ""),
        lens=str(payload.get("lens") or "general"),
        profile="tutor",
        session_id=session_id,
    ))


def session_integrity(conn: sqlite3.Connection, *, session_id: str) -> dict[str, object]:
    exchanges = conn.execute(
        """SELECT e.id,
                  EXISTS(SELECT 1 FROM turn_assessments ta WHERE ta.exchange_id = e.id) AS has_turn,
                  EXISTS(SELECT 1 FROM anki_card_decisions d WHERE d.exchange_id = e.id) AS has_card
             FROM exchanges e
            WHERE e.session_id = ? AND e.skill = 'study-review'
            ORDER BY e.id""",
        (session_id,),
    ).fetchall()
    missing_turns = [int(row["id"]) for row in exchanges if not row["has_turn"]]
    missing_cards = [int(row["id"]) for row in exchanges if not row["has_card"]]
    missing_dimensions = [
        int(row["id"])
        for row in conn.execute(
            """SELECT cr.id FROM claim_results cr
                 JOIN exchanges e ON e.id = cr.exchange_id
                 LEFT JOIN claim_assessments ca ON ca.claim_result_id = cr.id
                WHERE e.session_id = ? AND e.skill = 'study-review' AND ca.id IS NULL
                ORDER BY cr.id""",
            (session_id,),
        ).fetchall()
    ]
    pending = [
        {
            "assessment_id": int(row["id"]),
            "concept": str(row["concept"]),
            "verification_status": str(row["verification_status"] or ""),
        }
        for row in conn.execute(
            """SELECT ca.id, ca.concept, ca.verification_status
                 FROM claim_assessments ca JOIN exchanges e ON e.id = ca.exchange_id
                WHERE e.session_id = ? AND ca.assessment_status = 'pending_adjudication'
                ORDER BY ca.id""",
            (session_id,),
        ).fetchall()
    ]
    blockers = []
    if missing_turns:
        blockers.append(f"exchanges missing typed turn envelopes: {missing_turns}")
    if missing_cards:
        blockers.append(f"exchanges missing card decisions: {missing_cards}")
    if missing_dimensions:
        blockers.append(f"graded claim results missing dimensions: {missing_dimensions}")
    return {
        "ok": not blockers,
        "session_id": session_id,
        "assessed_exchanges": len(exchanges),
        "pending_adjudication": pending,
        "blockers": blockers,
    }


def close_session(
    conn: sqlite3.Connection,
    payload: dict[str, object],
    *,
    end_session: Callable[..., dict[str, Any]],
) -> dict[str, object]:
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("close-session requires session_id")
    summary = str(payload.get("summary") or "").strip()
    next_strategy = str(payload.get("next_strategy") or "").strip()
    if not summary or not next_strategy:
        raise ValueError("close-session requires summary and next_strategy")
    stats = payload.get("stats", {})
    if not isinstance(stats, dict):
        raise ValueError("close-session stats must be an object")
    integrity = session_integrity(conn, session_id=session_id)
    if not integrity["ok"]:
        raise ValueError(
            "study-review session integrity blockers: "
            + "; ".join(str(item) for item in integrity["blockers"])
        )
    return end_session(
        conn,
        session_id=session_id,
        summary=summary,
        next_strategy=next_strategy,
        stats_json=json.dumps(stats, separators=(",", ":")),
    )
