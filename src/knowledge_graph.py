#!/usr/bin/env python3
"""Knowledge Graph — tracks learner topic mastery, confidence decay, and study gaps."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kg_constants import ABBREVIATION_MAP, DATA_DIR
from kg_schema import SCHEMA_SQL
from kg_memory import KnowledgeGraphMemoryMixin
from kg_learning import KnowledgeGraphLearningMixin
from kg_signals import KnowledgeGraphSignalMixin
from kg_anki import KnowledgeGraphAnkiMixin
from kg_exports import KnowledgeGraphExportMixin

DEFAULT_DB_PATH = DATA_DIR / "knowledge_graph.db"

# Signal-type → quality weight for stability computation.
# Higher weight = stronger evidence of durable retention.
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
    """Compute stability factor for a topic from its encounter history.

    Returns a multiplier on the decay half-life in [1.0, 10.0].
    Higher stability = slower decay = longer retention.
    """
    encounter_bonus = math.log2(1 + encounter_count)
    diversity_bonus = min(1.0, signal_type_count * 0.25)
    raw = 1.0 + encounter_bonus + signal_quality_sum + diversity_bonus
    return max(1.0, min(10.0, raw))


def compute_difficulty(correct_count: int, incorrect_count: int) -> float:
    """Estimate topic difficulty from recall signal history.

    Uses a Bayesian estimate with a weak prior toward 0.5 (unknown).
    Returns difficulty in [0.1, 1.0]. Higher = harder.
    """
    total = correct_count + incorrect_count + 2  # +2 pseudo-observations
    error_rate = (incorrect_count + 1) / total
    return max(0.1, min(1.0, error_rate))


def _is_duplicate_column_error(exc: sqlite3.OperationalError) -> bool:
    """Return True when SQLite reports an idempotent ADD COLUMN collision."""
    return "duplicate column name" in str(exc).lower()


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

# Canonical ACGME domain names — the single source of truth for category values.
# All categories written to the DB should be one of these or empty string.
CANONICAL_DOMAINS: set[str] = {
    "Vascular Neurological Surgery",
    "Traumatic Brain Injury",
    "Critical Care",
    "Brain Tumor",
    "Medical Knowledge \u2014 Neuroanatomy and Neuroimaging",
    "Spinal Neurological Surgery",
    "Pediatric Neurological Surgery",
    "Surgical Treatment of Epilepsy and Movement Disorders",
    "Medical Knowledge \u2014 Neurosciences, Neuropathology, and Neurology",
    "Pain and Peripheral Nerve Disorders",
    "Anatomy",
}

# Legacy category → canonical domain normalization
_CATEGORY_NORMALIZE: dict[str, str] = {
    "vascular": "Vascular Neurological Surgery",
    "vascular_neurological_surgery": "Vascular Neurological Surgery",
    "spine": "Spinal Neurological Surgery",
    "spinal_neurological_surgery": "Spinal Neurological Surgery",
    "tumor_(neuro-oncology)": "Brain Tumor",
    "brain_tumor": "Brain Tumor",
    "tumor": "Brain Tumor",
    "trauma": "Traumatic Brain Injury",
    "traumatic_brain_injury": "Traumatic Brain Injury",
    "critical_care": "Critical Care",
    "critical_care_and_general_neurosurgery": "Critical Care",
    "pediatric": "Pediatric Neurological Surgery",
    "pediatric_neurological_surgery": "Pediatric Neurological Surgery",
    "functional_and_stereotactic": "Surgical Treatment of Epilepsy and Movement Disorders",
    "functional": "Surgical Treatment of Epilepsy and Movement Disorders",
    "surgical_treatment_of_epilepsy_and_movement_disorders": "Surgical Treatment of Epilepsy and Movement Disorders",
    "pain_and_peripheral_nerve_disorders": "Pain and Peripheral Nerve Disorders",
    "medical_knowledge_\u2014_neuroanatomy_and_neuroimaging": "Medical Knowledge \u2014 Neuroanatomy and Neuroimaging",
    "medical_knowledge_\u2014_neurosciences,_neuropathology,_and_neurology": "Medical Knowledge \u2014 Neurosciences, Neuropathology, and Neurology",
    "Anatomy": "Anatomy",
}

# Keyword → canonical domain for category inference on new topics.
# Checked in order; first match wins. More specific patterns first.
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Vascular Neurological Surgery", [
        "aneurysm", "acha", "anterior choroidal artery", "vasospasm",
        "subarachnoid hemorrhage", "clipping", "coiling", "flow diversion",
        "circle of willis", "endothelin", "nimodipine", "cavernous malformation",
        "arteriovenous malformation", "dural av fistula", "endovascular",
    ]),
    ("Traumatic Brain Injury", [
        "traumatic brain injury", "epidural hematoma", "subdural hematoma",
        "decompressive craniectomy", "secondary injury",
    ]),
    ("Critical Care", [
        "intracranial pressure", "cerebral perfusion pressure", "neurocritical",
        "antihypertensive", "hypertensive encephalopathy", "autonomic dysreflexia",
        "osmotherapy", "mannitol",
    ]),
    ("Brain Tumor", [
        "meningioma", "glioma", "glioblastoma", "temozolomide", "tumor",
        "pituitary adenoma", "craniotomy",
    ]),
    ("Medical Knowledge \u2014 Neuroanatomy and Neuroimaging", [
        "internal capsule", "basal ganglia", "thalamus", "hippocampus",
        "papez circuit", "fornix", "cingulum", "limbic", "brainstem",
        "cranial nerve", "somatotopic",
    ]),
    ("Spinal Neurological Surgery", [
        "cervical", "lumbar", "thoracic", "spondylolisthesis", "laminectomy",
        "disc herniation", "syringomyelia", "chiari",
    ]),
    ("Pediatric Neurological Surgery", [
        "hydrocephalus", "ventriculoperitoneal shunt", "external ventricular drain",
    ]),
    ("Surgical Treatment of Epilepsy and Movement Disorders", [
        "deep brain stimulation", "capsulotomy", "responsive neurostimulation",
    ]),
]

# Maximum topic name length. Longer strings are likely sentences, not topics.
_MAX_TOPIC_LENGTH = 120

# Stopwords stripped from token-overlap matching
_TOPIC_STOPWORDS: set[str] = {
    "the", "a", "an", "and", "or", "of", "in", "for", "to", "with",
    "is", "are", "was", "were", "by", "on", "at", "from", "after",
    "these", "this", "that", "how", "what", "does", "do", "target",
    "management", "treatment", "surgical", "clinical",
}


# ---------------------------------------------------------------------------
# Compact recall merge (memory_guidance hybrid path)
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# KnowledgeGraph
# ---------------------------------------------------------------------------

class KnowledgeGraph(KnowledgeGraphSignalMixin, KnowledgeGraphLearningMixin, KnowledgeGraphMemoryMixin, KnowledgeGraphAnkiMixin, KnowledgeGraphExportMixin):
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

    def _run_migration(self, sql: str) -> None:
        """Run one idempotent schema migration."""
        try:
            self.conn.execute(sql)
            self.conn.commit()
        except sqlite3.OperationalError as exc:
            if _is_duplicate_column_error(exc):
                return
            raise

    def _run_migrations(self, statements: list[str]) -> None:
        """Run idempotent schema migrations in order."""
        for sql in statements:
            self._run_migration(sql)

    def _run_migration_script(self, sql: str) -> None:
        """Run an idempotent schema script."""
        self.conn.executescript(sql)
        self.conn.commit()

    def _init_db(self) -> None:
        """Create all tables and indexes if they don't exist."""
        try:
            with self.conn:
                self.conn.executescript(SCHEMA_SQL)
            # ── Schema migrations — safe to re-run (idempotent) ──

            self._run_migrations([
                "ALTER TABLE topics ADD COLUMN clinical_context TEXT DEFAULT ''",
                "ALTER TABLE topics ADD COLUMN specificity_level INTEGER DEFAULT 1",
                "ALTER TABLE topics ADD COLUMN parent_topic TEXT DEFAULT ''",
                "ALTER TABLE topics ADD COLUMN stability_factor REAL DEFAULT 1.0",
                "ALTER TABLE topics ADD COLUMN difficulty REAL DEFAULT 0.5",
            ])

            self._run_migrations([
                "ALTER TABLE concept_mastery ADD COLUMN transfer_validated INTEGER DEFAULT 0",
                "ALTER TABLE concept_mastery ADD COLUMN next_review_due TEXT DEFAULT NULL",
                "ALTER TABLE concept_mastery ADD COLUMN review_interval_days REAL DEFAULT 1.0",
                "ALTER TABLE concept_mastery ADD COLUMN ease_factor REAL DEFAULT 2.5",
                "ALTER TABLE concept_mastery ADD COLUMN root_cause TEXT DEFAULT ''",
                "ALTER TABLE concept_mastery ADD COLUMN error_process TEXT DEFAULT ''",
                "ALTER TABLE concept_mastery ADD COLUMN teaching_notes TEXT DEFAULT ''",
            ])

            self._run_migration(
                "ALTER TABLE concept_mastery ADD COLUMN concept_confidence REAL DEFAULT 0.0"
            )

            self._run_migrations([
                "ALTER TABLE session_narratives ADD COLUMN session_success_rate REAL DEFAULT NULL",
                "ALTER TABLE session_narratives ADD COLUMN strategy_outcome TEXT DEFAULT ''",
            ])

            self._run_migration(
                "ALTER TABLE session_narratives ADD COLUMN topic_fingerprint TEXT DEFAULT ''"
            )

            self._run_migrations([
                "ALTER TABLE learning_exchanges ADD COLUMN consolidated_at TEXT DEFAULT NULL",
                "ALTER TABLE learning_exchanges ADD COLUMN memory_event_id INTEGER DEFAULT NULL",
                "ALTER TABLE learning_exchanges ADD COLUMN dedupe_key TEXT DEFAULT ''",
                "ALTER TABLE episode_summaries ADD COLUMN source_exchange_ids TEXT DEFAULT '[]'",
                "ALTER TABLE episode_summaries ADD COLUMN source_memory_event_ids TEXT DEFAULT '[]'",
                "ALTER TABLE episode_summaries ADD COLUMN memory_hash TEXT DEFAULT ''",
                "ALTER TABLE episode_summaries ADD COLUMN dedupe_key TEXT DEFAULT ''",
                "ALTER TABLE concept_evolution ADD COLUMN trigger_memory_event_id INTEGER DEFAULT NULL",
            ])

            self._run_migrations([
                "CREATE INDEX IF NOT EXISTS idx_xchg_consolidated ON learning_exchanges(consolidated_at)",
                "CREATE INDEX IF NOT EXISTS idx_episode_session_skill ON episode_summaries(session_ts, skill)",
            ])

            self._run_migration_script("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    entity_type UNINDEXED,
                    entity_id UNINDEXED,
                    session_ts UNINDEXED,
                    skill UNINDEXED,
                    topic_text,
                    concept_text,
                    question_text,
                    answer_text,
                    correction_text,
                    misconception,
                    root_cause,
                    summary_text,
                    event_text,
                    payload_text
                );
            """)

            self._run_migration(
                """UPDATE learning_exchanges
                   SET consolidated_at = COALESCE(consolidated_at, session_ts)
                   WHERE consolidated_at IS NULL
                     AND lance_row_id IS NOT NULL
                     AND lance_row_id != ''"""
            )

        except Exception as exc:
            print(f"[knowledge_graph] schema init error: {exc}", file=sys.stderr)
            raise

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

    @staticmethod
    def _normalize_category(category: str) -> str:
        """Normalize a category string to a canonical ACGME domain name."""
        if not category:
            return ""
        if category in CANONICAL_DOMAINS:
            return category
        return _CATEGORY_NORMALIZE.get(category, category)

    @staticmethod
    def _infer_category(display_name: str) -> str:
        """Infer category from topic name keywords. Returns canonical domain or ''."""
        name_lower = display_name.lower()
        for domain, keywords in _CATEGORY_KEYWORDS:
            for kw in keywords:
                if kw in name_lower:
                    return domain
        return ""

    @staticmethod
    def _topic_tokens(name: str) -> set[str]:
        """Extract meaningful tokens from a topic name for similarity matching."""
        tokens = set(re.split(r"[\s\-_(),:;/]+", name.lower()))
        return tokens - _TOPIC_STOPWORDS - {""}

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _find_topic(self, canonical_name: str) -> dict | None:
        """Look up by canonical_name, then aliases, then substring LIKE match."""
        try:
            canonical_name = (canonical_name or "").strip()
            if not canonical_name:
                return None

            # Exact canonical match
            row = self.conn.execute(
                "SELECT * FROM topics WHERE canonical_name = ?", (canonical_name,)
            ).fetchone()
            if row:
                return dict(row)

            escaped = self._escape_like(canonical_name)

            # Alias match (JSON string contains exact alias token)
            row = self.conn.execute(
                """SELECT * FROM topics
                   WHERE aliases LIKE ? ESCAPE '\\'
                   ORDER BY encounter_count DESC
                   LIMIT 1""",
                (f'%"{escaped}"%',),
            ).fetchone()
            if row:
                return dict(row)

            # Substring LIKE match (handles "vasospasm" finding
            # "cerebral vasospasm after SAH") with tighter ranking.
            if len(canonical_name) >= 4:
                rows = self.conn.execute(
                    """SELECT * FROM topics
                       WHERE canonical_name LIKE ? ESCAPE '\\'
                       ORDER BY ABS(LENGTH(canonical_name) - ?) ASC, encounter_count DESC
                       LIMIT 5""",
                    (f"%{escaped}%", len(canonical_name)),
                ).fetchall()
                if rows:
                    boundary_pat = re.compile(
                        rf"(?<![a-z0-9]){re.escape(canonical_name)}(?![a-z0-9])"
                    )
                    for r in rows:
                        cname = (r["canonical_name"] or "").lower()
                        if boundary_pat.search(cname):
                            return dict(r)
                    return dict(rows[0])

            # Reverse containment only for longer canonical names to reduce
            # accidental collisions on short generic tokens.
            if len(canonical_name) >= 8:
                row = self.conn.execute(
                    """SELECT * FROM topics
                       WHERE ? LIKE '%' || canonical_name || '%'
                       ORDER BY LENGTH(canonical_name) DESC, encounter_count DESC
                       LIMIT 1""",
                    (canonical_name,),
                ).fetchone()
                if row:
                    return dict(row)

            # Token-overlap matching — catches near-duplicates like
            # "cerebral vasospasm pathophysiology and management" vs
            # "cerebral vasospasm pathophysiology diagnosis".
            # Only runs for multi-word topics to avoid false positives.
            input_tokens = self._topic_tokens(canonical_name)
            if len(input_tokens) >= 3:
                # Fetch studied topics (encounter_count > 0) as candidates
                candidates = self.conn.execute(
                    "SELECT * FROM topics WHERE encounter_count > 0 ORDER BY encounter_count DESC"
                ).fetchall()
                best, best_score = None, 0.0
                for cand in candidates:
                    cand_tokens = self._topic_tokens(cand["canonical_name"])
                    if not cand_tokens:
                        continue
                    overlap = input_tokens & cand_tokens
                    shorter = min(len(input_tokens), len(cand_tokens))
                    if shorter < 2:
                        continue
                    score = len(overlap) / shorter
                    if score > best_score and score >= 0.70 and len(overlap) >= 2:
                        best_score = score
                        best = cand
                if best:
                    return dict(best)

            return None
        except Exception as exc:
            print(f"[knowledge_graph] _find_topic error: {exc}", file=sys.stderr)
            return None

    def _lookup_curriculum_id(self, canonical_name: str, display_name: str = "") -> int | None:
        """Return curriculum_id for a canonical topic name, or None if not in curriculum.

        Tries three strategies:
        1. Exact match on topic_name (snake_case key)
        2. Normalized match: underscores→spaces on both sides
        3. Case-insensitive display_name match
        """
        # Strategy 1: exact topic_name match
        row = self.conn.execute(
            "SELECT curriculum_id FROM curriculum_topics WHERE LOWER(topic_name) = ?",
            (canonical_name,),
        ).fetchone()
        if row:
            return row["curriculum_id"]

        # Strategy 2: normalized match (underscores/hyphens → spaces)
        import re
        normalized = re.sub(r"[_\-]+", " ", canonical_name).strip().lower()
        row = self.conn.execute(
            "SELECT curriculum_id FROM curriculum_topics WHERE LOWER(REPLACE(REPLACE(topic_name, '_', ' '), '-', ' ')) = ?",
            (normalized,),
        ).fetchone()
        if row:
            return row["curriculum_id"]

        # Strategy 3: display_name match
        if display_name:
            row = self.conn.execute(
                "SELECT curriculum_id FROM curriculum_topics WHERE LOWER(display_name) = ?",
                (display_name.strip().lower(),),
            ).fetchone()
            if row:
                return row["curriculum_id"]

        return None

    def _upsert_topic(self, canonical_name: str, display_name: str, category: str = "") -> int:
        """Find or create a topic. Returns topic_id.

        Applies three data-quality guards:
        1. Truncates sentence-length topics (>_MAX_TOPIC_LENGTH) to prevent
           full sentences from becoming topic names.
        2. Normalizes category to canonical ACGME domain names.
        3. Infers category from keywords when not provided.
        """
        try:
            # Guard: truncate sentence-length topic names
            if len(canonical_name) > _MAX_TOPIC_LENGTH:
                canonical_name = canonical_name[:_MAX_TOPIC_LENGTH].rsplit(" ", 1)[0]
                display_name = display_name[:_MAX_TOPIC_LENGTH].rsplit(" ", 1)[0]

            # Normalize category
            category = self._normalize_category(category)

            existing = self._find_topic(canonical_name)
            if existing:
                updates: list[str] = []
                params: list = []

                # Add display_name as alias if different from canonical
                if display_name.lower() != canonical_name:
                    aliases = json.loads(existing["aliases"]) if existing["aliases"] else []
                    norm_display = display_name.strip().lower()
                    if norm_display not in aliases and norm_display != canonical_name:
                        aliases.append(norm_display)
                        updates.append("aliases = ?")
                        params.append(json.dumps(aliases))

                # Back-fill curriculum_id if missing
                if existing["curriculum_id"] is None:
                    cid = self._lookup_curriculum_id(canonical_name, display_name)
                    if cid is not None:
                        updates.append("curriculum_id = ?")
                        params.append(cid)

                # Back-fill category if missing
                if not existing["category"] and category:
                    updates.append("category = ?")
                    params.append(category)
                elif not existing["category"]:
                    inferred = self._infer_category(display_name)
                    if inferred:
                        updates.append("category = ?")
                        params.append(inferred)

                if updates:
                    params.append(existing["topic_id"])
                    with self.conn:
                        self.conn.execute(
                            f"UPDATE topics SET {', '.join(updates)} WHERE topic_id = ?",
                            params,
                        )
                return existing["topic_id"]

            # Insert new topic — resolve curriculum_id at creation time
            curriculum_id = self._lookup_curriculum_id(canonical_name, display_name)
            now = datetime.now(timezone.utc).isoformat()
            aliases: list[str] = []
            norm_display = display_name.strip().lower()
            if norm_display != canonical_name:
                aliases.append(norm_display)

            # Infer category if not provided
            if not category:
                category = self._infer_category(display_name)
                # Also try curriculum domain if we found a curriculum_id
                if not category and curriculum_id:
                    cur_row = self.conn.execute(
                        "SELECT domain FROM curriculum_topics WHERE curriculum_id = ?",
                        (curriculum_id,),
                    ).fetchone()
                    if cur_row:
                        category = cur_row["domain"]

            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO topics
                       (canonical_name, display_name, aliases, category,
                        confidence, depth, encounter_count, first_seen, last_seen,
                        curriculum_id)
                       VALUES (?, ?, ?, ?, 0.0, 0, 0, ?, ?, ?)""",
                    (canonical_name, display_name, json.dumps(aliases), category, now, now,
                     curriculum_id),
                )
                return int(cur.lastrowid or -1)
        except Exception as exc:
            print(f"[knowledge_graph] _upsert_topic error: {exc}", file=sys.stderr)
            return -1

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

    def _update_stability(self, topic_id: int) -> None:
        """Recompute stability_factor and difficulty for a topic from its signal history."""
        row = self.conn.execute(
            "SELECT encounter_count FROM topics WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()
        if not row:
            return

        signals = self.conn.execute(
            "SELECT signal_type, COUNT(*) as cnt FROM signal_events "
            "WHERE topic_id = ? GROUP BY signal_type",
            (topic_id,),
        ).fetchall()

        quality_sum = 0.0
        distinct_types = 0
        correct_count = 0
        incorrect_count = 0

        for sig in signals:
            st = sig["signal_type"]
            cnt = sig["cnt"]
            quality_sum += SIGNAL_QUALITY_WEIGHTS.get(st, 0.0) * cnt
            distinct_types += 1
            if st in ("correct_recall", "drill"):
                correct_count += cnt
            elif st in ("incorrect_recall", "weakness_identified"):
                incorrect_count += cnt

        stability = compute_stability(row["encounter_count"], quality_sum, distinct_types)
        difficulty = compute_difficulty(correct_count, incorrect_count)

        with self.conn:
            self.conn.execute(
                "UPDATE topics SET stability_factor = ?, difficulty = ? WHERE topic_id = ?",
                (stability, difficulty, topic_id),
            )

    def apply_decay(self, topic_id: int = None) -> None:
        """Apply stability-weighted forgetting-curve decay to topic confidence.

        Half-life formula:
            half_life_hours = 48 * (2 ** max(0, depth - 1)) * stability_factor

        stability_factor is computed from encounter history, signal quality,
        and signal diversity.  Topics with more high-quality encounters decay
        much slower.
        """
        try:
            now = datetime.now(timezone.utc)
            if topic_id is not None:
                rows = self.conn.execute(
                    "SELECT topic_id, confidence, depth, last_decay_ts, last_seen, "
                    "       stability_factor FROM topics WHERE topic_id = ?",
                    (topic_id,),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT topic_id, confidence, depth, last_decay_ts, last_seen, "
                    "       stability_factor FROM topics"
                ).fetchall()

            for row in rows:
                tid = row["topic_id"]
                old_confidence = row["confidence"]
                depth = row["depth"]
                stability = row["stability_factor"] if row["stability_factor"] else 1.0

                # Determine reference timestamp
                ref_ts = self._parse_ts(row["last_decay_ts"]) or self._parse_ts(row["last_seen"])
                if ref_ts is None:
                    continue

                hours_since = (now - ref_ts).total_seconds() / 3600
                if hours_since <= 1:
                    continue  # skip if decayed recently

                half_life_hours = 48 * (2 ** max(0, depth - 1)) * stability
                decay_factor = 0.5 ** (hours_since / half_life_hours)
                new_confidence = max(0.0, min(1.0, old_confidence * decay_factor))

                with self.conn:
                    self.conn.execute(
                        "UPDATE topics SET confidence = ?, last_decay_ts = ? WHERE topic_id = ?",
                        (new_confidence, now.isoformat(), tid),
                    )
        except Exception as exc:
            print(f"[knowledge_graph] apply_decay error: {exc}", file=sys.stderr)

        # Also run concept-level SRS decay
        self._apply_concept_srs_decay()

    def _apply_concept_srs_decay(self) -> None:
        """Mark 'known' concepts whose next_review_due has passed as 'due'.

        'due' is a new intermediate status: the concept was known but hasn't
        been verified since its scheduled review date.  It will appear in
        concept_review_queue() before 'unknown' concepts, signalling that
        a quick recall check — not re-teaching — is needed.

        Round 3 addition: also pull forward SM-2 review for 'known' concepts
        whose concept_confidence has fallen below 0.35. These are concepts that
        were once confirmed but have since been missed — the SM-2 schedule may
        not yet reflect this weakness. Halving review_interval_days ensures they
        resurface before the full SM-2 interval elapses.

        Each status transition (known → due) is recorded in concept_evolution
        so that the audit trail reflects silent decay, not only active testing.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()

            # ── SM-2 schedule decay ──
            # Capture affected rows BEFORE the bulk UPDATE so we can log each transition.
            srs_due = self.conn.execute(
                """SELECT concept_id, topic_id, times_confirmed, times_missed,
                          concept_confidence
                   FROM concept_mastery
                   WHERE status = 'known'
                     AND next_review_due IS NOT NULL
                     AND next_review_due < ?""",
                (now,),
            ).fetchall()

            with self.conn:
                self.conn.execute(
                    """UPDATE concept_mastery
                       SET status = 'due'
                       WHERE status = 'known'
                         AND next_review_due IS NOT NULL
                         AND next_review_due < ?""",
                    (now,),
                )

            for row in srs_due:
                self.log_concept_evolution(
                    concept_id=row["concept_id"],
                    topic_id=row["topic_id"],
                    new_status="due",
                    trigger_type="decay",
                    previous_status="known",
                    times_confirmed=row["times_confirmed"] or 0,
                    times_missed=row["times_missed"] or 0,
                    evolution_note="Concept transitioned known -> due: SRS review interval elapsed",
                )

            # ── Confidence-coupled decay ──
            # concept_confidence > 0.0 guard: skips legacy rows never given a score
            conf_due = self.conn.execute(
                """SELECT concept_id, topic_id, times_confirmed, times_missed,
                          concept_confidence
                   FROM concept_mastery
                   WHERE status = 'known'
                     AND concept_confidence IS NOT NULL
                     AND concept_confidence > 0.0
                     AND concept_confidence < 0.35""",
            ).fetchall()

            with self.conn:
                self.conn.execute(
                    """UPDATE concept_mastery
                       SET status = 'due',
                           review_interval_days = MAX(1.0, review_interval_days * 0.5)
                       WHERE status = 'known'
                         AND concept_confidence IS NOT NULL
                         AND concept_confidence > 0.0
                         AND concept_confidence < 0.35""",
                )

            for row in conf_due:
                cc = row["concept_confidence"] or 0.0
                self.log_concept_evolution(
                    concept_id=row["concept_id"],
                    topic_id=row["topic_id"],
                    new_status="due",
                    trigger_type="decay",
                    previous_status="known",
                    times_confirmed=row["times_confirmed"] or 0,
                    times_missed=row["times_missed"] or 0,
                    evolution_note=f"Concept transitioned known -> due: confidence below threshold (cc={cc:.2f})",
                )

        except Exception as exc:
            print(f"[knowledge_graph] _apply_concept_srs_decay error: {exc}", file=sys.stderr)

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

    def generate_recommendations(
        self,
        n: int = 10,
        rotation_filter: str = None,
        apply_decay_first: bool = False,
    ) -> list[dict]:
        """Core gap detection: decay all topics, score curriculum gaps, return top N.

        Returns a list of dicts with curriculum info, learner info, gap_score,
        and gap_type.
        """
        try:
            # Optional state refresh for CLI workflows that expect decay now.
            if apply_decay_first:
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

            # Per-domain breakdown — single aggregated query instead of N+1
            domains = []
            domain_agg = self.conn.execute(
                """SELECT ct.domain,
                          COUNT(DISTINCT ct.curriculum_id) AS total,
                          COUNT(DISTINCT CASE WHEN t.encounter_count > 0 THEN ct.curriculum_id END) AS encountered,
                          AVG(CASE WHEN t.encounter_count > 0 THEN t.confidence END) AS avg_conf
                   FROM curriculum_topics ct
                   LEFT JOIN topics t ON t.curriculum_id = ct.curriculum_id
                   GROUP BY ct.domain ORDER BY ct.domain"""
            ).fetchall()

            # Depth distribution per domain (one query)
            depth_all = self.conn.execute(
                """SELECT ct.domain, t.depth, COUNT(*) AS cnt
                   FROM curriculum_topics ct
                   JOIN topics t ON t.curriculum_id = ct.curriculum_id
                   GROUP BY ct.domain, t.depth"""
            ).fetchall()
            depth_by_domain = defaultdict(dict)
            for r in depth_all:
                depth_by_domain[r["domain"]][r["depth"]] = r["cnt"]

            # Strongest/weakest per domain (two queries total instead of 2*N)
            strongest_all = self.conn.execute(
                """SELECT ct.domain, t.canonical_name, t.confidence,
                          ROW_NUMBER() OVER (PARTITION BY ct.domain ORDER BY t.confidence DESC) AS rn
                   FROM curriculum_topics ct
                   JOIN topics t ON t.curriculum_id = ct.curriculum_id
                   WHERE t.encounter_count > 0"""
            ).fetchall()
            strongest_by_domain = {}
            weakest_by_domain = {}
            # Also collect weakest from same data
            weakest_all = self.conn.execute(
                """SELECT ct.domain, t.canonical_name, t.confidence,
                          ROW_NUMBER() OVER (PARTITION BY ct.domain ORDER BY t.confidence ASC) AS rn
                   FROM curriculum_topics ct
                   JOIN topics t ON t.curriculum_id = ct.curriculum_id
                   WHERE t.encounter_count > 0"""
            ).fetchall()
            for r in strongest_all:
                if r["rn"] == 1:
                    strongest_by_domain[r["domain"]] = {"name": r["canonical_name"], "confidence": r["confidence"]}
            for r in weakest_all:
                if r["rn"] == 1:
                    weakest_by_domain[r["domain"]] = {"name": r["canonical_name"], "confidence": r["confidence"]}

            for dr in domain_agg:
                domain = dr["domain"]
                total = dr["total"]
                encountered = dr["encountered"]
                avg_d = round(dr["avg_conf"], 3) if dr["avg_conf"] is not None else 0.0
                domains.append({
                    "domain": domain,
                    "total": total,
                    "encountered": encountered,
                    "coverage_pct": round(100 * encountered / total, 1) if total else 0,
                    "avg_confidence": avg_d,
                    "depth_distribution": depth_by_domain.get(domain, {}),
                    "strongest": strongest_by_domain.get(domain),
                    "weakest": weakest_by_domain.get(domain),
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

    def close(self) -> None:
        """Close the database connection."""
        try:
            self.conn.close()
        except Exception:
            pass

_DEPTH_LABELS = {
    0: "never-seen",
    1: "surface",
    2: "mechanism",
    3: "surgical-decision",
    4: "complication-mastery",
}

if __name__ == "__main__":
    from knowledge_graph_cli import main

    main()
