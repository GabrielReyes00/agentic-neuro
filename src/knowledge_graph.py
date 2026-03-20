#!/usr/bin/env python3
"""Knowledge Graph — tracks learner topic mastery, confidence decay, and study gaps."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "knowledge_graph.db"

# ---------------------------------------------------------------------------
# Abbreviation map — small, self-contained (no circular imports)
# ---------------------------------------------------------------------------
ABBREVIATION_MAP: dict[str, str] = {
    "sah": "subarachnoid hemorrhage",
    "tbi": "traumatic brain injury",
    "evd": "external ventricular drain",
    "avm": "arteriovenous malformation",
    "dbs": "deep brain stimulation",
    "icp": "intracranial pressure",
    "csf": "cerebrospinal fluid",
    "vp": "ventriculoperitoneal",
    "srs": "stereotactic radiosurgery",
    "mca": "middle cerebral artery",
    "aca": "anterior cerebral artery",
    "pca": "posterior cerebral artery",
    "pica": "posterior inferior cerebellar artery",
    "gbm": "glioblastoma",
    "idh": "isocitrate dehydrogenase",
    "acdf": "anterior cervical discectomy and fusion",
    "sci": "spinal cord injury",
}

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

# Domain → category mapping for curriculum loading
_DOMAIN_CATEGORY_MAP: dict[str, str] = {
    "Vascular": "vascular",
    "Spine": "spine",
    "Tumor": "tumor",
    "Functional & Stereotactic": "functional",
    "Trauma": "trauma",
    "Pediatric Neurosurgery": "pediatric",
    "Critical Care & General Neurosurgery": "critical_care",
}


# ═══════════════════════════════════════════════════════════════════════════
# KnowledgeGraph
# ═══════════════════════════════════════════════════════════════════════════

class KnowledgeGraph:
    """SQLite-backed learner knowledge graph for topic mastery tracking."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # WAL mode for concurrent reads
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self._init_db()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create all tables and indexes if they don't exist."""
        try:
            with self.conn:
                self.conn.executescript(_SCHEMA_SQL)
            # Schema migrations — safe to re-run (idempotent)
            try:
                self.conn.execute(
                    "ALTER TABLE concept_mastery ADD COLUMN transfer_validated INTEGER DEFAULT 0"
                )
                self.conn.commit()
            except Exception:
                pass  # Column already exists
        except Exception as exc:
            print(f"[knowledge_graph] schema init error: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_topic(raw: str) -> str:
        """Canonical name normalisation.

        Steps: lowercase → strip → expand abbreviations → strip leading
        articles → basic singularisation.
        """
        text = raw.strip().lower()

        # Expand abbreviations (whole-word match)
        tokens = text.split()
        tokens = [ABBREVIATION_MAP.get(t, t) for t in tokens]
        text = " ".join(tokens)

        # Strip leading articles
        for article in ("the ", "a ", "an "):
            if text.startswith(article):
                text = text[len(article):]
                break

        # Basic singularisation: strip trailing 's' if word > 4 chars
        # Protect medical terms ending in -is, -us, -sis, -tis, -ous, -ias
        _no_strip = ("is", "us", "sis", "tis", "ous", "ias", "ess")
        tokens = text.split()
        tokens = [
            t[:-1] if len(t) > 4 and t.endswith("s") and not t.endswith("ss") and not t.endswith(_no_strip)
            else t
            for t in tokens
        ]
        text = " ".join(tokens).strip()

        return text

    # ------------------------------------------------------------------
    # Topic CRUD
    # ------------------------------------------------------------------

    def _find_topic(self, canonical_name: str) -> dict | None:
        """Look up by canonical_name, then aliases, then substring LIKE match."""
        try:
            # Exact canonical match
            row = self.conn.execute(
                "SELECT * FROM topics WHERE canonical_name = ?", (canonical_name,)
            ).fetchone()
            if row:
                return dict(row)

            # Alias match
            rows = self.conn.execute("SELECT * FROM topics").fetchall()
            for r in rows:
                aliases = json.loads(r["aliases"]) if r["aliases"] else []
                if canonical_name in aliases:
                    return dict(r)

            # Substring LIKE match (handles "vasospasm" finding "cerebral vasospasm after SAH")
            row = self.conn.execute(
                "SELECT * FROM topics WHERE canonical_name LIKE ? ORDER BY encounter_count DESC LIMIT 1",
                (f"%{canonical_name}%",),
            ).fetchone()
            if row:
                return dict(row)

            # Reverse: query contains the stored canonical_name
            for r in rows:
                if r["canonical_name"] in canonical_name:
                    return dict(r)

            return None
        except Exception as exc:
            print(f"[knowledge_graph] _find_topic error: {exc}", file=sys.stderr)
            return None

    def _upsert_topic(self, canonical_name: str, display_name: str, category: str = "") -> int:
        """Find or create a topic. Returns topic_id."""
        try:
            existing = self._find_topic(canonical_name)
            if existing:
                # Add display_name as alias if different from canonical
                if display_name.lower() != canonical_name:
                    aliases = json.loads(existing["aliases"]) if existing["aliases"] else []
                    norm_display = display_name.strip().lower()
                    if norm_display not in aliases and norm_display != canonical_name:
                        aliases.append(norm_display)
                        with self.conn:
                            self.conn.execute(
                                "UPDATE topics SET aliases = ? WHERE topic_id = ?",
                                (json.dumps(aliases), existing["topic_id"]),
                            )
                return existing["topic_id"]

            # Insert new topic
            now = datetime.now(timezone.utc).isoformat()
            aliases: list[str] = []
            norm_display = display_name.strip().lower()
            if norm_display != canonical_name:
                aliases.append(norm_display)

            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO topics
                       (canonical_name, display_name, aliases, category,
                        confidence, depth, encounter_count, first_seen, last_seen)
                       VALUES (?, ?, ?, ?, 0.0, 0, 0, ?, ?)""",
                    (canonical_name, display_name, json.dumps(aliases), category, now, now),
                )
                return cur.lastrowid  # type: ignore[return-value]
        except Exception as exc:
            print(f"[knowledge_graph] _upsert_topic error: {exc}", file=sys.stderr)
            return -1

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
    ) -> None:
        """Main signal logging entry point.

        Normalises the topic, upserts it, records a signal event, and
        updates topic-level aggregates (confidence, depth, encounter_count).
        """
        try:
            canonical = self._normalize_topic(topic_name)
            display = topic_name.strip()
            topic_id = self._upsert_topic(canonical, display, category)
            if topic_id < 0:
                return

            # Confidence delta
            meta = metadata or {}
            if signal_type == "anki_review":
                delta = float(meta.get("confidence_delta", 0.0))
            else:
                delta = SIGNAL_DELTAS.get(signal_type, 0.0)

            now = datetime.now(timezone.utc).isoformat()

            with self.conn:
                # Insert event
                self.conn.execute(
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
        except Exception as exc:
            print(f"[knowledge_graph] log_signal error: {exc}", file=sys.stderr)

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

    def log_study_session(
        self,
        topics: list[str],
        understood: list[str] | None = None,
        gaps: list[str] | None = None,
        gap_details: list[dict] | None = None,
        depth: int = 1,
        source: str = "rag",
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
        try:
            understood = understood or []
            gaps = gaps or []
            gap_details = gap_details or []

            # Merge gap_details into gaps list for counting
            # (gap_details entries carry richer metadata but still count as gaps)
            _gap_concepts_from_details = [gd.get("concept", "") for gd in gap_details if gd.get("concept")]
            all_gap_concepts = list(gaps) + _gap_concepts_from_details

            # Confidence delta based on ratio of understood vs gaps
            total = len(understood) + len(all_gap_concepts)
            if total == 0:
                # No interaction observed — minimal credit for exposure
                delta = 0.02
            elif len(gaps) == 0:
                # Everything understood — strong signal
                delta = 0.06 + min(0.04, len(understood) * 0.01)
            elif len(understood) == 0:
                # Everything missed — negative signal
                delta = -0.03 - min(0.04, len(gaps) * 0.01)
            else:
                # Mixed — weighted by ratio
                ratio = len(understood) / total
                delta = (ratio * 0.08) - ((1 - ratio) * 0.04)

            meta = {}
            if understood:
                meta["understood"] = understood
            if gaps:
                meta["gaps"] = gaps

            now = datetime.utcnow().isoformat()

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

                # ── Upsert concept mastery dictionary ──
                for concept in understood:
                    concept_clean = concept.strip().lower()
                    if not concept_clean:
                        continue
                    existing = self.conn.execute(
                        "SELECT concept_id, status, times_confirmed, times_missed FROM concept_mastery WHERE topic_id = ? AND concept_text = ?",
                        (tid, concept_clean),
                    ).fetchone()
                    if existing:
                        self.conn.execute(
                            "UPDATE concept_mastery SET status = 'known', times_confirmed = times_confirmed + 1, last_updated = ? WHERE concept_id = ?",
                            (now, existing["concept_id"]),
                        )
                    else:
                        self.conn.execute(
                            "INSERT INTO concept_mastery (topic_id, concept_text, status, times_confirmed, times_missed, first_seen, last_updated) VALUES (?, ?, 'known', 1, 0, ?, ?)",
                            (tid, concept_clean, now, now),
                        )

                # Simple gaps (no error details)
                for concept in gaps:
                    self._upsert_concept_gap(tid, concept, now)

                # Rich gap details (with error type, misconception, remediation)
                for gd in gap_details:
                    concept = gd.get("concept", "")
                    if not concept:
                        continue
                    self._upsert_concept_gap(
                        tid, concept, now,
                        error_type=gd.get("error_type", ""),
                        misconception=gd.get("misconception", ""),
                        remediation=gd.get("remediation", ""),
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
    ) -> None:
        """Insert or update a concept gap entry with optional error intelligence."""
        concept_clean = concept.strip().lower()
        if not concept_clean:
            return
        existing = self.conn.execute(
            "SELECT concept_id, status FROM concept_mastery WHERE topic_id = ? AND concept_text = ?",
            (topic_id, concept_clean),
        ).fetchone()
        if existing:
            # Update: flip status, increment miss count, and update error context
            updates = ["status = 'unknown'", "times_missed = times_missed + 1", "last_updated = ?"]
            params = [now]
            if error_type:
                updates.append("error_type = ?")
                params.append(error_type)
            if misconception:
                updates.append("misconception = ?")
                params.append(misconception)
            if remediation:
                updates.append("remediation = ?")
                params.append(remediation)
            params.append(existing["concept_id"])
            self.conn.execute(
                f"UPDATE concept_mastery SET {', '.join(updates)} WHERE concept_id = ?",
                params,
            )
        else:
            self.conn.execute(
                """INSERT INTO concept_mastery
                   (topic_id, concept_text, status, error_type, misconception, remediation,
                    times_confirmed, times_missed, first_seen, last_updated)
                   VALUES (?, ?, 'unknown', ?, ?, ?, 0, 1, ?, ?)""",
                (topic_id, concept_clean, error_type, misconception, remediation, now, now),
            )
        # Auto-populate confusion matrix for cross_contamination errors
        if error_type == "cross_contamination" and misconception:
            self._record_confusion_pair(concept_clean, misconception)

    def _record_confusion_pair(self, concept_a: str, misconception: str) -> None:
        """Append a confusion pair to data/confusion_matrix.json when not already tracked."""
        matrix_path = BASE_DIR / "data" / "confusion_matrix.json"
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

    # ------------------------------------------------------------------
    # Status & introspection
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """Return summary statistics about the knowledge graph."""
        try:
            total_topics = self.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
            total_events = self.conn.execute("SELECT COUNT(*) FROM signal_events").fetchone()[0]

            # By category
            cat_rows = self.conn.execute(
                "SELECT category, COUNT(*) AS cnt FROM topics GROUP BY category ORDER BY cnt DESC"
            ).fetchall()
            by_category = {r["category"] or "(uncategorised)": r["cnt"] for r in cat_rows}

            # Recent topics
            recent_rows = self.conn.execute(
                "SELECT canonical_name, confidence, depth, last_seen "
                "FROM topics ORDER BY last_seen DESC LIMIT 10"
            ).fetchall()
            recent = [dict(r) for r in recent_rows]

            # Average confidence
            avg_row = self.conn.execute(
                "SELECT AVG(confidence) AS avg_conf FROM topics"
            ).fetchone()
            avg_confidence = round(avg_row["avg_conf"], 3) if avg_row["avg_conf"] is not None else 0.0

            # Depth distribution
            depth_rows = self.conn.execute(
                "SELECT depth, COUNT(*) AS cnt FROM topics GROUP BY depth ORDER BY depth"
            ).fetchall()
            by_depth = {f"depth_{r['depth']}": r["cnt"] for r in depth_rows}

            return {
                "total_topics": total_topics,
                "total_events": total_events,
                "by_category": by_category,
                "recent_topics": recent,
                "avg_confidence": avg_confidence,
                "by_depth": by_depth,
            }
        except Exception as exc:
            print(f"[knowledge_graph] status error: {exc}", file=sys.stderr)
            return {}

    def topic_detail(self, topic_name: str) -> dict:
        """Return full detail for a single topic including event history."""
        try:
            canonical = self._normalize_topic(topic_name)
            topic = self._find_topic(canonical)
            if not topic:
                return {"error": f"Topic '{topic_name}' not found."}

            events = self.conn.execute(
                """SELECT event_id, timestamp, source, signal_type,
                          depth_at_event, confidence_delta, metadata
                   FROM signal_events
                   WHERE topic_id = ?
                   ORDER BY timestamp DESC""",
                (topic["topic_id"],),
            ).fetchall()
            event_list = [dict(e) for e in events]

            # Summary
            total_encounters = topic["encounter_count"]
            conf_trajectory = [e["confidence_delta"] for e in event_list]

            # Per-concept mastery dictionary
            concepts = self.conn.execute(
                """SELECT concept_text, status, times_confirmed, times_missed,
                          error_type, misconception, remediation,
                          first_seen, last_updated
                   FROM concept_mastery WHERE topic_id = ?
                   ORDER BY status DESC, last_updated DESC""",
                (topic["topic_id"],),
            ).fetchall()
            concept_list = [dict(c) for c in concepts]

            return {
                "topic": dict(topic),
                "events": event_list,
                "concept_mastery": {
                    "known": [c for c in concept_list if c["status"] == "known"],
                    "unknown": [c for c in concept_list if c["status"] == "unknown"],
                },
                "summary": {
                    "total_encounters": total_encounters,
                    "confidence_trajectory": conf_trajectory,
                    "current_confidence": topic["confidence"],
                    "current_depth": topic["depth"],
                    "first_seen": topic["first_seen"],
                    "last_seen": topic["last_seen"],
                },
            }
        except Exception as exc:
            print(f"[knowledge_graph] topic_detail error: {exc}", file=sys.stderr)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Backfill from telemetry logs
    # ------------------------------------------------------------------

    def backfill_from_telemetry(self, telemetry_path: str) -> dict:
        """Read search_telemetry.jsonl and retroactively create topic nodes
        and signal events. Skips entries with empty queries or all-zero hits.

        Returns dict with counts of topics_created and events_logged.
        """
        path = Path(telemetry_path)
        if not path.exists():
            print(f"[knowledge_graph] telemetry file not found: {path}", file=sys.stderr)
            return {"topics_created": 0, "events_logged": 0}

        topics_before = self.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
        events_before = self.conn.execute("SELECT COUNT(*) FROM signal_events").fetchone()[0]

        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    query = entry.get("query", "").strip()
                    if not query:
                        continue

                    hit_counts = entry.get("hit_counts", {})
                    if all(v == 0 for v in hit_counts.values()):
                        continue

                    confidence = entry.get("confidence", "")
                    self.log_rag_query(
                        query=query,
                        confidence=confidence,
                        hit_counts=hit_counts,
                    )

            topics_after = self.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
            events_after = self.conn.execute("SELECT COUNT(*) FROM signal_events").fetchone()[0]

            result = {
                "topics_created": topics_after - topics_before,
                "events_logged": events_after - events_before,
            }
            return result
        except Exception as exc:
            print(f"[knowledge_graph] backfill error: {exc}", file=sys.stderr)
            return {"topics_created": 0, "events_logged": 0}

    # ------------------------------------------------------------------
    # Phase 2: Decay, Curriculum, Recommendations
    # ------------------------------------------------------------------

    def _parse_ts(self, ts_str: str | None) -> datetime | None:
        """Parse an ISO timestamp string, tolerating missing timezone.
        Always returns a timezone-aware datetime (UTC) or None."""
        if not ts_str:
            return None
        try:
            ts_str = ts_str.strip()
            # Strip trailing 'Z' and treat as UTC
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1]
            dt = datetime.fromisoformat(ts_str)
            # Always ensure timezone-aware (default to UTC)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def apply_decay(self, topic_id: int = None) -> None:
        """Apply Ebbinghaus forgetting-curve decay to topic confidence.

        If topic_id is given, apply to that topic only; otherwise batch-decay
        all topics.
        """
        try:
            now = datetime.now(timezone.utc)
            if topic_id is not None:
                rows = self.conn.execute(
                    "SELECT topic_id, confidence, depth, last_decay_ts, last_seen FROM topics WHERE topic_id = ?",
                    (topic_id,),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT topic_id, confidence, depth, last_decay_ts, last_seen FROM topics"
                ).fetchall()

            for row in rows:
                tid = row["topic_id"]
                old_confidence = row["confidence"]
                depth = row["depth"]

                # Determine reference timestamp
                ref_ts = self._parse_ts(row["last_decay_ts"]) or self._parse_ts(row["last_seen"])
                if ref_ts is None:
                    continue

                hours_since = (now - ref_ts).total_seconds() / 3600
                if hours_since <= 1:
                    continue  # skip if decayed recently

                half_life_hours = 48 * (2 ** max(0, depth - 1))
                decay_factor = 0.5 ** (hours_since / half_life_hours)
                new_confidence = max(0.0, min(1.0, old_confidence * decay_factor))

                with self.conn:
                    self.conn.execute(
                        "UPDATE topics SET confidence = ?, last_decay_ts = ? WHERE topic_id = ?",
                        (new_confidence, now.isoformat(), tid),
                    )
        except Exception as exc:
            print(f"[knowledge_graph] apply_decay error: {exc}", file=sys.stderr)

    def load_curriculum(self, json_path: str) -> dict:
        """Load curriculum from a JSON skeleton file.

        For each topic in each subdomain/domain: INSERT OR IGNORE into
        curriculum_topics, upsert into topics, and link via curriculum_id.

        Returns {"loaded": N, "skipped": M}.
        """
        try:
            path = Path(json_path)
            if not path.exists():
                print(f"[knowledge_graph] curriculum file not found: {path}", file=sys.stderr)
                return {"loaded": 0, "skipped": 0}

            with open(path, "r") as f:
                data = json.load(f)

            now = datetime.now(timezone.utc).isoformat()
            loaded = 0
            skipped = 0

            domains = data if isinstance(data, list) else data.get("domains", data.get("curriculum", []))

            for domain_obj in domains:
                domain_name = domain_obj.get("domain", domain_obj.get("name", ""))
                subdomains = domain_obj.get("subdomains", domain_obj.get("topics", []))

                for subdomain_obj in subdomains:
                    # Handle both nested subdomain and flat topic lists
                    if isinstance(subdomain_obj, dict) and "topics" in subdomain_obj:
                        subdomain_name = subdomain_obj.get("subdomain", subdomain_obj.get("name", ""))
                        topics = subdomain_obj["topics"]
                    elif isinstance(subdomain_obj, dict):
                        # The subdomain IS a topic
                        subdomain_name = ""
                        topics = [subdomain_obj]
                    else:
                        continue

                    for topic_obj in topics:
                        topic_name = topic_obj.get("topic_name", topic_obj.get("name", ""))
                        if not topic_name:
                            continue

                        display_name = topic_obj.get("display_name", topic_name)
                        acgme = topic_obj.get("acgme_milestone", "")
                        priority = topic_obj.get("priority", 2)
                        pgy_target = topic_obj.get("pgy_target", 1)

                        with self.conn:
                            cur = self.conn.execute(
                                """INSERT OR IGNORE INTO curriculum_topics
                                   (domain, subdomain, topic_name, display_name,
                                    acgme_milestone, priority, pgy_target, source, added_ts)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (domain_name, subdomain_name, topic_name, display_name,
                                 acgme, priority, pgy_target, "ABNS", now),
                            )

                            if cur.rowcount > 0:
                                loaded += 1

                                # Get the curriculum_id
                                cid_row = self.conn.execute(
                                    "SELECT curriculum_id FROM curriculum_topics WHERE topic_name = ?",
                                    (topic_name,),
                                ).fetchone()
                                curriculum_id = cid_row["curriculum_id"] if cid_row else None

                                # Upsert into topics table
                                canonical = self._normalize_topic(topic_name)
                                category = _DOMAIN_CATEGORY_MAP.get(domain_name, domain_name.lower().replace(" ", "_"))
                                topic_id = self._upsert_topic(canonical, display_name, category)

                                # Link curriculum_id
                                if topic_id > 0 and curriculum_id is not None:
                                    self.conn.execute(
                                        "UPDATE topics SET curriculum_id = ? WHERE topic_id = ?",
                                        (curriculum_id, topic_id),
                                    )
                            else:
                                skipped += 1

            return {"loaded": loaded, "skipped": skipped}
        except Exception as exc:
            print(f"[knowledge_graph] load_curriculum error: {exc}", file=sys.stderr)
            return {"loaded": 0, "skipped": 0}

    def generate_recommendations(self, n: int = 10, rotation_filter: str = None) -> list[dict]:
        """Core gap detection: decay all topics, score curriculum gaps, return top N.

        Returns a list of dicts with curriculum info, learner info, gap_score,
        and gap_type.
        """
        try:
            # Step 1: batch decay
            self.apply_decay()

            # Step 2: get all curriculum topics
            curriculum_rows = self.conn.execute(
                "SELECT * FROM curriculum_topics"
            ).fetchall()

            if not curriculum_rows:
                return []

            now = datetime.now(timezone.utc)
            thirty_days_ago = (now - timedelta(days=30)).isoformat()
            priority_weight = {1: 3.0, 2: 2.0, 3: 1.0}

            results = []

            for crow in curriculum_rows:
                c = dict(crow)
                topic_name = c["topic_name"]
                priority = c.get("priority", 2)
                pw = priority_weight.get(priority, 1.0)
                domain = c.get("domain", "")

                # Find matching learner topic
                canonical = self._normalize_topic(topic_name)
                learner = self._find_topic(canonical)

                if learner is None:
                    # Never encountered
                    base = 0.8
                    gap_type = "never_encountered"
                    error_count = 0
                else:
                    confidence_gap = 1.0 - learner["confidence"]
                    depth_penalty = max(0, 3 - learner["depth"]) * 0.1
                    # Count error signals in last 30 days
                    err_row = self.conn.execute(
                        """SELECT COUNT(*) AS cnt FROM signal_events
                           WHERE topic_id = ?
                             AND signal_type IN ('incorrect_recall', 'weakness_identified')
                             AND timestamp > ?""",
                        (learner["topic_id"], thirty_days_ago),
                    ).fetchone()
                    error_count = err_row["cnt"] if err_row else 0
                    error_penalty = min(0.3, error_count * 0.1)
                    base = confidence_gap + depth_penalty + error_penalty

                    # Determine gap type
                    if error_count >= 3:
                        gap_type = "error_cluster"
                    elif learner["confidence"] < 0.3 and learner["encounter_count"] > 0:
                        gap_type = "decaying"
                    elif learner["depth"] <= 1 and priority == 1:
                        gap_type = "shallow"
                    else:
                        gap_type = "general_gap"

                # Rotation boost
                if rotation_filter and domain.lower().startswith(rotation_filter.lower()):
                    base += 0.3

                gap_score = base * pw

                results.append({
                    "curriculum_topic": c,
                    "learner_topic": dict(learner) if learner else None,
                    "gap_score": round(gap_score, 4),
                    "gap_type": gap_type,
                    "error_count": error_count,
                })

            # Sort by gap_score descending
            results.sort(key=lambda x: x["gap_score"], reverse=True)
            return results[:n]

        except Exception as exc:
            print(f"[knowledge_graph] generate_recommendations error: {exc}", file=sys.stderr)
            return []

    def format_recommendations(self, recs: list[dict], rotation: str = None) -> str:
        """Format recommendation list as a clean text report."""
        try:
            # Summary stats
            total_curriculum = self.conn.execute("SELECT COUNT(*) FROM curriculum_topics").fetchone()[0]
            tracked = self.conn.execute(
                "SELECT COUNT(*) FROM topics WHERE curriculum_id IS NOT NULL"
            ).fetchone()[0]
            pct = round(100 * tracked / total_curriculum, 1) if total_curriculum > 0 else 0.0
            avg_row = self.conn.execute("SELECT AVG(confidence) AS ac FROM topics WHERE curriculum_id IS NOT NULL").fetchone()
            avg_conf = round(avg_row["ac"], 2) if avg_row["ac"] is not None else 0.0

            lines: list[str] = []
            lines.append("=" * 60)
            lines.append("  STUDY RECOMMENDATIONS")
            lines.append("=" * 60)
            lines.append(f"  Topics tracked: {tracked} / {total_curriculum} curriculum items ({pct}%)")
            lines.append(f"  Average confidence: {avg_conf:.2f}")
            lines.append(f"  Current rotation: {rotation or 'Not set'}")
            lines.append("")

            # Group by gap_type
            gap_order = ["never_encountered", "decaying", "shallow", "error_cluster", "general_gap"]
            gap_headers = {
                "never_encountered": "\U0001f534 Urgent Gaps (Never Encountered, Priority 1):",
                "decaying": "\U0001f4c9 Decaying Knowledge:",
                "shallow": "\U0001f4ca Shallow Depth (Priority 1, Surface Only):",
                "error_cluster": "\u26a0\ufe0f Error Clusters:",
                "general_gap": "\U0001f4cb General Gaps:",
            }

            grouped: dict[str, list[dict]] = {g: [] for g in gap_order}
            for r in recs:
                gt = r.get("gap_type", "general_gap")
                grouped.setdefault(gt, []).append(r)

            # Sort within each group by gap_score
            for g in grouped:
                grouped[g].sort(key=lambda x: x["gap_score"], reverse=True)

            idx = 1
            for gt in gap_order:
                items = grouped.get(gt, [])
                if not items:
                    continue

                lines.append(f"  {gap_headers.get(gt, gt)}:")
                for r in items:
                    ct = r["curriculum_topic"]
                    lt = r["learner_topic"]
                    name = ct.get("display_name", ct.get("topic_name", "?"))
                    domain = ct.get("domain", "")
                    acgme = ct.get("acgme_milestone", "")

                    if gt == "never_encountered":
                        lines.append(f"    {idx}. [{name}] \u2014 Domain: {domain}, ACGME: {acgme}")
                        lines.append("       Never encountered in study or practice")
                    elif gt == "decaying":
                        conf = lt["confidence"] if lt else 0.0
                        last_seen = (lt.get("last_seen") or "")[:10] if lt else "?"
                        # Calculate days ago
                        ls_dt = self._parse_ts(lt.get("last_seen")) if lt else None
                        days_ago = (datetime.now(timezone.utc) - ls_dt).days if ls_dt else "?"
                        lines.append(f"    {idx}. [{name}] \u2014 Conf: {conf:.2f}, Last seen: {days_ago} days ago")
                        lines.append("       Was studied but confidence has decayed below threshold")
                    elif gt == "shallow":
                        depth = lt["depth"] if lt else 0
                        depth_label = _DEPTH_LABELS.get(depth, f"level-{depth}")
                        encounters = lt["encounter_count"] if lt else 0
                        lines.append(f"    {idx}. [{name}] \u2014 Depth: {depth_label}, Encounters: {encounters}")
                        lines.append("       Needs mechanistic or decision-making practice")
                    elif gt == "error_cluster":
                        ec = r.get("error_count", 0)
                        lines.append(f"    {idx}. [{name}] \u2014 {ec} errors in last 30 days")
                        lines.append("       Repeated difficulty \u2014 targeted review needed")
                    else:  # general_gap
                        score = r["gap_score"]
                        conf = lt["confidence"] if lt else 0.0
                        lines.append(f"    {idx}. [{name}] \u2014 Score: {score:.2f}, Conf: {conf:.2f}")

                    idx += 1
                lines.append("")

            lines.append("=" * 60)
            return "\n".join(lines)
        except Exception as exc:
            print(f"[knowledge_graph] format_recommendations error: {exc}", file=sys.stderr)
            return f"Error formatting recommendations: {exc}"

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Phase 3.5 — ACGME Milestone Report
    # ------------------------------------------------------------------

    def milestone_report(self) -> dict:
        """Aggregate concept mastery by ACGME milestone for a competency dashboard.

        Returns:
            dict with keys:
                total_milestones: int
                milestones: list of milestone dicts sorted weakest-first, each with:
                    milestone, domain, total_topics, studied_topics, coverage_pct,
                    avg_confidence, gap_count, topics (list of {name, confidence, encounters})
        """
        try:
            rows = self.conn.execute(
                """SELECT ct.acgme_milestone, ct.domain, ct.display_name,
                          ct.topic_name, ct.priority,
                          COALESCE(MAX(t.confidence), 0.0) AS confidence,
                          COALESCE(SUM(t.encounter_count), 0) AS encounter_count,
                          MAX(t.depth) AS depth
                   FROM curriculum_topics ct
                   LEFT JOIN topics t ON t.curriculum_id = ct.curriculum_id
                   WHERE ct.acgme_milestone IS NOT NULL AND ct.acgme_milestone != ''
                   GROUP BY ct.curriculum_id
                   ORDER BY ct.acgme_milestone, ct.domain, ct.priority"""
            ).fetchall()

            milestone_groups: dict[str, list[dict]] = {}
            for r in rows:
                key = r["acgme_milestone"]
                milestone_groups.setdefault(key, []).append(dict(r))

            milestones = []
            for milestone_label, topics in milestone_groups.items():
                studied = [t for t in topics if (t.get("encounter_count") or 0) > 0]
                confidences = [t["confidence"] for t in studied if t.get("confidence") is not None]
                gaps = [t for t in topics
                        if (t.get("encounter_count") or 0) == 0 or (t.get("confidence") or 0.0) < 0.1]

                domain_counts: dict[str, int] = {}
                for t in topics:
                    d = t.get("domain") or ""
                    domain_counts[d] = domain_counts.get(d, 0) + 1
                primary_domain = max(domain_counts, key=domain_counts.get) if domain_counts else ""

                milestones.append({
                    "milestone": milestone_label,
                    "domain": primary_domain,
                    "total_topics": len(topics),
                    "studied_topics": len(studied),
                    "coverage_pct": round(100 * len(studied) / len(topics), 1) if topics else 0.0,
                    "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
                    "gap_count": len(gaps),
                    "topics": [
                        {
                            "name": t.get("display_name") or t.get("topic_name") or "",
                            "confidence": round(t.get("confidence") or 0.0, 3),
                            "encounters": t.get("encounter_count") or 0,
                        }
                        for t in topics
                    ],
                })

            milestones.sort(key=lambda m: (m["coverage_pct"], m["avg_confidence"]))
            return {"total_milestones": len(milestones), "milestones": milestones}

        except Exception as exc:
            print(f"[knowledge_graph] milestone_report error: {exc}", file=sys.stderr)
            return {"total_milestones": 0, "milestones": [], "error": str(exc)}

    # ------------------------------------------------------------------
    # Phase 4 — Anki Integration
    # ------------------------------------------------------------------

    def _anki_request(self, url: str, action: str, params: dict | None = None) -> object:
        """Send a request to AnkiConnect and return the result."""
        payload: dict = {"action": action, "version": 6}
        if params:
            payload["params"] = params
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res.get("result")

    def sync_anki(self, url: str = "http://localhost:8765") -> dict:
        """Pull Anki review data via AnkiConnect and snapshot into the knowledge graph."""
        try:
            # 1. Test connection
            try:
                self._anki_request(url, "version")
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                return {"status": "unavailable", "reason": str(exc)}

            # 2. Find cards in Neuro-related decks
            card_ids = self._anki_request(url, "findCards", {"query": "deck:Neuro*"})
            if not card_ids:
                card_ids = self._anki_request(url, "findCards", {"query": "deck:*"})
            if not card_ids:
                return {"status": "synced", "cards": 0, "matched": 0, "unmatched": 0, "snapshot_id": None}

            # 3. Fetch card info in batches of 50
            all_cards: list[dict] = []
            for i in range(0, len(card_ids), 50):
                batch = card_ids[i : i + 50]
                batch_info = self._anki_request(url, "cardsInfo", {"cards": batch})
                if batch_info:
                    all_cards.extend(batch_info)

            # 4. Create snapshot
            now = datetime.now(timezone.utc).isoformat()
            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO anki_sync_snapshots (synced_at, total_cards, total_reviews, metadata)
                       VALUES (?, ?, 0, '{}')""",
                    (now, len(all_cards)),
                )
                snapshot_id = cur.lastrowid

            # 5. Get previous snapshot's note IDs to avoid duplicate signal logging
            prev_note_ids: set[int] = set()
            prev_snap = self.conn.execute(
                "SELECT snapshot_id FROM anki_sync_snapshots WHERE snapshot_id < ? ORDER BY snapshot_id DESC LIMIT 1",
                (snapshot_id,),
            ).fetchone()
            if prev_snap:
                rows = self.conn.execute(
                    "SELECT anki_note_id FROM anki_card_stats WHERE snapshot_id = ?",
                    (prev_snap["snapshot_id"],),
                ).fetchall()
                prev_note_ids = {r["anki_note_id"] for r in rows}

            # 6. Process each card
            matched = 0
            unmatched = 0

            for card in all_cards:
                note_id = card.get("note", 0)
                deck_name = card.get("deckName", "")
                interval = card.get("interval", 0)
                factor = card.get("factor", 2500)
                reps = card.get("reps", 0)
                lapses = card.get("lapses", 0)

                # Extract first field value (card front text)
                fields = card.get("fields", {})
                card_front = ""
                if fields:
                    first_field = next(iter(fields.values()), {})
                    card_front = first_field.get("value", "")[:200] if isinstance(first_field, dict) else str(first_field)[:200]

                ease_factor = factor / 1000.0

                # Topic matching
                matched_topic_id = None
                if card_front:
                    normalized = self._normalize_topic(card_front)
                    topic = self._find_topic(normalized)
                    if topic:
                        matched_topic_id = topic["topic_id"]
                        matched += 1

                        # Log signal only for cards not in the previous snapshot
                        if note_id not in prev_note_ids:
                            if ease_factor >= 2.5 and interval >= 21:
                                self.log_signal(
                                    topic_name=card_front,
                                    source="anki",
                                    signal_type="anki_review",
                                    metadata={"confidence_delta": 0.03},
                                )
                            elif ease_factor < 2.0 or lapses >= 3:
                                self.log_signal(
                                    topic_name=card_front,
                                    source="anki",
                                    signal_type="anki_review",
                                    metadata={"confidence_delta": -0.05},
                                )
                            # Otherwise: normal retention, no change
                    else:
                        unmatched += 1
                else:
                    unmatched += 1

                # Insert card stat row
                with self.conn:
                    self.conn.execute(
                        """INSERT INTO anki_card_stats
                           (snapshot_id, anki_note_id, deck_name, card_front,
                            interval_days, ease_factor, reps, lapses, matched_topic_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (snapshot_id, note_id, deck_name, card_front,
                         interval, ease_factor, reps, lapses, matched_topic_id),
                    )

            return {
                "status": "synced",
                "cards": len(all_cards),
                "matched": matched,
                "unmatched": unmatched,
                "snapshot_id": snapshot_id,
            }

        except Exception as exc:
            return {"status": "unavailable", "reason": f"sync_anki error: {exc}"}

    def log_anki_creation(self, topic: str, card_count: int, claim_texts: list[str] = None) -> None:
        """Log knowledge graph signals when new Anki cards are created.

        Called from anki_sync_cli.py after card dispatch.
        """
        try:
            if claim_texts:
                for claim in claim_texts:
                    self.log_signal(
                        topic_name=claim,
                        source="anki",
                        signal_type="card_created",
                        depth_at_event=2,
                    )
            else:
                self.log_signal(
                    topic_name=topic,
                    source="anki",
                    signal_type="card_created",
                    depth_at_event=2,
                )
        except Exception as exc:
            print(f"[knowledge_graph] log_anki_creation error: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Visual dashboards (JSON output for agent-formatted display)
    # ------------------------------------------------------------------

    def dashboard(self) -> dict:
        """Domain-level progress dashboard with heatmap data.

        Returns a dict with domain summaries (topic counts, avg confidence,
        depth distribution, coverage) suitable for agent-formatted display.
        """
        try:
            total_topics = self.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
            total_events = self.conn.execute("SELECT COUNT(*) FROM signal_events").fetchone()[0]
            avg_row = self.conn.execute("SELECT AVG(confidence) FROM topics").fetchone()
            avg_conf = round(avg_row[0], 3) if avg_row[0] is not None else 0.0

            # Studied vs never-seen
            studied = self.conn.execute(
                "SELECT COUNT(*) FROM topics WHERE encounter_count > 0"
            ).fetchone()[0]

            # Per-domain breakdown via curriculum_topics joined with topics
            domains = []
            domain_rows = self.conn.execute(
                """SELECT DISTINCT domain FROM curriculum_topics ORDER BY domain"""
            ).fetchall()

            for dr in domain_rows:
                domain = dr["domain"]
                # Total curriculum topics in this domain
                cur_total = self.conn.execute(
                    "SELECT COUNT(*) FROM curriculum_topics WHERE domain = ?", (domain,)
                ).fetchone()[0]

                # Topics that have been encountered (joined via topic_name match)
                cur_encountered = self.conn.execute(
                    """SELECT COUNT(*) FROM curriculum_topics ct
                       JOIN topics t ON t.curriculum_id = ct.curriculum_id
                       WHERE ct.domain = ? AND t.encounter_count > 0""",
                    (domain,),
                ).fetchone()[0]

                # Average confidence for this domain
                avg_d = self.conn.execute(
                    """SELECT AVG(t.confidence) FROM curriculum_topics ct
                       JOIN topics t ON t.curriculum_id = ct.curriculum_id
                       WHERE ct.domain = ?""",
                    (domain,),
                ).fetchone()[0]
                avg_d = round(avg_d, 3) if avg_d is not None else 0.0

                # Depth distribution for this domain
                depth_rows = self.conn.execute(
                    """SELECT t.depth, COUNT(*) AS cnt FROM curriculum_topics ct
                       JOIN topics t ON t.curriculum_id = ct.curriculum_id
                       WHERE ct.domain = ?
                       GROUP BY t.depth ORDER BY t.depth""",
                    (domain,),
                ).fetchall()
                depth_dist = {r["depth"]: r["cnt"] for r in depth_rows}

                # Strongest topic (highest confidence)
                strongest = self.conn.execute(
                    """SELECT t.canonical_name, t.confidence FROM curriculum_topics ct
                       JOIN topics t ON t.curriculum_id = ct.curriculum_id
                       WHERE ct.domain = ? AND t.encounter_count > 0
                       ORDER BY t.confidence DESC LIMIT 1""",
                    (domain,),
                ).fetchone()

                # Weakest encountered topic
                weakest = self.conn.execute(
                    """SELECT t.canonical_name, t.confidence FROM curriculum_topics ct
                       JOIN topics t ON t.curriculum_id = ct.curriculum_id
                       WHERE ct.domain = ? AND t.encounter_count > 0
                       ORDER BY t.confidence ASC LIMIT 1""",
                    (domain,),
                ).fetchone()

                domains.append({
                    "domain": domain,
                    "total": cur_total,
                    "encountered": cur_encountered,
                    "coverage_pct": round(100 * cur_encountered / cur_total, 1) if cur_total else 0,
                    "avg_confidence": avg_d,
                    "depth_distribution": depth_dist,
                    "strongest": {"name": strongest["canonical_name"], "confidence": strongest["confidence"]} if strongest else None,
                    "weakest": {"name": weakest["canonical_name"], "confidence": weakest["confidence"]} if weakest else None,
                })

            # Recent activity (last 20 events)
            recent_events = self.conn.execute(
                """SELECT se.timestamp, se.source, se.signal_type, se.confidence_delta,
                          t.canonical_name AS topic
                   FROM signal_events se
                   JOIN topics t ON t.topic_id = se.topic_id
                   ORDER BY se.timestamp DESC LIMIT 20"""
            ).fetchall()

            return {
                "total_topics": total_topics,
                "total_events": total_events,
                "studied": studied,
                "never_seen": total_topics - studied,
                "avg_confidence": avg_conf,
                "domains": domains,
                "recent_activity": [dict(r) for r in recent_events],
            }

        except Exception as exc:
            print(f"[knowledge_graph] dashboard error: {exc}", file=sys.stderr)
            return {"error": str(exc)}

    def topics_list(self, domain: str = None, min_confidence: float = None,
                    max_confidence: float = None, depth: int = None,
                    sort_by: str = "confidence", only_studied: bool = False,
                    limit: int = 50) -> list[dict]:
        """Return a filtered, sorted list of topics for display.

        Args:
            domain: Filter by curriculum domain (e.g. "Vascular")
            min_confidence: Only topics >= this confidence
            max_confidence: Only topics <= this confidence
            depth: Only topics at this exact depth
            sort_by: "confidence" (desc), "confidence_asc", "encounters", "recent", "alpha"
            only_studied: If True, only topics with encounter_count > 0
            limit: Max topics to return (default 50)
        """
        try:
            query = """
                SELECT t.canonical_name, t.display_name, t.category, t.confidence,
                       t.depth, t.encounter_count, t.last_seen,
                       ct.domain, ct.priority, ct.acgme_milestone, ct.pgy_target
                FROM topics t
                LEFT JOIN curriculum_topics ct ON t.curriculum_id = ct.curriculum_id
                WHERE 1=1
            """
            params: list = []

            if domain:
                query += " AND ct.domain = ?"
                params.append(domain)
            if min_confidence is not None:
                query += " AND t.confidence >= ?"
                params.append(min_confidence)
            if max_confidence is not None:
                query += " AND t.confidence <= ?"
                params.append(max_confidence)
            if depth is not None:
                query += " AND t.depth = ?"
                params.append(depth)
            if only_studied:
                query += " AND t.encounter_count > 0"

            sort_map = {
                "confidence": "t.confidence DESC",
                "confidence_asc": "t.confidence ASC",
                "encounters": "t.encounter_count DESC",
                "recent": "t.last_seen DESC",
                "alpha": "t.canonical_name ASC",
            }
            query += f" ORDER BY {sort_map.get(sort_by, 't.confidence DESC')}"
            query += f" LIMIT {limit}"

            rows = self.conn.execute(query, params).fetchall()

            _depth_labels = {0: "never-seen", 1: "surface", 2: "mechanistic", 3: "decision-making"}
            return [
                {
                    "name": r["display_name"] or r["canonical_name"],
                    "category": r["category"],
                    "domain": r["domain"] or "",
                    "confidence": round(r["confidence"], 3),
                    "depth": r["depth"],
                    "depth_label": _depth_labels.get(r["depth"], f"depth-{r['depth']}"),
                    "encounters": r["encounter_count"],
                    "last_seen": (r["last_seen"] or "")[:10],
                    "priority": r["priority"],
                    "acgme": r["acgme_milestone"] or "",
                    "pgy_target": r["pgy_target"],
                }
                for r in rows
            ]

        except Exception as exc:
            print(f"[knowledge_graph] topics_list error: {exc}", file=sys.stderr)
            return []

    def activity_feed(self, n: int = 30) -> list[dict]:
        """Return the last N signal events as a chronological feed."""
        try:
            rows = self.conn.execute(
                """SELECT se.timestamp, se.source, se.signal_type, se.depth_at_event,
                          se.confidence_delta, se.metadata,
                          t.canonical_name AS topic, t.confidence AS current_confidence
                   FROM signal_events se
                   JOIN topics t ON t.topic_id = se.topic_id
                   ORDER BY se.timestamp DESC LIMIT ?""",
                (n,),
            ).fetchall()

            _source_icons = {
                "rag": "search", "bootcamp": "sim", "intraop": "procedure",
                "anki": "cards", "user": "manual",
            }

            return [
                {
                    "timestamp": r["timestamp"][:19].replace("T", " "),
                    "source": _source_icons.get(r["source"], r["source"]),
                    "signal": r["signal_type"],
                    "topic": r["topic"],
                    "delta": r["confidence_delta"],
                    "current_confidence": round(r["current_confidence"], 3),
                    "depth": r["depth_at_event"],
                }
                for r in rows
            ]

        except Exception as exc:
            print(f"[knowledge_graph] activity_feed error: {exc}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # Prefrontal Cortex — Learner-Aware Context Injection
    # ------------------------------------------------------------------

    _DEPTH_LABELS = {0: "never-seen", 1: "surface", 2: "mechanistic", 3: "decision-making"}

    # Words too generic to match on individually
    _STOP_WORDS = {
        "the", "and", "for", "with", "from", "that", "this", "after", "before",
        "during", "between", "about", "into", "through", "management", "treatment",
        "diagnosis", "clinical", "surgical", "approach", "technique", "presentation",
    }

    def _fuzzy_find_topics_in_query(self, query: str) -> list[str]:
        """Find stored topics whose canonical names significantly overlap with the query.

        Uses token overlap scoring: for each stored topic, count how many of its
        significant words appear in the query.  Return topics with >=50% word overlap,
        sorted by overlap ratio descending, capped at 3.
        """
        try:
            query_lower = query.lower()
            query_tokens = set(re.split(r"\W+", query_lower)) - self._STOP_WORDS - {""}

            if len(query_tokens) < 2:
                return []

            # Get all topics with encounters > 0 first, then others
            rows = self.conn.execute(
                "SELECT canonical_name FROM topics ORDER BY encounter_count DESC"
            ).fetchall()

            scored = []
            for r in rows:
                cn = r["canonical_name"]
                cn_tokens = set(re.split(r"\W+", cn)) - self._STOP_WORDS - {""}
                if len(cn_tokens) < 2:
                    continue
                overlap = cn_tokens & query_tokens
                ratio = len(overlap) / len(cn_tokens)
                if ratio >= 0.5 and len(overlap) >= 2:
                    scored.append((ratio, cn))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [s[1] for s in scored[:3]]
        except Exception:
            return []

    def learner_context(self, query: str) -> dict:
        """Pre-flight check: build a learner context block for the given query.

        Extracts topics from the query, retrieves the learner's full history
        with each, identifies cross-capability patterns, and returns a
        structured JSON block the agent uses to adapt its response.

        Returns a dict with:
          - topics: per-topic learner state (confidence, depth, encounters, errors, signals)
          - adaptive_guidance: plain-English directives for the agent
          - cross_capability_patterns: detected patterns across modalities
          - suggested_depth: recommended target depth for this interaction
        """
        try:
            raw_topics = self.extract_topics_from_query(query)
            now = datetime.now(timezone.utc)
            thirty_days_ago = (now - timedelta(days=30)).isoformat()
            seven_days_ago = (now - timedelta(days=7)).isoformat()

            topic_contexts = []
            guidance_lines = []
            patterns = []
            max_suggested_depth = 1
            seen_topic_ids = set()  # prevent duplicate entries

            # Also try to find topics by matching significant words from
            # the full query against all stored canonical names.  This
            # catches cases where extract_topics_from_query returns one
            # long phrase that doesn't exactly match any stored topic
            # but *contains* the key concept words.
            if len(raw_topics) <= 1:
                _extra = self._fuzzy_find_topics_in_query(query)
                for et in _extra:
                    norm = self._normalize_topic(et)
                    if norm not in [self._normalize_topic(r) for r in raw_topics]:
                        raw_topics.append(et)

            for raw in raw_topics:
                if not raw:
                    continue
                canonical = self._normalize_topic(raw)
                topic = self._find_topic(canonical)
                if topic and topic["topic_id"] in seen_topic_ids:
                    continue
                if topic:
                    seen_topic_ids.add(topic["topic_id"])

                if topic is None:
                    # Never encountered
                    topic_contexts.append({
                        "topic": raw,
                        "status": "never_encountered",
                        "confidence": 0.0,
                        "depth": 0,
                        "depth_label": "never-seen",
                        "encounters": 0,
                        "last_seen": None,
                        "recent_signals": [],
                        "error_count_30d": 0,
                        "curriculum_priority": self._get_curriculum_priority(canonical),
                    })
                    guidance_lines.append(
                        f"'{raw}' is brand new — start from foundational principles, "
                        f"build the conceptual scaffold before advancing to mechanisms."
                    )
                    continue

                tid = topic["topic_id"]

                # Recent signals (last 30 days) — include metadata for content history
                recent_signals = self.conn.execute(
                    """SELECT timestamp, source, signal_type, depth_at_event,
                            confidence_delta, metadata
                       FROM signal_events
                       WHERE topic_id = ? AND timestamp > ?
                       ORDER BY timestamp DESC LIMIT 10""",
                    (tid, thirty_days_ago),
                ).fetchall()
                recent_signals_parsed = []
                _prior_summaries = []
                for _sig in recent_signals:
                    sd = dict(_sig)
                    _meta_raw = sd.pop("metadata", None)
                    if _meta_raw:
                        try:
                            _meta_obj = json.loads(_meta_raw) if isinstance(_meta_raw, str) else _meta_raw
                            # Extract learning summaries from study_session events
                            _summary = _meta_obj.get("concepts_taught")
                            if _summary:
                                _prior_summaries.extend(
                                    _summary if isinstance(_summary, list) else [_summary]
                                )
                            _comprehension = _meta_obj.get("comprehension")
                            if _comprehension:
                                sd["comprehension"] = _comprehension
                        except (json.JSONDecodeError, TypeError):
                            pass
                    recent_signals_parsed.append(sd)
                recent_signals = recent_signals_parsed

                # Error count (last 30 days)
                err_count = self.conn.execute(
                    """SELECT COUNT(*) FROM signal_events
                       WHERE topic_id = ?
                         AND signal_type IN ('incorrect_recall', 'weakness_identified')
                         AND timestamp > ?""",
                    (tid, thirty_days_ago),
                ).fetchone()[0]

                # Capability coverage: which sources have touched this topic?
                source_set = set()
                all_signals = self.conn.execute(
                    "SELECT DISTINCT source FROM signal_events WHERE topic_id = ?",
                    (tid,),
                ).fetchall()
                for s in all_signals:
                    source_set.add(s["source"])

                # Days since last seen
                last_seen_dt = self._parse_ts(topic.get("last_seen"))
                days_ago = (now - last_seen_dt).days if last_seen_dt else None

                depth = topic["depth"]
                confidence = topic["confidence"]
                encounters = topic["encounter_count"]

                tc = {
                    "topic": raw,
                    "canonical": topic["canonical_name"],
                    "status": "known",
                    "confidence": round(confidence, 3),
                    "depth": depth,
                    "depth_label": self._DEPTH_LABELS.get(depth, f"depth-{depth}"),
                    "encounters": encounters,
                    "last_seen": topic.get("last_seen", "")[:10],
                    "days_since_last_seen": days_ago,
                    "recent_signals": recent_signals,
                    "error_count_30d": err_count,
                    "sources_used": sorted(source_set),
                    "curriculum_priority": self._get_curriculum_priority(canonical),
                }
                # Add learning history from study_session events
                if _prior_summaries:
                    tc["prior_concepts_taught"] = _prior_summaries[:6]

                # ── Per-concept mastery dictionary ──
                concepts = self.conn.execute(
                    """SELECT concept_text, status, times_confirmed, times_missed,
                              error_type, misconception, remediation, last_updated
                       FROM concept_mastery WHERE topic_id = ?
                       ORDER BY last_updated DESC""",
                    (tid,),
                ).fetchall()
                if concepts:
                    tc["concepts_known"] = [
                        {"concept": c["concept_text"],
                         "confirmed": c["times_confirmed"],
                         "last_updated": c["last_updated"][:10]}
                        for c in concepts if c["status"] == "known"
                    ]
                    tc["concepts_unknown"] = [
                        {"concept": c["concept_text"],
                         "missed": c["times_missed"],
                         "error_type": c["error_type"] or None,
                         "misconception": c["misconception"] or None,
                         "remediation": c["remediation"] or None,
                         "last_updated": c["last_updated"][:10]}
                        for c in concepts if c["status"] == "unknown"
                    ]
                    # Guidance from concept mastery
                    n_known = len(tc["concepts_known"])
                    n_unknown = len(tc["concepts_unknown"])
                    if n_unknown > 0:
                        gap_details = []
                        for c in tc["concepts_unknown"][:5]:
                            detail = c["concept"]
                            if c.get("misconception"):
                                detail += f" (misconception: {c['misconception']})"
                            elif c.get("error_type"):
                                detail += f" ({c['error_type']})"
                            gap_details.append(detail)
                        guidance_lines.append(
                            f"'{raw}' has {n_unknown} specific concept gap(s): "
                            + "; ".join(gap_details)
                            + f". Target these directly — do not re-teach the {n_known} concepts already mastered."
                        )

                topic_contexts.append(tc)

                # --- Generate adaptive guidance ---

                # Depth-adaptive guidance
                if depth == 0:
                    guidance_lines.append(
                        f"'{raw}' exists in the graph but has never been studied — "
                        f"treat as new, start from foundations."
                    )
                elif depth == 1:
                    guidance_lines.append(
                        f"'{raw}' was seen at surface level (conf={confidence:.2f}) — "
                        f"skip the overview, target mechanisms and the 'why'."
                    )
                    max_suggested_depth = max(max_suggested_depth, 2)
                elif depth == 2 and confidence < 0.15:
                    guidance_lines.append(
                        f"'{raw}' has been explored mechanistically but confidence is still low "
                        f"(conf={confidence:.2f}) — reinforce the mechanism, then bridge to "
                        f"clinical application with concrete scenarios."
                    )
                    max_suggested_depth = max(max_suggested_depth, 2)
                elif depth == 2 and confidence >= 0.15:
                    guidance_lines.append(
                        f"'{raw}' has mechanistic understanding (conf={confidence:.2f}) — "
                        f"advance to clinical decision-making, surgical indications, and complications."
                    )
                    max_suggested_depth = max(max_suggested_depth, 3)
                elif depth >= 3 and confidence < 0.3:
                    guidance_lines.append(
                        f"'{raw}' has been tested at decision-making level but confidence "
                        f"remains low (conf={confidence:.2f}) — there may be a conceptual gap. "
                        f"Re-anchor the core mechanism before advancing."
                    )
                    max_suggested_depth = max(max_suggested_depth, 2)
                elif depth >= 3 and confidence >= 0.3:
                    guidance_lines.append(
                        f"'{raw}' is at decision-making depth (conf={confidence:.2f}) — "
                        f"focus on nuance, controversies, edge cases, and board-style reasoning."
                    )
                    max_suggested_depth = max(max_suggested_depth, 3)

                # Learning history guidance
                if _prior_summaries and encounters >= 2:
                    guidance_lines.append(
                        f"Prior sessions on '{raw}' taught: "
                        + "; ".join(str(s)[:80] for s in _prior_summaries[:3])
                        + " — build on this, don't repeat the same ground."
                    )

                # Error pattern detection
                if err_count >= 2:
                    # Find the specific error signals
                    err_signals = [s for s in recent_signals
                                   if s["signal_type"] in ("incorrect_recall", "weakness_identified")]
                    err_sources = [s["source"] for s in err_signals]
                    guidance_lines.append(
                        f"⚠️ '{raw}' has {err_count} errors in the last 30 days "
                        f"(sources: {', '.join(set(err_sources))}). "
                        f"Proactively address the gap pattern — don't just re-teach, "
                        f"isolate what keeps being missed."
                    )

                # Decay detection
                if days_ago and days_ago > 21 and confidence < 0.2:
                    guidance_lines.append(
                        f"'{raw}' hasn't been seen in {days_ago} days and confidence "
                        f"has decayed to {confidence:.2f} — include a brief recall anchor "
                        f"before advancing."
                    )

                # Cross-capability pattern detection
                if "rag" in source_set and "bootcamp" not in source_set and encounters >= 2:
                    patterns.append({
                        "type": "studied_not_tested",
                        "topic": raw,
                        "message": f"'{raw}' has been studied {encounters}x but never "
                                   f"tested in simulation — consider offering a bootcamp scenario.",
                    })

                if "bootcamp" in source_set and "rag" not in source_set:
                    patterns.append({
                        "type": "tested_not_studied",
                        "topic": raw,
                        "message": f"'{raw}' was encountered in simulation but never "
                                   f"studied in depth — foundational knowledge may have gaps.",
                    })

                if err_count >= 2 and "rag" in source_set:
                    patterns.append({
                        "type": "knowledge_application_gap",
                        "topic": raw,
                        "message": f"'{raw}' has been studied but errors persist — "
                                   f"the gap may be in application, not knowledge. "
                                   f"A targeted clinical scenario would test transfer.",
                    })

                if "anki" in source_set:
                    # Check Anki card performance
                    anki_stats = self.conn.execute(
                        """SELECT AVG(ease_factor) AS avg_ease, AVG(lapses) AS avg_lapse
                           FROM anki_card_stats
                           WHERE matched_topic_id = ?
                           ORDER BY snapshot_id DESC LIMIT 20""",
                        (tid,),
                    ).fetchone()
                    if anki_stats and anki_stats["avg_ease"] is not None:
                        if anki_stats["avg_ease"] < 2.0 or (anki_stats["avg_lapse"] or 0) >= 3:
                            patterns.append({
                                "type": "anki_struggling",
                                "topic": raw,
                                "message": f"Anki cards for '{raw}' show poor retention "
                                           f"(ease={anki_stats['avg_ease']:.1f}, "
                                           f"lapses={anki_stats['avg_lapse']:.0f}) — "
                                           f"the underlying concept may need re-teaching.",
                            })

            # Domain coverage check (if topics map to a single domain)
            domains_seen = set()
            for tc in topic_contexts:
                cp = tc.get("curriculum_priority")
                if cp and cp.get("domain"):
                    domains_seen.add(cp["domain"])

            if len(domains_seen) == 1:
                domain = list(domains_seen)[0]
                domain_stats = self.conn.execute(
                    """SELECT COUNT(*) AS total,
                              SUM(CASE WHEN t.encounter_count > 0 THEN 1 ELSE 0 END) AS studied
                       FROM curriculum_topics ct
                       LEFT JOIN topics t ON t.curriculum_id = ct.curriculum_id
                       WHERE ct.domain = ?""",
                    (domain,),
                ).fetchone()
                if domain_stats and domain_stats["total"] > 0:
                    coverage = round(100 * (domain_stats["studied"] or 0) / domain_stats["total"], 1)
                    if coverage < 10:
                        patterns.append({
                            "type": "low_domain_coverage",
                            "topic": domain,
                            "message": f"Domain '{domain}' has only {coverage}% coverage — "
                                       f"there are many related topics still unexplored.",
                        })

            # ── Meta-cognitive learning patterns ──
            learning_style = []
            try:
                lp_rows = self.conn.execute(
                    "SELECT pattern_type, description, confidence FROM learning_patterns ORDER BY confidence DESC LIMIT 5"
                ).fetchall()
                for lp in lp_rows:
                    learning_style.append({
                        "pattern": lp["pattern_type"],
                        "description": lp["description"],
                        "confidence": round(lp["confidence"], 2),
                    })
            except Exception:
                pass

            # ── Spaced verification: concepts due for review ──
            # Exclude topics currently being queried (they'll get fresh signal)
            query_topic_canonicals = [
                tc.get("canonical", tc.get("topic", ""))
                for tc in topic_contexts if tc.get("status") != "never_encountered"
            ]
            review_queue = self.get_review_queue(
                n=5,
                exclude_topics=query_topic_canonicals,
            )
            # Also check if any concepts from the CURRENT query's topics are due
            current_topic_ids = set()
            for tc in topic_contexts:
                if tc.get("canonical"):
                    t = self._find_topic(tc["canonical"])
                    if t:
                        current_topic_ids.add(t["topic_id"])
            same_topic_due = []
            if current_topic_ids:
                for tid in current_topic_ids:
                    rows = self.conn.execute(
                        """SELECT concept_text, times_confirmed, times_missed,
                                  last_updated, error_type, misconception
                           FROM concept_mastery
                           WHERE topic_id = ? AND status = 'known'""",
                        (tid,),
                    ).fetchall()
                    for row in rows:
                        has_err = (row["times_missed"] or 0) > 0
                        base = 3.0 if has_err else 7.0
                        confirmed = row["times_confirmed"] or 1
                        interval = base * (1 + 0.3 * confirmed) ** 1.5
                        last_up = self._parse_ts(row["last_updated"])
                        if last_up:
                            days_since = (now - last_up).total_seconds() / 86400.0
                            if days_since >= interval:
                                same_topic_due.append({
                                    "concept": row["concept_text"],
                                    "days_overdue": round(days_since - interval, 1),
                                    "error_history": has_err,
                                })

            if same_topic_due:
                guidance_lines.append(
                    f"VERIFICATION OPPORTUNITY: {len(same_topic_due)} previously 'known' concept(s) "
                    f"on the current topic are overdue for review: "
                    + ", ".join(c["concept"] for c in same_topic_due[:5])
                    + ". Weave a quick verification question into the Gym section."
                )

            # Compile the context block
            result = {
                "query": query,
                "topics": topic_contexts,
                "suggested_depth": max_suggested_depth,
                "adaptive_guidance": guidance_lines,
                "cross_capability_patterns": patterns,
            }
            if learning_style:
                result["learning_patterns"] = learning_style
            if review_queue:
                result["concepts_due_for_review"] = review_queue
            if same_topic_due:
                result["same_topic_review_due"] = same_topic_due

            # ── Remediation directives (error-type → mode routing) ──
            remediation_directives = self.generate_remediation_directives(query)
            if remediation_directives:
                result["remediation_directives"] = remediation_directives
                top = remediation_directives[0]
                guidance_lines.append(
                    f"REMEDIATION TARGET: '{top['concept']}' has a {top['error_type']} gap "
                    f"(missed {top['times_missed']}x). Recommended mode: {top['recommended_mode']}. "
                    f"{top['framing_hint']}"
                )

            # ── Transfer validation candidates ──
            transfer_candidates = self.get_transfer_candidates(n=5)
            if transfer_candidates:
                result["transfer_candidates"] = transfer_candidates
                guidance_lines.append(
                    f"TRANSFER OPPORTUNITY: {len(transfer_candidates)} concept(s) are confirmed "
                    f"but never tested in a different context: "
                    + ", ".join(c["concept"] for c in transfer_candidates[:3])
                    + ". Design the Gym scenario to test one in a novel clinical context."
                )

            return result

        except Exception as exc:
            print(f"[knowledge_graph] learner_context error: {exc}", file=sys.stderr)
            return {"query": query, "topics": [], "adaptive_guidance": [], "cross_capability_patterns": [], "error": str(exc)}

    # ------------------------------------------------------------------
    # Closed-Loop Adaptive Routing — Remediation Directives
    # ------------------------------------------------------------------

    _REMEDIATION_MAP = {
        "numerical_recall": {
            "recommended_mode": "drill",
            "framing_template": "Fill-in-the-blank on exact values: {concept}.",
        },
        "conceptual_confusion": {
            "recommended_mode": "socratic",
            "framing_template": "Force reasoning through the mechanism step-by-step: {concept}. The gap is in the causal chain.",
        },
        "cross_contamination": {
            "recommended_mode": "disambiguation",
            "framing_template": "Side-by-side comparison needed: {concept} vs {misconception}. Previously cross-contaminated.",
        },
        "application_failure": {
            "recommended_mode": "scenario",
            "framing_template": "Clinical scenario requiring application of: {concept}. Knows the fact, can't apply it.",
        },
        "reasoning_gap": {
            "recommended_mode": "scaffold",
            "framing_template": "Step-by-step causal chain walkthrough for: {concept}. A link in the reasoning is missing.",
        },
        "omission": {
            "recommended_mode": "teach",
            "framing_template": "Never encountered: {concept}. Start from foundations.",
        },
    }

    def generate_remediation_directives(self, query: str) -> list[dict]:
        """Generate error-type-matched remediation directives for concepts
        related to the given query that are currently in 'unknown' status
        with a known error_type.

        Returns a list of dicts sorted by times_missed descending (cap 10):
            {concept, topic, topic_canonical, error_type, misconception,
             recommended_mode, framing_hint, times_missed}
        """
        try:
            raw_topics = self.extract_topics_from_query(query)
            if len(raw_topics) <= 1:
                _extra = self._fuzzy_find_topics_in_query(query)
                for et in _extra:
                    norm = self._normalize_topic(et)
                    if norm not in [self._normalize_topic(r) for r in raw_topics]:
                        raw_topics.append(et)

            directives: list[dict] = []
            seen_concepts: set[str] = set()

            for raw in raw_topics:
                if not raw:
                    continue
                canonical = self._normalize_topic(raw)
                topic = self._find_topic(canonical)
                if not topic:
                    continue

                rows = self.conn.execute(
                    """SELECT concept_text, error_type, misconception, remediation, times_missed
                       FROM concept_mastery
                       WHERE topic_id = ? AND status = 'unknown'
                             AND error_type IS NOT NULL AND error_type != ''
                       ORDER BY times_missed DESC""",
                    (topic["topic_id"],),
                ).fetchall()

                for row in rows:
                    concept = row["concept_text"]
                    if concept in seen_concepts:
                        continue
                    seen_concepts.add(concept)

                    error_type = row["error_type"]
                    mapping = self._REMEDIATION_MAP.get(error_type, self._REMEDIATION_MAP["omission"])
                    misconception = row["misconception"] or ""
                    framing = mapping["framing_template"].format(
                        concept=concept,
                        misconception=misconception or "unknown",
                    )
                    if misconception:
                        framing += f" Prior misconception: {misconception}"

                    directives.append({
                        "concept": concept,
                        "topic": raw,
                        "topic_canonical": canonical,
                        "error_type": error_type,
                        "misconception": misconception or None,
                        "recommended_mode": mapping["recommended_mode"],
                        "framing_hint": framing,
                        "times_missed": row["times_missed"] or 0,
                    })

            directives.sort(key=lambda d: d["times_missed"], reverse=True)
            return directives[:10]

        except Exception as exc:
            print(f"[knowledge_graph] generate_remediation_directives error: {exc}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # Mechanism-Level Transfer Validation
    # ------------------------------------------------------------------

    def get_transfer_candidates(self, n: int = 5) -> list[dict]:
        """Return concepts eligible for cross-context transfer validation.

        A concept is a transfer candidate when:
        - status = 'known'
        - times_confirmed >= 2
        - transfer_validated = 0

        Returns list of dicts:
            {concept, topic, topic_canonical, domain, times_confirmed, last_updated}
        """
        try:
            rows = self.conn.execute(
                """SELECT cm.concept_text, cm.times_confirmed, cm.last_updated,
                          t.canonical_name, t.category,
                          COALESCE(t.display_name, t.canonical_name) AS display_name
                   FROM concept_mastery cm
                   JOIN topics t ON cm.topic_id = t.topic_id
                   WHERE cm.status = 'known'
                     AND cm.times_confirmed >= 2
                     AND (cm.transfer_validated IS NULL OR cm.transfer_validated = 0)
                   ORDER BY cm.times_confirmed DESC, cm.last_updated ASC
                   LIMIT ?""",
                (n,),
            ).fetchall()

            candidates = []
            for row in rows:
                canonical = row["canonical_name"]
                cp = self._get_curriculum_priority(canonical)
                domain = cp.get("domain", row["category"] or "general") if cp else (row["category"] or "general")
                candidates.append({
                    "concept": row["concept_text"],
                    "topic": row["display_name"],
                    "topic_canonical": canonical,
                    "domain": domain,
                    "times_confirmed": row["times_confirmed"],
                    "last_updated": row["last_updated"][:10] if row["last_updated"] else None,
                })
            return candidates

        except Exception as exc:
            print(f"[knowledge_graph] get_transfer_candidates error: {exc}", file=sys.stderr)
            return []

    def log_transfer_outcome(
        self,
        concept_text: str,
        topic_name: str,
        new_context: str,
        success: bool,
    ) -> None:
        """Log the result of a transfer validation attempt.

        Parameters
        ----------
        concept_text : str
            The concept that was tested in a new context.
        topic_name : str
            The original topic the concept belongs to.
        new_context : str
            Description of the new clinical context where transfer was tested.
        success : bool
            Whether the learner correctly demonstrated the concept in the new context.
        """
        try:
            canonical = self._normalize_topic(topic_name)
            topic = self._find_topic(canonical)
            if not topic:
                print(f"[knowledge_graph] log_transfer: topic '{topic_name}' not found", file=sys.stderr)
                return

            concept_row = self.conn.execute(
                "SELECT concept_id, status FROM concept_mastery WHERE topic_id = ? AND concept_text = ?",
                (topic["topic_id"], concept_text),
            ).fetchone()

            if not concept_row:
                print(f"[knowledge_graph] log_transfer: concept '{concept_text}' not found in topic '{topic_name}'", file=sys.stderr)
                return

            now = datetime.now(timezone.utc).isoformat()
            cid = concept_row["concept_id"]

            if success:
                self.conn.execute(
                    """UPDATE concept_mastery
                       SET transfer_validated = 1,
                           times_confirmed = times_confirmed + 1,
                           last_updated = ?
                       WHERE concept_id = ?""",
                    (now, cid),
                )
                self.log_signal(
                    topic_name=topic_name,
                    source="transfer_validation",
                    signal_type="correct_recall",
                    depth_at_event=3,
                    metadata={"transfer_context": new_context, "concept": concept_text},
                )
            else:
                self.conn.execute(
                    """UPDATE concept_mastery
                       SET status = 'unknown',
                           transfer_validated = 0,
                           times_missed = times_missed + 1,
                           error_type = 'application_failure',
                           last_updated = ?
                       WHERE concept_id = ?""",
                    (now, cid),
                )
                self.log_signal(
                    topic_name=topic_name,
                    source="transfer_validation",
                    signal_type="incorrect_recall",
                    depth_at_event=3,
                    metadata={"transfer_context": new_context, "concept": concept_text},
                )
            self.conn.commit()

        except Exception as exc:
            print(f"[knowledge_graph] log_transfer_outcome error: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Spaced Verification — Review Queue
    # ------------------------------------------------------------------

    def get_review_queue(
        self,
        n: int = 5,
        domain: str | None = None,
        exclude_topics: list[str] | None = None,
    ) -> list[dict]:
        """Return concepts due for spaced verification, ranked by urgency.

        The review interval uses an expanding schedule based on confirmation
        count, with shorter intervals for concepts that have error history:

            interval_days = base * (1 + 0.3 * times_confirmed) ^ 1.5

        where base = 3 days (has error history) or 7 days (clean).

        A concept is "due" when now - last_updated > interval_days.
        Results are ranked by: overdue_ratio DESC, curriculum_priority ASC,
        times_confirmed ASC (least-confirmed first for tiebreaking).

        Parameters
        ----------
        n : int
            Maximum number of concepts to return.
        domain : str | None
            If set, only return concepts from topics in this curriculum domain.
        exclude_topics : list[str] | None
            Topic canonical names to skip (e.g., the topic currently being studied).

        Returns
        -------
        list[dict]
            Each entry: {concept, topic, topic_canonical, domain, confidence,
                         times_confirmed, times_missed, days_overdue,
                         interval_days, last_updated, error_history}
        """
        try:
            now = datetime.now(timezone.utc)
            exclude_topics = exclude_topics or []
            exclude_set = {self._normalize_topic(t) for t in exclude_topics}

            # Fetch all "known" concepts with their topic metadata
            query = """
                SELECT cm.concept_text, cm.times_confirmed, cm.times_missed,
                       cm.last_updated, cm.error_type, cm.misconception,
                       t.canonical_name, t.display_name, t.confidence, t.topic_id
                FROM concept_mastery cm
                JOIN topics t ON cm.topic_id = t.topic_id
                WHERE cm.status = 'known'
            """
            rows = self.conn.execute(query).fetchall()

            candidates = []
            for row in rows:
                canonical = row["canonical_name"]
                if canonical in exclude_set:
                    continue

                # Calculate spaced interval
                has_error_history = (row["times_missed"] or 0) > 0
                base = 3.0 if has_error_history else 7.0
                confirmed = row["times_confirmed"] or 1
                interval_days = base * (1 + 0.3 * confirmed) ** 1.5

                # Check if due
                last_updated = self._parse_ts(row["last_updated"])
                if last_updated is None:
                    continue
                days_since = (now - last_updated).total_seconds() / 86400.0
                if days_since < interval_days:
                    continue  # Not due yet

                # Overdue ratio — how far past the interval we are
                overdue_ratio = days_since / interval_days if interval_days > 0 else 999.0

                # Curriculum priority lookup
                cp = self._get_curriculum_priority(canonical)
                cur_domain = cp.get("domain", "") if cp else ""
                cur_priority = cp.get("priority", 3) if cp else 3

                # Domain filter
                if domain and cur_domain.lower() != domain.lower():
                    continue

                candidates.append({
                    "concept": row["concept_text"],
                    "topic": row["display_name"],
                    "topic_canonical": canonical,
                    "domain": cur_domain,
                    "confidence": round(row["confidence"], 3),
                    "times_confirmed": confirmed,
                    "times_missed": row["times_missed"] or 0,
                    "days_overdue": round(days_since - interval_days, 1),
                    "interval_days": round(interval_days, 1),
                    "last_updated": row["last_updated"][:10] if row["last_updated"] else "",
                    "error_history": bool(has_error_history),
                    "error_type": row["error_type"] or None,
                    "misconception": row["misconception"] or None,
                    "_overdue_ratio": overdue_ratio,
                    "_priority": cur_priority,
                })

            # Rank: most overdue first, then highest curriculum priority (1=core), then least confirmed
            candidates.sort(key=lambda c: (-c["_overdue_ratio"], c["_priority"], c["times_confirmed"]))

            # Clean internal sort keys before returning
            result = []
            for c in candidates[:n]:
                c.pop("_overdue_ratio", None)
                c.pop("_priority", None)
                result.append(c)

            return result

        except Exception as exc:
            print(f"[knowledge_graph] get_review_queue error: {exc}", file=sys.stderr)
            return []

    def _get_curriculum_priority(self, canonical_name: str) -> dict | None:
        """Look up curriculum metadata for a topic."""
        try:
            row = self.conn.execute(
                "SELECT domain, priority, pgy_target, acgme_milestone FROM curriculum_topics WHERE topic_name = ?",
                (canonical_name,),
            ).fetchone()
            if row:
                return dict(row)

            # Fuzzy match
            row = self.conn.execute(
                "SELECT domain, priority, pgy_target, acgme_milestone FROM curriculum_topics WHERE topic_name LIKE ? LIMIT 1",
                (f"%{canonical_name}%",),
            ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def close(self) -> None:
        """Close the database connection."""
        try:
            self.conn.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# SQL Schema (all tables)
# ═══════════════════════════════════════════════════════════════════════════

_SCHEMA_SQL = """
-- Core topics table
CREATE TABLE IF NOT EXISTS topics (
    topic_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name  TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    aliases         TEXT DEFAULT '[]',
    category        TEXT DEFAULT '',
    confidence      REAL DEFAULT 0.0,
    depth           INTEGER DEFAULT 0,
    encounter_count INTEGER DEFAULT 0,
    first_seen      TEXT,
    last_seen       TEXT,
    last_decay_ts   TEXT,
    curriculum_id   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_topics_canonical ON topics(canonical_name);
CREATE INDEX IF NOT EXISTS idx_topics_category ON topics(category);
CREATE INDEX IF NOT EXISTS idx_topics_confidence ON topics(confidence);

-- Signal events
CREATE TABLE IF NOT EXISTS signal_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id    INTEGER NOT NULL,
    timestamp   TEXT NOT NULL,
    source      TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    depth_at_event INTEGER DEFAULT 1,
    confidence_delta REAL DEFAULT 0.0,
    metadata    TEXT DEFAULT '{}',
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);
CREATE INDEX IF NOT EXISTS idx_events_topic ON signal_events(topic_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON signal_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_source ON signal_events(source);

-- Curriculum topics (Phase 2)
CREATE TABLE IF NOT EXISTS curriculum_topics (
    curriculum_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    domain          TEXT NOT NULL,
    subdomain       TEXT DEFAULT '',
    topic_name      TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    acgme_milestone TEXT DEFAULT '',
    priority        INTEGER DEFAULT 2,
    pgy_target      INTEGER DEFAULT 1,
    source          TEXT DEFAULT 'ABNS',
    added_ts        TEXT
);
CREATE INDEX IF NOT EXISTS idx_curriculum_domain ON curriculum_topics(domain);
CREATE INDEX IF NOT EXISTS idx_curriculum_priority ON curriculum_topics(priority);

-- Anki sync snapshots (Phase 4)
CREATE TABLE IF NOT EXISTS anki_sync_snapshots (
    snapshot_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    synced_at     TEXT NOT NULL,
    total_cards   INTEGER DEFAULT 0,
    total_reviews INTEGER DEFAULT 0,
    metadata      TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS anki_card_stats (
    stat_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id   INTEGER NOT NULL,
    anki_note_id  INTEGER NOT NULL,
    deck_name     TEXT NOT NULL,
    card_front    TEXT DEFAULT '',
    interval_days INTEGER DEFAULT 0,
    ease_factor   REAL DEFAULT 2.5,
    reps          INTEGER DEFAULT 0,
    lapses        INTEGER DEFAULT 0,
    last_review   TEXT,
    matched_topic_id INTEGER,
    FOREIGN KEY (snapshot_id) REFERENCES anki_sync_snapshots(snapshot_id),
    FOREIGN KEY (matched_topic_id) REFERENCES topics(topic_id)
);
CREATE INDEX IF NOT EXISTS idx_anki_stats_topic ON anki_card_stats(matched_topic_id);

-- Per-concept mastery dictionary (living state per topic)
CREATE TABLE IF NOT EXISTS concept_mastery (
    concept_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id      INTEGER NOT NULL,
    concept_text  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'unknown',  -- 'known' or 'unknown'
    error_type    TEXT DEFAULT '',                   -- numerical_recall, conceptual_confusion, cross_contamination, application_failure, reasoning_gap, omission
    misconception TEXT DEFAULT '',                   -- what wrong belief or confusion exists
    remediation   TEXT DEFAULT '',                   -- what teaching approach worked (or was attempted)
    times_confirmed INTEGER DEFAULT 0,
    times_missed  INTEGER DEFAULT 0,
    first_seen    TEXT NOT NULL,
    last_updated  TEXT NOT NULL,
    transfer_validated INTEGER DEFAULT 0,
    notes         TEXT DEFAULT '',
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id),
    UNIQUE(topic_id, concept_text)
);
CREATE INDEX IF NOT EXISTS idx_concept_topic ON concept_mastery(topic_id);
CREATE INDEX IF NOT EXISTS idx_concept_status ON concept_mastery(status);

-- Meta-cognitive learning patterns (accumulated across all topics)
CREATE TABLE IF NOT EXISTS learning_patterns (
    pattern_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_type  TEXT NOT NULL,                     -- e.g. 'strong_mechanistic_learner', 'cross_contamination_prone'
    description   TEXT NOT NULL,                     -- human-readable description
    evidence      TEXT DEFAULT '[]',                 -- JSON list of supporting observations
    confidence    REAL DEFAULT 0.5,                  -- how confident we are in this pattern (0-1)
    first_detected TEXT NOT NULL,
    last_updated  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_patterns_type ON learning_patterns(pattern_type);

-- Rotation schedule (Phase 5)
CREATE TABLE IF NOT EXISTS rotation_schedule (
    rotation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    rotation_name TEXT NOT NULL,
    start_date    TEXT NOT NULL,
    end_date      TEXT NOT NULL,
    category      TEXT DEFAULT '',
    notes         TEXT DEFAULT ''
);
"""


# ═══════════════════════════════════════════════════════════════════════════
# CLI Formatting Helpers
# ═══════════════════════════════════════════════════════════════════════════

_DEPTH_LABELS = {
    0: "never-seen",
    1: "surface",
    2: "mechanism",
    3: "surgical-decision",
    4: "complication-mastery",
}


def _print_status(data: dict) -> None:
    """Pretty-print the status summary."""
    if not data:
        print("No data available.")
        return

    print("=" * 60)
    print("  KNOWLEDGE GRAPH STATUS")
    print("=" * 60)
    print(f"  Total topics:  {data.get('total_topics', 0)}")
    print(f"  Total events:  {data.get('total_events', 0)}")
    print(f"  Avg confidence: {data.get('avg_confidence', 0.0):.3f}")
    print()

    # By category
    by_cat = data.get("by_category", {})
    if by_cat:
        print("  Topics by Category:")
        for cat, cnt in by_cat.items():
            print(f"    {cat:<25s} {cnt:>4d}")
        print()

    # By depth
    by_depth = data.get("by_depth", {})
    if by_depth:
        print("  Topics by Depth:")
        for key, cnt in by_depth.items():
            level = int(key.replace("depth_", ""))
            label = _DEPTH_LABELS.get(level, f"level-{level}")
            print(f"    {level} ({label:<22s}) {cnt:>4d}")
        print()

    # Recent topics
    recent = data.get("recent_topics", [])
    if recent:
        print("  Recent Topics (last 10):")
        print(f"    {'Topic':<35s} {'Conf':>6s} {'Depth':>6s}  Last Seen")
        print(f"    {'-'*35} {'-'*6} {'-'*6}  {'-'*20}")
        for t in recent:
            name = t.get("canonical_name", "?")[:35]
            conf = t.get("confidence", 0.0)
            depth = t.get("depth", 0)
            last = (t.get("last_seen") or "")[:19]
            print(f"    {name:<35s} {conf:>6.3f} {depth:>6d}  {last}")

    print("=" * 60)


def _print_topic_detail(data: dict) -> None:
    """Pretty-print topic detail."""
    if "error" in data:
        print(f"Error: {data['error']}")
        return

    topic = data.get("topic", {})
    summary = data.get("summary", {})
    events = data.get("events", [])

    print("=" * 60)
    print(f"  TOPIC: {topic.get('display_name', topic.get('canonical_name', '?'))}")
    print("=" * 60)
    print(f"  Canonical:     {topic.get('canonical_name', '')}")
    print(f"  Category:      {topic.get('category', '') or '(none)'}")
    print(f"  Confidence:    {summary.get('current_confidence', 0.0):.3f}")
    depth = summary.get("current_depth", 0)
    print(f"  Depth:         {depth} ({_DEPTH_LABELS.get(depth, '?')})")
    print(f"  Encounters:    {summary.get('total_encounters', 0)}")
    print(f"  First seen:    {(summary.get('first_seen') or '')[:19]}")
    print(f"  Last seen:     {(summary.get('last_seen') or '')[:19]}")
    aliases = json.loads(topic.get("aliases", "[]")) if topic.get("aliases") else []
    if aliases:
        print(f"  Aliases:       {', '.join(aliases)}")
    print()

    if events:
        print(f"  Signal History ({len(events)} events):")
        print(f"    {'Timestamp':<20s} {'Source':<12s} {'Signal':<22s} {'Depth':>5s} {'Delta':>7s}")
        print(f"    {'-'*20} {'-'*12} {'-'*22} {'-'*5} {'-'*7}")
        for e in events[:30]:  # cap display at 30
            ts = (e.get("timestamp") or "")[:19]
            src = (e.get("source") or "")[:12]
            sig = (e.get("signal_type") or "")[:22]
            dep = e.get("depth_at_event", 0)
            delta = e.get("confidence_delta", 0.0)
            sign = "+" if delta >= 0 else ""
            print(f"    {ts:<20s} {src:<12s} {sig:<22s} {dep:>5d} {sign}{delta:>6.3f}")
        if len(events) > 30:
            print(f"    ... and {len(events) - 30} more events")

    # Concept mastery dictionary
    cm = data.get("concept_mastery", {})
    known = cm.get("known", [])
    unknown = cm.get("unknown", [])
    if known or unknown:
        print()
        print(f"  Concept Mastery ({len(known)} known, {len(unknown)} gaps):")
        if known:
            print(f"    ✅ KNOWN:")
            for c in known:
                confirmed = c.get("times_confirmed", 0)
                print(f"       • {c['concept_text']} (confirmed {confirmed}x, last: {c.get('last_updated', '')[:10]})")
        if unknown:
            print(f"    ❌ GAPS:")
            for c in unknown:
                missed = c.get("times_missed", 0)
                line = f"       • {c['concept_text']} (missed {missed}x, last: {c.get('last_updated', '')[:10]})"
                if c.get("error_type"):
                    line += f"\n         ↳ Error type: {c['error_type']}"
                if c.get("misconception"):
                    line += f"\n         ↳ Misconception: {c['misconception']}"
                if c.get("remediation"):
                    line += f"\n         ↳ Remediation: {c['remediation']}"
                print(line)

    print("=" * 60)


# ═══════════════════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Knowledge Graph — learner topic mastery tracker",
    )
    subparsers = parser.add_subparsers(dest="command")

    # status
    subparsers.add_parser("status", help="Show knowledge graph summary")

    # topic_detail
    p_td = subparsers.add_parser("topic_detail", help="Show detail for a single topic")
    p_td.add_argument("topic", type=str, help="Topic name to look up")

    # log_event
    p_le = subparsers.add_parser("log_event", help="Log a signal event")
    p_le.add_argument("--topic", required=True, help="Topic name")
    p_le.add_argument("--source", required=True, help="Signal source (rag, bootcamp, anki, intraop, manual)")
    p_le.add_argument("--signal-type", required=True, help="Signal type")
    p_le.add_argument("--depth", type=int, default=1, help="Depth at event (0-4)")
    p_le.add_argument("--category", default="", help="Topic category")

    # log_bootcamp
    p_lb = subparsers.add_parser("log_bootcamp", help="Log bootcamp session results")
    p_lb.add_argument("--topics", required=True, help="Comma-separated topics covered")
    p_lb.add_argument("--weaknesses", default="", help="Comma-separated weaknesses identified")
    p_lb.add_argument("--module", default="", help="Bootcamp module name")
    p_lb.add_argument("--outcome", default="partial", help="Outcome: pass, partial, fail")

    # log_study_session (agent-level post-interaction signal — per-concept mastery)
    p_ls = subparsers.add_parser("log_study", help="Log per-concept learning signal (what was understood vs. missed)")
    p_ls.add_argument("--topics", required=True, help="Comma-separated topic names covered")
    p_ls.add_argument("--understood", default="", help="Comma-separated concepts the user demonstrated understanding of")
    p_ls.add_argument("--gaps", default="", help="Comma-separated concepts the user missed, got wrong, or was confused by")
    p_ls.add_argument("--gap-details", default="", help="JSON list of rich gap entries: [{\"concept\":\"...\",\"error_type\":\"...\",\"misconception\":\"...\",\"remediation\":\"...\"}]")
    p_ls.add_argument("--depth", type=int, default=1, help="Depth of material (1=surface, 2=mechanistic, 3=decision-making)")
    p_ls.add_argument("--source", default="rag", help="Capability source: rag, bootcamp, intraop")

    # log_learning_pattern (meta-cognitive pattern)
    p_lp = subparsers.add_parser("log_pattern", help="Log a meta-cognitive learning pattern")
    p_lp.add_argument("--type", required=True, dest="pattern_type", help="Pattern type: strong_mechanistic_learner, cross_contamination_prone, numerical_recall_weak, visual_spatial_strength, application_transfer_gap")
    p_lp.add_argument("--description", required=True, help="Human-readable pattern description")
    p_lp.add_argument("--evidence", default="", help="Supporting observation from this session")

    # add_topic
    p_at = subparsers.add_parser("add_topic", help="Add or update a topic")
    p_at.add_argument("--name", required=True, help="Topic name")
    p_at.add_argument("--category", default="", help="Topic category")
    p_at.add_argument("--source", default="attending-directive", help="Source for curriculum entry")
    p_at.add_argument("--priority", type=int, default=None, help="Curriculum priority (1=core, 2=important, 3=advanced)")

    # backfill
    p_bf = subparsers.add_parser("backfill", help="Backfill from telemetry log")
    p_bf.add_argument("--telemetry", required=True, help="Path to search_telemetry.jsonl")

    # load_curriculum
    load_parser = subparsers.add_parser("load_curriculum", help="Load curriculum from JSON skeleton")
    load_parser.add_argument("--path", default=str(BASE_DIR / "data" / "curriculum_skeleton.json"))

    # gaps / recommendations
    gaps_parser = subparsers.add_parser("gaps", help="Show study gap recommendations")
    gaps_parser.add_argument("--top", type=int, default=10)
    gaps_parser.add_argument("--rotation", default=None)

    # apply_decay (manual trigger)
    subparsers.add_parser("apply_decay", help="Apply forgetting-curve decay to all topics")

    # sync_anki
    sync_anki_parser = subparsers.add_parser("sync_anki", help="Sync Anki review data into knowledge graph")
    sync_anki_parser.add_argument("--url", default="http://localhost:8765")

    # dashboard (JSON for agent display)
    subparsers.add_parser("dashboard", help="Domain progress dashboard (JSON output)")

    # topics (filtered list, JSON for agent display)
    topics_parser = subparsers.add_parser("topics", help="Filtered topic list (JSON output)")
    topics_parser.add_argument("--domain", default=None, help="Filter by domain (e.g. 'Vascular')")
    topics_parser.add_argument("--min-confidence", type=float, default=None)
    topics_parser.add_argument("--max-confidence", type=float, default=None)
    topics_parser.add_argument("--depth", type=int, default=None)
    topics_parser.add_argument("--sort", default="confidence", choices=["confidence", "confidence_asc", "encounters", "recent", "alpha"])
    topics_parser.add_argument("--only-studied", action="store_true")
    topics_parser.add_argument("--limit", type=int, default=50)

    # activity (recent signal events, JSON for agent display)
    activity_parser = subparsers.add_parser("activity", help="Recent activity feed (JSON output)")
    activity_parser.add_argument("--n", type=int, default=30)

    # review_queue (spaced verification — concepts due for re-testing)
    rq_parser = subparsers.add_parser("review_queue", help="Concepts due for spaced verification (JSON output)")
    rq_parser.add_argument("--n", type=int, default=10, help="Max concepts to return")
    rq_parser.add_argument("--domain", default=None, help="Filter by curriculum domain")

    # context (prefrontal cortex — learner-aware pre-flight check)
    context_parser = subparsers.add_parser("context", help="Learner context for a query (JSON output)")
    context_parser.add_argument("query", help="The user's query to contextualize")
    context_parser.add_argument("--output", default=None, metavar="PATH",
                                help="Write JSON output to this file path in addition to stdout")

    # milestone_report
    subparsers.add_parser("milestone_report", help="ACGME milestone competency dashboard (JSON output)")

    # transfer_candidates
    tc_parser = subparsers.add_parser("transfer_candidates", help="Concepts ready for cross-context transfer validation (JSON)")
    tc_parser.add_argument("--n", type=int, default=5, help="Max candidates to return")

    # log_transfer
    lt_parser = subparsers.add_parser("log_transfer", help="Log outcome of a transfer validation attempt")
    lt_parser.add_argument("--concept", required=True, help="Concept text that was tested")
    lt_parser.add_argument("--topic", required=True, help="Original topic the concept belongs to")
    lt_parser.add_argument("--context", required=True, help="New clinical context where transfer was tested")
    lt_parser.add_argument("--success", action="store_true", help="Set if the learner succeeded")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    kg = KnowledgeGraph()

    try:
        if args.command == "status":
            data = kg.status()
            _print_status(data)

        elif args.command == "topic_detail":
            data = kg.topic_detail(args.topic)
            _print_topic_detail(data)

        elif args.command == "log_event":
            kg.log_signal(
                topic_name=args.topic,
                source=args.source,
                signal_type=args.signal_type,
                depth_at_event=args.depth,
                category=args.category,
            )
            print(f"Logged {args.signal_type} event for '{args.topic}' (source={args.source}, depth={args.depth})")

        elif args.command == "log_bootcamp":
            # Map outcome to signal type
            outcome_map = {
                "pass": "correct_recall",
                "partial": "partial_recall",
                "fail": "incorrect_recall",
            }
            signal = outcome_map.get(args.outcome.lower(), "partial_recall")
            meta = {"module": args.module, "outcome": args.outcome}

            topics = [t.strip() for t in args.topics.split(",") if t.strip()]
            weaknesses = [w.strip() for w in args.weaknesses.split(",") if w.strip()] if args.weaknesses else []

            for topic in topics:
                kg.log_signal(
                    topic_name=topic,
                    source="bootcamp",
                    signal_type=signal,
                    depth_at_event=3,
                    metadata=meta,
                )

            for weakness in weaknesses:
                kg.log_signal(
                    topic_name=weakness,
                    source="bootcamp",
                    signal_type="weakness_identified",
                    depth_at_event=3,
                    metadata=meta,
                )

            print(f"Logged {len(topics)} topic(s) and {len(weaknesses)} weakness(es) from bootcamp module '{args.module}'")

        elif args.command == "log_study":
            topics = [t.strip() for t in args.topics.split(",") if t.strip()]
            understood = [c.strip() for c in args.understood.split(",") if c.strip()] if args.understood else []
            gaps = [c.strip() for c in args.gaps.split(",") if c.strip()] if args.gaps else []
            gap_details = None
            if args.gap_details:
                try:
                    gap_details = json.loads(args.gap_details)
                except json.JSONDecodeError:
                    print("Warning: --gap-details must be valid JSON, ignoring", file=sys.stderr)
            kg.log_study_session(
                topics=topics,
                understood=understood,
                gaps=gaps,
                gap_details=gap_details,
                depth=args.depth,
                source=args.source,
            )
            n_gaps = len(gaps) + (len(gap_details) if gap_details else 0)
            print(f"Logged study session: {len(topics)} topic(s), {len(understood)} understood, {n_gaps} gap(s)")

        elif args.command == "log_pattern":
            kg.log_learning_pattern(
                pattern_type=args.pattern_type,
                description=args.description,
                evidence=args.evidence,
            )
            print(f"Logged learning pattern: {args.pattern_type}")

        elif args.command == "add_topic":
            canonical = KnowledgeGraph._normalize_topic(args.name)
            topic_id = kg._upsert_topic(canonical, args.name, args.category)

            if args.priority is not None:
                try:
                    now = datetime.now(timezone.utc).isoformat()
                    domain = args.category or "general"
                    with kg.conn:
                        kg.conn.execute(
                            """INSERT OR IGNORE INTO curriculum_topics
                               (domain, topic_name, display_name, priority, source, added_ts)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (domain, canonical, args.name, args.priority, args.source, now),
                        )
                    print(f"Added topic '{args.name}' (id={topic_id}) with curriculum priority={args.priority}, source='{args.source}'")
                except Exception as exc:
                    print(f"Topic created but curriculum entry failed: {exc}", file=sys.stderr)
            else:
                print(f"Added topic '{args.name}' (id={topic_id}, category='{args.category}')")

        elif args.command == "backfill":
            result = kg.backfill_from_telemetry(args.telemetry)
            print(f"Backfill complete: {result['topics_created']} topics created, {result['events_logged']} events logged")

        elif args.command == "load_curriculum":
            result = kg.load_curriculum(args.path)
            print(f"Curriculum loaded: {result['loaded']} topics, {result['skipped']} already existed")

        elif args.command == "gaps":
            recs = kg.generate_recommendations(n=args.top, rotation_filter=args.rotation)
            print(kg.format_recommendations(recs, rotation=args.rotation))

        elif args.command == "apply_decay":
            kg.apply_decay()
            print("Decay applied to all topics.")

        elif args.command == "sync_anki":
            result = kg.sync_anki(url=args.url)
            if result.get("status") == "unavailable":
                print(f"Anki is not available: {result.get('reason', 'unknown')}")
            elif result.get("status") == "synced":
                print(f"Anki sync complete: {result['cards']} cards, {result['matched']} matched to topics, {result['unmatched']} unmatched")
            else:
                print(f"Anki sync: {result}")

        elif args.command == "dashboard":
            data = kg.dashboard()
            print(json.dumps(data, indent=2, default=str))

        elif args.command == "topics":
            data = kg.topics_list(
                domain=args.domain,
                min_confidence=args.min_confidence,
                max_confidence=args.max_confidence,
                depth=args.depth,
                sort_by=args.sort,
                only_studied=args.only_studied,
                limit=args.limit,
            )
            print(json.dumps(data, indent=2, default=str))

        elif args.command == "activity":
            data = kg.activity_feed(n=args.n)
            print(json.dumps(data, indent=2, default=str))

        elif args.command == "review_queue":
            data = kg.get_review_queue(n=args.n, domain=args.domain)
            print(json.dumps({"due_concepts": data, "count": len(data)}, indent=2, default=str))

        elif args.command == "context":
            data = kg.learner_context(args.query)
            output_str = json.dumps(data, indent=2, default=str)
            print(output_str)
            if args.output:
                out_path = Path(args.output)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(output_str, encoding="utf-8")

        elif args.command == "milestone_report":
            data = kg.milestone_report()
            print(json.dumps(data, indent=2, default=str))

        elif args.command == "transfer_candidates":
            data = kg.get_transfer_candidates(n=args.n)
            print(json.dumps({"candidates": data, "count": len(data)}, indent=2, default=str))

        elif args.command == "log_transfer":
            kg.log_transfer_outcome(
                concept_text=args.concept,
                topic_name=args.topic,
                new_context=args.context,
                success=args.success,
            )
            outcome = "SUCCESS" if args.success else "FAILURE"
            print(f"Logged transfer {outcome}: '{args.concept}' tested in context: '{args.context}'")

    finally:
        kg.close()


if __name__ == "__main__":
    main()
