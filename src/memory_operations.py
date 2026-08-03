"""Deterministic helpers for the curation and graph layers of study memory.

This module is the bridge between the agent and the SQLite store. It prepares
evidence (candidate packets), validates and applies agent-authored curation
payloads, and tracks the rolling curation counter. It does not summarize, call
an LLM, or fabricate edges.

Schema lives in ``study_memory.py``; this module assumes the connection it
receives was opened via ``study_memory._get_db`` (so SCHEMA_SQL ran and the
``curation_state`` singleton row exists).
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

CURATION_THRESHOLD = 5

DEFAULT_RECENT_SESSIONS = 5
DEFAULT_CLAIM_RESULTS_LIMIT = 80
HIGH_PRIORITY_STATES = ("missed", "partially_repaired", "regressed")
HIGH_PRIORITIES = ("urgent", "high")
EXISTING_SUMMARIES_CAP = 12
RELATIONSHIP_HINT_CAP = 20
ALLOWED_SUMMARY_TYPES = frozenset({"thematic", "proficiency_map"})
ALLOWED_RELATION_TYPES = frozenset({"confused_with", "prerequisite"})
ALLOWED_SHADOW_SEVERITIES = frozenset({"low", "medium", "high", "urgent"})
ALLOWED_SHADOW_BINDING_TYPES = frozenset({"trigger", "contrast", "context"})
ACTIVE_STATUS = "active"
SUPERSEDED_STATUS = "superseded"

COMPACT_CLAIM_TEXT_LIMIT = 240
COMPACT_SUMMARY_TEXT_LIMIT = 600
COMPACT_SESSION_TEXT_LIMIT = 320


class CurationError(Exception):
    """Raised when a curation payload or state transition is invalid."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str | None, limit: int) -> str:
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _estimate_tokens(payload: dict) -> int:
    return max(1, len(json.dumps(payload, ensure_ascii=False)) // 4)


# ---------------------------------------------------------------------------
# Curation state + session counting
# ---------------------------------------------------------------------------


def ensure_curation_state(conn: sqlite3.Connection) -> None:
    """Ensure the singleton ``curation_state`` row exists.

    SCHEMA_SQL already does this, but call sites that hold the connection may
    invoke this defensively (cheap).
    """
    conn.execute("INSERT OR IGNORE INTO curation_state (id) VALUES (1)")


def mark_session_counted(
    conn: sqlite3.Connection,
    session_id: str,
    now: str | None = None,
) -> bool:
    """Mark ``session_id`` as counted toward the next curation pass.

    Returns ``True`` only when this session was newly counted. Re-running
    ``end-session`` for the same session_id is a no-op for the counter, so the
    threshold tracks unique ended sessions.
    """
    ensure_curation_state(conn)
    ts = now or _now()
    cur = conn.execute(
        "INSERT OR IGNORE INTO curation_counted_sessions (session_id, counted_at) VALUES (?, ?)",
        (session_id, ts),
    )
    newly_counted = cur.rowcount == 1
    if newly_counted:
        conn.execute(
            "UPDATE curation_state SET sessions_since_last_curation = sessions_since_last_curation + 1 WHERE id = 1"
        )
    return newly_counted


def curation_status(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_curation_state(conn)
    row = conn.execute(
        "SELECT sessions_since_last_curation, last_curation_ts, last_curation_version FROM curation_state WHERE id = 1"
    ).fetchone()
    sessions_since = int(row["sessions_since_last_curation"]) if row else 0
    return {
        "sessions_since_last_curation": sessions_since,
        "last_curation_ts": row["last_curation_ts"] if row else "",
        "last_curation_version": int(row["last_curation_version"]) if row else 0,
        "threshold": CURATION_THRESHOLD,
        "recommended": sessions_since >= CURATION_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# Candidate packet
# ---------------------------------------------------------------------------


def _resolve_topic_id(conn: sqlite3.Connection, topic_slug_or_hint: str) -> int | None:
    if not topic_slug_or_hint:
        return None
    hint = topic_slug_or_hint.strip().lower()
    row = conn.execute(
        "SELECT id FROM topics WHERE canonical_slug = ?",
        (hint,),
    ).fetchone()
    if row:
        return int(row["id"])
    row = conn.execute(
        "SELECT topic_id FROM topic_aliases WHERE alias = ?",
        (hint,),
    ).fetchone()
    if row:
        return int(row["topic_id"])
    return None


def _recent_sessions(
    conn: sqlite3.Connection,
    *,
    limit: int,
    topic_id: int | None,
) -> list[dict[str, Any]]:
    where = "WHERE ended != ''"
    params: list[Any] = []
    if topic_id is not None:
        where += " AND (s.primary_topic_id = ? OR EXISTS (SELECT 1 FROM session_topics st WHERE st.session_id = s.session_id AND st.topic_id = ?))"
        params.extend([topic_id, topic_id])
    rows = conn.execute(
        f"""SELECT s.session_id, s.ended, s.summary, s.next_strategy, t.canonical_slug AS primary_topic
            FROM sessions s
            LEFT JOIN topics t ON t.id = s.primary_topic_id
            {where}
            ORDER BY s.ended DESC
            LIMIT ?""",
        [*params, limit],
    ).fetchall()
    return [
        {
            "session_id": r["session_id"],
            "ended": r["ended"],
            "primary_topic": r["primary_topic"] or "",
            "summary": _truncate(r["summary"], COMPACT_SESSION_TEXT_LIMIT),
            "next_strategy": _truncate(r["next_strategy"], COMPACT_SESSION_TEXT_LIMIT),
        }
        for r in rows
    ]


def _high_priority_claim_states(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
) -> list[dict[str, Any]]:
    where = "WHERE cs.state IN (?, ?, ?) AND cs.priority IN (?, ?)"
    params: list[Any] = [*HIGH_PRIORITY_STATES, *HIGH_PRIORITIES]
    if topic_id is not None:
        where += " AND cs.topic_id = ?"
        params.append(topic_id)
    rows = conn.execute(
        f"""SELECT cs.id, cs.topic_id, cs.concept_id, cs.claim_text, cs.state, cs.priority,
                   cs.gap_type, cs.last_result_id, cs.last_seen_ts,
                   t.canonical_slug AS topic, c.display_name AS concept
              FROM claim_state cs
              JOIN topics t ON t.id = cs.topic_id
              JOIN concepts c ON c.id = cs.concept_id
              {where}
              ORDER BY CASE cs.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
                       cs.last_seen_ts DESC""",
        params,
    ).fetchall()
    return [
        {
            "claim_state_id": int(r["id"]),
            "topic": r["topic"],
            "concept_id": int(r["concept_id"]),
            "concept": r["concept"],
            "claim": _truncate(r["claim_text"], COMPACT_CLAIM_TEXT_LIMIT),
            "state": r["state"],
            "priority": r["priority"],
            "gap_type": r["gap_type"] or "",
            "last_result_id": int(r["last_result_id"]) if r["last_result_id"] is not None else None,
            "last_seen_ts": r["last_seen_ts"],
        }
        for r in rows
    ]


def _recent_claim_results(
    conn: sqlite3.Connection,
    *,
    limit: int,
    topic_id: int | None,
    mode: str,
) -> list[dict[str, Any]]:
    where = ""
    params: list[Any] = []
    if topic_id is not None:
        where = "WHERE cr.topic_id = ?"
        params.append(topic_id)
    rows = conn.execute(
        f"""SELECT cr.id, cr.topic_id, cr.concept_id, cr.claim_text, cr.score, cr.gap_type,
                   cr.learner_claim, cr.demonstrated_edge, cr.misconception_text,
                   cr.missing_edge, cr.corrected_rule, cr.clinical_consequence,
                   cr.retest_prompt_shape, cr.teaching_intervention, cr.created_at,
                   COALESCE(NULLIF(cr.inventory_concept_id, ''), c.inventory_concept_id, '') AS inventory_concept_id,
                   ex.session_id, ex.skill, t.canonical_slug AS topic, c.display_name AS concept
              FROM claim_results cr
              JOIN exchanges ex ON ex.id = cr.exchange_id
              JOIN topics t ON t.id = cr.topic_id
              JOIN concepts c ON c.id = cr.concept_id
              {where}
              ORDER BY cr.created_at DESC
              LIMIT ?""",
        [*params, limit],
    ).fetchall()
    out = []
    for r in rows:
        record = {
            "claim_result_id": int(r["id"]),
            "session_id": r["session_id"],
            "skill": r["skill"] or "",
            "topic": r["topic"],
            "concept_id": int(r["concept_id"]),
            "inventory_concept_id": str(r["inventory_concept_id"] or ""),
            "concept": r["concept"],
            "claim": _truncate(r["claim_text"], COMPACT_CLAIM_TEXT_LIMIT),
            "score": int(r["score"]),
            "gap_type": r["gap_type"] or "",
            "learner_claim": _truncate(r["learner_claim"], COMPACT_CLAIM_TEXT_LIMIT),
            "demonstrated_edge": _truncate(r["demonstrated_edge"], COMPACT_CLAIM_TEXT_LIMIT),
            "misconception": _truncate(r["misconception_text"], COMPACT_CLAIM_TEXT_LIMIT),
            "missing_edge": _truncate(r["missing_edge"], COMPACT_CLAIM_TEXT_LIMIT),
        }
        if mode == "detailed":
            record["corrected_rule"] = _truncate(r["corrected_rule"], COMPACT_CLAIM_TEXT_LIMIT)
            record["clinical_consequence"] = _truncate(r["clinical_consequence"], COMPACT_CLAIM_TEXT_LIMIT)
            record["retest_prompt_shape"] = _truncate(r["retest_prompt_shape"], COMPACT_CLAIM_TEXT_LIMIT)
            record["teaching_intervention"] = _truncate(r["teaching_intervention"], COMPACT_CLAIM_TEXT_LIMIT)
            record["created_at"] = r["created_at"]
        out.append({
            key: value for key, value in record.items()
            if value not in (None, "", [], {})
        })
    return out


def _existing_summaries(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
) -> tuple[list[dict[str, Any]], int]:
    where = "WHERE ms.status = 'active'"
    params: list[Any] = []
    if topic_id is not None:
        # Topic-scoped queries surface: (a) summaries scoped to this topic, (b) truly
        # global summaries (both topic_id and concept_id NULL), and (c) concept-scoped
        # summaries whose concept belongs to this topic. Concept-scoped summaries do
        # NOT leak into unrelated topic queries.
        where += (
            " AND ("
            "ms.topic_id = ? "
            "OR (ms.topic_id IS NULL AND ms.concept_id IS NULL) "
            "OR (ms.topic_id IS NULL AND ms.concept_id IN (SELECT id FROM concepts WHERE topic_id = ?))"
            ")"
        )
        params.extend([topic_id, topic_id])
    total = int(
        conn.execute(
            f"SELECT COUNT(*) AS n FROM memory_summaries ms {where}",
            params,
        ).fetchone()["n"]
    )
    rows = conn.execute(
        f"""SELECT ms.id, ms.summary_type, ms.topic_id, ms.concept_id, ms.content,
                   ms.importance_score, ms.generated_at, t.canonical_slug AS topic
              FROM memory_summaries ms
              LEFT JOIN topics t ON t.id = ms.topic_id
              {where}
              ORDER BY ms.importance_score DESC, ms.generated_at DESC
              LIMIT ?""",
        [*params, EXISTING_SUMMARIES_CAP],
    ).fetchall()
    out = [
        {
            "summary_id": int(r["id"]),
            "summary_type": r["summary_type"],
            "topic": r["topic"] or "",
            "concept_id": int(r["concept_id"]) if r["concept_id"] is not None else None,
            "content": _truncate(r["content"], COMPACT_SUMMARY_TEXT_LIMIT),
            "importance_score": float(r["importance_score"]),
            "generated_at": r["generated_at"],
        }
        for r in rows
    ]
    omitted = max(0, total - len(out))
    return out, omitted


def _existing_shadow_rules(conn: sqlite3.Connection, *, topic_id: int | None) -> list[dict[str, Any]]:
    where = "WHERE sr.status IN ('active', 'repaired', 'regressed')"
    params: list[Any] = []
    if topic_id is not None:
        where += " AND EXISTS (SELECT 1 FROM shadow_rule_bindings srb JOIN concepts c ON c.id = srb.concept_id WHERE srb.shadow_rule_id = sr.id AND c.topic_id = ?)"
        params.append(topic_id)
    rows = conn.execute(
        f"""SELECT sr.id, sr.false_rule, sr.corrected_rule, sr.clinical_consequence,
                   sr.probe_shape, sr.severity, sr.status, sr.updated_at
              FROM shadow_rules sr
              {where}
             ORDER BY CASE sr.severity WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                      sr.updated_at DESC
             LIMIT 12""",
        params,
    ).fetchall()
    return [
        {
            "shadow_rule_id": int(row["id"]),
            "false_rule": _truncate(row["false_rule"], COMPACT_CLAIM_TEXT_LIMIT),
            "corrected_rule": _truncate(row["corrected_rule"], COMPACT_CLAIM_TEXT_LIMIT),
            "clinical_consequence": _truncate(row["clinical_consequence"], COMPACT_CLAIM_TEXT_LIMIT),
            "probe_shape": _truncate(row["probe_shape"], COMPACT_CLAIM_TEXT_LIMIT),
            "severity": row["severity"],
            "status": row["status"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _retrieval_cards_compact(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
) -> list[dict[str, Any]]:
    where = "WHERE rc.status = 'active' AND rc.card_type IN ('must_retest','session_handoff','recent_repair')"
    params: list[Any] = []
    if topic_id is not None:
        where += " AND rc.topic_id = ?"
        params.append(topic_id)
    rows = conn.execute(
        f"""SELECT rc.id, rc.card_type, rc.priority, rc.summary, rc.claim_state_id,
                   t.canonical_slug AS topic
              FROM retrieval_cards rc
              JOIN topics t ON t.id = rc.topic_id
              {where}
              ORDER BY CASE rc.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                       rc.updated_ts DESC
              LIMIT 30""",
        params,
    ).fetchall()
    return [
        {
            "card_id": int(r["id"]),
            "topic": r["topic"],
            "card_type": r["card_type"],
            "priority": r["priority"],
            "summary": _truncate(r["summary"], COMPACT_CLAIM_TEXT_LIMIT),
            "claim_state_id": int(r["claim_state_id"]) if r["claim_state_id"] is not None else None,
        }
        for r in rows
    ]


def _candidate_relationship_hints(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
    claim_result_ids: Iterable[int],
) -> list[dict[str, Any]]:
    """High-precision, non-assertive hints for personalized graph curation.

    One co-miss is coincidence, not a relationship. Surface a pair only when
    explicit misconception/correction text names the other concept, or when the
    pair recurs across at least two sessions. Canonical-identity duplicates are
    excluded because they need realignment rather than a ``confused_with`` edge.
    """
    cr_ids = list(claim_result_ids)
    if not cr_ids:
        return []
    placeholders = ",".join("?" * len(cr_ids))
    rows = conn.execute(
        f"""SELECT ex.session_id, cr.id AS claim_result_id, cr.concept_id,
                   c.display_name AS concept, cr.gap_type, cr.misconception_text,
                   cr.missing_edge, cr.corrected_rule,
                   COALESCE(NULLIF(cr.inventory_concept_id, ''), c.inventory_concept_id, '') AS inventory_concept_id
              FROM claim_results cr
              JOIN exchanges ex ON ex.id = cr.exchange_id
              JOIN concepts c ON c.id = cr.concept_id
              WHERE cr.id IN ({placeholders}) AND cr.score < 2""",
        cr_ids,
    ).fetchall()
    by_session: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_session.setdefault(r["session_id"], []).append(r)
    pair_support: dict[tuple[int, int], dict[str, Any]] = {}
    generic_tokens = {
        "and", "the", "with", "from", "management", "clinical", "rule",
        "target", "threshold", "treatment", "patient", "concept",
    }

    def tokens(text: str) -> set[str]:
        return {
            word for word in re.findall(r"[a-z0-9]+", text.lower())
            if len(word) > 2 and word not in generic_tokens
        }

    for session_id, entries in by_session.items():
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a, b = entries[i], entries[j]
                ca, cb = int(a["concept_id"]), int(b["concept_id"])
                if ca == cb:
                    continue
                inv_a = str(a["inventory_concept_id"] or "")
                inv_b = str(b["inventory_concept_id"] or "")
                if inv_a and inv_a == inv_b:
                    continue
                pair = (min(ca, cb), max(ca, cb))
                bucket = pair_support.setdefault(pair, {
                    "sessions": set(),
                    "claim_result_ids": set(),
                    "explicit_terms": set(),
                    "explicit": False,
                    "concepts": {
                        ca: str(a["concept"]),
                        cb: str(b["concept"]),
                    },
                })
                bucket["sessions"].add(str(session_id))
                bucket["claim_result_ids"].update({
                    int(a["claim_result_id"]), int(b["claim_result_id"])
                })
                for source, other in ((a, b), (b, a)):
                    if str(source["gap_type"] or "") not in {"conceptual_confusion", "cross_contamination"}:
                        continue
                    evidence_text = " ".join(str(source[field] or "") for field in (
                        "misconception_text", "missing_edge", "corrected_rule"
                    ))
                    shared = tokens(evidence_text) & tokens(str(other["concept"] or ""))
                    if shared:
                        bucket["explicit"] = True
                        bucket["explicit_terms"].update(shared)

    hints: list[dict[str, Any]] = []
    for pair, support in pair_support.items():
        sessions = sorted(support["sessions"])
        explicit = bool(support["explicit"])
        if not explicit and len(sessions) < 2:
            continue
        hints.append({
            "source_concept_id": pair[0],
            "target_concept_id": pair[1],
            "source_concept": support["concepts"].get(pair[0], ""),
            "target_concept": support["concepts"].get(pair[1], ""),
            "hint_type": "explicit_cross_reference" if explicit else "repeated_co_miss",
            "confidence": "high" if explicit and len(sessions) >= 2 else "medium",
            "supporting_session_ids": sessions,
            "supporting_claim_result_ids": sorted(support["claim_result_ids"]),
            "matched_concept_terms": sorted(support["explicit_terms"]),
            "agent_validation_required": True,
        })
    hints.sort(key=lambda item: (
        0 if item["hint_type"] == "explicit_cross_reference" else 1,
        -len(item["supporting_session_ids"]),
        item["source_concept_id"],
        item["target_concept_id"],
    ))
    return hints[:RELATIONSHIP_HINT_CAP]


def build_curation_candidates(
    conn: sqlite3.Connection,
    *,
    mode: str = "compact",
    topic: str = "",
    recent_sessions: int = DEFAULT_RECENT_SESSIONS,
    limit: int = DEFAULT_CLAIM_RESULTS_LIMIT,
) -> dict[str, Any]:
    if mode not in {"compact", "detailed"}:
        raise CurationError(f"unknown mode: {mode!r} (expected 'compact' or 'detailed')")
    ensure_curation_state(conn)
    state = curation_status(conn)
    topic_id = _resolve_topic_id(conn, topic) if topic else None
    if topic and topic_id is None:
        raise CurationError(f"unknown topic: {topic!r} (no matching canonical_slug or alias)")

    sessions_payload = _recent_sessions(conn, limit=recent_sessions, topic_id=topic_id)
    high_priority = _high_priority_claim_states(conn, topic_id=topic_id)
    recent = _recent_claim_results(conn, limit=limit, topic_id=topic_id, mode=mode)
    cards = _retrieval_cards_compact(conn, topic_id=topic_id)
    summaries, summaries_omitted = _existing_summaries(conn, topic_id=topic_id)
    hints = _candidate_relationship_hints(
        conn,
        topic_id=topic_id,
        claim_result_ids=[r["claim_result_id"] for r in recent],
    )

    packet: dict[str, Any] = {
        "built_at_version": state["last_curation_version"],
        "built_at_ts": _now(),
        "mode": mode,
        "topic_scope": topic or "",
        "curation_state": state,
        "recent_sessions": sessions_payload,
        "high_priority_claim_states": high_priority,
        "recent_claim_results": recent,
        "retrieval_cards": cards,
        "existing_summaries": summaries,
        "existing_summaries_omitted": summaries_omitted,
        "existing_shadow_rules": _existing_shadow_rules(conn, topic_id=topic_id),
        "candidate_relationship_hints": hints,
        "instructions": {
            "agent_task": (
                "Return an apply-curation payload. Every summary must cite >=2 claim_result evidence ids. "
                "Every relationship must cite evidence. Use client_id strings to link relationships to "
                "summaries authored in the same payload. Shadow rules must cite >=2 claim_result ids, bind "
                "to explicit concepts, and describe a changed-frame probe. Prefer supersede_summary_ids over "
                "duplicates. Cap each pass at ~5 summaries, ~5 relationships, and ~3 shadow rules."
            ),
            "relationship_types": {
                "confused_with": (
                    "Symmetric. Assert only when evidence shows cross-contamination between the two "
                    "concepts (the learner swaps them) or repeated misses on one whose corrections name "
                    "the other. Surfaced at recall as a discrimination probe."
                ),
                "prerequisite": (
                    "Directed: source must be mastered before target. Assert only when evidence shows the "
                    "learner repeatedly fails the target AND the corrections point to an unmastered "
                    "foundational concept (the source) — i.e. the surface miss is really an upstream gap. "
                    "Set source = the foundation, target = the dependent concept; order is meaningful. "
                    "Surfaced at recall so the agent can shore up the prerequisite before re-drilling the target."
                ),
            },
            "shadow_rule_doctrine": (
                "Author a shadow rule only for a coherent false decision rule that can leak across contexts. "
                "Do not duplicate a single claim miss. Extinction is not a curation judgment: it requires "
                "recorded changed-frame and multi-context transfer passes."
            ),
            "doctrine_ref": ".agents/shared/commands/memory-curation.md#doctrine",
        },
    }
    packet["token_budget_estimate"] = _estimate_tokens(packet)
    return packet


# ---------------------------------------------------------------------------
# Apply payload
# ---------------------------------------------------------------------------


def _require(condition: bool, msg: str) -> None:
    if not condition:
        raise CurationError(msg)


def _validate_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CurationError(f"{field} must be an integer, got {type(value).__name__}")
    return value


def _validate_summary(summary: dict[str, Any], idx: int) -> None:
    _require(isinstance(summary, dict), f"summaries[{idx}] must be an object")
    summary_type = summary.get("summary_type")
    _require(
        summary_type in ALLOWED_SUMMARY_TYPES,
        f"summaries[{idx}].summary_type must be one of {sorted(ALLOWED_SUMMARY_TYPES)}, got {summary_type!r}",
    )
    content = summary.get("content")
    _require(
        isinstance(content, str) and content.strip(),
        f"summaries[{idx}].content must be a non-empty string",
    )
    evidence = summary.get("evidence_claim_result_ids") or []
    _require(
        isinstance(evidence, list) and len(evidence) >= 2,
        f"summaries[{idx}].evidence_claim_result_ids must list >=2 claim_result_ids (doctrine: evidence floor)",
    )
    for j, eid in enumerate(evidence):
        _validate_int(eid, f"summaries[{idx}].evidence_claim_result_ids[{j}]")
    topic_slug = summary.get("topic_slug") or None
    concept_id = summary.get("concept_id")
    inventory_concept_id = str(summary.get("inventory_concept_id") or "").strip()
    scope_present = sum(1 for v in (topic_slug, concept_id, inventory_concept_id) if v not in (None, ""))
    _require(
        scope_present <= 1,
        f"summaries[{idx}] must set at most one of topic_slug / concept_id / inventory_concept_id",
    )
    importance = summary.get("importance_score", 0.5)
    _require(
        isinstance(importance, (int, float)) and 0.0 <= float(importance) <= 1.0,
        f"summaries[{idx}].importance_score must be a number in [0, 1]",
    )
    client_id = summary.get("client_id", "")
    _require(
        isinstance(client_id, str),
        f"summaries[{idx}].client_id must be a string when present",
    )


def _validate_relationship(rel: dict[str, Any], idx: int) -> None:
    _require(isinstance(rel, dict), f"relationships[{idx}] must be an object")
    relation_type = rel.get("relation_type")
    _require(
        relation_type in ALLOWED_RELATION_TYPES,
        f"relationships[{idx}].relation_type must be one of {sorted(ALLOWED_RELATION_TYPES)}, got {relation_type!r}",
    )
    # prerequisite is directed: source is the foundational concept that must be
    # mastered before target. confused_with is symmetric. Both are surfaced at
    # retrieval (graph_signals), so both are writable. Directionality matters for
    # prerequisite, so source/target order is meaningful and must not be swapped.
    src = _validate_int(rel.get("source_concept_id"), f"relationships[{idx}].source_concept_id")
    tgt = _validate_int(rel.get("target_concept_id"), f"relationships[{idx}].target_concept_id")
    _require(src != tgt, f"relationships[{idx}]: self-edge forbidden (source == target == {src})")
    strength = rel.get("strength", 0.5)
    _require(
        isinstance(strength, (int, float)) and 0.0 <= float(strength) <= 1.0,
        f"relationships[{idx}].strength must be a number in [0, 1]",
    )
    origin = rel.get("origin", "curated")
    _require(
        origin in ("curated", "model_proposed"),
        f"relationships[{idx}].origin must be 'curated' or 'model_proposed', got {origin!r}",
    )
    if origin == "model_proposed":
        # Native-knowledge discovery (landscape-is-a-skeleton rule): the agent spotted a missing
        # prerequisite/confusion the per-turn log does not yet evidence. It is
        # persisted distinctly and requires a rationale instead of claim
        # evidence, so it stays auditable and never poses as evidence-backed
        # learner-model truth.
        _require(
            isinstance(rel.get("rationale"), str) and rel["rationale"].strip(),
            f"relationships[{idx}].origin='model_proposed' requires a non-empty rationale",
        )
    else:
        evidence_claims = rel.get("evidence_claim_result_ids") or []
        evidence_summary_client = rel.get("evidence_summary_client_id") or ""
        _require(
            bool(evidence_claims) or bool(evidence_summary_client),
            f"relationships[{idx}] must cite evidence (claim_result_ids or evidence_summary_client_id)",
        )
        for j, eid in enumerate(evidence_claims):
            _validate_int(eid, f"relationships[{idx}].evidence_claim_result_ids[{j}]")


def _resolve_inventory_concept_id(conn: sqlite3.Connection, inventory_concept_id: str) -> int | None:
    inv = str(inventory_concept_id or "").strip()
    if not inv:
        return None
    row = conn.execute(
        "SELECT id FROM concepts WHERE inventory_concept_id = ? ORDER BY id LIMIT 1",
        (inv,),
    ).fetchone()
    return int(row["id"]) if row else None


def _resolve_shadow_binding_concept_id(conn: sqlite3.Connection, binding: dict[str, Any], idx: int, rule_idx: int) -> int:
    if binding.get("concept_id") not in (None, ""):
        return _validate_int(binding.get("concept_id"), f"shadow_rules[{rule_idx}].bindings[{idx}].concept_id")
    inv = str(binding.get("inventory_concept_id") or "").strip()
    _require(inv, f"shadow_rules[{rule_idx}].bindings[{idx}] requires concept_id or inventory_concept_id")
    resolved = _resolve_inventory_concept_id(conn, inv)
    _require(
        resolved is not None,
        f"shadow_rules[{rule_idx}].bindings[{idx}].inventory_concept_id={inv!r} did not resolve to a learner concept",
    )
    return int(resolved)


def _validate_shadow_rule(rule: dict[str, Any], idx: int) -> None:
    _require(isinstance(rule, dict), f"shadow_rules[{idx}] must be an object")
    for field in ("false_rule", "corrected_rule", "clinical_consequence", "probe_shape"):
        _require(
            isinstance(rule.get(field), str) and rule[field].strip(),
            f"shadow_rules[{idx}].{field} must be a non-empty string",
        )
    severity = rule.get("severity", "medium")
    _require(
        severity in ALLOWED_SHADOW_SEVERITIES,
        f"shadow_rules[{idx}].severity must be one of {sorted(ALLOWED_SHADOW_SEVERITIES)}",
    )
    evidence = rule.get("evidence_claim_result_ids") or []
    _require(
        isinstance(evidence, list) and len(evidence) >= 2,
        f"shadow_rules[{idx}].evidence_claim_result_ids must list >=2 claim_result_ids (doctrine: evidence floor)",
    )
    for j, eid in enumerate(evidence):
        _validate_int(eid, f"shadow_rules[{idx}].evidence_claim_result_ids[{j}]")
    bindings = rule.get("bindings") or []
    _require(isinstance(bindings, list) and bindings, f"shadow_rules[{idx}].bindings must not be empty")
    for j, binding in enumerate(bindings):
        _require(isinstance(binding, dict), f"shadow_rules[{idx}].bindings[{j}] must be an object")
        has_concept = binding.get("concept_id") not in (None, "")
        has_inv = bool(str(binding.get("inventory_concept_id") or "").strip())
        _require(
            has_concept or has_inv,
            f"shadow_rules[{idx}].bindings[{j}] requires concept_id or inventory_concept_id",
        )
        if has_concept:
            _validate_int(binding.get("concept_id"), f"shadow_rules[{idx}].bindings[{j}].concept_id")
        binding_type = binding.get("binding_type", "trigger")
        _require(
            binding_type in ALLOWED_SHADOW_BINDING_TYPES,
            f"shadow_rules[{idx}].bindings[{j}].binding_type must be one of {sorted(ALLOWED_SHADOW_BINDING_TYPES)}",
        )
    evidence_summary_client = rule.get("evidence_summary_client_id") or ""
    _require(
        isinstance(evidence_summary_client, str),
        f"shadow_rules[{idx}].evidence_summary_client_id must be a string when present",
    )


def apply_curation_payload(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Validate and atomically apply an agent-authored curation payload.

    Raises ``CurationError`` for any validation failure. On any error after the
    transaction begins, the transaction is rolled back so no partial state lands.
    """
    _require(isinstance(payload, dict), "payload must be a JSON object")
    summaries = payload.get("summaries") or []
    relationships = payload.get("relationships") or []
    shadow_rules = payload.get("shadow_rules") or []
    supersede_ids = payload.get("supersede_summary_ids") or []
    _require(isinstance(summaries, list), "summaries must be a list")
    _require(isinstance(relationships, list), "relationships must be a list")
    _require(isinstance(shadow_rules, list), "shadow_rules must be a list")
    _require(isinstance(supersede_ids, list), "supersede_summary_ids must be a list")
    _require(
        bool(summaries) or bool(relationships) or bool(shadow_rules) or bool(supersede_ids),
        "payload must contain at least one of: summaries, relationships, shadow_rules, supersede_summary_ids",
    )

    built_at_version = payload.get("built_at_version")
    _require(
        isinstance(built_at_version, int) and not isinstance(built_at_version, bool),
        "payload.built_at_version must be an integer (copy from candidate packet)",
    )

    for i, s in enumerate(summaries):
        _validate_summary(s, i)
    for i, r in enumerate(relationships):
        _validate_relationship(r, i)
    for i, rule in enumerate(shadow_rules):
        _validate_shadow_rule(rule, i)
    for i, sid in enumerate(supersede_ids):
        _validate_int(sid, f"supersede_summary_ids[{i}]")

    client_ids = [s.get("client_id", "") for s in summaries if s.get("client_id")]
    _require(len(client_ids) == len(set(client_ids)), "summaries[].client_id values must be unique within a payload")

    ts = now or _now()

    # Flush any pending implicit transaction so the atomic block below is
    # well-defined under Python's sqlite3 auto-transaction semantics.
    if conn.in_transaction:
        conn.commit()

    try:
        version_row = conn.execute(
            "SELECT last_curation_version FROM curation_state WHERE id = 1"
        ).fetchone()
        current_version = int(version_row["last_curation_version"]) if version_row else 0
        _require(
            built_at_version == current_version,
            f"stale built_at_version: payload={built_at_version} db={current_version}; rebuild candidates and retry",
        )

        evidence_ids: set[int] = set()
        for s in summaries:
            for eid in s.get("evidence_claim_result_ids", []):
                evidence_ids.add(int(eid))
        for r in relationships:
            for eid in r.get("evidence_claim_result_ids", []) or []:
                evidence_ids.add(int(eid))
        for rule in shadow_rules:
            for eid in rule.get("evidence_claim_result_ids", []) or []:
                evidence_ids.add(int(eid))
        if evidence_ids:
            placeholders = ",".join("?" * len(evidence_ids))
            existing = {
                int(row["id"])
                for row in conn.execute(
                    f"SELECT id FROM claim_results WHERE id IN ({placeholders})",
                    list(evidence_ids),
                ).fetchall()
            }
            missing_evidence = evidence_ids - existing
            _require(
                not missing_evidence,
                f"unknown claim_result_ids referenced as evidence: {sorted(missing_evidence)}",
            )

        concept_ids: set[int] = set()
        for s in summaries:
            cid = s.get("concept_id")
            if cid is not None:
                concept_ids.add(int(cid))
        for r in relationships:
            concept_ids.add(int(r["source_concept_id"]))
            concept_ids.add(int(r["target_concept_id"]))
        for rule in shadow_rules:
            for binding in rule.get("bindings", []):
                concept_ids.add(int(binding["concept_id"]))
        if concept_ids:
            placeholders = ",".join("?" * len(concept_ids))
            existing_concepts = {
                int(row["id"])
                for row in conn.execute(
                    f"SELECT id FROM concepts WHERE id IN ({placeholders})",
                    list(concept_ids),
                ).fetchall()
            }
            missing_concepts = concept_ids - existing_concepts
            _require(
                not missing_concepts,
                f"unknown concept_ids referenced: {sorted(missing_concepts)}",
            )

        topic_slug_to_id: dict[str, int] = {}
        for i, s in enumerate(summaries):
            slug = s.get("topic_slug")
            if slug:
                tid = _resolve_topic_id(conn, slug)
                _require(tid is not None, f"summaries[{i}].topic_slug not found: {slug!r}")
                topic_slug_to_id[slug] = int(tid)

        if supersede_ids:
            placeholders = ",".join("?" * len(supersede_ids))
            existing_super = {
                int(row["id"]): row["status"]
                for row in conn.execute(
                    f"SELECT id, status FROM memory_summaries WHERE id IN ({placeholders})",
                    list(supersede_ids),
                ).fetchall()
            }
            missing_super = set(int(x) for x in supersede_ids) - set(existing_super)
            _require(
                not missing_super,
                f"supersede_summary_ids reference unknown summaries: {sorted(missing_super)}",
            )

        client_to_summary_id: dict[str, int] = {}
        new_summary_ids: list[int] = []
        new_version = current_version + 1
        for s in summaries:
            slug = s.get("topic_slug")
            topic_id = topic_slug_to_id[slug] if slug else None
            concept_id = s.get("concept_id")
            inventory_concept_id = str(s.get("inventory_concept_id") or "").strip() or None
            if concept_id is None and inventory_concept_id:
                concept_id = _resolve_inventory_concept_id(conn, inventory_concept_id)
            client_id = s.get("client_id", "")
            cur = conn.execute(
                """INSERT INTO memory_summaries
                       (client_id, summary_type, topic_id, concept_id, inventory_concept_id, content,
                        importance_score, generated_at, version, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
                (
                    client_id,
                    s["summary_type"],
                    topic_id,
                    concept_id,
                    inventory_concept_id,
                    s["content"].strip(),
                    float(s.get("importance_score", 0.5)),
                    ts,
                    new_version,
                ),
            )
            summary_id = int(cur.lastrowid)
            new_summary_ids.append(summary_id)
            if client_id:
                client_to_summary_id[client_id] = summary_id
            for eid in s.get("evidence_claim_result_ids", []):
                conn.execute(
                    "INSERT OR IGNORE INTO memory_summary_evidence (summary_id, claim_result_id) VALUES (?, ?)",
                    (summary_id, int(eid)),
                )

        superseded_applied: list[int] = []
        for sid in supersede_ids:
            cur = conn.execute(
                "UPDATE memory_summaries SET status = 'superseded' WHERE id = ? AND status = 'active'",
                (int(sid),),
            )
            if cur.rowcount:
                superseded_applied.append(int(sid))

        new_relationship_ids: list[int] = []
        for i, r in enumerate(relationships):
            evidence_client = r.get("evidence_summary_client_id") or ""
            evidence_summary_id = client_to_summary_id.get(evidence_client) if evidence_client else None
            _require(
                not evidence_client or evidence_summary_id is not None,
                f"relationships[{i}].evidence_summary_client_id={evidence_client!r} does not match any summary in this payload",
            )
            origin = r.get("origin", "curated")
            rationale = str(r.get("rationale", "")).strip()
            # Reconciliation: an evidence-backed ('curated') edge always dominates a
            # model_proposed one, so native-knowledge discovery is additive and
            # never silently overwrites learner-model structure. A model_proposed
            # edge landing on an existing curated edge leaves strength/evidence
            # untouched; only a curated update may raise them.
            cur = conn.execute(
                """INSERT INTO concept_relationships
                       (source_concept_id, target_concept_id, relation_type, strength,
                        evidence_summary_id, origin, rationale, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_concept_id, target_concept_id, relation_type) DO UPDATE SET
                       strength = CASE WHEN excluded.origin = 'curated'
                                       THEN excluded.strength ELSE concept_relationships.strength END,
                       evidence_summary_id = CASE WHEN excluded.origin = 'curated'
                                       THEN COALESCE(excluded.evidence_summary_id, concept_relationships.evidence_summary_id)
                                       ELSE concept_relationships.evidence_summary_id END,
                       origin = CASE WHEN excluded.origin = 'curated' OR concept_relationships.origin = 'curated'
                                       THEN 'curated' ELSE 'model_proposed' END,
                       rationale = CASE WHEN excluded.origin = 'curated' THEN concept_relationships.rationale
                                       ELSE COALESCE(NULLIF(excluded.rationale, ''), concept_relationships.rationale) END,
                       updated_at = excluded.updated_at""",
                (
                    int(r["source_concept_id"]),
                    int(r["target_concept_id"]),
                    r["relation_type"],
                    float(r.get("strength", 0.5)),
                    evidence_summary_id,
                    origin,
                    rationale,
                    ts,
                    ts,
                ),
            )
            rel_id_row = conn.execute(
                """SELECT id FROM concept_relationships
                   WHERE source_concept_id = ? AND target_concept_id = ? AND relation_type = ?""",
                (int(r["source_concept_id"]), int(r["target_concept_id"]), r["relation_type"]),
            ).fetchone()
            rel_id = int(rel_id_row["id"])
            new_relationship_ids.append(rel_id)
            for eid in r.get("evidence_claim_result_ids", []) or []:
                conn.execute(
                    "INSERT OR IGNORE INTO concept_relationship_evidence (relationship_id, claim_result_id) VALUES (?, ?)",
                    (rel_id, int(eid)),
                )

        new_shadow_rule_ids: list[int] = []
        for i, rule in enumerate(shadow_rules):
            evidence_client = rule.get("evidence_summary_client_id") or ""
            evidence_summary_id = client_to_summary_id.get(evidence_client) if evidence_client else None
            _require(
                not evidence_client or evidence_summary_id is not None,
                f"shadow_rules[{i}].evidence_summary_client_id={evidence_client!r} does not match any summary in this payload",
            )
            conn.execute(
                """INSERT INTO shadow_rules
                       (false_rule, corrected_rule, clinical_consequence, probe_shape, severity,
                        status, evidence_summary_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                   ON CONFLICT(false_rule, corrected_rule) DO UPDATE SET
                       clinical_consequence = excluded.clinical_consequence,
                       probe_shape = excluded.probe_shape,
                       severity = excluded.severity,
                       status = CASE WHEN shadow_rules.status = 'extinguished' THEN 'regressed' ELSE shadow_rules.status END,
                       evidence_summary_id = COALESCE(excluded.evidence_summary_id, shadow_rules.evidence_summary_id),
                       updated_at = excluded.updated_at""",
                (
                    rule["false_rule"].strip(),
                    rule["corrected_rule"].strip(),
                    rule["clinical_consequence"].strip(),
                    rule["probe_shape"].strip(),
                    rule.get("severity", "medium"),
                    evidence_summary_id,
                    ts,
                    ts,
                ),
            )
            rule_row = conn.execute(
                "SELECT id FROM shadow_rules WHERE false_rule = ? AND corrected_rule = ?",
                (rule["false_rule"].strip(), rule["corrected_rule"].strip()),
            ).fetchone()
            shadow_rule_id = int(rule_row["id"])
            new_shadow_rule_ids.append(shadow_rule_id)
            for eid in rule.get("evidence_claim_result_ids", []):
                conn.execute(
                    "INSERT OR IGNORE INTO shadow_rule_evidence (shadow_rule_id, claim_result_id) VALUES (?, ?)",
                    (shadow_rule_id, int(eid)),
                )
            for j, binding in enumerate(rule.get("bindings", [])):
                concept_id = _resolve_shadow_binding_concept_id(conn, binding, j, i)
                conn.execute(
                    """INSERT OR IGNORE INTO shadow_rule_bindings
                       (shadow_rule_id, concept_id, binding_type) VALUES (?, ?, ?)""",
                    (shadow_rule_id, concept_id, binding.get("binding_type", "trigger")),
                )

        conn.execute(
            """UPDATE curation_state
                  SET sessions_since_last_curation = 0,
                      last_curation_ts = ?,
                      last_curation_version = ?
                  WHERE id = 1""",
            (ts, new_version),
        )
        conn.execute("DELETE FROM curation_counted_sessions")

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "ok": True,
        "new_version": new_version,
        "summaries_created": new_summary_ids,
        "relationships_upserted": new_relationship_ids,
        "shadow_rules_upserted": new_shadow_rule_ids,
        "superseded": superseded_applied,
        "applied_at": ts,
    }


# ---------------------------------------------------------------------------
# Retrieval helpers (used by study_memory.retrieval_summary --include-curated)
# ---------------------------------------------------------------------------


def curated_summaries_for_summary(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
    limit: int = 8,
    relevant_concept_ids: Iterable[int] = (),
    anchor_count: int = 2,
) -> list[dict[str, Any]]:
    """Return curated summaries for the topic, focus-filtered to today's cards.

    Selection policy:
    - First, take the top ``anchor_count`` summaries by importance (regardless of
      whether they overlap with today's cards). These are the dominant patterns
      the agent should always see.
    - Then, fill remaining slots up to ``limit`` from summaries that cite at
      least one ``relevant_concept_ids`` via their evidence joins. Order by
      importance DESC, generated_at DESC.
    - Non-anchor summaries that do not cite any relevant concept are dropped.
    - When ``relevant_concept_ids`` is empty, falls back to top N by importance
      (the original behavior).
    """
    relevant_ids = sorted({int(c) for c in relevant_concept_ids})

    where = "WHERE ms.status = 'active'"
    params: list[Any] = []
    if topic_id is not None:
        # Topic-scoped retrieval surfaces: topic matches, truly global, OR concept-scoped
        # to a concept under this topic. Concept-scoped summaries never leak across topics.
        where += (
            " AND ("
            "ms.topic_id = ? "
            "OR (ms.topic_id IS NULL AND ms.concept_id IS NULL) "
            "OR (ms.topic_id IS NULL AND ms.concept_id IN (SELECT id FROM concepts WHERE topic_id = ?))"
            ")"
        )
        params.extend([topic_id, topic_id])

    if relevant_ids:
        rel_placeholders = ",".join("?" * len(relevant_ids))
        relevance_expr = (
            f"EXISTS (SELECT 1 FROM memory_summary_evidence mse "
            f"JOIN claim_results cr ON cr.id = mse.claim_result_id "
            f"WHERE mse.summary_id = ms.id AND cr.concept_id IN ({rel_placeholders})) AS is_relevant"
        )
        rows = conn.execute(
            f"""SELECT ms.id, ms.summary_type, ms.content, ms.importance_score, ms.generated_at,
                       ms.concept_id, t.canonical_slug AS topic,
                       {relevance_expr}
                  FROM memory_summaries ms
                  LEFT JOIN topics t ON t.id = ms.topic_id
                  {where}
                  ORDER BY ms.importance_score DESC, ms.generated_at DESC""",
            [*relevant_ids, *params],
        ).fetchall()
    else:
        rows = conn.execute(
            f"""SELECT ms.id, ms.summary_type, ms.content, ms.importance_score, ms.generated_at,
                       ms.concept_id, t.canonical_slug AS topic,
                       1 AS is_relevant
                  FROM memory_summaries ms
                  LEFT JOIN topics t ON t.id = ms.topic_id
                  {where}
                  ORDER BY ms.importance_score DESC, ms.generated_at DESC""",
            params,
        ).fetchall()

    if not rows:
        return []

    take = min(limit, len(rows))
    anchors = rows[: min(anchor_count, take)]
    anchor_ids = {int(r["id"]) for r in anchors}
    remaining_slots = take - len(anchors)
    picked = list(anchors)
    if remaining_slots > 0:
        for r in rows[len(anchors):]:
            if int(r["id"]) in anchor_ids:
                continue
            if not int(r["is_relevant"]):
                continue
            picked.append(r)
            if len(picked) >= take:
                break

    from mastery_intelligence import parse_escalation_clause  # noqa: PLC0415

    out: list[dict[str, Any]] = []
    for r in picked:
        item = {
            "summary_id": int(r["id"]),
            "summary_type": r["summary_type"],
            "topic": r["topic"] or "",
            "concept_id": int(r["concept_id"]) if r["concept_id"] is not None else None,
            "content": r["content"],
            "importance_score": float(r["importance_score"]),
            "generated_at": r["generated_at"],
        }
        directive = parse_escalation_clause(str(r["content"] or ""))
        if directive:
            item["escalation_directive"] = directive
        out.append(item)
    return out


def graph_signals_for_summary(
    conn: sqlite3.Connection,
    *,
    must_retest_concept_ids: Iterable[int],
    per_concept_cap: int = 3,
    strength_floor: float = 0.6,
) -> list[dict[str, Any]]:
    """Surface graph neighbors of the top must_retest concepts.

    Two edge types are surfaced, each carrying a ``direction`` the agent uses to
    interpret it:

    - ``confused_with`` (symmetric): the neighbor is a discrimination probe — when
      you finish drilling the current concept, contrast it against this neighbor.
      direction is always ``bidirectional``.
    - ``prerequisite`` (directed): source must be mastered before target. When the
      current must_retest concept is the *target*, the neighbor is an upstream
      foundation (``prerequisite_of_current``) — a repeated miss here may really be
      an unmastered prerequisite, so check it first. When the current concept is
      the *source*, the neighbor is downstream (``depends_on_current``) — mastering
      the current concept unblocks it.
    """
    concept_ids = list(dict.fromkeys(int(c) for c in must_retest_concept_ids))
    if not concept_ids:
        return []
    signals: list[dict[str, Any]] = []
    for cid in concept_ids:
        rows = conn.execute(
            """SELECT cr.id, cr.relation_type, cr.source_concept_id, cr.target_concept_id,
                      cr.strength, cr.evidence_summary_id, cr.updated_at, cr.origin, cr.rationale,
                      cs.display_name AS source_name,
                      ct.display_name AS target_name
                 FROM concept_relationships cr
                 JOIN concepts cs ON cs.id = cr.source_concept_id
                 JOIN concepts ct ON ct.id = cr.target_concept_id
                 WHERE cr.relation_type IN ('confused_with', 'prerequisite')
                   AND cr.strength >= ?
                   AND (cr.source_concept_id = ? OR cr.target_concept_id = ?)
                 ORDER BY cr.strength DESC, cr.updated_at DESC
                 LIMIT ?""",
            (strength_floor, cid, cid, per_concept_cap),
        ).fetchall()
        for r in rows:
            is_source = int(r["source_concept_id"]) == cid
            other_id = int(r["target_concept_id"]) if is_source else int(r["source_concept_id"])
            other_name = r["target_name"] if is_source else r["source_name"]
            if r["relation_type"] == "prerequisite":
                direction = "depends_on_current" if is_source else "prerequisite_of_current"
            else:
                direction = "bidirectional"
            signals.append({
                "relationship_id": int(r["id"]),
                "from_concept_id": cid,
                "to_concept_id": other_id,
                "to_concept": other_name,
                "relation_type": r["relation_type"],
                "direction": direction,
                "strength": float(r["strength"]),
                "evidence_summary_id": int(r["evidence_summary_id"]) if r["evidence_summary_id"] is not None else None,
                "origin": r["origin"] if "origin" in r.keys() else "curated",
                "rationale": (r["rationale"] if "rationale" in r.keys() else "") or "",
            })
    return signals


def shadow_rule_signals_for_summary(
    conn: sqlite3.Connection,
    *,
    relevant_concept_ids: Iterable[int] = (),
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Surface bounded active false-rule probes linked to today's concepts."""
    concept_ids = sorted({int(value) for value in relevant_concept_ids})
    params: list[Any] = []
    where = "WHERE sr.status IN ('active', 'regressed', 'repaired')"
    if concept_ids:
        placeholders = ",".join("?" * len(concept_ids))
        where += f" AND srb.concept_id IN ({placeholders})"
        params.extend(concept_ids)
    rows = conn.execute(
        f"""SELECT DISTINCT sr.id, sr.false_rule, sr.corrected_rule, sr.clinical_consequence,
                   sr.probe_shape, sr.severity, sr.status, sr.updated_at
              FROM shadow_rules sr
              JOIN shadow_rule_bindings srb ON srb.shadow_rule_id = sr.id
              {where}
             ORDER BY CASE sr.severity WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                      CASE sr.status WHEN 'regressed' THEN 0 WHEN 'active' THEN 1 ELSE 2 END,
                      sr.updated_at DESC
             LIMIT ?""",
        [*params, max(0, limit)],
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        status = str(row["status"])
        counts = conn.execute(
            """SELECT
                   SUM(CASE WHEN check_type = 'changed_frame' AND outcome = 'pass' THEN 1 ELSE 0 END) AS changed_frames,
                   COUNT(DISTINCT CASE WHEN check_type = 'transfer' AND outcome = 'pass' THEN context_label END) AS transfer_contexts
               FROM shadow_rule_checks WHERE shadow_rule_id = ?""",
            (int(row["id"]),),
        ).fetchone()
        changed_frames = int(counts["changed_frames"] or 0)
        transfer_contexts = int(counts["transfer_contexts"] or 0)
        extinction_progress = {
            "changed_frame_passes": changed_frames,
            "transfer_context_passes": transfer_contexts,
            "extinguished": changed_frames >= 1 and transfer_contexts >= 2,
        }
        if status == "repaired" and extinction_progress["extinguished"]:
            continue
        bindings = conn.execute(
            """SELECT srb.concept_id, srb.binding_type, c.display_name AS concept
                 FROM shadow_rule_bindings srb
                 JOIN concepts c ON c.id = srb.concept_id
                WHERE srb.shadow_rule_id = ?
                ORDER BY srb.binding_type, c.display_name""",
            (int(row["id"]),),
        ).fetchall()
        next_action = "Inject one changed-frame discriminator probe. Do not telegraph the false rule."
        if status == "repaired":
            next_action = (
                "Shadow rule is partially extinguished; continue changed-frame and transfer-context probes "
                "before treating the false rule as gone."
            )
        out.append({
            "shadow_rule_id": int(row["id"]),
            "false_rule": row["false_rule"],
            "corrected_rule": row["corrected_rule"],
            "clinical_consequence": row["clinical_consequence"],
            "probe_shape": row["probe_shape"],
            "severity": row["severity"],
            "status": status,
            "extinction_progress": extinction_progress,
            "bindings": [
                {
                    "concept_id": int(binding["concept_id"]),
                    "concept": binding["concept"],
                    "binding_type": binding["binding_type"],
                }
                for binding in bindings
            ],
            "next_action": next_action,
        })
    return out
