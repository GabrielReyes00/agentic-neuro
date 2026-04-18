#!/usr/bin/env python3
"""Signal ingestion and study-session logging mixin for KnowledgeGraph."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone

from kg_constants import DATA_DIR

# Signal-type → confidence delta
SIGNAL_DELTAS: dict[str, float] = {
    "query": 0.03,
    "lecture_received": 0.08,
    "card_created": 0.05,
    "correct_recall": 0.12,
    "partial_recall": 0.04,
    "incorrect_recall": -0.10,
    "weakness_identified": -0.15,
    "anki_review": 0.0,  # variable — caller passes via metadata
}

# Question-word prefixes stripped during topic extraction
_QUESTION_PREFIXES = [
    "what is the", "what is", "what are the", "what are",
    "explain the", "explain", "how does the", "how does",
    "how do", "why does the", "why does", "why do",
    "mechanism of", "mechanisms of", "pathophysiology of",
    "compare", "contrast", "differentiate between",
    "describe the", "describe", "tell me about",
]

# Depth-2 trigger words
_DEPTH2_KEYWORDS = {"mechanism", "why", "how does", "pathophysiology", "pathogenesis"}


class KnowledgeGraphSignalMixin:
    """Topic signal logging, natural-language extraction, and concept-gap updates."""

    # ------------------------------------------------------------------
    # Signal logging
    # ------------------------------------------------------------------

    def log_signal(
        self,
        topic_name: str,
        source: str,
        signal_type: str,
        depth_at_event: int = 1,
        metadata: dict | None = None,
        category: str = "",
    ) -> int:
        """Main signal logging entry point.

        Normalises the topic, upserts it, records a signal event, and
        updates topic-level aggregates (confidence, depth, encounter_count).

        Returns the signal event id, or -1 if logging failed.
        """
        try:
            canonical = self._normalize_topic(topic_name)
            display = topic_name.strip()
            topic_id = self._upsert_topic(canonical, display, category)
            if topic_id < 0:
                return -1

            # Confidence delta
            meta = metadata or {}
            if signal_type == "anki_review":
                delta = float(meta.get("confidence_delta", 0.0))
            else:
                delta = SIGNAL_DELTAS.get(signal_type, 0.0)

            now = datetime.now(timezone.utc).isoformat()

            with self.conn:
                # Insert event
                cur = self.conn.execute(
                    """INSERT INTO signal_events
                       (topic_id, timestamp, source, signal_type,
                        depth_at_event, confidence_delta, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (topic_id, now, source, signal_type,
                     depth_at_event, delta, json.dumps(meta)),
                )

                # Update topic aggregates
                row = self.conn.execute(
                    "SELECT confidence, depth FROM topics WHERE topic_id = ?",
                    (topic_id,),
                ).fetchone()
                if row:
                    new_conf = max(0.0, min(1.0, row["confidence"] + delta))
                    new_depth = max(row["depth"], depth_at_event)
                    self.conn.execute(
                        """UPDATE topics
                           SET confidence = ?, depth = ?,
                               encounter_count = encounter_count + 1,
                               last_seen = ?
                           WHERE topic_id = ?""",
                        (new_conf, new_depth, now, topic_id),
                    )
                    self._update_stability(topic_id)
                return cur.lastrowid or -1
        except Exception as exc:
            print(f"[knowledge_graph] log_signal error: {exc}", file=sys.stderr)
            return -1

    # ------------------------------------------------------------------
    # Topic extraction from natural-language queries
    # ------------------------------------------------------------------

    @staticmethod
    def extract_topics_from_query(query: str) -> list[str]:
        """Extract 1-3 topic keywords from a RAG query string.

        Strips question words, splits on delimiters ("and", "vs", ","),
        and returns the cleaned medical concepts.
        """
        text = query.strip()

        # Strip question-word prefixes (longest match first)
        lower = text.lower()
        for prefix in sorted(_QUESTION_PREFIXES, key=len, reverse=True):
            if lower.startswith(prefix):
                text = text[len(prefix):].strip()
                break

        # Split on delimiters
        parts = re.split(r"\b(?:and|vs\.?|versus)\b|,", text, flags=re.IGNORECASE)
        topics = [p.strip().strip("?").strip() for p in parts if p and p.strip()]

        # Cap at 3
        return topics[:3]

    # ------------------------------------------------------------------
    # Convenience: log a RAG query
    # ------------------------------------------------------------------

    def log_rag_query(
        self,
        query: str,
        confidence: str = "",
        hit_counts: dict | None = None,
        source_books: list | None = None,
    ) -> None:
        """Log a RAG retrieval event (lightweight metadata only).

        This captures WHAT was searched and retrieval quality. It does NOT
        capture what the user learned — that signal comes from the agent's
        post-interaction log_study_session() call after presenting and
        assessing user comprehension.
        """
        try:
            topics = self.extract_topics_from_query(query)
            lower_q = query.lower()

            depth = 1
            for kw in _DEPTH2_KEYWORDS:
                if kw in lower_q:
                    depth = 2
                    break

            meta: dict = {}
            if confidence:
                meta["confidence"] = confidence
            if hit_counts:
                meta["hit_counts"] = hit_counts
            if source_books:
                meta["source_books"] = source_books

            for topic in topics:
                if topic:
                    self.log_signal(
                        topic_name=topic,
                        source="rag",
                        signal_type="query",
                        depth_at_event=depth,
                        metadata=meta,
                    )
        except Exception as exc:
            print(f"[knowledge_graph] log_rag_query error: {exc}", file=sys.stderr)

    def _upsert_understood_concepts(
        self,
        topic_id: int,
        topic: str,
        understood: list[str],
        now: str,
        now_dt: datetime,
        trigger_ids: dict,
    ) -> None:
        """Upsert concepts the learner demonstrated as understood."""
        for concept in understood:
            concept_clean = concept.strip().lower()
            if not concept_clean:
                continue
            existing = self.conn.execute(
                """SELECT concept_id, status, times_confirmed, times_missed,
                          ease_factor, review_interval_days,
                          concept_confidence, teaching_notes,
                          root_cause, error_process, remediation, misconception
                   FROM concept_mastery WHERE topic_id = ? AND concept_text = ?""",
                (topic_id, concept_clean),
            ).fetchone()
            if existing:
                old_ef = existing["ease_factor"] if existing["ease_factor"] is not None else 2.5
                old_interval = existing["review_interval_days"] if existing["review_interval_days"] is not None else 1.0
                new_ef = min(2.5, old_ef + 0.1)
                new_interval = old_interval * new_ef
                next_due = (now_dt + timedelta(days=new_interval)).isoformat()
                was_unknown = existing["status"] in ("unknown", "due")
                old_cc = existing["concept_confidence"] if existing["concept_confidence"] is not None else 0.0
                new_cc = min(1.0, old_cc + (0.15 * new_ef / 2.5))
                self.conn.execute(
                    """UPDATE concept_mastery
                       SET status = 'known',
                           times_confirmed = times_confirmed + 1,
                           last_updated = ?,
                           ease_factor = ?,
                           review_interval_days = ?,
                           next_review_due = ?,
                           concept_confidence = ?
                       WHERE concept_id = ?""",
                    (now, new_ef, new_interval, next_due, new_cc, existing["concept_id"]),
                )
                if was_unknown:
                    self.mark_teaching_worked(concept_clean, topic)
                    self.log_concept_evolution(
                        concept_id=existing["concept_id"],
                        topic_id=topic_id,
                        new_status="known",
                        trigger_type="correct_recall",
                        previous_status=existing["status"],
                        previous_misconception=existing["misconception"] or "",
                        times_confirmed=(existing["times_confirmed"] or 0) + 1,
                        times_missed=existing["times_missed"] or 0,
                        **trigger_ids,
                        evolution_note="Concept transitioned unknown -> known after correct recall",
                    )
                if was_unknown and not (existing["teaching_notes"] or "").strip():
                    self._auto_populate_teaching_notes(
                        concept_id=existing["concept_id"],
                        root_cause=existing["root_cause"] or "",
                        error_process=existing["error_process"] or "",
                        remediation=existing["remediation"] or "",
                        session_date=now[:10],
                    )
            else:
                new_interval = 2.5
                next_due = (now_dt + timedelta(days=new_interval)).isoformat()
                cur = self.conn.execute(
                    """INSERT INTO concept_mastery
                       (topic_id, concept_text, status, times_confirmed, times_missed,
                        ease_factor, review_interval_days, next_review_due,
                        concept_confidence, first_seen, last_updated)
                       VALUES (?, ?, 'known', 1, 0, 2.5, 2.5, ?, 0.4, ?, ?)""",
                    (topic_id, concept_clean, next_due, now, now),
                )
                concept_id = cur.lastrowid
                if concept_id:
                    self.log_concept_evolution(
                        concept_id=concept_id,
                        topic_id=topic_id,
                        new_status="known",
                        trigger_type="correct_recall",
                        previous_status="",
                        times_confirmed=1,
                        times_missed=0,
                        **trigger_ids,
                        evolution_note="First logged correct recall",
                    )

    def _upsert_session_gap_concepts(
        self,
        topic_id: int,
        gaps: list[str],
        gap_details: list[dict],
        now: str,
        trigger_ids: dict,
    ) -> None:
        """Upsert simple and richly-typed gaps observed in a study session."""
        for concept in gaps:
            self._upsert_concept_gap(topic_id, concept, now, **trigger_ids)

        for gap in gap_details:
            concept = gap.get("concept", "")
            if not concept:
                continue
            self._upsert_concept_gap(
                topic_id,
                concept,
                now,
                error_type=gap.get("error_type", ""),
                misconception=gap.get("misconception", ""),
                remediation=gap.get("remediation", ""),
                root_cause=gap.get("root_cause", ""),
                error_process=gap.get("error_process", ""),
                **trigger_ids,
            )

    @staticmethod
    def _study_session_delta(understood: list[str], gap_concepts: list[str]) -> float:
        """Compute topic confidence delta from demonstrated and missed concepts."""
        total = len(understood) + len(gap_concepts)
        if total == 0:
            return 0.02
        if len(gap_concepts) == 0:
            return 0.06 + min(0.04, len(understood) * 0.01)
        if len(understood) == 0:
            return -0.03 - min(0.04, len(gap_concepts) * 0.01)
        ratio = len(understood) / total
        return (ratio * 0.08) - ((1 - ratio) * 0.04)

    @staticmethod
    def _study_session_metadata(
        understood: list[str],
        gaps: list[str],
        gap_details: list[dict],
        trigger_ids: dict,
    ) -> dict:
        """Build signal metadata for a study-session event."""
        meta = {}
        if understood:
            meta["understood"] = understood
        if gaps:
            meta["gaps"] = gaps
        if gap_details:
            meta["gap_details"] = gap_details
        for key, value in trigger_ids.items():
            if value is not None:
                meta[key] = value
        return meta

    def log_study_session(
        self,
        topics: list[str],
        understood: list[str] | None = None,
        gaps: list[str] | None = None,
        gap_details: list[dict] | None = None,
        depth: int = 1,
        source: str = "rag",
        trigger_exchange_id: int | None = None,
        trigger_signal_id: int | None = None,
        trigger_memory_event_id: int | None = None,
    ) -> None:
        """Log a post-interaction learning signal with per-concept mastery.

        Called by the AGENT after presenting a synthesis and observing the
        user's response. Captures WHICH specific concepts were demonstrated
        vs. which were missed, with optional error intelligence on gaps.

        Parameters
        ----------
        topics : list[str]
            Topic names covered in the session.
        understood : list[str] | None
            Specific concepts the user demonstrated understanding of.
            e.g., ["calcium channel mechanism", "Fisher grade 3 highest risk"]
        gaps : list[str] | None
            Specific concepts the user missed (simple list — use this OR gap_details).
            e.g., ["nimodipine dosing 60mg q4h", "vasospasm peak days 7-10"]
        gap_details : list[dict] | None
            Rich error-typed gap entries (use this for deeper intelligence). Each dict:
            {"concept": str, "error_type": str, "misconception": str, "remediation": str}
            Error types: numerical_recall, conceptual_confusion, cross_contamination,
                         application_failure, reasoning_gap, omission
        depth : int
            Depth of material presented (1=surface, 2=mechanistic, 3=decision-making).
        source : str
            Capability that drove the session ("rag", "bootcamp", "intraop").
        """
        required_gap_fields = {
            "concept", "error_type", "error_process",
            "misconception", "root_cause", "remediation",
        }
        for idx, gap in enumerate(gap_details or []):
            missing = required_gap_fields - set(gap)
            if missing:
                raise ValueError(
                    "gap_details entries must include "
                    f"{sorted(required_gap_fields)}; entry {idx} missing {sorted(missing)}"
                )

        try:
            understood = understood or []
            gaps = gaps or []
            gap_details = gap_details or []

            # Merge gap_details into gaps list for counting
            # (gap_details entries carry richer metadata but still count as gaps)
            _gap_concepts_from_details = [gd.get("concept", "") for gd in gap_details if gd.get("concept")]
            all_gap_concepts = list(gaps) + _gap_concepts_from_details

            now = datetime.now(timezone.utc).isoformat()
            trigger_ids = {
                "trigger_exchange_id": trigger_exchange_id,
                "trigger_signal_id": trigger_signal_id,
                "trigger_memory_event_id": trigger_memory_event_id,
            }
            delta = self._study_session_delta(understood, all_gap_concepts)
            meta = self._study_session_metadata(
                understood,
                gaps,
                gap_details,
                trigger_ids,
            )

            for topic in topics:
                if not topic:
                    continue
                self.log_signal(
                    topic_name=topic,
                    source=source,
                    signal_type="study_session",
                    depth_at_event=depth,
                    metadata=meta,
                )
                # Apply per-concept delta to topic confidence
                canonical = self._normalize_topic(topic)
                t = self._find_topic(canonical)
                if not t:
                    continue
                tid = t["topic_id"]
                new_conf = max(0.0, min(1.0, t["confidence"] + delta))
                with self.conn:
                    self.conn.execute(
                        "UPDATE topics SET confidence = ? WHERE topic_id = ?",
                        (new_conf, tid),
                    )
                self._update_stability(tid)

                # ── Upsert concept mastery dictionary ──
                now_dt = self._parse_ts(now) or datetime.now(timezone.utc)
                self._upsert_understood_concepts(
                    tid,
                    topic,
                    understood,
                    now,
                    now_dt,
                    trigger_ids,
                )
                self._upsert_session_gap_concepts(
                    tid,
                    gaps,
                    gap_details,
                    now,
                    trigger_ids,
                )

                self.conn.commit()

        except Exception as exc:
            print(f"[knowledge_graph] log_study_session error: {exc}", file=sys.stderr)

    def _upsert_concept_gap(
        self,
        topic_id: int,
        concept: str,
        now: str,
        error_type: str = "",
        misconception: str = "",
        remediation: str = "",
        root_cause: str = "",
        error_process: str = "",
        trigger_exchange_id: int | None = None,
        trigger_signal_id: int | None = None,
        trigger_memory_event_id: int | None = None,
    ) -> None:
        """Insert or update a concept gap entry with optional error intelligence.

        SM-2 on miss: reset review_interval_days=1.0, ease_factor=max(1.3, ef-0.2),
        next_review_due = now + 1 day.
        """
        concept_clean = concept.strip().lower()
        if not concept_clean:
            return

        # SM-2: compute new interval/ease on miss
        now_dt = self._parse_ts(now) or datetime.now(timezone.utc)
        next_due = (now_dt + timedelta(days=1)).isoformat()

        existing = self.conn.execute(
            """SELECT concept_id, status, ease_factor, review_interval_days,
                      concept_confidence, times_confirmed, times_missed
               FROM concept_mastery WHERE topic_id = ? AND concept_text = ?""",
            (topic_id, concept_clean),
        ).fetchone()
        if existing:
            was_known = existing["status"] == "known"
            old_ef = existing["ease_factor"] if existing["ease_factor"] is not None else 2.5
            new_ef = max(1.3, old_ef - 0.2)
            # Iteration 1: degrade concept_confidence on miss (halve + subtract floor)
            old_cc = existing["concept_confidence"] if existing["concept_confidence"] is not None else 0.0
            new_cc = max(0.0, old_cc * 0.5 - 0.05)
            updates = [
                "status = 'unknown'",
                "times_missed = times_missed + 1",
                "last_updated = ?",
                "review_interval_days = 1.0",
                "ease_factor = ?",
                "next_review_due = ?",
                "concept_confidence = ?",
            ]
            params: list = [now, new_ef, next_due, new_cc]
            if error_type:
                updates.append("error_type = ?")
                params.append(error_type)
            if misconception:
                updates.append("misconception = ?")
                params.append(misconception)
            if remediation:
                updates.append("remediation = ?")
                params.append(remediation)
            if root_cause:
                updates.append("root_cause = ?")
                params.append(root_cause)
            if error_process:
                updates.append("error_process = ?")
                params.append(error_process)
            params.append(existing["concept_id"])
            self.conn.execute(
                f"UPDATE concept_mastery SET {', '.join(updates)} WHERE concept_id = ?",
                params,
            )
            # Log concept evolution: regression known -> unknown
            if was_known:
                self.log_concept_evolution(
                    concept_id=existing["concept_id"],
                    topic_id=topic_id,
                    new_status="unknown",
                    trigger_type="incorrect_recall",
                    previous_status="known",
                    error_type=error_type,
                    misconception=misconception,
                    remediation=remediation,
                    times_confirmed=existing["times_confirmed"] or 0,
                    times_missed=(existing["times_missed"] or 0) + 1,
                    trigger_exchange_id=trigger_exchange_id,
                    trigger_signal_id=trigger_signal_id,
                    trigger_memory_event_id=trigger_memory_event_id,
                    evolution_note=f"Regression: known -> unknown. {misconception}" if misconception else "Regression: known -> unknown",
                )
        else:
            cur = self.conn.execute(
                """INSERT INTO concept_mastery
                   (topic_id, concept_text, status, error_type, misconception, remediation,
                    root_cause, error_process, times_confirmed, times_missed,
                    review_interval_days, ease_factor, next_review_due,
                    first_seen, last_updated)
                   VALUES (?, ?, 'unknown', ?, ?, ?, ?, ?, 0, 1, 1.0, 2.5, ?, ?, ?)""",
                (topic_id, concept_clean, error_type, misconception, remediation,
                 root_cause, error_process, next_due, now, now),
            )
            concept_id = cur.lastrowid
            if concept_id:
                self.log_concept_evolution(
                    concept_id=concept_id,
                    topic_id=topic_id,
                    new_status="unknown",
                    trigger_type="incorrect_recall",
                    previous_status="",
                    error_type=error_type,
                    misconception=misconception,
                    remediation=remediation,
                    times_confirmed=0,
                    times_missed=1,
                    trigger_exchange_id=trigger_exchange_id,
                    trigger_signal_id=trigger_signal_id,
                    trigger_memory_event_id=trigger_memory_event_id,
                    evolution_note=f"First logged gap. {misconception}" if misconception else "First logged gap",
                )
        # Auto-populate confusion matrix for cross_contamination errors
        if error_type == "cross_contamination" and misconception:
            self._record_confusion_pair(concept_clean, misconception)
        # Also persist to concept_relationships table for DB-queryable confusable pairs
        if error_type == "cross_contamination" and misconception:
            self._record_concept_relationship(
                concept_a=concept_clean,
                concept_b=misconception.strip().lower(),
                relationship="confusable_with",
                source="auto_gap",
                now=now,
            )

    def _record_confusion_pair(self, concept_a: str, misconception: str) -> None:
        """Append a confusion pair to data/confusion_matrix.json when not already tracked."""
        matrix_path = DATA_DIR / "confusion_matrix.json"
        try:
            pairs = json.loads(matrix_path.read_text(encoding="utf-8")) if matrix_path.exists() else []
            for p in pairs:
                ca, cb = p.get("concept_a", ""), p.get("concept_b", "")
                if (ca == concept_a and cb == misconception) or (ca == misconception and cb == concept_a):
                    return  # already tracked (either direction)
            pairs.append({
                "concept_a": concept_a,
                "concept_b": misconception,
                "disambiguation_axis": "",
                "source": "auto_logged",
                "first_added": datetime.utcnow().isoformat(),
            })
            matrix_path.write_text(json.dumps(pairs, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[knowledge_graph] _record_confusion_pair error: {exc}", file=sys.stderr)

    def _record_concept_relationship(
        self,
        concept_a: str,
        concept_b: str,
        relationship: str,
        topic_a: str = "",
        topic_b: str = "",
        strength: float = 0.5,
        notes: str = "",
        source: str = "auto",
        now: str | None = None,
    ) -> None:
        """Insert a concept relationship if it does not already exist (either direction)."""
        if not concept_a or not concept_b:
            return
        ts = now or datetime.now(timezone.utc).isoformat()
        try:
            existing = self.conn.execute(
                """SELECT rel_id FROM concept_relationships
                   WHERE ((concept_a = ? AND concept_b = ?) OR (concept_a = ? AND concept_b = ?))
                     AND relationship = ?""",
                (concept_a, concept_b, concept_b, concept_a, relationship),
            ).fetchone()
            if existing:
                return
            with self.conn:
                self.conn.execute(
                    """INSERT INTO concept_relationships
                       (concept_a, topic_a, concept_b, topic_b, relationship,
                        strength, notes, source, created_ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (concept_a, topic_a, concept_b, topic_b, relationship,
                     strength, notes, source, ts),
                )
        except Exception as exc:
            print(f"[knowledge_graph] _record_concept_relationship error: {exc}", file=sys.stderr)

    def log_learning_pattern(
        self,
        pattern_type: str,
        description: str,
        evidence: str = "",
    ) -> None:
        """Upsert a meta-cognitive learning pattern observation."""
        try:
            now = datetime.utcnow().isoformat()
            existing = self.conn.execute(
                "SELECT pattern_id, evidence, confidence FROM learning_patterns WHERE pattern_type = ?",
                (pattern_type,),
            ).fetchone()
            if existing:
                # Append evidence and increase confidence
                prev_evidence = json.loads(existing["evidence"]) if existing["evidence"] else []
                if evidence and evidence not in prev_evidence:
                    prev_evidence.append(evidence)
                new_conf = min(1.0, (existing["confidence"] or 0.5) + 0.05)
                self.conn.execute(
                    """UPDATE learning_patterns
                       SET description = ?, evidence = ?, confidence = ?, last_updated = ?
                       WHERE pattern_id = ?""",
                    (description, json.dumps(prev_evidence), new_conf, now, existing["pattern_id"]),
                )
            else:
                ev_list = [evidence] if evidence else []
                self.conn.execute(
                    """INSERT INTO learning_patterns
                       (pattern_type, description, evidence, confidence, first_detected, last_updated)
                       VALUES (?, ?, ?, 0.5, ?, ?)""",
                    (pattern_type, description, json.dumps(ev_list), now, now),
                )
            self.conn.commit()
        except Exception as exc:
            print(f"[knowledge_graph] log_learning_pattern error: {exc}", file=sys.stderr)
