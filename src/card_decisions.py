"""Explicit per-exchange Anki card decisions for learner memory."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


VALID_CARD_DECISIONS = frozenset(
    {
        "enqueue",
        "skip_routine_correct",
        "skip_equivalent",
        "skip_low_value",
        "skip_not_durable",
        "defer_unavailable",
    }
)


def record_anki_card_decision(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    exchange_id: int,
    decision: str,
    rationale: str = "",
    commit: bool = True,
) -> dict[str, object]:
    """Persist one explicit card/no-card judgment for an assessed exchange."""
    if decision not in VALID_CARD_DECISIONS:
        raise ValueError(f"invalid Anki card decision: {decision}")
    exchange = conn.execute(
        "SELECT id, session_id FROM exchanges WHERE id = ?",
        (exchange_id,),
    ).fetchone()
    if exchange is None:
        raise ValueError(f"unknown exchange_id: {exchange_id}")
    if str(exchange["session_id"]) != session_id:
        raise ValueError(
            f"exchange {exchange_id} belongs to session {exchange['session_id']!r}, "
            f"not {session_id!r}"
        )
    rationale = rationale.strip()
    if decision != "enqueue" and not rationale:
        raise ValueError(f"{decision} requires a rationale")
    decided_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO anki_card_decisions
              (exchange_id, session_id, decision, rationale, decided_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(exchange_id) DO UPDATE SET
               session_id = excluded.session_id,
               decision = excluded.decision,
               rationale = excluded.rationale,
               decided_at = excluded.decided_at""",
        (exchange_id, session_id, decision, rationale, decided_at),
    )
    if commit:
        conn.commit()
    return {
        "exchange_id": exchange_id,
        "session_id": session_id,
        "decision": decision,
        "rationale": rationale,
        "decided_at": decided_at,
    }


def card_decision_rows(
    conn: sqlite3.Connection,
    session_id: str,
) -> list[dict[str, object]]:
    """Return one decision row per assessed exchange in a session."""
    rows = conn.execute(
        """SELECT e.id AS exchange_id,
                  e.session_id,
                  c.display_name AS concept,
                  MIN(cr.score) AS minimum_score,
                  d.decision,
                  d.rationale
             FROM exchanges e
             JOIN claim_results cr ON cr.exchange_id = e.id
             JOIN concepts c ON c.id = e.concept_id
             LEFT JOIN anki_card_decisions d ON d.exchange_id = e.id
            WHERE e.session_id = ?
            GROUP BY e.id, e.session_id, c.display_name, d.decision, d.rationale
            ORDER BY e.turn, e.id""",
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]
