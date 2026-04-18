#!/usr/bin/env python3
"""Long-term memory mixin for KnowledgeGraph."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from kg_constants import BASE_DIR


def _merge_compact_recall_for_guidance(
    fast: dict,
    semantic: dict,
    max_results: int,
) -> dict:
    """Merge compact recall payloads: preserve fast-path order, fill with semantic-only ids."""
    fe = fast.get("exchanges") or []
    se = semantic.get("exchanges") or []
    seen: set[int] = set()
    merged_ex: list[dict] = []
    for ex in fe:
        eid = ex.get("exchange_id")
        if eid is None:
            continue
        ie = int(eid)
        if ie in seen:
            continue
        seen.add(ie)
        merged_ex.append(ex)
    for ex in se:
        if len(merged_ex) >= max_results:
            break
        eid = ex.get("exchange_id")
        if eid is None:
            continue
        ie = int(eid)
        if ie in seen:
            continue
        seen.add(ie)
        merged_ex.append(ex)
    merged_ex = merged_ex[:max_results]

    fs = fast.get("episode_summaries") or []
    ss = semantic.get("episode_summaries") or []
    seen_s: set[int] = set()
    merged_sum: list[dict] = []
    for s in fs + ss:
        sid = s.get("summary_id")
        if sid is None:
            continue
        isid = int(sid)
        if isid in seen_s:
            continue
        seen_s.add(isid)
        merged_sum.append(s)

    fp = fast.get("patterns") or {}
    sp = semantic.get("patterns") or {}

    def _merge_pattern_list(key: str, dedupe_key: str | None) -> list:
        la = list(fp.get(key) or [])
        lb = list(sp.get(key) or [])
        if not dedupe_key:
            return (la + lb)[:10]
        out: list = []
        seen_k: set[str] = set()
        for item in la + lb:
            if not isinstance(item, dict):
                continue
            k = str(item.get(dedupe_key) or "")
            if not k or k in seen_k:
                continue
            seen_k.add(k)
            out.append(item)
            if len(out) >= 10:
                break
        return out

    merged_patterns = {
        "persistent_confusions": _merge_pattern_list(
            "persistent_confusions", "concept_misconception"
        ),
        "effective_teaching": _merge_pattern_list("effective_teaching", "approach"),
        "failed_teaching": _merge_pattern_list("failed_teaching", "approach"),
    }

    return {
        "exchanges": merged_ex,
        "episode_summaries": merged_sum,
        "patterns": merged_patterns,
        "full_ids_available": [e["exchange_id"] for e in merged_ex],
    }


def _rrf_rank(rankings: list[dict[int, int]], limit: int, k: int = 60) -> list[int]:
    """Return ids ordered by Reciprocal Rank Fusion across ranked streams."""
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for item_id, rank in ranking.items():
            scores[item_id] += 1.0 / (k + rank)
    return sorted(scores, key=lambda item_id: -scores[item_id])[:limit]


class KnowledgeGraphMemoryMixin:
    """Memory/event-store, recall, and study-planning behavior."""

    # ------------------------------------------------------------------
    # Episodic Memory — lossless learning exchange capture
    # ------------------------------------------------------------------

    def _memory_hash(self, *parts: object) -> str:
        """Stable hash for idempotent memory writes."""
        payload = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _resolve_concept_text(self, concept_text: str, topic_id: int | None = None) -> str:
        """Resolve a concept alias to its canonical text when a mapping exists."""
        alias = concept_text.strip().lower()
        if not alias:
            return ""
        try:
            if topic_id is not None:
                row = self.conn.execute(
                    """SELECT canonical_concept FROM concept_aliases
                       WHERE alias = ? AND (topic_id = ? OR topic_id IS NULL)
                       ORDER BY topic_id IS NULL ASC, alias_id DESC
                       LIMIT 1""",
                    (alias, topic_id),
                ).fetchone()
            else:
                row = self.conn.execute(
                    """SELECT canonical_concept FROM concept_aliases
                       WHERE alias = ? ORDER BY alias_id DESC LIMIT 1""",
                    (alias,),
                ).fetchone()
            if row and row["canonical_concept"]:
                return row["canonical_concept"].strip().lower()
        except Exception:
            pass
        return alias

    def add_concept_alias(
        self,
        alias: str,
        canonical_concept: str,
        topic_name: str = "",
        source: str = "manual",
    ) -> dict[str, object]:
        """Add or update a concept alias mapping."""
        try:
            alias_clean = alias.strip().lower()
            canonical_clean = canonical_concept.strip().lower()
            if not alias_clean or not canonical_clean:
                return {"ok": False, "error": "alias and canonical_concept are required"}
            topic_id = None
            if topic_name:
                topic_id = self._upsert_topic(self._normalize_topic(topic_name), topic_name.strip())
                if topic_id < 0:
                    topic_id = None
            now = datetime.now(timezone.utc).isoformat()
            with self.conn:
                existing = self.conn.execute(
                    """SELECT alias_id FROM concept_aliases
                       WHERE alias = ? AND topic_id IS ?""",
                    (alias_clean, topic_id),
                ).fetchone()
                if existing:
                    self.conn.execute(
                        """UPDATE concept_aliases
                           SET canonical_concept = ?, source = ?, created_ts = ?
                           WHERE alias_id = ?""",
                        (canonical_clean, source, now, existing["alias_id"]),
                    )
                    alias_id = existing["alias_id"]
                else:
                    cur = self.conn.execute(
                        """INSERT INTO concept_aliases
                           (alias, canonical_concept, topic_id, source, created_ts)
                           VALUES (?, ?, ?, ?, ?)""",
                        (alias_clean, canonical_clean, topic_id, source, now),
                    )
                    alias_id = cur.lastrowid or -1
            return {
                "ok": alias_id > 0,
                "alias_id": alias_id,
                "alias": alias_clean,
                "canonical_concept": canonical_clean,
                "topic_id": topic_id,
            }
        except Exception as exc:
            print(f"[knowledge_graph] add_concept_alias error: {exc}", file=sys.stderr)
            return {"ok": False, "error": str(exc)}

    def _upsert_memory_fts(
        self,
        entity_type: str,
        entity_id: int,
        session_ts: str = "",
        skill: str = "",
        topic_text: str = "",
        concept_text: str = "",
        question_text: str = "",
        answer_text: str = "",
        correction_text: str = "",
        misconception: str = "",
        root_cause: str = "",
        summary_text: str = "",
        event_text: str = "",
        payload_text: str = "",
    ) -> None:
        """Maintain the optional FTS5 memory index. Non-fatal if unavailable."""
        try:
            with self.conn:
                self.conn.execute(
                    "DELETE FROM memory_fts WHERE entity_type = ? AND entity_id = ?",
                    (entity_type, entity_id),
                )
                self.conn.execute(
                    """INSERT INTO memory_fts
                       (entity_type, entity_id, session_ts, skill,
                        topic_text, concept_text, question_text, answer_text,
                        correction_text, misconception, root_cause,
                        summary_text, event_text, payload_text)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entity_type, entity_id, session_ts, skill,
                        topic_text, concept_text, question_text, answer_text,
                        correction_text, misconception, root_cause,
                        summary_text, event_text, payload_text,
                    ),
                )
        except Exception:
            pass

    def _fts_match_query(self, query: str) -> str:
        tokens = [
            t.lower() for t in re.findall(r"[A-Za-z0-9]+", query or "")
            if len(t) >= 2
        ]
        return " OR ".join(f"{t}*" for t in tokens[:8])

    def append_memory_event(
        self,
        event_type: str,
        session_ts: str,
        turn_number: int,
        skill: str,
        topic_name: str = "",
        concept_text: str = "",
        actor: str = "",
        content_text: str = "",
        payload: dict[str, object] | None = None,
        source: str = "",
        idempotency_key: str = "",
        derived_from_event_id: int | None = None,
        derived: dict[str, object] | None = None,
        domain: str = "",
    ) -> int:
        """Append a raw memory event and return its id.

        This is the source-of-truth capture layer. Derived tables may summarize
        or index the event, but they should not be the only place the raw
        interaction survives.
        """
        try:
            topic_id = None
            if topic_name:
                topic_id = self._upsert_topic(self._normalize_topic(topic_name), topic_name.strip(), domain)
                if topic_id < 0:
                    topic_id = None
            concept_clean = self._resolve_concept_text(concept_text, topic_id)
            payload_json = json.dumps(payload or {}, sort_keys=True, default=str)
            derived_json = json.dumps(derived or {}, sort_keys=True, default=str)
            key = idempotency_key or self._memory_hash(
                event_type, session_ts, turn_number, skill, topic_id,
                concept_clean, actor, content_text, payload_json,
            )
            existing = self.conn.execute(
                "SELECT memory_event_id FROM memory_events WHERE idempotency_key = ? LIMIT 1",
                (key,),
            ).fetchone()
            if existing:
                return existing["memory_event_id"]

            now = datetime.now(timezone.utc).isoformat()
            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO memory_events
                       (event_ts, session_ts, turn_number, skill, topic_id,
                        concept_text, event_type, actor, content_text,
                        payload_json, source, idempotency_key,
                        derived_from_event_id, derived_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        now, session_ts, turn_number, skill, topic_id,
                        concept_clean, event_type, actor, content_text,
                        payload_json, source or skill, key,
                        derived_from_event_id, derived_json,
                    ),
                )
                event_id = cur.lastrowid or -1
            if event_id > 0:
                self._upsert_memory_fts(
                    "memory_event",
                    event_id,
                    session_ts=session_ts,
                    skill=skill,
                    topic_text=topic_name,
                    concept_text=concept_clean,
                    event_text=content_text,
                    payload_text=payload_json,
                )
            return event_id
        except Exception as exc:
            print(f"[knowledge_graph] append_memory_event error: {exc}", file=sys.stderr)
            return -1

    def set_memory_session(
        self,
        session_ts: str,
        skill: str,
        topic_text: str = "",
        memory_enabled: bool = False,
        consent_scope: str = "",
        status: str = "active",
        notes: str = "",
    ) -> dict[str, object]:
        """Record explicit memory mode for a session."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            ended_ts = now if status == "complete" else None
            with self.conn:
                existing = self.conn.execute(
                    """SELECT started_ts FROM memory_sessions
                       WHERE session_ts = ? AND skill = ?""",
                    (session_ts, skill),
                ).fetchone()
                if existing:
                    self.conn.execute(
                        """UPDATE memory_sessions
                           SET topic_text = COALESCE(NULLIF(?, ''), topic_text),
                               memory_enabled = ?,
                               consent_scope = COALESCE(NULLIF(?, ''), consent_scope),
                               status = ?,
                               ended_ts = COALESCE(?, ended_ts),
                               notes = COALESCE(NULLIF(?, ''), notes)
                           WHERE session_ts = ? AND skill = ?""",
                        (
                            topic_text, 1 if memory_enabled else 0,
                            consent_scope, status, ended_ts, notes,
                            session_ts, skill,
                        ),
                    )
                else:
                    self.conn.execute(
                        """INSERT INTO memory_sessions
                           (session_ts, skill, topic_text, memory_enabled,
                            consent_scope, status, started_ts, ended_ts, notes)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            session_ts, skill, topic_text,
                            1 if memory_enabled else 0, consent_scope,
                            status, now, ended_ts, notes,
                        ),
                    )
            self.append_memory_event(
                event_type=f"session_{status}",
                session_ts=session_ts,
                turn_number=0,
                skill=skill,
                topic_name=topic_text,
                actor="system",
                content_text=f"Memory session {status}: enabled={bool(memory_enabled)} scope={consent_scope}",
                payload={
                    "memory_enabled": bool(memory_enabled),
                    "consent_scope": consent_scope,
                    "status": status,
                    "notes": notes,
                },
                source="memory_session",
            )
            return {
                "ok": True,
                "session_ts": session_ts,
                "skill": skill,
                "memory_enabled": bool(memory_enabled),
                "status": status,
                "consent_scope": consent_scope,
            }
        except Exception as exc:
            print(f"[knowledge_graph] set_memory_session error: {exc}", file=sys.stderr)
            return {"ok": False, "error": str(exc)}

    def is_memory_session_enabled(self, session_ts: str, skill: str) -> bool:
        """Return True only when explicit memory mode is enabled for a session."""
        try:
            row = self.conn.execute(
                """SELECT memory_enabled FROM memory_sessions
                   WHERE session_ts = ? AND skill = ?""",
                (session_ts, skill),
            ).fetchone()
            return bool(row and row["memory_enabled"])
        except Exception:
            return False

    def resolve_memory_session(
        self,
        session_ts: str,
        skill: str,
        topic_text: str = "",
        prefer_active: bool = True,
    ) -> dict[str, object]:
        """Resolve agent-supplied timestamps to the active memory session.

        CLI agents occasionally create a fresh timestamp for every memory
        write.  When there is exactly one plausible active, memory-enabled
        session for the same skill/topic, route the write there and return a
        warning so callers can surface or log the correction.
        """
        supplied_ts = (session_ts or "").strip()
        skill_clean = (skill or "").strip()
        topic_clean = (topic_text or "").strip()
        try:
            exact = self.conn.execute(
                """SELECT * FROM memory_sessions
                   WHERE session_ts = ? AND skill = ?
                   LIMIT 1""",
                (supplied_ts, skill_clean),
            ).fetchone()
            if exact:
                return {
                    "ok": True,
                    "session_ts": supplied_ts,
                    "supplied_session_ts": supplied_ts,
                    "changed": False,
                    "memory_enabled": bool(exact["memory_enabled"]),
                    "status": exact["status"] or "",
                    "warning": "" if exact["memory_enabled"] else "session exists but memory is disabled",
                }
            if not prefer_active or not skill_clean:
                return {
                    "ok": True,
                    "session_ts": supplied_ts,
                    "supplied_session_ts": supplied_ts,
                    "changed": False,
                    "memory_enabled": False,
                    "status": "",
                    "warning": "no matching enabled memory_session found",
                }

            active_rows = [
                dict(row) for row in self.conn.execute(
                    """SELECT * FROM memory_sessions
                       WHERE skill = ?
                         AND memory_enabled = 1
                         AND status = 'active'
                       ORDER BY started_ts DESC
                       LIMIT 8""",
                    (skill_clean,),
                ).fetchall()
            ]
            if not active_rows:
                return {
                    "ok": True,
                    "session_ts": supplied_ts,
                    "supplied_session_ts": supplied_ts,
                    "changed": False,
                    "memory_enabled": False,
                    "status": "",
                    "warning": "no active enabled memory_session found",
                }

            topic_norm = self._normalize_topic(topic_clean) if topic_clean else ""
            topic_matches = []
            for row in active_rows:
                row_topic = row.get("topic_text") or ""
                row_norm = self._normalize_topic(row_topic) if row_topic else ""
                if topic_norm and (
                    topic_norm == row_norm
                    or topic_norm in row_norm
                    or row_norm in topic_norm
                ):
                    topic_matches.append(row)
            candidates = topic_matches or (active_rows if len(active_rows) == 1 else [])
            if not candidates:
                return {
                    "ok": True,
                    "session_ts": supplied_ts,
                    "supplied_session_ts": supplied_ts,
                    "changed": False,
                    "memory_enabled": False,
                    "status": "",
                    "warning": "multiple active memory sessions; supplied timestamp left unchanged",
                    "active_session_candidates": [
                        {
                            "session_ts": row["session_ts"],
                            "skill": row["skill"],
                            "topic_text": row["topic_text"],
                            "started_ts": row["started_ts"],
                        }
                        for row in active_rows
                    ],
                }

            chosen = candidates[0]
            resolved_ts = chosen["session_ts"]
            changed = bool(supplied_ts and supplied_ts != resolved_ts)
            return {
                "ok": True,
                "session_ts": resolved_ts,
                "supplied_session_ts": supplied_ts,
                "changed": changed,
                "memory_enabled": True,
                "status": chosen["status"] or "",
                "topic_text": chosen["topic_text"] or "",
                "warning": (
                    f"session timestamp auto-routed to active memory_session {resolved_ts}"
                    if changed else ""
                ),
            }
        except Exception as exc:
            print(f"[knowledge_graph] resolve_memory_session error: {exc}", file=sys.stderr)
            return {
                "ok": False,
                "session_ts": supplied_ts,
                "supplied_session_ts": supplied_ts,
                "changed": False,
                "memory_enabled": False,
                "error": str(exc),
            }

    def _infer_response_confidence(self, answer_text: str) -> str:
        """Infer high/low confidence from user phrasing when not passed explicitly."""
        text = f" {answer_text.lower()} "
        low_markers = [
            "not sure", "unsure", "i think", "i guess", "maybe", "probably",
            "can't remember", "dont know", "don't know", "uncertain",
        ]
        high_markers = [
            "definitely", "clearly", "obviously", "i know", "for sure",
            "must be", "has to be",
        ]
        if any(m in text for m in low_markers):
            return "low"
        if any(m in text for m in high_markers):
            return "high"
        return ""

    def log_exchange(
        self,
        session_ts: str,
        turn_number: int,
        skill: str,
        topic_name: str,
        concept_text: str,
        question_text: str,
        answer_text: str,
        answer_correct: int,
        correction_text: str = "",
        error_type: str = "",
        error_process: str = "",
        misconception: str = "",
        root_cause: str = "",
        teaching_approach: str = "",
        retrieval_sources: str = "",
        breakthrough: bool = False,
        insight_text: str = "",
        signal_event_id: int | None = None,
        memory_event_id: int | None = None,
        domain: str = "",
        depth: int = 1,
    ) -> int:
        """Log a single learning exchange (question + answer + correction).

        This captures the CONTENT that signal_events discards: the actual
        question asked, the user's verbatim answer, the correction given,
        and which teaching approach was used.  One row per Q&A cycle.

        Returns the exchange_id of the inserted row, or -1 on error.
        """
        try:
            canonical = self._normalize_topic(topic_name)
            topic_id = self._upsert_topic(canonical, topic_name.strip(), domain)
            if topic_id < 0:
                topic_id = None  # allow insert without valid topic link
            concept_clean = self._resolve_concept_text(concept_text, topic_id)
            dedupe_key = self._memory_hash(
                "learning_exchange", session_ts, turn_number, skill, topic_id,
                concept_clean, question_text, answer_text,
            )

            existing = self.conn.execute(
                """SELECT exchange_id, signal_event_id, memory_event_id
                   FROM learning_exchanges
                   WHERE dedupe_key = ?
                      OR (session_ts = ? AND turn_number = ? AND skill = ?
                          AND topic_id IS ?
                          AND concept_text = ?
                          AND question_text = ?
                          AND answer_text = ?)
                   ORDER BY exchange_id ASC
                   LIMIT 1""",
                (
                    dedupe_key, session_ts, turn_number, skill, topic_id, concept_clean,
                    question_text, answer_text,
                ),
            ).fetchone()
            if existing:
                updates = []
                params: list[object] = []
                if signal_event_id is not None and not existing["signal_event_id"]:
                    updates.append("signal_event_id = ?")
                    params.append(signal_event_id)
                if memory_event_id is not None and not existing["memory_event_id"]:
                    updates.append("memory_event_id = ?")
                    params.append(memory_event_id)
                if updates:
                    with self.conn:
                        self.conn.execute(
                            f"UPDATE learning_exchanges SET {', '.join(updates)} WHERE exchange_id = ?",
                            (*params, existing["exchange_id"]),
                        )
                return existing["exchange_id"]

            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO learning_exchanges
                       (session_ts, turn_number, skill, topic_id, concept_text,
                        domain, depth, question_text, answer_text, answer_correct,
                        correction_text, error_type, misconception, root_cause,
                        teaching_approach, retrieval_sources,
                        breakthrough, insight_text, signal_event_id, memory_event_id,
                        dedupe_key)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_ts, turn_number, skill, topic_id,
                        concept_clean,
                        domain, depth,
                        question_text, answer_text, answer_correct,
                        correction_text, error_type, misconception, root_cause,
                        teaching_approach, retrieval_sources,
                        1 if breakthrough else 0, insight_text,
                        signal_event_id,
                        memory_event_id,
                        dedupe_key,
                    ),
                )
                exchange_id = cur.lastrowid or -1
            if exchange_id > 0:
                self._upsert_memory_fts(
                    "learning_exchange",
                    exchange_id,
                    session_ts=session_ts,
                    skill=skill,
                    topic_text=topic_name,
                    concept_text=concept_clean,
                    question_text=question_text,
                    answer_text=answer_text,
                    correction_text=correction_text,
                    misconception=misconception,
                    root_cause=root_cause,
                    payload_text=json.dumps({
                        "answer_correct": answer_correct,
                        "error_type": error_type,
                        "teaching_approach": teaching_approach,
                        "breakthrough": breakthrough,
                        "insight": insight_text,
                    }, sort_keys=True),
                )
            return exchange_id
        except Exception as exc:
            print(f"[knowledge_graph] log_exchange error: {exc}", file=sys.stderr)
            return -1

    def log_answer(
        self,
        session_ts: str,
        turn_number: int,
        skill: str,
        topic_name: str,
        concept_text: str,
        question_text: str,
        answer_text: str,
        answer_correct: int,
        correction_text: str = "",
        error_type: str = "",
        error_process: str = "",
        misconception: str = "",
        root_cause: str = "",
        remediation: str = "",
        teaching_approach: str = "",
        retrieval_sources: str = "",
        breakthrough: bool = False,
        insight_text: str = "",
        domain: str = "",
        depth: int = 1,
        response_confidence: str = "",
    ) -> dict:
        """Atomically log one active teaching answer across memory layers.

        This is the preferred active-learning write path. It keeps the
        behavioral signal, verbatim episodic exchange, concept mastery update,
        concept evolution provenance, and calibration metadata aligned.
        """
        try:
            signal_map = {0: "incorrect_recall", 1: "partial_recall", 2: "correct_recall"}
            signal_type = signal_map.get(answer_correct, "partial_recall")
            canonical = self._normalize_topic(topic_name)
            topic_id = self._upsert_topic(canonical, topic_name.strip(), domain)
            if topic_id < 0:
                topic_id = None
            concept_clean = self._resolve_concept_text(concept_text, topic_id)
            if not teaching_approach and hasattr(self, "_infer_teaching_approach_v2"):
                teaching_approach = self._infer_teaching_approach_v2(
                    question_text=question_text,
                    answer_text=answer_text,
                    correction_text=correction_text,
                    skill=skill,
                    topic_name=topic_name,
                    concept_text=concept_clean,
                    answer_correct=answer_correct,
                    depth=depth,
                )
            if int(answer_correct or 0) < 2 and hasattr(self, "_infer_missing_error_metadata_v2"):
                inferred = self._infer_missing_error_metadata_v2(
                    answer_correct=answer_correct,
                    answer_text=answer_text,
                    correction_text=correction_text,
                    error_type=error_type,
                    root_cause=root_cause,
                    misconception=misconception,
                    concept_text=concept_clean,
                    question_text=question_text,
                )
                error_type = inferred.get("error_type", error_type)
                root_cause = inferred.get("root_cause", root_cause)
                misconception = inferred.get("misconception", misconception)
            content_text = f"Q: {question_text}\nA: {answer_text}"
            if correction_text:
                content_text += f"\nCorrection: {correction_text}"
            memory_payload = {
                "question": question_text,
                "answer": answer_text,
                "answer_correct": answer_correct,
                "correction": correction_text,
                "error_type": error_type,
                "error_process": error_process,
                "misconception": misconception,
                "root_cause": root_cause,
                "remediation": remediation,
                "teaching_approach": teaching_approach,
                "retrieval_sources": retrieval_sources,
                "breakthrough": breakthrough,
                "insight": insight_text,
                "depth": depth,
                "domain": domain,
            }
            confidence = response_confidence.strip().lower() or self._infer_response_confidence(answer_text)
            if confidence in ("high", "low"):
                memory_payload["response_confidence"] = confidence
                memory_payload["response_confidence_source"] = (
                    "explicit" if response_confidence.strip() else "language_inference"
                )
            memory_event_id = self.append_memory_event(
                event_type="active_answer",
                session_ts=session_ts,
                turn_number=turn_number,
                skill=skill,
                topic_name=topic_name,
                concept_text=concept_clean,
                actor="user",
                content_text=content_text,
                payload=memory_payload,
                source=skill,
                domain=domain,
            )
            existing = self.conn.execute(
                """SELECT exchange_id, signal_event_id, memory_event_id
                   FROM learning_exchanges
                   WHERE session_ts = ? AND turn_number = ? AND skill = ?
                     AND concept_text = ?
                     AND question_text = ?
                     AND answer_text = ?
                   ORDER BY exchange_id ASC
                   LIMIT 1""",
                (
                    session_ts, turn_number, skill, concept_clean,
                    question_text, answer_text,
                ),
            ).fetchone()
            if existing and existing["signal_event_id"]:
                if memory_event_id > 0 and not existing["memory_event_id"]:
                    with self.conn:
                        self.conn.execute(
                            "UPDATE learning_exchanges SET memory_event_id = ? WHERE exchange_id = ?",
                            (memory_event_id, existing["exchange_id"]),
                        )
                v2_result = {}
                if hasattr(self, "record_active_answer_v2"):
                    try:
                        v2_result = self.record_active_answer_v2(
                            session_ts=session_ts,
                            turn_number=turn_number,
                            skill=skill,
                            topic_name=topic_name,
                            concept_text=concept_clean,
                            question_text=question_text,
                            answer_text=answer_text,
                            answer_correct=answer_correct,
                            correction_text=correction_text,
                            error_type=error_type,
                            error_process=error_process,
                            misconception=misconception,
                            root_cause=root_cause,
                            remediation=remediation,
                            teaching_approach=teaching_approach,
                            retrieval_sources=retrieval_sources,
                            breakthrough=breakthrough,
                            insight_text=insight_text,
                            domain=domain,
                            depth=depth,
                            response_confidence=confidence,
                            memory_event_id=memory_event_id if memory_event_id > 0 else existing["memory_event_id"],
                            exchange_id=existing["exchange_id"],
                            signal_event_id=existing["signal_event_id"],
                        )
                    except Exception as exc:
                        print(f"[knowledge_graph] record_active_answer_v2 dedupe error: {exc}", file=sys.stderr)
                return {
                    "ok": True,
                    "signal_event_id": existing["signal_event_id"],
                    "exchange_id": existing["exchange_id"],
                    "memory_event_id": memory_event_id if memory_event_id > 0 else existing["memory_event_id"],
                    "signal_type": signal_type,
                    "concept": concept_clean,
                    "deduped": True,
                    "memory_v2": v2_result,
                }
            signal_meta = {
                "concept": concept_clean,
                "answer_correct": answer_correct,
                "active_answer": True,
                "memory_event_id": memory_event_id,
            }
            if confidence in ("high", "low"):
                signal_meta["response_confidence"] = confidence
                signal_meta["response_confidence_source"] = (
                    "explicit" if response_confidence.strip() else "language_inference"
                )

            signal_event_id = self.log_signal(
                topic_name=topic_name,
                source=skill,
                signal_type=signal_type,
                depth_at_event=depth,
                metadata=signal_meta,
                category=domain,
            )

            exchange_id = self.log_exchange(
                session_ts=session_ts,
                turn_number=turn_number,
                skill=skill,
                topic_name=topic_name,
                concept_text=concept_clean,
                question_text=question_text,
                answer_text=answer_text,
                answer_correct=answer_correct,
                correction_text=correction_text,
                error_type=error_type,
                misconception=misconception,
                root_cause=root_cause,
                teaching_approach=teaching_approach,
                retrieval_sources=retrieval_sources,
                breakthrough=breakthrough,
                insight_text=insight_text,
                signal_event_id=signal_event_id if signal_event_id > 0 else None,
                memory_event_id=memory_event_id if memory_event_id > 0 else None,
                domain=domain,
                depth=depth,
            )

            if answer_correct == 2:
                understood = [concept_clean]
                gaps: list[str] = []
                gap_details: list[dict] = []
            else:
                understood = []
                gaps = []
                gap_details = [{
                    "concept": concept_clean,
                    "error_type": error_type or ("partial_recall" if answer_correct == 1 else "unknown"),
                    "misconception": misconception,
                    "root_cause": root_cause,
                    "error_process": error_process,
                    "remediation": remediation or correction_text or teaching_approach,
                }]

            self.log_study_session(
                topics=[topic_name],
                understood=understood,
                gaps=gaps,
                gap_details=gap_details,
                depth=depth,
                source=skill,
                trigger_exchange_id=exchange_id if exchange_id > 0 else None,
                trigger_signal_id=signal_event_id if signal_event_id > 0 else None,
                trigger_memory_event_id=memory_event_id if memory_event_id > 0 else None,
            )

            v2_result = {}
            if hasattr(self, "record_active_answer_v2"):
                try:
                    v2_result = self.record_active_answer_v2(
                        session_ts=session_ts,
                        turn_number=turn_number,
                        skill=skill,
                        topic_name=topic_name,
                        concept_text=concept_clean,
                        question_text=question_text,
                        answer_text=answer_text,
                        answer_correct=answer_correct,
                        correction_text=correction_text,
                        error_type=error_type,
                        error_process=error_process,
                        misconception=misconception,
                        root_cause=root_cause,
                        remediation=remediation,
                        teaching_approach=teaching_approach,
                        retrieval_sources=retrieval_sources,
                        breakthrough=breakthrough,
                        insight_text=insight_text,
                        domain=domain,
                        depth=depth,
                        response_confidence=confidence,
                        memory_event_id=memory_event_id if memory_event_id > 0 else None,
                        exchange_id=exchange_id if exchange_id > 0 else None,
                        signal_event_id=signal_event_id if signal_event_id > 0 else None,
                    )
                except Exception as exc:
                    print(f"[knowledge_graph] record_active_answer_v2 error: {exc}", file=sys.stderr)

            return {
                "ok": exchange_id > 0 and signal_event_id > 0,
                "signal_event_id": signal_event_id,
                "exchange_id": exchange_id,
                "memory_event_id": memory_event_id,
                "signal_type": signal_type,
                "concept": concept_clean,
                "memory_v2": v2_result,
            }
        except Exception as exc:
            print(f"[knowledge_graph] log_answer error: {exc}", file=sys.stderr)
            return {"ok": False, "error": str(exc)}

    def get_session_exchanges(self, session_ts: str) -> list[dict]:
        """Return all learning exchanges for a given session timestamp."""
        try:
            rows = self.conn.execute(
                """SELECT le.*, t.display_name AS topic_display
                   FROM learning_exchanges le
                   LEFT JOIN topics t ON le.topic_id = t.topic_id
                   WHERE le.session_ts = ?
                   ORDER BY le.turn_number""",
                (session_ts,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            print(f"[knowledge_graph] get_session_exchanges error: {exc}", file=sys.stderr)
            return []

    def link_exchanges_to_narrative(self, session_ts: str, narrative_id: int) -> int:
        """Set narrative_id on all exchanges for a session. Returns count updated."""
        try:
            with self.conn:
                cur = self.conn.execute(
                    "UPDATE learning_exchanges SET narrative_id = ? WHERE session_ts = ?",
                    (narrative_id, session_ts),
                )
                return cur.rowcount
        except Exception as exc:
            print(f"[knowledge_graph] link_exchanges_to_narrative error: {exc}", file=sys.stderr)
            return 0

    def exchange_history(
        self,
        topic_name: str | None = None,
        concept_text: str | None = None,
        error_type: str | None = None,
        answer_correct: int | None = None,
        skill: str | None = None,
        days_back: int = 90,
        top: int = 20,
        breakthrough_only: bool = False,
    ) -> list[dict]:
        """Query learning exchanges with structured filters.

        Parameters
        ----------
        topic_name : str | None
            Filter by topic (substring match on display_name).
        concept_text : str | None
            Filter by concept (substring match).
        error_type : str | None
            Exact match on error_type.
        answer_correct : int | None
            0=incorrect, 1=partial, 2=correct.
        skill : str | None
            Exact match on skill.
        days_back : int
            Lookback window in days.
        top : int
            Max rows to return.
        breakthrough_only : bool
            If True, only return exchanges marked as breakthroughs.

        Returns a list of dicts ordered by session_ts DESC, turn_number DESC.
        """
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
            clauses = ["le.session_ts >= ?"]
            params: list = [cutoff]

            if topic_name:
                clauses.append("t.display_name LIKE ?")
                params.append(f"%{topic_name}%")
            if concept_text:
                clauses.append("le.concept_text LIKE ?")
                params.append(f"%{concept_text.strip().lower()}%")
            if error_type:
                clauses.append("le.error_type = ?")
                params.append(error_type)
            if answer_correct is not None:
                clauses.append("le.answer_correct = ?")
                params.append(answer_correct)
            if skill:
                clauses.append("le.skill = ?")
                params.append(skill)
            if breakthrough_only:
                clauses.append("le.breakthrough = 1")

            where = " AND ".join(clauses)
            sql = f"""SELECT le.*, t.display_name AS topic_display
                      FROM learning_exchanges le
                      LEFT JOIN topics t ON le.topic_id = t.topic_id
                      WHERE {where}
                      ORDER BY le.session_ts DESC, le.turn_number DESC
                      LIMIT ?"""
            params.append(top)

            rows = self.conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            print(f"[knowledge_graph] exchange_history error: {exc}", file=sys.stderr)
            return []

    def create_episode_summary(
        self,
        session_ts: str,
        skill: str,
        narrative_id: int | None = None,
        memory_text: str = "",
        exchanges: list[dict] | None = None,
        persistent_confusions: list[dict] | None = None,
        effective_approaches: list[dict] | None = None,
        failed_approaches: list[dict] | None = None,
    ) -> int:
        """Create an episode summary for a session.

        Computes aggregate counts from provided exchanges and persists
        the natural-language memory_text for semantic retrieval.

        Returns the summary_id of the inserted row, or -1 on error.
        """
        try:
            exs = exchanges or []
            correct = sum(1 for e in exs if e.get("answer_correct") == 2)
            partial = sum(1 for e in exs if e.get("answer_correct") == 1)
            incorrect = sum(1 for e in exs if e.get("answer_correct") == 0)
            breakthroughs = sum(1 for e in exs if e.get("breakthrough"))
            source_exchange_ids = [
                int(e["exchange_id"]) for e in exs
                if e.get("exchange_id") is not None
            ]
            source_memory_event_ids = [
                int(e["memory_event_id"]) for e in exs
                if e.get("memory_event_id")
            ]
            memory_hash = hashlib.sha256(
                (memory_text + "|" + ",".join(str(x) for x in sorted(source_exchange_ids))).encode("utf-8")
            ).hexdigest()
            dedupe_key = self._memory_hash("episode_summary", session_ts, skill)

            existing = self.conn.execute(
                """SELECT summary_id
                   FROM episode_summaries
                   WHERE dedupe_key = ?
                      OR (session_ts = ? AND skill = ?)
                   ORDER BY summary_id ASC
                   LIMIT 1""",
                (dedupe_key, session_ts, skill),
            ).fetchone()
            if existing:
                with self.conn:
                    self.conn.execute(
                        """UPDATE episode_summaries
                           SET narrative_id = COALESCE(?, narrative_id),
                               persistent_confusions = ?,
                               effective_approaches = ?,
                               failed_approaches = ?,
                               exchange_count = ?,
                               correct_count = ?,
                               partial_count = ?,
                               incorrect_count = ?,
                               breakthrough_count = ?,
                               memory_text = ?,
                               source_exchange_ids = ?,
                               source_memory_event_ids = ?,
                               memory_hash = ?,
                               dedupe_key = ?
                           WHERE summary_id = ?""",
                        (
                            narrative_id,
                            json.dumps(persistent_confusions or []),
                            json.dumps(effective_approaches or []),
                            json.dumps(failed_approaches or []),
                            len(exs), correct, partial, incorrect, breakthroughs,
                            memory_text,
                            json.dumps(source_exchange_ids),
                            json.dumps(source_memory_event_ids),
                            memory_hash,
                            dedupe_key,
                            existing["summary_id"],
                        ),
                    )
                summary_id = existing["summary_id"]
                self._upsert_memory_fts(
                    "episode_summary",
                    summary_id,
                    session_ts=session_ts,
                    skill=skill,
                    summary_text=memory_text,
                    payload_text=json.dumps({
                        "source_exchange_ids": source_exchange_ids,
                        "source_memory_event_ids": source_memory_event_ids,
                        "persistent_confusions": persistent_confusions or [],
                        "effective_approaches": effective_approaches or [],
                        "failed_approaches": failed_approaches or [],
                    }, sort_keys=True, default=str),
                )
                return summary_id

            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO episode_summaries
                       (session_ts, skill, narrative_id,
                        persistent_confusions, effective_approaches, failed_approaches,
                        exchange_count, correct_count, partial_count,
                        incorrect_count, breakthrough_count, memory_text,
                        source_exchange_ids, source_memory_event_ids,
                        memory_hash, dedupe_key)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_ts, skill, narrative_id,
                        json.dumps(persistent_confusions or []),
                        json.dumps(effective_approaches or []),
                        json.dumps(failed_approaches or []),
                        len(exs), correct, partial, incorrect, breakthroughs,
                        memory_text,
                        json.dumps(source_exchange_ids),
                        json.dumps(source_memory_event_ids),
                        memory_hash,
                        dedupe_key,
                    ),
                )
                summary_id = cur.lastrowid or -1
            if summary_id > 0:
                self._upsert_memory_fts(
                    "episode_summary",
                    summary_id,
                    session_ts=session_ts,
                    skill=skill,
                    summary_text=memory_text,
                    payload_text=json.dumps({
                        "source_exchange_ids": source_exchange_ids,
                        "source_memory_event_ids": source_memory_event_ids,
                        "persistent_confusions": persistent_confusions or [],
                        "effective_approaches": effective_approaches or [],
                        "failed_approaches": failed_approaches or [],
                    }, sort_keys=True, default=str),
                )
            return summary_id
        except Exception as exc:
            print(f"[knowledge_graph] create_episode_summary error: {exc}", file=sys.stderr)
            return -1

    @staticmethod
    def _episode_memory_text(session_ts: str, exchanges: list[dict]) -> str:
        """Build compact natural-language memory text for semantic episode retrieval."""
        topics: set[str] = set()
        correct = partial = incorrect = 0
        error_lines: list[str] = []
        approach_lines: list[str] = []
        for ex in exchanges:
            topic = ex.get("topic_display") or ex.get("concept_text", "")
            if topic:
                topics.add(topic)
            answer_correct = ex.get("answer_correct", -1)
            if answer_correct == 2:
                correct += 1
            elif answer_correct == 1:
                partial += 1
            elif answer_correct == 0:
                incorrect += 1
                error_lines.append(
                    f"Q: {ex.get('question_text', '')[:80]} Gabriel answered: "
                    f"{ex.get('answer_text', '')[:60]} -- correct: "
                    f"{ex.get('correction_text', '')[:80]}. "
                    f"Error type: {ex.get('error_type', 'unknown')}."
                )
            approach = ex.get("teaching_approach", "")
            worked = ex.get("teaching_worked", -1)
            if approach and worked in (0, 1):
                approach_lines.append(f"{approach} ({'worked' if worked == 1 else 'failed'})")

        total = correct + partial + incorrect
        date_str = session_ts[:10] if session_ts else "unknown"
        topics_str = ", ".join(sorted(topics)[:5]) or "unknown"
        parts = [f"Session on {topics_str} ({date_str}). {correct}/{total} correct."]
        if error_lines:
            parts.append("Errors: " + " ".join(error_lines[:5]))
        if approach_lines:
            parts.append("Approaches: " + ", ".join(sorted(set(approach_lines))[:5]) + ".")
        return " ".join(parts)

    def consolidate_episodic_memory(
        self,
        limit: int = 5,
        fallback_skill: str = "",
    ) -> dict:
        """Consolidate unconsolidated exchanges into summaries and semantic memory rows."""
        recent_sessions = self.conn.execute(
            """SELECT DISTINCT session_ts FROM learning_exchanges
               WHERE consolidated_at IS NULL
                  OR consolidated_at = ''
                  OR lance_row_id IS NULL
                  OR lance_row_id = ''
               ORDER BY session_ts DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        total_consolidated = 0
        total_embedded = 0

        for session_row in recent_sessions:
            session_ts = session_row["session_ts"]
            exchanges = self.get_session_exchanges(session_ts)
            if not exchanges:
                continue

            skill = exchanges[0].get("skill") or fallback_skill
            nar_row = self.conn.execute(
                """SELECT narrative_id FROM session_narratives
                   WHERE skill = ? ORDER BY session_ts DESC LIMIT 1""",
                (skill,),
            ).fetchone()
            narrative_id = nar_row["narrative_id"] if nar_row else None
            if narrative_id:
                self.link_exchanges_to_narrative(session_ts, narrative_id)

            memory_text = self._episode_memory_text(session_ts, exchanges)
            summary_id = self.create_episode_summary(
                session_ts=session_ts,
                skill=skill,
                narrative_id=narrative_id,
                memory_text=memory_text,
                exchanges=exchanges,
            )
            total_consolidated += len(exchanges)

            try:
                import lance_retriever as lr
                exchanges_to_embed = [
                    ex for ex in exchanges
                    if not (ex.get("lance_row_id") or "").strip()
                ]
                summary_row = self.conn.execute(
                    "SELECT lance_row_id FROM episode_summaries WHERE summary_id = ?",
                    (summary_id,),
                ).fetchone() if summary_id > 0 else None
                summary_needs_embed = (
                    summary_id > 0
                    and (not summary_row or not (summary_row["lance_row_id"] or "").strip())
                )
                summary_dict = {
                    "summary_id": summary_id,
                    "session_ts": session_ts,
                    "skill": skill,
                    "memory_text": memory_text,
                } if summary_needs_embed else None
                embed_result = lr.embed_episodes(
                    exchanges_to_embed,
                    episode_summary=summary_dict,
                )
                total_embedded += embed_result.get("rows_inserted", 0)

                row_ids = embed_result.get("row_ids", [])
                for i, ex in enumerate(exchanges_to_embed):
                    if i < len(row_ids):
                        self.conn.execute(
                            "UPDATE learning_exchanges SET lance_row_id = ? WHERE exchange_id = ?",
                            (row_ids[i], ex["exchange_id"]),
                        )
                if summary_needs_embed and summary_id > 0 and len(row_ids) > len(exchanges_to_embed):
                    self.conn.execute(
                        "UPDATE episode_summaries SET lance_row_id = ? WHERE summary_id = ?",
                        (row_ids[-1], summary_id),
                    )
            except Exception as exc:
                print(f"[knowledge_graph] episodic embedding failed (non-fatal): {exc}", file=sys.stderr)

            self.conn.execute(
                "UPDATE learning_exchanges SET consolidated_at = ? WHERE session_ts = ?",
                (datetime.now(timezone.utc).isoformat(), session_ts),
            )
            self.conn.commit()

        return {
            "sessions": len(recent_sessions),
            "exchanges_consolidated": total_consolidated,
            "rows_embedded": total_embedded,
        }

    def mark_teaching_worked(self, concept_text: str, topic_name: str | None = None) -> int:
        """Retroactively mark the most recent incorrect exchange for a concept
        as having its teaching approach work (because the concept was later
        recalled correctly).

        Returns exchange_id of the updated row, or -1 if none found.
        """
        try:
            canonical_concept = concept_text.strip().lower()
            clauses = ["le.concept_text = ?", "le.answer_correct = 0", "le.teaching_worked = -1"]
            params: list = [canonical_concept]

            if topic_name:
                canonical_topic = self._normalize_topic(topic_name)
                clauses.append("t.canonical_name = ?")
                params.append(canonical_topic)

            where = " AND ".join(clauses)
            row = self.conn.execute(
                f"""SELECT le.exchange_id
                    FROM learning_exchanges le
                    LEFT JOIN topics t ON le.topic_id = t.topic_id
                    WHERE {where}
                    ORDER BY le.session_ts DESC, le.turn_number DESC
                    LIMIT 1""",
                params,
            ).fetchone()

            if row:
                with self.conn:
                    self.conn.execute(
                        "UPDATE learning_exchanges SET teaching_worked = 1 WHERE exchange_id = ?",
                        (row["exchange_id"],),
                    )
                return row["exchange_id"]
            return -1
        except Exception as exc:
            print(f"[knowledge_graph] mark_teaching_worked error: {exc}", file=sys.stderr)
            return -1

    # ── Concept Evolution Tracking ──

    def log_concept_evolution(
        self,
        concept_id: int,
        topic_id: int,
        new_status: str,
        trigger_type: str,
        previous_status: str = "",
        previous_misconception: str = "",
        error_type: str = "",
        misconception: str = "",
        remediation: str = "",
        times_confirmed: int = 0,
        times_missed: int = 0,
        trigger_exchange_id: int | None = None,
        trigger_signal_id: int | None = None,
        trigger_memory_event_id: int | None = None,
        evolution_note: str = "",
    ) -> int:
        """Record a concept state change in the evolution history.

        Called automatically when concept_mastery is updated via
        log_study_session() or _upsert_concept_gap().

        Returns evolution_id or -1 on error.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO concept_evolution
                       (concept_id, topic_id, timestamp, status,
                        error_type, misconception, remediation,
                        times_confirmed, times_missed,
                        trigger_type, trigger_exchange_id, trigger_signal_id,
                        trigger_memory_event_id,
                        previous_status, previous_misconception, evolution_note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (concept_id, topic_id, now, new_status,
                     error_type, misconception, remediation,
                     times_confirmed, times_missed,
                     trigger_type, trigger_exchange_id, trigger_signal_id,
                     trigger_memory_event_id,
                     previous_status, previous_misconception, evolution_note),
                )
                return cur.lastrowid or -1
        except Exception as exc:
            print(f"[knowledge_graph] log_concept_evolution error: {exc}", file=sys.stderr)
            return -1

    def concept_evolution_history(
        self,
        concept_text: str | None = None,
        topic_name: str | None = None,
        days_back: int = 180,
        limit: int = 50,
    ) -> list[dict]:
        """Query the evolution history for a concept or topic.

        Returns a list of state-change records ordered by timestamp DESC.
        """
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
            clauses = ["ce.timestamp >= ?"]
            params: list = [cutoff]

            if concept_text:
                clauses.append("cm.concept_text LIKE ?")
                params.append(f"%{concept_text.strip().lower()}%")
            if topic_name:
                clauses.append("t.display_name LIKE ?")
                params.append(f"%{topic_name}%")

            where = " AND ".join(clauses)
            params.append(limit)

            rows = self.conn.execute(
                f"""SELECT ce.*, cm.concept_text, t.display_name AS topic_display
                    FROM concept_evolution ce
                    JOIN concept_mastery cm ON ce.concept_id = cm.concept_id
                    LEFT JOIN topics t ON ce.topic_id = t.topic_id
                    WHERE {where}
                    ORDER BY ce.timestamp DESC
                    LIMIT ?""",
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            print(f"[knowledge_graph] concept_evolution_history error: {exc}", file=sys.stderr)
            return []

    def derive_session_confusions(
        self,
        session_ts: str | None = None,
        skill: str | None = None,
        hours_back: int = 4,
    ) -> list[dict]:
        """Derive key_confusions pairs from recent learning_exchanges.

        Queries exchanges with confusion error types (cross_contamination,
        conceptual_confusion) and constructs concept pairs suitable for
        log_session_narrative's key_confusions parameter.

        Parameters
        ----------
        session_ts : str | None
            If provided, use as the start boundary (ISO timestamp). Otherwise
            looks back hours_back hours from now.
        skill : str | None
            Filter to a specific skill (e.g. 'study-session').
        hours_back : int
            Hours to look back when session_ts is not provided (default 4).

        Returns
        -------
        list[dict]
            Each dict: {"concept_a": str, "concept_b": str,
                        "disambiguation_axis": str, "misconception": str}
        """
        try:
            now = datetime.now(timezone.utc)
            cutoff = session_ts if session_ts else (now - timedelta(hours=hours_back)).isoformat()

            clauses = [
                "le.session_ts >= ?",
                "le.error_type IN ('cross_contamination', 'conceptual_confusion')",
                "le.answer_correct = 0",
            ]
            params: list = [cutoff]

            if skill:
                clauses.append("le.skill = ?")
                params.append(skill)

            rows = self.conn.execute(
                f"""SELECT le.concept_text, le.misconception, le.correction_text,
                          le.error_type, le.root_cause, t.display_name AS topic
                   FROM learning_exchanges le
                   LEFT JOIN topics t ON le.topic_id = t.topic_id
                   WHERE {' AND '.join(clauses)}
                   ORDER BY le.session_ts DESC""",
                params,
            ).fetchall()

            confusions: list[dict] = []
            seen: set[str] = set()

            for row in rows:
                concept_a = (row["concept_text"] or "").strip()
                if not concept_a:
                    continue

                # Extract concept_b from misconception using proximity markers
                misconception = row["misconception"] or ""
                concept_b = ""
                for marker in (" with ", " for ", " vs ", " versus ", " instead of ", " not "):
                    idx = misconception.lower().find(marker)
                    if idx >= 0:
                        candidate = misconception[idx + len(marker):].strip()
                        for stop in [".", ",", ";", "("]:
                            stop_idx = candidate.find(stop)
                            if 0 < stop_idx < 60:
                                candidate = candidate[:stop_idx].strip()
                        if candidate and len(candidate) >= 3:
                            concept_b = candidate[:60]
                            break

                # disambiguation_axis: prefer root_cause, else derive from error_type
                if row["root_cause"]:
                    axis = row["root_cause"][:120]
                elif row["error_type"] == "cross_contamination":
                    axis = "Distinguish the specific pathway/structure that applies to each concept"
                else:
                    axis = "Clarify the precise definitional boundary between the two concepts"

                key = f"{concept_a.lower()}|{concept_b.lower()}"
                if key in seen:
                    continue
                seen.add(key)

                confusions.append({
                    "concept_a": concept_a,
                    "concept_b": concept_b if concept_b else "(see misconception)",
                    "disambiguation_axis": axis,
                    "misconception": misconception[:100],
                })

            return confusions
        except Exception as exc:
            print(f"[knowledge_graph] derive_session_confusions error: {exc}", file=sys.stderr)
            return []

    def domain_error_profile(self, domain: str, days_back: int = 90) -> dict:
        """Aggregate error patterns for a clinical domain.

        Returns a structured profile of error types, misconception themes,
        teaching approach effectiveness, and ZPD indicators for the domain.
        Useful for session planning and identifying domain-specific blind spots.

        Parameters
        ----------
        domain : str
            Domain slug (e.g. 'vascular', 'spine', 'tumor').
        days_back : int
            Lookback window in days (default 90).

        Returns
        -------
        dict
            {
              "domain": str,
              "total_exchanges": int,
              "error_type_distribution": {"type": count, ...},
              "top_misconceptions": [{"concept": str, "misconception": str, "count": int}],
              "teaching_approach_effectiveness": [{"approach": str, "success_rate": float, "n": int}],
              "persistent_gaps": [{"concept": str, "times_missed": int, "error_type": str}],
              "signal_summary": {"correct": int, "partial": int, "incorrect": int}
            }
        """
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

            # ── Error type distribution from learning_exchanges ──
            et_rows = self.conn.execute(
                """SELECT le.error_type, COUNT(*) AS n
                   FROM learning_exchanges le
                   WHERE le.domain = ? AND le.session_ts >= ?
                     AND le.error_type IS NOT NULL AND le.error_type != ''
                   GROUP BY le.error_type
                   ORDER BY n DESC""",
                (domain, cutoff),
            ).fetchall()
            error_dist = {r["error_type"]: r["n"] for r in et_rows}

            # ── Top misconceptions ──
            misc_rows = self.conn.execute(
                """SELECT le.concept_text, le.misconception, COUNT(*) AS n
                   FROM learning_exchanges le
                   WHERE le.domain = ? AND le.session_ts >= ?
                     AND le.misconception IS NOT NULL AND le.misconception != ''
                     AND le.answer_correct = 0
                   GROUP BY le.concept_text, le.misconception
                   ORDER BY n DESC
                   LIMIT 10""",
                (domain, cutoff),
            ).fetchall()
            top_misconceptions = [
                {"concept": r["concept_text"] or "", "misconception": r["misconception"] or "", "count": r["n"]}
                for r in misc_rows
            ]

            # ── Teaching approach effectiveness ──
            ta_rows = self.conn.execute(
                """SELECT le.teaching_approach,
                          COUNT(*) AS n,
                          SUM(CASE WHEN le.answer_correct = 2 THEN 1 ELSE 0 END) AS correct
                   FROM learning_exchanges le
                   WHERE le.domain = ? AND le.session_ts >= ?
                     AND le.teaching_approach IS NOT NULL AND le.teaching_approach != ''
                   GROUP BY le.teaching_approach
                   HAVING n >= 2
                   ORDER BY (correct * 1.0 / n) DESC""",
                (domain, cutoff),
            ).fetchall()
            ta_effectiveness = [
                {
                    "approach": r["teaching_approach"],
                    "success_rate": round(r["correct"] / r["n"], 3) if r["n"] else 0.0,
                    "n": r["n"],
                }
                for r in ta_rows
            ]

            # ── Persistent concept gaps from concept_mastery ──
            pg_rows = self.conn.execute(
                """SELECT cm.concept_text, cm.times_missed, cm.error_type, t.display_name AS topic
                   FROM concept_mastery cm
                   JOIN topics t ON cm.topic_id = t.topic_id
                   WHERE t.category = ? AND cm.status IN ('unknown', 'due')
                     AND cm.times_missed >= 2
                   ORDER BY cm.times_missed DESC
                   LIMIT 10""",
                (domain,),
            ).fetchall()
            persistent_gaps = [
                {"concept": r["concept_text"] or "", "times_missed": r["times_missed"] or 0,
                 "error_type": r["error_type"] or "", "topic": r["topic"] or ""}
                for r in pg_rows
            ]

            # ── Signal summary from signal_events ──
            sig_rows = self.conn.execute(
                """SELECT se.signal_type, COUNT(*) AS n
                   FROM signal_events se
                   JOIN topics t ON se.topic_id = t.topic_id
                   WHERE t.category = ? AND se.timestamp >= ?
                   GROUP BY se.signal_type""",
                (domain, cutoff),
            ).fetchall()
            sig_map: dict[str, int] = {}
            for r in sig_rows:
                sig_map[r["signal_type"]] = r["n"]

            return {
                "domain": domain,
                "days_back": days_back,
                "total_exchanges": sum(error_dist.values()) or sum(sig_map.values()),
                "error_type_distribution": error_dist,
                "top_misconceptions": top_misconceptions,
                "teaching_approach_effectiveness": ta_effectiveness,
                "persistent_gaps": persistent_gaps,
                "signal_summary": {
                    "correct": sig_map.get("correct_recall", 0),
                    "partial": sig_map.get("partial_recall", 0),
                    "incorrect": sig_map.get("incorrect_recall", 0),
                },
            }
        except Exception as exc:
            print(f"[knowledge_graph] domain_error_profile error: {exc}", file=sys.stderr)
            return {"domain": domain, "error": str(exc)}

    def _recall_filter_clauses(
        self,
        cutoff: str,
        topic_name: str | None,
        domain: str | None,
        error_type: str | None,
        answer_correct: int | None,
        skill: str | None,
    ) -> tuple[list[str], list]:
        """Build structured recall WHERE clauses and params."""
        clauses = ["le.session_ts >= ?"]
        params: list = [cutoff]
        if topic_name:
            clauses.append("t.display_name LIKE ?")
            params.append(f"%{topic_name}%")
        if domain:
            clauses.append("le.domain = ?")
            params.append(domain)
        if error_type:
            clauses.append("le.error_type = ?")
            params.append(error_type)
        if answer_correct is not None:
            clauses.append("le.answer_correct = ?")
            params.append(answer_correct)
        if skill:
            clauses.append("le.skill = ?")
            params.append(skill)
        return clauses, params

    def _recall_structured_rows(self, clauses: list[str], params: list, limit: int) -> list[dict]:
        """Return structured-filter exchange rows."""
        sql = (
            f"SELECT le.*, t.display_name AS topic_display "
            f"FROM learning_exchanges le "
            f"LEFT JOIN topics t ON le.topic_id = t.topic_id "
            f"WHERE {' AND '.join(clauses)} "
            f"ORDER BY le.session_ts DESC, le.turn_number DESC "
            f"LIMIT ?"
        )
        return [
            dict(row)
            for row in self.conn.execute(sql, [*params, limit]).fetchall()
        ]

    def _recall_keyword_ids(self, query: str, cutoff: str) -> set[int]:
        """Return exchange IDs matching simple keyword LIKE search."""
        keywords = [w for w in (query or "").lower().split() if len(w) >= 3]
        if not keywords:
            return set()

        kw_clauses = []
        kw_params: list = [cutoff]
        for kw in keywords[:5]:
            kw_clauses.append(
                "(le.concept_text LIKE ? OR le.question_text LIKE ? "
                "OR le.correction_text LIKE ? OR le.misconception LIKE ?)"
            )
            pat = f"%{kw}%"
            kw_params.extend([pat, pat, pat, pat])
        sql = (
            f"SELECT le.exchange_id FROM learning_exchanges le "
            f"WHERE le.session_ts >= ? AND ({' OR '.join(kw_clauses)}) "
            f"LIMIT 50"
        )
        return {
            row["exchange_id"]
            for row in self.conn.execute(sql, kw_params).fetchall()
        }

    def _recall_fts_rows(self, query: str, cutoff: str, skill: str | None, limit: int) -> list[dict]:
        """Return FTS/BM25 rows for exact memory text search."""
        fts_query = self._fts_match_query(query)
        if not fts_query:
            return []
        try:
            clauses = [
                "memory_fts MATCH ?",
                "entity_type = 'learning_exchange'",
                "session_ts >= ?",
            ]
            params: list = [fts_query, cutoff]
            if skill:
                clauses.append("skill = ?")
                params.append(skill)
            params.append(limit)
            return [
                dict(row)
                for row in self.conn.execute(
                    f"""SELECT entity_id AS exchange_id, bm25(memory_fts) AS bm25_rank
                        FROM memory_fts
                        WHERE {' AND '.join(clauses)}
                        ORDER BY bm25_rank ASC
                        LIMIT ?""",
                    params,
                ).fetchall()
            ]
        except Exception:
            return []

    @staticmethod
    def _recall_semantic_rows(query: str, max_results: int, use_semantic: bool) -> list[dict]:
        """Return LanceDB semantic episodic-memory rows when available."""
        if not use_semantic or not query or len(query.strip()) < 5:
            return []
        try:
            import lance_retriever as lr
            return [
                row for row in lr.search_episodic_memory(query, max_results=max_results * 2)
                if row.get("exchange_id", -1) > 0
            ]
        except Exception:
            return []

    def _recall_rankings(
        self,
        struct_rows: list[dict],
        keyword_ids: set[int],
        fts_rows: list[dict],
        semantic_rows: list[dict],
    ) -> list[dict[int, int]]:
        """Build per-stream ranked exchange-id maps for RRF fusion."""
        struct_ranking = {
            row["exchange_id"]: rank
            for rank, row in enumerate(struct_rows)
        }

        keyword_ranking: dict[int, int] = {}
        if keyword_ids:
            ordered_ids = list(keyword_ids)
            placeholders = ",".join("?" for _ in ordered_ids)
            rows = self.conn.execute(
                f"SELECT exchange_id FROM learning_exchanges "
                f"WHERE exchange_id IN ({placeholders}) "
                f"ORDER BY session_ts DESC, turn_number DESC",
                ordered_ids,
            ).fetchall()
            keyword_ranking = {
                row["exchange_id"]: rank
                for rank, row in enumerate(rows)
            }

        fts_ranking = {
            row["exchange_id"]: rank
            for rank, row in enumerate(fts_rows)
            if row.get("exchange_id", -1) > 0
        }
        semantic_ranking = {
            row["exchange_id"]: rank
            for rank, row in enumerate(semantic_rows)
            if row.get("exchange_id", -1) > 0
        }
        return [struct_ranking, keyword_ranking, fts_ranking, semantic_ranking]

    def _fetch_ranked_exchanges(self, ranked_ids: list[int], struct_rows: list[dict]) -> list[dict]:
        """Fetch full exchange rows for RRF-selected IDs in rank order."""
        struct_by_id = {row["exchange_id"]: row for row in struct_rows}
        exchanges = []
        missing_ids = []
        for xid in ranked_ids:
            if xid in struct_by_id:
                exchanges.append(struct_by_id[xid])
            else:
                missing_ids.append(xid)

        if missing_ids:
            placeholders = ",".join("?" for _ in missing_ids)
            extra = self.conn.execute(
                f"SELECT le.*, t.display_name AS topic_display "
                f"FROM learning_exchanges le "
                f"LEFT JOIN topics t ON le.topic_id = t.topic_id "
                f"WHERE le.exchange_id IN ({placeholders})",
                missing_ids,
            ).fetchall()
            extra_by_id = {row["exchange_id"]: dict(row) for row in extra}
            for xid in missing_ids:
                if xid in extra_by_id:
                    exchanges.append(extra_by_id[xid])

        id_order = {xid: i for i, xid in enumerate(ranked_ids)}
        exchanges.sort(key=lambda row: id_order.get(row["exchange_id"], 999))
        return exchanges

    def _episode_summaries_for_exchanges(self, exchanges: list[dict]) -> list[dict]:
        """Return episode summaries for sessions represented in exchange rows."""
        session_tss = list({row["session_ts"] for row in exchanges})
        if not session_tss:
            return []
        placeholders = ",".join("?" for _ in session_tss)
        rows = self.conn.execute(
            f"SELECT * FROM episode_summaries WHERE session_ts IN ({placeholders}) "
            f"ORDER BY session_ts DESC",
            session_tss,
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _episode_patterns(exchanges: list[dict]) -> dict:
        """Extract persistent confusions and teaching-effectiveness patterns."""
        confusion_counter: dict[str, int] = defaultdict(int)
        effective_counter: dict[str, dict] = {}
        failed_counter: dict[str, dict] = {}

        for exchange in exchanges:
            if exchange.get("answer_correct") == 0 and exchange.get("misconception"):
                key = f"{exchange.get('concept_text', '')}:{exchange.get('misconception', '')}"
                confusion_counter[key] += 1

            approach = exchange.get("teaching_approach", "")
            if not approach:
                continue
            if exchange.get("teaching_worked") == 1:
                if approach not in effective_counter:
                    effective_counter[approach] = {"approach": approach, "concepts": [], "count": 0}
                effective_counter[approach]["count"] += 1
                effective_counter[approach]["concepts"].append(exchange.get("concept_text", ""))
            elif exchange.get("teaching_worked") == 0:
                if approach not in failed_counter:
                    failed_counter[approach] = {"approach": approach, "concepts": [], "count": 0}
                failed_counter[approach]["count"] += 1
                failed_counter[approach]["concepts"].append(exchange.get("concept_text", ""))

        persistent_confusions = [
            {"concept_misconception": key, "frequency": count}
            for key, count in sorted(confusion_counter.items(), key=lambda item: -item[1])
            if count >= 2
        ]
        return {
            "persistent_confusions": persistent_confusions[:10],
            "effective_teaching": list(effective_counter.values())[:10],
            "failed_teaching": list(failed_counter.values())[:10],
        }

    def recall_episodes(
        self,
        query: str = "",
        topic_name: str | None = None,
        domain: str | None = None,
        error_type: str | None = None,
        answer_correct: int | None = None,
        skill: str | None = None,
        days_back: int = 90,
        max_results: int = 10,
        use_semantic: bool = True,
    ) -> dict:
        """Retrieve relevant past learning exchanges via RRF-fused retrieval.

        Fuses three retrieval streams using Reciprocal Rank Fusion (k=60):
          1. Structured SQLite filters (topic, domain, error_type, correctness)
          2. Keyword LIKE matching across content fields
          3. Semantic search via LanceDB episodic_memory embeddings

        Items appearing in multiple streams are boosted. Produces significantly
        more relevant results than the prior naive set-union merge.

        Returns:
          {
            "exchanges": [...],
            "episode_summaries": [...],
            "patterns": {
              "persistent_confusions": [...],
              "effective_teaching": [...],
              "failed_teaching": [...]
            }
          }
        """
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

            # ── Stream 1: Structured filter on learning_exchanges ──
            clauses, params = self._recall_filter_clauses(
                cutoff,
                topic_name,
                domain,
                error_type,
                answer_correct,
                skill,
            )

            # ── Stream 2: Keyword search from query across content fields ──
            keyword_ids = self._recall_keyword_ids(query, cutoff)

            # ── Stream 2b: SQLite FTS5/BM25 over exact memory text ──
            fts_rows = self._recall_fts_rows(
                query,
                cutoff,
                skill,
                limit=max_results * 3,
            )
            struct_rows = self._recall_structured_rows(
                clauses,
                params,
                limit=max_results * 3,
            )

            # ── Stream 3: Semantic search via LanceDB ──
            semantic_rows = self._recall_semantic_rows(query, max_results, use_semantic)

            rankings = self._recall_rankings(
                struct_rows,
                keyword_ids,
                fts_rows,
                semantic_rows,
            )
            sorted_ids = _rrf_rank(rankings, limit=max_results)
            exchanges = self._fetch_ranked_exchanges(sorted_ids, struct_rows)

            # ── Episode summaries for matching sessions ──
            summaries = self._episode_summaries_for_exchanges(exchanges)

            # ── Pattern extraction from results ──
            patterns = self._episode_patterns(exchanges)
            return {
                "exchanges": exchanges,
                "episode_summaries": summaries,
                "patterns": patterns,
            }
        except Exception as exc:
            print(f"[knowledge_graph] recall_episodes error: {exc}", file=sys.stderr)
            return {"exchanges": [], "episode_summaries": [], "patterns": {}}

    def recall_episodes_compact(
        self,
        query: str = "",
        topic_name: str | None = None,
        domain: str | None = None,
        error_type: str | None = None,
        answer_correct: int | None = None,
        skill: str | None = None,
        days_back: int = 90,
        max_results: int = 10,
        use_semantic: bool = True,
    ) -> dict:
        """Compact version of recall_episodes() for preflight token savings.

        Returns the same structure but with truncated text fields and a
        one-line summary per exchange instead of full verbatim content.
        Includes exchange_ids so full content can be fetched on demand
        via exchange_history().
        """
        full = self.recall_episodes(
            query=query, topic_name=topic_name, domain=domain,
            error_type=error_type, answer_correct=answer_correct,
            skill=skill, days_back=days_back, max_results=max_results,
            use_semantic=use_semantic,
        )

        compact_exchanges = []
        for ex in full.get("exchanges", []):
            correct_label = {0: "INCORRECT", 1: "PARTIAL", 2: "CORRECT"}.get(
                ex.get("answer_correct", -1), "UNKNOWN"
            )
            concept = ex.get("concept_text", "")[:40]
            misconception = ex.get("misconception", "")
            one_liner = f"{concept} ({correct_label})"
            if misconception:
                one_liner += f" -- {misconception[:50]}"

            entry = {
                "exchange_id": ex.get("exchange_id"),
                "concept": concept,
                "correct": ex.get("answer_correct"),
                "one_liner": one_liner,
                "date": (ex.get("session_ts") or "")[:10],
            }
            # Only include optional fields when they carry information
            if ex.get("error_type"):
                entry["error_type"] = ex["error_type"]
            if ex.get("teaching_approach"):
                entry["teaching_approach"] = ex["teaching_approach"]
            compact_exchanges.append(entry)

        compact_summaries = []
        for s in full.get("episode_summaries", []):
            compact_summaries.append({
                "session_ts": (s.get("session_ts") or "")[:10],
                "exchange_count": s.get("exchange_count", 0),
                "correct_count": s.get("correct_count", 0),
                "incorrect_count": s.get("incorrect_count", 0),
                "memory_preview": (s.get("memory_text") or "")[:80],
            })

        return {
            "exchanges": compact_exchanges,
            "episode_summaries": compact_summaries,
            "patterns": full.get("patterns", {}),
            "full_ids_available": [e["exchange_id"] for e in compact_exchanges],
        }

    def teaching_effectiveness(
        self,
        domain: str | None = None,
        days_back: int = 90,
    ) -> dict:
        """Analyze which teaching approaches work best for the learner.

        Returns a dict mapping teaching_approach → {success, failure, rate}.
        Only includes approaches with at least 2 data points.
        """
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
            clauses = ["le.session_ts >= ?", "le.teaching_approach != ''"]
            params: list = [cutoff]

            if domain:
                clauses.append("le.domain = ?")
                params.append(domain)

            where = " AND ".join(clauses)
            rows = self.conn.execute(
                f"""SELECT le.teaching_approach, le.teaching_worked
                    FROM learning_exchanges le
                    WHERE {where}""",
                params,
            ).fetchall()

            stats: dict[str, dict] = {}
            for row in rows:
                approach = row["teaching_approach"]
                worked = row["teaching_worked"]
                if approach not in stats:
                    stats[approach] = {"success": 0, "failure": 0, "unknown": 0}
                if worked == 1:
                    stats[approach]["success"] += 1
                elif worked == 0:
                    stats[approach]["failure"] += 1
                else:
                    stats[approach]["unknown"] += 1

            # Filter to approaches with at least 2 data points, compute rate
            result = {}
            for approach, s in stats.items():
                total = s["success"] + s["failure"]
                if total >= 2:
                    result[approach] = {
                        "success": s["success"],
                        "failure": s["failure"],
                        "unknown": s["unknown"],
                        "rate": round(s["success"] / total, 2) if total else 0.0,
                    }
                elif s["success"] + s["failure"] + s["unknown"] >= 1:
                    # Include with insufficient data flag
                    result[approach] = {
                        "success": s["success"],
                        "failure": s["failure"],
                        "unknown": s["unknown"],
                        "rate": None,
                        "note": "insufficient_data",
                    }

            return result
        except Exception as exc:
            print(f"[knowledge_graph] teaching_effectiveness error: {exc}", file=sys.stderr)
            return {}

    def memory_doctor(self) -> dict:
        """Audit long-term memory integrity without mutating state."""
        try:
            tables = {}
            for table in (
                "memory_events", "memory_sessions", "concept_aliases",
                "learning_exchanges", "episode_summaries", "concept_evolution",
            ):
                tables[table] = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]

            exchange_links = dict(self.conn.execute(
                """SELECT COUNT(*) AS total,
                          COALESCE(SUM(CASE WHEN memory_event_id IS NULL THEN 1 ELSE 0 END), 0) AS no_memory_event_link,
                          COALESCE(SUM(CASE WHEN signal_event_id IS NULL THEN 1 ELSE 0 END), 0) AS no_signal_link,
                          COALESCE(SUM(CASE WHEN narrative_id IS NULL THEN 1 ELSE 0 END), 0) AS no_narrative_link,
                          COALESCE(SUM(CASE WHEN lance_row_id IS NULL OR lance_row_id = '' THEN 1 ELSE 0 END), 0) AS no_lance_link,
                          COALESCE(SUM(CASE WHEN consolidated_at IS NULL OR consolidated_at = '' THEN 1 ELSE 0 END), 0) AS unconsolidated
                   FROM learning_exchanges"""
            ).fetchone())

            summary_links = dict(self.conn.execute(
                """SELECT COUNT(*) AS total,
                          COALESCE(SUM(CASE WHEN narrative_id IS NULL THEN 1 ELSE 0 END), 0) AS no_narrative_link,
                          COALESCE(SUM(CASE WHEN lance_row_id IS NULL OR lance_row_id = '' THEN 1 ELSE 0 END), 0) AS no_lance_link,
                          COALESCE(SUM(CASE WHEN source_exchange_ids IS NULL OR source_exchange_ids = '[]' THEN 1 ELSE 0 END), 0) AS no_source_exchange_ids,
                          COALESCE(SUM(CASE WHEN source_memory_event_ids IS NULL OR source_memory_event_ids = '[]' THEN 1 ELSE 0 END), 0) AS no_source_memory_event_ids
                   FROM episode_summaries"""
            ).fetchone())

            fts_status = {"available": False, "rows": 0}
            try:
                fts_status["rows"] = self.conn.execute(
                    "SELECT COUNT(*) AS n FROM memory_fts"
                ).fetchone()["n"]
                fts_status["available"] = True
            except Exception as exc:
                fts_status["error"] = str(exc)

            duplicate_summaries = [
                dict(r) for r in self.conn.execute(
                    """SELECT session_ts, skill, COUNT(*) AS n, GROUP_CONCAT(summary_id) AS summary_ids
                       FROM episode_summaries
                       GROUP BY session_ts, skill
                       HAVING COUNT(*) > 1
                       ORDER BY n DESC"""
                ).fetchall()
            ]

            duplicate_exchanges = [
                dict(r) for r in self.conn.execute(
                    """SELECT session_ts, turn_number, skill, concept_text, COUNT(*) AS n,
                              GROUP_CONCAT(exchange_id) AS exchange_ids
                       FROM learning_exchanges
                       GROUP BY session_ts, turn_number, skill, concept_text, question_text, answer_text
                       HAVING COUNT(*) > 1
                       ORDER BY n DESC"""
                ).fetchall()
            ]

            calibration = self.compute_calibration_profile()
            lance_status: dict = {"path": str(BASE_DIR), "episodic_rows": None, "duplicate_exchange_ids": []}
            try:
                import lancedb
                db = lancedb.connect(str(BASE_DIR))
                raw_names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
                names = list(raw_names.tables) if hasattr(raw_names, "tables") else list(raw_names)
                lance_status["tables"] = names
                if "episodic_memory" in names:
                    table = db.open_table("episodic_memory")
                    lance_status["episodic_rows"] = table.count_rows()
                    try:
                        df = table.to_pandas()
                        if "exchange_id" in df.columns:
                            counts = (
                                df[df["exchange_id"] > 0]
                                .groupby("exchange_id")
                                .size()
                                .reset_index(name="n")
                            )
                            dups = counts[counts["n"] > 1].to_dict(orient="records")
                            lance_status["duplicate_exchange_ids"] = dups[:20]
                    except Exception as exc:
                        lance_status["detail_error"] = str(exc)
            except Exception as exc:
                lance_status["error"] = str(exc)

            return {
                "db_path": str(self.db_path),
                "counts": tables,
                "exchange_links": exchange_links,
                "summary_links": summary_links,
                "duplicate_summaries": duplicate_summaries,
                "duplicate_exchanges": duplicate_exchanges,
                "calibration": calibration,
                "fts": fts_status,
                "lancedb": lance_status,
                "v2": self.memory_v2_doctor() if hasattr(self, "memory_v2_doctor") else {},
            }
        except Exception as exc:
            print(f"[knowledge_graph] memory_doctor error: {exc}", file=sys.stderr)
            return {"error": str(exc)}

    def reindex_memory_fts(self) -> dict:
        """Rebuild the optional SQLite FTS memory index from durable rows."""
        try:
            with self.conn:
                self.conn.execute("DELETE FROM memory_fts")
            counts = {"memory_events": 0, "learning_exchanges": 0, "episode_summaries": 0}

            event_rows = self.conn.execute(
                """SELECT me.*, t.display_name AS topic_display
                   FROM memory_events me
                   LEFT JOIN topics t ON me.topic_id = t.topic_id"""
            ).fetchall()
            for row in event_rows:
                self._upsert_memory_fts(
                    "memory_event",
                    row["memory_event_id"],
                    session_ts=row["session_ts"],
                    skill=row["skill"],
                    topic_text=row["topic_display"] or "",
                    concept_text=row["concept_text"] or "",
                    event_text=row["content_text"] or "",
                    payload_text=row["payload_json"] or "{}",
                )
                counts["memory_events"] += 1

            exchange_rows = self.conn.execute(
                """SELECT le.*, t.display_name AS topic_display
                   FROM learning_exchanges le
                   LEFT JOIN topics t ON le.topic_id = t.topic_id"""
            ).fetchall()
            for row in exchange_rows:
                self._upsert_memory_fts(
                    "learning_exchange",
                    row["exchange_id"],
                    session_ts=row["session_ts"],
                    skill=row["skill"],
                    topic_text=row["topic_display"] or "",
                    concept_text=row["concept_text"] or "",
                    question_text=row["question_text"] or "",
                    answer_text=row["answer_text"] or "",
                    correction_text=row["correction_text"] or "",
                    misconception=row["misconception"] or "",
                    root_cause=row["root_cause"] or "",
                )
                counts["learning_exchanges"] += 1

            summary_rows = self.conn.execute("SELECT * FROM episode_summaries").fetchall()
            for row in summary_rows:
                self._upsert_memory_fts(
                    "episode_summary",
                    row["summary_id"],
                    session_ts=row["session_ts"],
                    skill=row["skill"],
                    summary_text=row["memory_text"] or "",
                    payload_text=json.dumps({
                        "source_exchange_ids": row["source_exchange_ids"] or "[]",
                        "source_memory_event_ids": row["source_memory_event_ids"] or "[]",
                    }, sort_keys=True),
                )
                counts["episode_summaries"] += 1
            return {"ok": True, "indexed": counts}
        except Exception as exc:
            print(f"[knowledge_graph] reindex_memory_fts error: {exc}", file=sys.stderr)
            return {"ok": False, "error": str(exc)}

    def memory_rebuild(self, apply: bool = False) -> dict:
        """Regenerate missing derived active-answer rows from memory_events.

        This is intentionally conservative: it fills missing learning_exchanges
        for active_answer events that do not already have an exchange link, but
        it does not delete or rewrite existing derived memory.
        """
        try:
            rows = self.conn.execute(
                """SELECT me.*, t.display_name AS topic_display, t.category AS topic_domain
                   FROM memory_events me
                   LEFT JOIN topics t ON me.topic_id = t.topic_id
                   WHERE me.event_type = 'active_answer'
                   ORDER BY me.session_ts, me.turn_number"""
            ).fetchall()
            planned = []
            for row in rows:
                existing = self.conn.execute(
                    "SELECT exchange_id FROM learning_exchanges WHERE memory_event_id = ? LIMIT 1",
                    (row["memory_event_id"],),
                ).fetchone()
                if existing:
                    continue
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except Exception:
                    payload = {}
                planned.append({
                    "memory_event_id": row["memory_event_id"],
                    "session_ts": row["session_ts"],
                    "turn_number": row["turn_number"],
                    "skill": row["skill"],
                    "topic": row["topic_display"] or "",
                    "concept": row["concept_text"] or "",
                    "answer_correct": payload.get("answer_correct", 1),
                })
                if apply:
                    self.log_exchange(
                        session_ts=row["session_ts"],
                        turn_number=row["turn_number"],
                        skill=row["skill"],
                        topic_name=row["topic_display"] or "",
                        concept_text=row["concept_text"] or "",
                        question_text=payload.get("question", ""),
                        answer_text=payload.get("answer", ""),
                        answer_correct=int(payload.get("answer_correct", 1)),
                        correction_text=payload.get("correction", ""),
                        error_type=payload.get("error_type", ""),
                        misconception=payload.get("misconception", ""),
                        root_cause=payload.get("root_cause", ""),
                        teaching_approach=payload.get("teaching_approach", ""),
                        retrieval_sources=payload.get("retrieval_sources", ""),
                        breakthrough=bool(payload.get("breakthrough")),
                        insight_text=payload.get("insight", ""),
                        memory_event_id=row["memory_event_id"],
                        domain=payload.get("domain", row["topic_domain"] or ""),
                        depth=int(payload.get("depth", 1)),
                    )
            reindex = self.reindex_memory_fts() if apply else {"ok": True, "skipped": True}
            return {
                "ok": True,
                "mode": "apply" if apply else "dry_run",
                "missing_active_answer_exchanges": planned,
                "count": len(planned),
                "reindex": reindex,
            }
        except Exception as exc:
            print(f"[knowledge_graph] memory_rebuild error: {exc}", file=sys.stderr)
            return {"ok": False, "error": str(exc)}

    def memory_cleanup_plan(self, apply: bool = False, backup: bool = False) -> dict:
        """Plan or apply safe historical cleanup for duplicate SQLite summaries.

        LanceDB duplicate row cleanup is reported, not applied here, because
        vector-table deletion semantics vary by LanceDB version.
        """
        try:
            if apply and not backup:
                return {"ok": False, "error": "Refusing cleanup without --backup"}
            backup_path = ""
            if apply and backup:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup_path = str(self.db_path.with_suffix(f".memory_cleanup_backup_{stamp}.db"))
                shutil.copy2(self.db_path, backup_path)

            groups = self.conn.execute(
                """SELECT session_ts, skill, GROUP_CONCAT(summary_id) AS ids, COUNT(*) AS n
                   FROM episode_summaries
                   GROUP BY session_ts, skill
                   HAVING COUNT(*) > 1"""
            ).fetchall()
            actions = []
            for group in groups:
                ids = sorted(int(x) for x in (group["ids"] or "").split(",") if x)
                if not ids:
                    continue
                keep = ids[0]
                delete_ids = ids[1:]
                actions.append({
                    "type": "dedupe_episode_summaries",
                    "session_ts": group["session_ts"],
                    "skill": group["skill"],
                    "keep_summary_id": keep,
                    "delete_summary_ids": delete_ids,
                })
                if apply and delete_ids:
                    placeholders = ",".join("?" for _ in delete_ids)
                    with self.conn:
                        self.conn.execute(
                            f"DELETE FROM episode_summaries WHERE summary_id IN ({placeholders})",
                            delete_ids,
                        )
                        for sid in delete_ids:
                            self.conn.execute(
                                "DELETE FROM memory_fts WHERE entity_type = 'episode_summary' AND entity_id = ?",
                                (sid,),
                            )
            return {
                "ok": True,
                "mode": "apply" if apply else "dry_run",
                "backup_path": backup_path,
                "actions": actions,
                "note": "LanceDB duplicate rows are reported by memory_doctor and should be cleaned with a version-specific vector-table migration.",
            }
        except Exception as exc:
            print(f"[knowledge_graph] memory_cleanup_plan error: {exc}", file=sys.stderr)
            return {"ok": False, "error": str(exc)}

    def memory_guidance(
        self,
        query: str,
        topic_name: str | None = None,
        skill: str | None = None,
        max_results: int = 5,
        hybrid_semantic: bool = False,
        semantic_fallback_threshold: int = 3,
    ) -> dict:
        """Policy-level teaching guidance from prior memory.

        Runs SQLite/FTS/keyword recall by default, without loading the
        embedding model. If hybrid_semantic is True and fewer than
        semantic_fallback_threshold exchanges match, augments with Lance
        semantic search.
        """
        try:
            recall_fast = self.recall_episodes_compact(
                query=query,
                topic_name=topic_name,
                skill=skill,
                max_results=max_results,
                use_semantic=False,
            )
            fast_n = len(recall_fast.get("exchanges") or [])
            semantic_augmented = False
            recall = recall_fast
            qstrip = (query or "").strip()
            if (
                hybrid_semantic
                and fast_n < semantic_fallback_threshold
                and len(qstrip) >= 3
            ):
                recall_sem = self.recall_episodes_compact(
                    query=query,
                    topic_name=topic_name,
                    skill=skill,
                    max_results=max_results,
                    use_semantic=True,
                )
                recall = _merge_compact_recall_for_guidance(
                    recall_fast, recall_sem, max_results
                )
                semantic_augmented = True

            actions = []
            for ex in recall.get("exchanges", []):
                if ex.get("correct") == 0:
                    actions.append({
                        "policy": "retest_prior_misconception",
                        "exchange_id": ex.get("exchange_id"),
                        "concept": ex.get("concept"),
                        "reason": ex.get("one_liner"),
                        "instruction": "Ask retrieval-first; do not explain until Gabriel commits to an answer.",
                    })
                elif ex.get("correct") == 2:
                    actions.append({
                        "policy": "avoid_reteaching_mastered_content",
                        "exchange_id": ex.get("exchange_id"),
                        "concept": ex.get("concept"),
                        "reason": "Previously correct recall.",
                        "instruction": "Use as an anchor or transfer test instead of re-explaining basics.",
                    })
            confusables = self.get_confusable_pairs(topic=topic_name or "")[:3]
            for pair in confusables:
                actions.append({
                    "policy": "train_discrimination_axis",
                    "concept": f"{pair.get('concept_a', '')} vs {pair.get('concept_b', '')}",
                    "reason": pair.get("disambiguation_axis") or "Known confusable pair.",
                    "instruction": "Contrast the discriminating feature in a vignette.",
                })
            if not actions:
                actions.append({
                    "policy": "cold_start",
                    "reason": "No relevant prior memory found.",
                    "instruction": "Start with a short active recall probe, then log the answer.",
                })
            context_pack = {}
            if hasattr(self, "context_pack"):
                try:
                    context_pack = self.context_pack(
                        query,
                        topic_name=topic_name,
                        skill=skill,
                        intent="teach",
                        max_tokens=900,
                        log_retrieval=False,
                    )
                except Exception as exc:
                    context_pack = {"ok": False, "error": str(exc)}
            return {
                "query": query,
                "topic": topic_name or "",
                "actions": actions[:8],
                "recall": recall,
                "context_pack": context_pack,
                "hybrid": {
                    "semantic_augmented": semantic_augmented,
                    "fast_exchange_count": fast_n,
                    "semantic_fallback_threshold": semantic_fallback_threshold,
                },
            }
        except Exception as exc:
            print(f"[knowledge_graph] memory_guidance error: {exc}", file=sys.stderr)
            return {"query": query, "error": str(exc), "actions": []}

    def study_plan(
        self,
        hours: float = 1.0,
        rotation: str | None = None,
        focus: str | None = None,
    ) -> dict:
        """Generate an integrated, memory-driven study plan.

        Fuses SRS due concepts, error-typed gaps, prior session strategy,
        confusable pairs, transfer candidates, and cognitive patterns into a
        ranked plan. This is intentionally structured so CLI agents can execute
        the plan directly instead of manually stitching JSON outputs together.
        """
        try:
            minutes_total = max(15, int(hours * 60))
            domain = focus or rotation
            items: list[dict] = []

            last = self.get_last_session_narrative(skill="study-session", topic=domain) if domain else self.get_last_session_narrative(skill="study-session")
            if last and last.get("next_session_strategy"):
                items.append({
                    "rank": 0,
                    "type": "continuity",
                    "topic": ", ".join(last.get("topics_json", [])[:3]) if isinstance(last.get("topics_json"), list) else "",
                    "recommended_skill": "study-session",
                    "estimated_minutes": 5,
                    "rationale": "Prior session strategy is unresolved and should shape the opening recall bridge.",
                    "action": last.get("next_session_strategy", ""),
                })

            for q in self.concept_review_queue_srs(n=6, domain=domain):
                items.append({
                    "type": "spaced_review",
                    "topic": q.get("topic", ""),
                    "concept": q.get("concept", ""),
                    "recommended_skill": "study-session",
                    "estimated_minutes": 5,
                    "rationale": f"SRS status={q.get('status')} days_overdue={q.get('days_overdue')} times_missed={q.get('times_missed')}.",
                    "action": "Ask a retrieval-first question before any explanation.",
                })

            for gap in self.fine_grained_gaps(top=6, domain=domain):
                topic_label = (
                    gap.get("display_name")
                    or gap.get("canonical_name")
                    or gap.get("topic")
                    or ""
                )
                items.append({
                    "type": "targeted_remediation",
                    "topic": topic_label,
                    "concept": gap.get("concept_text", ""),
                    "recommended_skill": "rag-workflow" if gap.get("error_type") in ("conceptual_confusion", "reasoning_gap") else "study-session",
                    "estimated_minutes": 10,
                    "rationale": f"Persistent concept gap: error_type={gap.get('error_type') or 'unknown'}, times_missed={gap.get('times_missed', 0)}.",
                    "action": gap.get("remediation") or "Use error-type matched remediation and immediately re-test.",
                })

            for pair in self.get_confusable_pairs(topic=domain or "")[:4]:
                items.append({
                    "type": "discrimination",
                    "topic": domain or "",
                    "concept": f"{pair.get('concept_a', '')} vs {pair.get('concept_b', '')}",
                    "recommended_skill": "study-session",
                    "estimated_minutes": 8,
                    "rationale": pair.get("disambiguation_axis") or "Known confusable pair; train the discriminating feature.",
                    "action": "Run two rapid discrimination vignettes with immediate correction.",
                })

            for t in self.get_transfer_candidates(n=4):
                items.append({
                    "type": "transfer_validation",
                    "topic": t.get("topic", ""),
                    "concept": t.get("concept", ""),
                    "recommended_skill": "intern-bootcamp",
                    "estimated_minutes": 8,
                    "rationale": "Concept is known but not yet validated in a different clinical context.",
                    "action": "Test in a scenario where surface cues from the original topic are absent.",
                })

            for pat in self.detect_cognitive_patterns()[:2]:
                items.append({
                    "type": "process_intervention",
                    "topic": ", ".join(pat.get("topics", [])[:3]),
                    "concept": pat.get("error_type", ""),
                    "recommended_skill": "study-session",
                    "estimated_minutes": 6,
                    "rationale": f"Recurring process-level error across {pat.get('topic_count')} topics.",
                    "action": pat.get("intervention_hint", "Address the reasoning process before adding content."),
                })

            priority = {
                "continuity": 0,
                "spaced_review": 1,
                "targeted_remediation": 2,
                "discrimination": 3,
                "transfer_validation": 4,
                "process_intervention": 5,
            }
            items.sort(key=lambda item: (priority.get(item["type"], 99), -int(item.get("estimated_minutes", 0))))

            selected = []
            used = 0
            for item in items:
                mins = int(item.get("estimated_minutes", 5))
                if selected and used + mins > minutes_total:
                    continue
                used += mins
                item = dict(item)
                item["rank"] = len(selected) + 1
                selected.append(item)
                if used >= minutes_total:
                    break

            if not selected:
                recs = self.generate_recommendations(n=3, rotation_filter=rotation, apply_decay_first=True)
                for rec in recs[:3]:
                    selected.append({
                        "rank": len(selected) + 1,
                        "type": "new_territory",
                        "topic": rec.get("display_name", rec.get("topic", "")),
                        "recommended_skill": "rag-workflow",
                        "estimated_minutes": max(10, minutes_total // max(1, len(recs[:3]))),
                        "rationale": rec.get("why", "High-priority curriculum gap."),
                        "action": "Use RAG neuro-scaffold, then ask one active recall question.",
                    })

            return {
                "hours": hours,
                "minutes_budget": minutes_total,
                "rotation": rotation or "",
                "focus": focus or "",
                "items": selected,
                "unselected_count": max(0, len(items) - len(selected)),
                "planner_inputs": {
                    "has_prior_strategy": bool(last and last.get("next_session_strategy")),
                    "calibration": self.compute_calibration_profile(),
                    "zpd": self.recommend_difficulty_target(),
                },
            }
        except Exception as exc:
            print(f"[knowledge_graph] study_plan error: {exc}", file=sys.stderr)
            return {"error": str(exc), "items": []}
