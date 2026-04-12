#!/usr/bin/env python3
"""Knowledge Graph — tracks learner topic mastery, confidence decay, and study gaps."""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
from collections import defaultdict
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
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_topics_canonical_name ON topics(canonical_name)"
                )
            # ── Schema migrations — safe to re-run (idempotent) ──

            # concept_mastery.transfer_validated (original)
            try:
                self.conn.execute(
                    "ALTER TABLE concept_mastery ADD COLUMN transfer_validated INTEGER DEFAULT 0"
                )
                self.conn.commit()
            except Exception:
                pass

            # document_sessions table (post-initial-release)
            try:
                self.conn.execute(
                    """CREATE TABLE IF NOT EXISTS document_sessions (
                        doc_id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        doc_path            TEXT NOT NULL UNIQUE,
                        doc_type            TEXT NOT NULL DEFAULT 'unknown',
                        session_count       INTEGER DEFAULT 0,
                        first_studied       TEXT,
                        last_studied        TEXT,
                        total_concepts      INTEGER DEFAULT 0,
                        concepts_covered    TEXT DEFAULT '[]',
                        concepts_understood TEXT DEFAULT '[]',
                        concepts_missed     TEXT DEFAULT '[]',
                        coverage_pct        REAL DEFAULT 0.0,
                        session_notes       TEXT DEFAULT ''
                    )"""
                )
                self.conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_doc_sessions_path ON document_sessions(doc_path)"
                )
                self.conn.commit()
            except Exception:
                pass

            # ── Redesign Phase: new columns on topics ──
            for col_sql in [
                "ALTER TABLE topics ADD COLUMN clinical_context TEXT DEFAULT ''",
                "ALTER TABLE topics ADD COLUMN specificity_level INTEGER DEFAULT 1",
                "ALTER TABLE topics ADD COLUMN parent_topic TEXT DEFAULT ''",
                "ALTER TABLE topics ADD COLUMN stability_factor REAL DEFAULT 1.0",
                "ALTER TABLE topics ADD COLUMN difficulty REAL DEFAULT 0.5",
            ]:
                try:
                    self.conn.execute(col_sql)
                    self.conn.commit()
                except Exception:
                    pass

            # ── Redesign Phase: new columns on concept_mastery ──
            for col_sql in [
                "ALTER TABLE concept_mastery ADD COLUMN next_review_due TEXT DEFAULT NULL",
                "ALTER TABLE concept_mastery ADD COLUMN review_interval_days REAL DEFAULT 1.0",
                "ALTER TABLE concept_mastery ADD COLUMN ease_factor REAL DEFAULT 2.5",
                "ALTER TABLE concept_mastery ADD COLUMN root_cause TEXT DEFAULT ''",
                "ALTER TABLE concept_mastery ADD COLUMN error_process TEXT DEFAULT ''",
                "ALTER TABLE concept_mastery ADD COLUMN teaching_notes TEXT DEFAULT ''",
            ]:
                try:
                    self.conn.execute(col_sql)
                    self.conn.commit()
                except Exception:
                    pass

            # ── Iteration 1: concept_confidence (partial mastery, 0.0–1.0) ──
            try:
                self.conn.execute(
                    "ALTER TABLE concept_mastery ADD COLUMN concept_confidence REAL DEFAULT 0.0"
                )
                self.conn.commit()
            except Exception:
                pass

            # ── Iteration 3: ZPD tracking on session_narratives ──
            for col_sql in [
                "ALTER TABLE session_narratives ADD COLUMN session_success_rate REAL DEFAULT NULL",
                "ALTER TABLE session_narratives ADD COLUMN strategy_outcome TEXT DEFAULT ''",
            ]:
                try:
                    self.conn.execute(col_sql)
                    self.conn.commit()
                except Exception:
                    pass

            # ── Round 3: topic_fingerprint for overlap-based narrative retrieval ──
            try:
                self.conn.execute(
                    "ALTER TABLE session_narratives ADD COLUMN topic_fingerprint TEXT DEFAULT ''"
                )
                self.conn.commit()
            except Exception:
                pass

            # ── Iteration 4: topic_adjacency for blind spot detection ──
            try:
                self.conn.executescript("""
                    CREATE TABLE IF NOT EXISTS topic_adjacency (
                        adj_id             INTEGER PRIMARY KEY AUTOINCREMENT,
                        topic_a            TEXT NOT NULL,
                        topic_b            TEXT NOT NULL,
                        domain             TEXT DEFAULT '',
                        adjacency_strength REAL DEFAULT 0.5,
                        source             TEXT DEFAULT '',
                        created_ts         TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_adj_a ON topic_adjacency(topic_a);
                    CREATE INDEX IF NOT EXISTS idx_adj_b ON topic_adjacency(topic_b);
                """)
                self.conn.commit()
            except Exception:
                pass

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
                    self._update_stability(topic_id)
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
                self._update_stability(tid)

                # ── Upsert concept mastery dictionary ──
                now_dt = self._parse_ts(now) or datetime.now(timezone.utc)
                for concept in understood:
                    concept_clean = concept.strip().lower()
                    if not concept_clean:
                        continue
                    existing = self.conn.execute(
                        """SELECT concept_id, status, times_confirmed, times_missed,
                                  ease_factor, review_interval_days,
                                  concept_confidence, teaching_notes,
                                  root_cause, error_process, remediation
                           FROM concept_mastery WHERE topic_id = ? AND concept_text = ?""",
                        (tid, concept_clean),
                    ).fetchone()
                    if existing:
                        # SM-2 on confirm: interval *= ease_factor; ef += 0.1 (cap 2.5)
                        old_ef = existing["ease_factor"] if existing["ease_factor"] is not None else 2.5
                        old_interval = existing["review_interval_days"] if existing["review_interval_days"] is not None else 1.0
                        new_ef = min(2.5, old_ef + 0.1)
                        new_interval = old_interval * new_ef
                        next_due = (now_dt + timedelta(days=new_interval)).isoformat()
                        # Iteration 1: update concept_confidence (continuous partial-mastery score)
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
                        # Auto-populate teaching_notes when concept first transitions unknown→known
                        if was_unknown and not (existing.get("teaching_notes") or "").strip():
                            self._auto_populate_teaching_notes(
                                concept_id=existing["concept_id"],
                                root_cause=existing.get("root_cause") or "",
                                error_process=existing.get("error_process") or "",
                                remediation=existing.get("remediation") or "",
                                session_date=now[:10],
                            )
                    else:
                        # First confirmation: interval = 1 day * 2.5 = 2.5 days
                        new_interval = 2.5
                        next_due = (now_dt + timedelta(days=new_interval)).isoformat()
                        self.conn.execute(
                            """INSERT INTO concept_mastery
                               (topic_id, concept_text, status, times_confirmed, times_missed,
                                ease_factor, review_interval_days, next_review_due,
                                concept_confidence, first_seen, last_updated)
                               VALUES (?, ?, 'known', 1, 0, 2.5, 2.5, ?, 0.4, ?, ?)""",
                            (tid, concept_clean, next_due, now, now),
                        )

                # Simple gaps (no error details)
                for concept in gaps:
                    self._upsert_concept_gap(tid, concept, now)

                # Rich gap details (with error type, misconception, remediation, root_cause, error_process)
                for gd in gap_details:
                    concept = gd.get("concept", "")
                    if not concept:
                        continue
                    self._upsert_concept_gap(
                        tid, concept, now,
                        error_type=gd.get("error_type", ""),
                        misconception=gd.get("misconception", ""),
                        remediation=gd.get("remediation", ""),
                        root_cause=gd.get("root_cause", ""),
                        error_process=gd.get("error_process", ""),
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
                      concept_confidence
               FROM concept_mastery WHERE topic_id = ? AND concept_text = ?""",
            (topic_id, concept_clean),
        ).fetchone()
        if existing:
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
        else:
            self.conn.execute(
                """INSERT INTO concept_mastery
                   (topic_id, concept_text, status, error_type, misconception, remediation,
                    root_cause, error_process, times_confirmed, times_missed,
                    review_interval_days, ease_factor, next_review_due,
                    first_seen, last_updated)
                   VALUES (?, ?, 'unknown', ?, ?, ?, ?, ?, 0, 1, 1.0, 2.5, ?, ?, ?)""",
                (topic_id, concept_clean, error_type, misconception, remediation,
                 root_cause, error_process, next_due, now, now),
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
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            with self.conn:
                # Standard SM-2 decay: overdue by schedule
                self.conn.execute(
                    """UPDATE concept_mastery
                       SET status = 'due'
                       WHERE status = 'known'
                         AND next_review_due IS NOT NULL
                         AND next_review_due < ?""",
                    (now,),
                )
            with self.conn:
                # Confidence-coupled decay: known concepts with degraded confidence
                # concept_confidence > 0.0 guard: skips legacy rows never given a score
                self.conn.execute(
                    """UPDATE concept_mastery
                       SET status = 'due',
                           review_interval_days = MAX(1.0, review_interval_days * 0.5)
                       WHERE status = 'known'
                         AND concept_confidence IS NOT NULL
                         AND concept_confidence > 0.0
                         AND concept_confidence < 0.35""",
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

    # ------------------------------------------------------------------
    # Prefrontal Cortex — Learner-Aware Context Injection
    # ------------------------------------------------------------------

    _DEPTH_LABELS = {0: "never-seen", 1: "surface", 2: "mechanistic", 3: "decision-making"}

    # Stop words for topic fingerprinting (broader than _STOP_WORDS — excludes clinical generics)
    _FP_STOPWORDS = frozenset({
        "in", "of", "the", "a", "an", "and", "or", "with", "after", "from",
        "for", "to", "at", "by", "on", "is", "are", "was", "were", "be",
        "this", "that", "these", "those", "when", "then", "into", "upon",
        "over", "under", "above", "during", "before", "between", "versus",
        "new", "newly", "acute", "chronic", "per", "post", "pre", "non",
        "high", "low", "mild", "moderate", "severe", "grade",
    })

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

    def _topic_fingerprint(self, topics: list[str]) -> str:
        """Generate a stable, normalized bag-of-words fingerprint from a list of topics.

        Used for overlap-based retrieval in get_last_session_narrative — replaces
        fragile LIKE '%first_word%' matching with a word-intersection score.

        Expands known abbreviations (via ABBREVIATION_MAP), splits on non-alpha chars,
        filters stop words, and returns a pipe-delimited sorted set of content words.

        Example: ["ICP management in TBI"] → "brain|injury|management|pressure|traumatic"
        """
        words: set[str] = set()
        for topic in topics:
            # Expand abbreviations using the module-level map
            expanded = topic.lower()
            for abbr, full in ABBREVIATION_MAP.items():
                expanded = re.sub(rf'\b{re.escape(abbr)}\b', full, expanded)
            for word in re.split(r'[\s()\[\]/\-,;:]+', expanded):
                word = word.strip(".,;:!?\"'")
                if len(word) > 3 and word not in self._FP_STOPWORDS:
                    words.add(word)
        return "|".join(sorted(words))

    def backfill_topic_fingerprints(self) -> dict:
        """Backfill topic_fingerprint for existing session_narratives rows.

        Safe to run multiple times — only updates rows where topic_fingerprint is empty.
        Returns {"updated": N}.
        """
        try:
            rows = self.conn.execute(
                "SELECT narrative_id, topics_json FROM session_narratives "
                "WHERE topic_fingerprint = '' OR topic_fingerprint IS NULL"
            ).fetchall()
            updated = 0
            for row in rows:
                topics: list[str] = []
                try:
                    raw = json.loads(row["topics_json"]) if row["topics_json"] else []
                    topics = raw if isinstance(raw, list) else [str(raw)]
                except Exception:
                    pass
                fp = self._topic_fingerprint(topics)
                with self.conn:
                    self.conn.execute(
                        "UPDATE session_narratives SET topic_fingerprint = ? WHERE narrative_id = ?",
                        (fp, row["narrative_id"]),
                    )
                updated += 1
            return {"updated": updated}
        except Exception as exc:
            print(f"[knowledge_graph] backfill_topic_fingerprints error: {exc}", file=sys.stderr)
            return {"updated": 0, "error": str(exc)}

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

            # ── Last session narrative for topic(s) — inject teaching strategy ──
            last_narrative = None
            if raw_topics:
                last_narrative = self.get_last_session_narrative(topic=raw_topics[0])
            if last_narrative and last_narrative.get("next_session_strategy"):
                guidance_lines.insert(0,
                    f"PRIOR SESSION STRATEGY (from {last_narrative.get('session_ts', '')[:10]}): "
                    + last_narrative["next_session_strategy"]
                )

            # ── Blocking gaps — prerequisite chains ──
            all_blocking_gaps: list[dict] = []
            for tc in topic_contexts:
                if tc.get("status") != "never_encountered":
                    bg = self.get_blocking_gaps(tc.get("topic", ""))
                    all_blocking_gaps.extend(bg)
            if all_blocking_gaps:
                blockers = [b for b in all_blocking_gaps if b.get("prerequisite_also_unknown")]
                if blockers:
                    guidance_lines.append(
                        f"PREREQUISITE GAPS: {len(blockers)} gap(s) have unmet prerequisites — "
                        + "; ".join(
                            f"'{b['gap_concept']}' requires '{b['blocking_concept']}'"
                            for b in blockers[:3]
                        )
                        + ". Address prerequisites before the higher-level concept."
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
            if last_narrative:
                result["last_session_narrative"] = {
                    "session_ts": last_narrative.get("session_ts", "")[:10],
                    "skill": last_narrative.get("skill", ""),
                    "next_session_strategy": last_narrative.get("next_session_strategy", ""),
                    "summary": last_narrative.get("summary", ""),
                    "teaching_failures": last_narrative.get("teaching_failures", []),
                }
            if all_blocking_gaps:
                result["blocking_gaps"] = all_blocking_gaps[:10]

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

            # ── Iteration 3: ZPD difficulty recommendation ──
            zpd = self.recommend_difficulty_target(n_sessions=5)
            if zpd.get("zpd_status") and zpd["zpd_status"] != "optimal":
                result["zpd_recommendation"] = zpd
                guidance_lines.append(f"ZPD ALERT: {zpd['hint']}")
            elif zpd.get("zpd_status") == "optimal":
                result["zpd_recommendation"] = zpd

            # ── Round 3: Learning velocity stagnation alerts ──
            velocity_data = self.learning_velocity(n_sessions=10)
            stagnant_domains = [
                d for d in velocity_data.get("domains", [])
                if d.get("stagnating")
                and d.get("signal_count", 0) >= 5
                and d.get("velocity", 0.0) != 0.0  # exclude never-studied domains (delta always 0)
            ]
            if stagnant_domains:
                result["stagnation_alerts"] = stagnant_domains
                for sd in stagnant_domains[:2]:
                    guidance_lines.append(
                        f"STAGNATION ALERT: '{sd['domain']}' domain shows no confidence growth "
                        f"across {sd['signal_count']} study signals (velocity={sd['velocity']:+.4f}). "
                        f"Current approach is not producing retention — change teaching modality: "
                        f"switch from passive review to active recall, Socratic questioning, or "
                        f"clinical scenario to break the plateau."
                    )

            # ── Iteration 4: Unknown unknowns — adjacent blind spots ──
            unknown_unknowns = self.detect_unknown_unknowns(query, n=4)
            if unknown_unknowns:
                result["unknown_unknowns"] = unknown_unknowns
                uu_names = [u["topic"] for u in unknown_unknowns[:3]]
                guidance_lines.append(
                    f"BLIND SPOT ALERT: {len(unknown_unknowns)} clinically adjacent topic(s) in "
                    f"the same curriculum subdomain have NEVER been studied: "
                    + ", ".join(uu_names)
                    + ". Consider surfacing one in the session's closing question."
                )

            # ── Cognitive error pattern detection (process-level) [Refinement #2] ──
            cognitive_patterns = self.detect_cognitive_patterns()
            if cognitive_patterns:
                result["cognitive_pattern_alerts"] = cognitive_patterns
                for cp in cognitive_patterns:
                    topics_str = ", ".join(cp["topics"][:3])
                    guidance_lines.append(
                        f"COGNITIVE PATTERN ALERT: '{cp['error_type']}' errors detected "
                        f"{cp['occurrence_count']}x across {cp['topic_count']} topics "
                        f"({topics_str}). This is a PROCESS-LEVEL error, not a content gap. "
                        f"Intervention: {cp['intervention_hint']}"
                    )

            # ── Confidence calibration profile [Refinement #1] ──
            calibration = self.compute_calibration_profile()
            if calibration.get("total_signals", 0) >= 5:
                result["calibration_profile"] = calibration
                if calibration.get("domain_alerts"):
                    for da in calibration["domain_alerts"]:
                        guidance_lines.append(
                            f"CALIBRATION ALERT: {da['alert']} "
                            f"(overconfident-wrong rate: {da['overconfident_wrong_rate']:.0%} "
                            f"across {da['sample_size']} signals)"
                        )
                if calibration.get("calibration_score") is not None and calibration["calibration_score"] < 0.5:
                    guidance_lines.append(
                        f"CALIBRATION WARNING: Overall calibration score is "
                        f"{calibration['calibration_score']:.2f}/1.00 — the learner's "
                        f"confidence frequently does not match their accuracy. Use prediction-error "
                        f"confrontation: let wrong answers play out before correcting."
                    )

            # ── Confusable pair alerts [Refinement #3] ──
            confusable = self.get_confusable_pairs(query)
            if confusable:
                result["confusable_pairs"] = confusable
                direct = [p for p in confusable if p.get("relevance") == "direct"]
                if direct:
                    p = direct[0]
                    guidance_lines.append(
                        f"DISCRIMINATION ALERT: This topic has a known confusable pair — "
                        f"'{p['concept_a']}' vs '{p['concept_b']}'. "
                        f"Disambiguation: {p.get('disambiguation_axis', 'not specified')}. "
                        f"Proactively teach the discrimination to prevent cross-contamination."
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

    # ------------------------------------------------------------------
    # Refinement #2: Cognitive Error Pattern Detection
    # ------------------------------------------------------------------

    _PROCESS_INTERVENTIONS = {
        "premature_closure": (
            "After your first diagnosis, always ask: 'What is the one thing that "
            "would make this NOT my diagnosis?' Check for it before committing."
        ),
        "anchoring": (
            "Explicitly generate 3 alternative explanations before acting on your "
            "leading diagnosis. Write them down."
        ),
        "cross_contamination": (
            "When two conditions share a feature, force yourself to name the ONE "
            "feature that discriminates them before choosing."
        ),
        "application_failure": (
            "Practice the concept under time pressure with gradually increasing "
            "complexity. The knowledge exists — it needs activation under stress."
        ),
        "reasoning_gap": (
            "When explaining your reasoning, narrate every step aloud. The gap is "
            "usually a skipped link you don't realize you're skipping."
        ),
        "numerical_recall": (
            "These values need to be automatic. Create rapid-fire drill cards and "
            "test until the number comes before the thought."
        ),
        "conceptual_confusion": (
            "Draw the mechanism diagram for each confused concept side by side. "
            "The confusion usually lives at one specific branch point."
        ),
    }

    def detect_cognitive_patterns(self) -> list[dict]:
        """Detect recurring cognitive error types across different topics.

        A cognitive pattern is flagged when the same error_type appears >=3
        times across >=2 different topics.  This signals a process-level
        thinking error, not a content gap.

        Returns list of dicts sorted by frequency:
            {error_type, occurrence_count, topic_count, topics,
             is_process_level, intervention_hint}
        """
        try:
            rows = self.conn.execute(
                """SELECT cm.error_type,
                          COUNT(*) AS freq,
                          COUNT(DISTINCT cm.topic_id) AS topic_count,
                          GROUP_CONCAT(DISTINCT COALESCE(t.display_name, t.canonical_name)) AS topics
                   FROM concept_mastery cm
                   JOIN topics t ON cm.topic_id = t.topic_id
                   WHERE cm.status = 'unknown'
                     AND cm.error_type IS NOT NULL AND cm.error_type != ''
                   GROUP BY cm.error_type
                   HAVING freq >= 3 AND topic_count >= 2
                   ORDER BY freq DESC"""
            ).fetchall()

            patterns = []
            for row in rows:
                error_type = row["error_type"]
                patterns.append({
                    "error_type": error_type,
                    "occurrence_count": row["freq"],
                    "topic_count": row["topic_count"],
                    "topics": row["topics"].split(",") if row["topics"] else [],
                    "is_process_level": True,
                    "intervention_hint": self._PROCESS_INTERVENTIONS.get(
                        error_type,
                        "Review your reasoning process for this error class.",
                    ),
                })
            return patterns

        except Exception as exc:
            print(f"[knowledge_graph] detect_cognitive_patterns error: {exc}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # Refinement #1: Confidence Calibration Tracking
    # ------------------------------------------------------------------

    def compute_calibration_profile(self) -> dict:
        """Compute a calibration profile from bootcamp signal_events metadata.

        Looks for 'calibration' entries in signal_events.metadata where source
        is 'bootcamp'.  Each entry is a list of:
            {"concept": str, "response_confidence": "high"|"low", "correct": bool}

        Returns:
            {total_signals, overconfident_wrong, underconfident_right,
             well_calibrated, calibration_score, domain_alerts}
        """
        try:
            rows = self.conn.execute(
                """SELECT se.metadata, t.canonical_name, t.category
                   FROM signal_events se
                   JOIN topics t ON se.topic_id = t.topic_id
                   WHERE se.source = 'bootcamp'
                     AND se.metadata LIKE '%calibration%'
                   ORDER BY se.timestamp DESC"""
            ).fetchall()

            total = 0
            overconfident_wrong = 0  # high confidence + incorrect
            underconfident_right = 0  # low confidence + correct
            well_calibrated = 0  # confidence matches accuracy
            domain_overconfidence: dict[str, int] = {}
            domain_total: dict[str, int] = {}

            for row in rows:
                try:
                    meta = json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"]
                    cal_entries = meta.get("calibration", [])
                    domain = row["category"] or "general"

                    for entry in cal_entries:
                        conf = entry.get("response_confidence", "").lower()
                        correct = entry.get("correct", False)
                        total += 1
                        domain_total[domain] = domain_total.get(domain, 0) + 1

                        if conf == "high" and not correct:
                            overconfident_wrong += 1
                            domain_overconfidence[domain] = domain_overconfidence.get(domain, 0) + 1
                        elif conf == "low" and correct:
                            underconfident_right += 1
                        else:
                            well_calibrated += 1
                except (json.JSONDecodeError, TypeError):
                    continue

            # Calibration score: 0.0 = terrible, 1.0 = perfect
            # Penalize overconfident-wrong more heavily than underconfident-right
            if total == 0:
                cal_score = None
            else:
                penalty = (overconfident_wrong * 2.0 + underconfident_right * 0.5) / total
                cal_score = round(max(0.0, 1.0 - penalty), 3)

            # Domain-level alerts: flag domains with >40% overconfident-wrong rate
            domain_alerts = []
            for domain, oc_count in domain_overconfidence.items():
                dtotal = domain_total.get(domain, 1)
                oc_rate = oc_count / dtotal
                if oc_rate >= 0.4 and dtotal >= 3:
                    domain_alerts.append({
                        "domain": domain,
                        "overconfident_wrong_rate": round(oc_rate, 2),
                        "sample_size": dtotal,
                        "alert": (
                            f"Learner historically overconfident in {domain} — "
                            f"use prediction-error confrontation, not direct correction."
                        ),
                    })

            return {
                "total_signals": total,
                "overconfident_wrong": overconfident_wrong,
                "underconfident_right": underconfident_right,
                "well_calibrated": well_calibrated,
                "calibration_score": cal_score,
                "domain_alerts": domain_alerts,
            }

        except Exception as exc:
            print(f"[knowledge_graph] compute_calibration_profile error: {exc}", file=sys.stderr)
            return {"total_signals": 0, "calibration_score": None, "domain_alerts": []}

    # ------------------------------------------------------------------
    # Refinement #3: Proactive Discrimination (Confusable Pairs)
    # ------------------------------------------------------------------

    def get_confusable_pairs(self, topic: str = "") -> list[dict]:
        """Return confusable pairs from confusion_matrix.json.

        If *topic* is provided, return only pairs where one member matches
        the topic string (case-insensitive substring match).  If empty,
        return all pairs.

        Returns list of dicts from confusion_matrix.json with an added
        'relevance' field ('direct' if topic matched, 'all' otherwise).
        """
        matrix_path = BASE_DIR / "data" / "confusion_matrix.json"
        try:
            if not matrix_path.exists():
                return []
            pairs = json.loads(matrix_path.read_text(encoding="utf-8"))
            if not topic:
                for p in pairs:
                    p["relevance"] = "all"
                return pairs

            topic_lower = topic.strip().lower()
            # Also extract significant words for broader matching
            _stop = {"the", "a", "an", "of", "in", "for", "and", "or", "vs", "with", "to", "is"}
            topic_words = {w for w in topic_lower.split() if w not in _stop and len(w) > 2}

            matched = []
            for p in pairs:
                ca = p.get("concept_a", "").lower()
                cb = p.get("concept_b", "").lower()
                combined = ca + " " + cb

                # Direct substring match
                if topic_lower in ca or topic_lower in cb:
                    p["relevance"] = "direct"
                    matched.append(p)
                # Significant word overlap (any 2+ words match)
                elif len(topic_words) >= 2:
                    combined_words = set(combined.split())
                    overlap = topic_words & combined_words
                    if len(overlap) >= 2:
                        p["relevance"] = "keyword"
                        matched.append(p)
                # Single word match for short queries
                elif topic_words and any(w in combined for w in topic_words):
                    p["relevance"] = "partial"
                    matched.append(p)

            return matched

        except Exception as exc:
            print(f"[knowledge_graph] get_confusable_pairs error: {exc}", file=sys.stderr)
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

            # Fetch 'known' and 'due' concepts with their topic metadata
            # 'due' = was known but next_review_due has passed (set by _apply_concept_srs_decay)
            query = """
                SELECT cm.concept_text, cm.times_confirmed, cm.times_missed,
                       cm.last_updated, cm.error_type, cm.misconception, cm.status,
                       t.canonical_name, t.display_name, t.confidence, t.topic_id
                FROM concept_mastery cm
                JOIN topics t ON cm.topic_id = t.topic_id
                WHERE cm.status IN ('known', 'due')
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

    # ------------------------------------------------------------------
    # Document session tracking (1:1 with Study Material vault docs)
    # ------------------------------------------------------------------

    def get_doc_status(self, doc_path: str) -> dict:
        """Return study state for a Study Material document.

        Returns a dict with keys: doc_path, status ('new'|'returning'),
        session_count, coverage_pct, total_concepts, first_studied,
        last_studied, concepts_covered, concepts_understood, concepts_missed,
        session_notes.
        """
        try:
            row = self.conn.execute(
                "SELECT * FROM document_sessions WHERE doc_path = ?", (doc_path,)
            ).fetchone()
            if not row:
                return {
                    "doc_path": doc_path,
                    "status": "new",
                    "session_count": 0,
                    "coverage_pct": 0.0,
                    "total_concepts": 0,
                    "first_studied": None,
                    "last_studied": None,
                    "concepts_covered": [],
                    "concepts_understood": [],
                    "concepts_missed": [],
                    "session_notes": "",
                }
            d = dict(row)
            d["concepts_covered"] = json.loads(d.get("concepts_covered") or "[]")
            d["concepts_understood"] = json.loads(d.get("concepts_understood") or "[]")
            d["concepts_missed"] = json.loads(d.get("concepts_missed") or "[]")
            d["status"] = "returning"
            return d
        except Exception as exc:
            print(f"[knowledge_graph] get_doc_status error: {exc}", file=sys.stderr)
            return {"doc_path": doc_path, "status": "error", "error": str(exc)}

    def log_doc_progress(
        self,
        doc_path: str,
        doc_type: str = "unknown",
        covered: list | None = None,
        understood: list | None = None,
        missed: list | None = None,
        coverage_pct: float = 0.0,
        total_concepts: int = 0,
    ) -> None:
        """Upsert document study progress, merging with existing session data.

        covered/understood: list of concept/question ID strings.
        missed: list of dicts {"concept": str, "error_type": str, ...} or plain strings.
        Concepts that appear in `understood` are automatically removed from `concepts_missed`.
        """
        covered = covered or []
        understood = understood or []
        missed = missed or []
        now = datetime.now(timezone.utc).isoformat()
        try:
            existing = self.conn.execute(
                "SELECT * FROM document_sessions WHERE doc_path = ?", (doc_path,)
            ).fetchone()

            if existing:
                ex_covered = json.loads(existing["concepts_covered"] or "[]")
                ex_understood = json.loads(existing["concepts_understood"] or "[]")
                ex_missed_list = json.loads(existing["concepts_missed"] or "[]")

                # Merge covered / understood (union, dedup)
                merged_covered = list(set(ex_covered) | set(covered))
                merged_understood = list(set(ex_understood) | set(understood))

                # Merge missed: latest entry for each concept wins
                missed_dict: dict = {}
                for m in ex_missed_list:
                    if isinstance(m, dict) and "concept" in m:
                        missed_dict[m["concept"]] = m
                    elif isinstance(m, str):
                        missed_dict[m] = {"concept": m}
                for m in missed:
                    if isinstance(m, dict) and "concept" in m:
                        missed_dict[m["concept"]] = m
                    elif isinstance(m, str):
                        missed_dict[m] = {"concept": m}
                # Promote to understood: remove from missed if now confirmed
                for u in understood:
                    missed_dict.pop(u, None)
                merged_missed = list(missed_dict.values())

                new_count = (existing["session_count"] or 0) + 1
                new_total = total_concepts if total_concepts > 0 else (existing["total_concepts"] or 0)
                with self.conn:
                    self.conn.execute(
                        """UPDATE document_sessions
                           SET session_count=?, last_studied=?, total_concepts=?,
                               concepts_covered=?, concepts_understood=?,
                               concepts_missed=?, coverage_pct=?
                           WHERE doc_path=?""",
                        (
                            new_count, now, new_total,
                            json.dumps(merged_covered), json.dumps(merged_understood),
                            json.dumps(merged_missed), coverage_pct, doc_path,
                        ),
                    )
            else:
                # Normalise missed to list-of-dicts
                missed_list = [
                    m if isinstance(m, dict) else {"concept": m}
                    for m in missed
                ]
                with self.conn:
                    self.conn.execute(
                        """INSERT INTO document_sessions
                           (doc_path, doc_type, session_count, first_studied, last_studied,
                            total_concepts, concepts_covered, concepts_understood,
                            concepts_missed, coverage_pct)
                           VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            doc_path, doc_type, now, now, total_concepts,
                            json.dumps(list(set(covered))),
                            json.dumps(list(set(understood))),
                            json.dumps(missed_list),
                            coverage_pct,
                        ),
                    )
        except Exception as exc:
            print(f"[knowledge_graph] log_doc_progress error: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Session Narrative — forward-looking teaching intelligence
    # ------------------------------------------------------------------

    def log_session_narrative(
        self,
        skill: str,
        topics: list[str],
        summary: str = "",
        teaching_successes: list[str] | None = None,
        teaching_failures: list[dict] | None = None,
        next_session_strategy: str = "",
        key_confusions: list[dict] | None = None,
        depth_profile: dict | None = None,
        duration_turns: int = 0,
        session_success_rate: float | None = None,
        current_understood: list[str] | None = None,
        current_gaps: list[str] | None = None,
    ) -> int:
        """Persist a session-level teaching narrative.

        This is the highest-value forward-looking record in the KG.
        ``next_session_strategy`` is a directive for the NEXT session, written
        by the agent at session end.  It survives context compression and
        is injected by preflight into the next session so the agent does not
        have to re-derive teaching strategy from raw gap data.

        Parameters
        ----------
        skill : str
            The skill that produced this session (study-session, intern-bootcamp, etc.)
        topics : list[str]
            Topic names covered.
        summary : str
            1-2 sentence session recap.
        teaching_successes : list[str]
            What approaches clicked (plain-English descriptions).
        teaching_failures : list[dict]
            What did not work.  Each dict: {"concept": str, "attempted": str, "why_failed": str}
        next_session_strategy : str
            Forward directive for the NEXT session on these topics.  Example:
            "Start with vasogenic vs cytotoxic edema distinction before ICP targets in brain tumors.
             Learner anchors on TBI numbers; mechanism-first teaching required."
        key_confusions : list[dict]
            Concept pairs confused this session.
            Each dict: {"concept_a": str, "concept_b": str, "disambiguation_axis": str}
        depth_profile : dict
            {topic: depth_achieved} mapping.
        duration_turns : int
            Number of interaction turns in the session.

        Returns
        -------
        int
            narrative_id of the inserted row.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()

            # Iteration 2: evaluate whether prior session's strategy worked, before inserting
            if topics and (current_understood is not None or current_gaps is not None):
                self._evaluate_prior_strategy_outcome(
                    skill=skill,
                    topics=topics,
                    current_understood=current_understood or [],
                    current_gaps=current_gaps or [],
                )

            # Round 3: compute topic fingerprint for overlap-based retrieval
            topic_fp = self._topic_fingerprint(topics or [])

            with self.conn:
                cur = self.conn.execute(
                    """INSERT INTO session_narratives
                       (session_ts, skill, topics_json, summary,
                        teaching_successes, teaching_failures, next_session_strategy,
                        key_confusions_json, depth_profile_json, duration_turns,
                        session_success_rate, topic_fingerprint)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        now, skill,
                        json.dumps(topics or []),
                        summary,
                        json.dumps(teaching_successes or []),
                        json.dumps(teaching_failures or []),
                        next_session_strategy,
                        json.dumps(key_confusions or []),
                        json.dumps(depth_profile or {}),
                        duration_turns,
                        session_success_rate,
                        topic_fp,
                    ),
                )
                narrative_id = cur.lastrowid or -1

            # Auto-persist key_confusions to concept_relationships table
            for pair in (key_confusions or []):
                ca = pair.get("concept_a", "").strip().lower()
                cb = pair.get("concept_b", "").strip().lower()
                if ca and cb:
                    self._record_concept_relationship(
                        concept_a=ca, concept_b=cb,
                        relationship="confusable_with",
                        notes=pair.get("disambiguation_axis", ""),
                        source=f"session_narrative:{skill}",
                        now=now,
                    )

            return narrative_id
        except Exception as exc:
            print(f"[knowledge_graph] log_session_narrative error: {exc}", file=sys.stderr)
            return -1

    def get_last_session_narrative(
        self,
        skill: str | None = None,
        topic: str | None = None,
    ) -> dict | None:
        """Return the most recent session narrative, optionally filtered by skill or topic.

        Uses fingerprint overlap scoring (Round 3) instead of LIKE substring matching.
        This makes retrieval robust to topic name variation, abbreviation differences,
        and paraphrasing — "ICP management in TBI" correctly matches a stored narrative
        about "ICP management in traumatic brain injury (severe)".

        Scoring: count of shared words between query fingerprint and stored fingerprint.
        Falls back to LIKE matching for old rows that have no stored fingerprint.
        Returns the most recent row with the highest overlap score (>=1), or the most
        recent row overall when topic is None.
        """
        try:
            # Fetch candidate pool (capped at 20 most recent for the skill)
            if skill:
                rows = self.conn.execute(
                    "SELECT * FROM session_narratives WHERE skill = ? ORDER BY session_ts DESC LIMIT 20",
                    (skill,),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM session_narratives ORDER BY session_ts DESC LIMIT 20"
                ).fetchall()

            if not rows:
                return None

            if not topic:
                row = rows[0]  # no topic filter — return most recent
            else:
                query_fp = self._topic_fingerprint([topic])
                query_words = set(query_fp.split("|")) if query_fp else set()

                best_row = None
                best_score = -1

                for candidate in rows:
                    stored_fp = ""
                    try:
                        stored_fp = candidate["topic_fingerprint"] or ""
                    except (IndexError, KeyError):
                        pass

                    if stored_fp:
                        stored_words = set(stored_fp.split("|"))
                        overlap = len(query_words & stored_words)
                    else:
                        # Legacy row without fingerprint — fall back to substring check
                        overlap = 1 if (topic.lower() in (candidate["topics_json"] or "").lower()) else 0

                    if overlap > best_score:
                        best_score = overlap
                        best_row = candidate

                # Require at least 1 word in common to consider it a match
                row = best_row if best_score >= 1 else None

            if not row:
                return None

            d = dict(row)
            for json_col in ("topics_json", "teaching_successes", "teaching_failures",
                             "key_confusions_json", "depth_profile_json", "linked_signal_ids"):
                if json_col in d and d[json_col]:
                    try:
                        d[json_col] = json.loads(d[json_col])
                    except (json.JSONDecodeError, TypeError):
                        pass
            return d
        except Exception as exc:
            print(f"[knowledge_graph] get_last_session_narrative error: {exc}", file=sys.stderr)
            return None

    # ------------------------------------------------------------------
    # Concept Relationships — prerequisite graph
    # ------------------------------------------------------------------

    def add_concept_relationship(
        self,
        concept_a: str,
        concept_b: str,
        relationship: str,
        topic_a: str = "",
        topic_b: str = "",
        strength: float = 0.5,
        notes: str = "",
        source: str = "manual",
    ) -> None:
        """Public API to add a concept relationship.

        relationship: 'prerequisite_of' | 'confusable_with' | 'extends' | 'differentiates_from'
        """
        now = datetime.now(timezone.utc).isoformat()
        self._record_concept_relationship(
            concept_a=concept_a.strip().lower(),
            concept_b=concept_b.strip().lower(),
            relationship=relationship,
            topic_a=topic_a,
            topic_b=topic_b,
            strength=strength,
            notes=notes,
            source=source,
            now=now,
        )

    def get_blocking_gaps(self, topic_name: str) -> list[dict]:
        """Return gaps for a topic that have prerequisite concept gaps blocking them.

        For each 'unknown' concept in the topic, checks concept_relationships for
        'prerequisite_of' entries pointing to that concept from other unknown concepts.
        This surfaces the root of a gap chain: "you can't learn X until you fix Y."

        Returns list of dicts:
            {gap_concept, topic, blocking_concept, blocking_topic, notes,
             root_cause, error_type, misconception}
        """
        try:
            canonical = self._normalize_topic(topic_name)
            topic = self._find_topic(canonical)
            if not topic:
                return []

            # Get all unknown concepts for this topic
            unknown_rows = self.conn.execute(
                """SELECT concept_text, error_type, misconception, root_cause
                   FROM concept_mastery WHERE topic_id = ? AND status IN ('unknown', 'due')""",
                (topic["topic_id"],),
            ).fetchall()

            results = []
            for row in unknown_rows:
                concept = row["concept_text"]
                # Find prerequisites for this concept
                prereqs = self.conn.execute(
                    """SELECT concept_a, topic_a, notes, strength
                       FROM concept_relationships
                       WHERE concept_b = ? AND relationship = 'prerequisite_of'""",
                    (concept,),
                ).fetchall()
                for p in prereqs:
                    # Check if the prerequisite concept is also unknown
                    prereq_concept = p["concept_a"]
                    prereq_topic = p["topic_a"]
                    is_unknown = False
                    if prereq_topic:
                        pt = self._find_topic(self._normalize_topic(prereq_topic))
                        if pt:
                            cm = self.conn.execute(
                                """SELECT status FROM concept_mastery
                                   WHERE topic_id = ? AND concept_text = ?""",
                                (pt["topic_id"], prereq_concept),
                            ).fetchone()
                            is_unknown = cm and cm["status"] in ("unknown", "due")
                    results.append({
                        "gap_concept": concept,
                        "topic": topic_name,
                        "blocking_concept": prereq_concept,
                        "blocking_topic": prereq_topic or topic_name,
                        "notes": p["notes"] or "",
                        "strength": p["strength"],
                        "prerequisite_also_unknown": is_unknown,
                        "error_type": row["error_type"] or "",
                        "misconception": row["misconception"] or "",
                        "root_cause": row["root_cause"] or "",
                    })
            results.sort(key=lambda x: (-x["strength"], x["prerequisite_also_unknown"]))
            return results
        except Exception as exc:
            print(f"[knowledge_graph] get_blocking_gaps error: {exc}", file=sys.stderr)
            return []

    def concept_chain(
        self, concept_text: str, topic_name: str | None = None, max_depth: int = 5
    ) -> dict:
        """Return the full prerequisite chain and extension chain for a concept.

        prerequisite_chain: concepts that must be known BEFORE this one
        extension_chain: concepts that BUILD ON this one (breadth this unlocks)

        Returns:
            {concept, topic, prerequisite_chain: [...], extension_chain: [...]}
        """
        try:
            concept_lower = concept_text.strip().lower()

            def _walk(start: str, direction: str, depth: int = 0) -> list[dict]:
                if depth >= max_depth:
                    return []
                if direction == "prerequisites":
                    rows = self.conn.execute(
                        """SELECT concept_a AS next_concept, topic_a AS next_topic, notes, strength
                           FROM concept_relationships
                           WHERE concept_b = ? AND relationship = 'prerequisite_of'""",
                        (start,),
                    ).fetchall()
                else:  # extensions
                    rows = self.conn.execute(
                        """SELECT concept_b AS next_concept, topic_b AS next_topic, notes, strength
                           FROM concept_relationships
                           WHERE concept_a = ? AND relationship IN ('prerequisite_of', 'extends')""",
                        (start,),
                    ).fetchall()
                chain = []
                for r in rows:
                    entry = {
                        "concept": r["next_concept"],
                        "topic": r["next_topic"] or "",
                        "notes": r["notes"] or "",
                        "strength": r["strength"],
                        "depth": depth + 1,
                    }
                    entry["chain"] = _walk(r["next_concept"], direction, depth + 1)
                    chain.append(entry)
                return chain

            return {
                "concept": concept_text,
                "topic": topic_name or "",
                "prerequisite_chain": _walk(concept_lower, "prerequisites"),
                "extension_chain": _walk(concept_lower, "extensions"),
            }
        except Exception as exc:
            print(f"[knowledge_graph] concept_chain error: {exc}", file=sys.stderr)
            return {"concept": concept_text, "topic": topic_name or "",
                    "prerequisite_chain": [], "extension_chain": []}

    # ------------------------------------------------------------------
    # Topic Specificity Validation
    # ------------------------------------------------------------------

    # Clinical qualifier patterns that indicate a fine-grained topic
    _CLINICAL_QUALIFIERS = [
        r"\bin\b", r"\bpost[\-\s]", r"\bfollowing\b", r"\bduring\b", r"\bafter\b",
        r"\bfor\b", r"\bdue to\b", r"\bsecondary to\b", r"\bassociated with\b",
        r"\bwith\b", r"\bversus\b", r"\bvs\.?\b", r"\brelated to\b",
        r"\bcaused by\b", r"\bfrom\b", r"\bcomplicating\b",
    ]

    def validate_topic_specificity(self, topic_name: str) -> dict:
        """Check whether a topic name is sufficiently specific.

        Returns dict with:
            name: str, specificity_level: int, has_qualifier: bool,
            recommendation: str
        """
        lower = topic_name.strip().lower()
        has_qualifier = any(
            re.search(pat, lower) for pat in self._CLINICAL_QUALIFIERS
        )
        word_count = len(lower.split())
        if has_qualifier and word_count >= 4:
            level = 3
            rec = ""
        elif has_qualifier or word_count >= 4:
            level = 2
            rec = (
                f"Consider adding a clinical context qualifier. "
                f"Instead of '{topic_name}', prefer e.g. "
                f"'{topic_name} in [specific condition]'."
            )
        else:
            level = 1
            rec = (
                f"Topic '{topic_name}' is too coarse. It will store correctly but "
                f"future sessions cannot distinguish clinical sub-contexts. "
                f"Prefer: '{topic_name} in [specific clinical setting/population]'."
            )
        return {
            "name": topic_name,
            "specificity_level": level,
            "has_qualifier": has_qualifier,
            "word_count": word_count,
            "recommendation": rec,
        }

    # ------------------------------------------------------------------
    # Fine-Grained Gaps — concept-level with root_cause + error_process
    # ------------------------------------------------------------------

    def fine_grained_gaps(self, top: int = 10, domain: str | None = None) -> list[dict]:
        """Return concept-level gaps with root_cause and error_process, ranked by urgency.

        Unlike ``generate_recommendations()`` which operates at topic level,
        this returns individual concept gaps — the unit of actual learning failure.
        Each entry carries the full causal chain: error_type → error_process → root_cause.

        Ranking: times_missed DESC, then next_review_due ASC (most overdue first).
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            query = """
                SELECT cm.concept_text, cm.error_type, cm.error_process, cm.root_cause,
                       cm.misconception, cm.remediation, cm.teaching_notes,
                       cm.times_missed, cm.times_confirmed,
                       cm.next_review_due, cm.last_updated, cm.status,
                       t.canonical_name, t.display_name, t.category,
                       COALESCE(ct.domain, t.category) AS domain,
                       ct.priority, ct.acgme_milestone
                FROM concept_mastery cm
                JOIN topics t ON cm.topic_id = t.topic_id
                LEFT JOIN curriculum_topics ct ON t.curriculum_id = ct.curriculum_id
                WHERE cm.status IN ('unknown', 'due')
            """
            params: list = []
            if domain:
                query += " AND (LOWER(COALESCE(ct.domain, t.category)) LIKE ?)"
                params.append(f"%{domain.lower()}%")
            query += " ORDER BY cm.times_missed DESC, cm.next_review_due ASC LIMIT ?"
            params.append(top)

            rows = self.conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                # Compute days overdue
                nrd = self._parse_ts(d.get("next_review_due"))
                now_dt = self._parse_ts(now) or datetime.now(timezone.utc)
                days_overdue = round((now_dt - nrd).total_seconds() / 86400, 1) if nrd else None
                d["days_overdue"] = days_overdue
                results.append(d)
            return results
        except Exception as exc:
            print(f"[knowledge_graph] fine_grained_gaps error: {exc}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # SRS-Based Concept Review Queue
    # ------------------------------------------------------------------

    def concept_review_queue_srs(
        self, n: int = 10, domain: str | None = None
    ) -> list[dict]:
        """Return concepts due for review using persisted SM-2 scheduling.

        Priority order:
        1. status='due' (known but past next_review_due) — quick recall check needed
        2. status='unknown' (failed), ordered by next_review_due ASC
        3. status='known' with next_review_due IS NULL (pre-migration) — use heuristic

        Returns list of dicts:
            {concept, topic, topic_canonical, domain, status, times_confirmed,
             times_missed, next_review_due, days_overdue, ease_factor,
             error_type, root_cause, error_process, misconception}
        """
        try:
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()

            query = """
                SELECT cm.concept_text, cm.status, cm.times_confirmed, cm.times_missed,
                       cm.next_review_due, cm.ease_factor, cm.review_interval_days,
                       cm.error_type, cm.root_cause, cm.error_process, cm.misconception,
                       t.canonical_name, t.display_name, t.category,
                       COALESCE(ct.domain, t.category) AS domain,
                       ct.priority
                FROM concept_mastery cm
                JOIN topics t ON cm.topic_id = t.topic_id
                LEFT JOIN curriculum_topics ct ON t.curriculum_id = ct.curriculum_id
                WHERE cm.status IN ('due', 'unknown')
                   OR (cm.status = 'known' AND cm.next_review_due IS NULL
                       AND cm.last_updated < ?)
            """
            # For the legacy heuristic: mark known concepts not seen in 7+ days
            seven_days_ago = (now - timedelta(days=7)).isoformat()
            params: list = [seven_days_ago]

            if domain:
                query = query.replace(
                    "WHERE cm.status IN ('due', 'unknown')",
                    f"WHERE (LOWER(COALESCE(ct.domain, t.category)) LIKE '%{domain.lower()}%') AND cm.status IN ('due', 'unknown')",
                )

            rows = self.conn.execute(query, params).fetchall()

            candidates = []
            for row in rows:
                nrd = self._parse_ts(row["next_review_due"])
                if nrd:
                    days_overdue = round((now - nrd).total_seconds() / 86400, 1)
                    days_overdue = max(0.0, days_overdue)
                else:
                    days_overdue = 0.0

                # Status priority: due=0, unknown=1, known_legacy=2
                status = row["status"]
                sort_priority = 0 if status == "due" else (1 if status == "unknown" else 2)

                candidates.append({
                    "concept": row["concept_text"],
                    "topic": row["display_name"],
                    "topic_canonical": row["canonical_name"],
                    "domain": row["domain"] or row["category"] or "",
                    "status": status,
                    "times_confirmed": row["times_confirmed"] or 0,
                    "times_missed": row["times_missed"] or 0,
                    "next_review_due": (row["next_review_due"] or "")[:10],
                    "days_overdue": days_overdue,
                    "ease_factor": round(row["ease_factor"] or 2.5, 2),
                    "error_type": row["error_type"] or "",
                    "root_cause": row["root_cause"] or "",
                    "error_process": row["error_process"] or "",
                    "misconception": row["misconception"] or "",
                    "_sort": (sort_priority, -days_overdue),
                })

            candidates.sort(key=lambda c: c["_sort"])
            for c in candidates:
                c.pop("_sort", None)
            return candidates[:n]

        except Exception as exc:
            print(f"[knowledge_graph] concept_review_queue_srs error: {exc}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # Migrate confusion_matrix.json → concept_relationships table
    # ------------------------------------------------------------------

    def migrate_confusion_matrix(self) -> dict:
        """One-time migration: import confusion_matrix.json into concept_relationships.

        Idempotent — skips pairs already present (either direction).
        Returns {"migrated": N, "skipped": M}.
        """
        matrix_path = BASE_DIR / "data" / "confusion_matrix.json"
        if not matrix_path.exists():
            return {"migrated": 0, "skipped": 0, "error": "confusion_matrix.json not found"}
        try:
            pairs = json.loads(matrix_path.read_text(encoding="utf-8"))
            migrated = 0
            skipped = 0
            for p in pairs:
                ca = p.get("concept_a", "").strip().lower()
                cb = p.get("concept_b", "").strip().lower()
                if not ca or not cb:
                    skipped += 1
                    continue
                existing = self.conn.execute(
                    """SELECT rel_id FROM concept_relationships
                       WHERE ((concept_a = ? AND concept_b = ?) OR (concept_a = ? AND concept_b = ?))
                         AND relationship = 'confusable_with'""",
                    (ca, cb, cb, ca),
                ).fetchone()
                if existing:
                    skipped += 1
                    continue
                now = p.get("first_added") or datetime.now(timezone.utc).isoformat()
                with self.conn:
                    self.conn.execute(
                        """INSERT INTO concept_relationships
                           (concept_a, concept_b, relationship, notes, source, strength, created_ts)
                           VALUES (?, ?, 'confusable_with', ?, ?, 0.5, ?)""",
                        (ca, cb,
                         p.get("disambiguation_axis", ""),
                         p.get("source", "manual"),
                         now),
                    )
                migrated += 1
            return {"migrated": migrated, "skipped": skipped}
        except Exception as exc:
            print(f"[knowledge_graph] migrate_confusion_matrix error: {exc}", file=sys.stderr)
            return {"migrated": 0, "skipped": 0, "error": str(exc)}

    def close(self) -> None:
        """Close the database connection."""
        try:
            self.conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Iteration 1: Teaching Notes Auto-Population
    # ------------------------------------------------------------------

    def _auto_populate_teaching_notes(
        self,
        concept_id: int,
        root_cause: str,
        error_process: str,
        remediation: str,
        session_date: str,
    ) -> None:
        """Auto-populate teaching_notes when a concept first transitions unknown → known.

        Called once per concept, at the moment of the transition. Records the
        causal chain that was addressed so the agent can re-use the same approach
        in future sessions without re-deriving it from raw gap data.
        """
        if not any([root_cause, error_process, remediation]):
            return
        parts: list[str] = [f"[{session_date}] First mastered:"]
        if error_process:
            parts.append(f"error process was '{error_process}'")
        if root_cause:
            parts.append(f"root cause: {root_cause[:120]}")
        if remediation:
            parts.append(f"what worked: {remediation[:120]}")
        note = " — ".join(parts)
        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE concept_mastery SET teaching_notes = TRIM(teaching_notes || char(10) || ?) WHERE concept_id = ?",
                    (note, concept_id),
                )
        except Exception as exc:
            print(f"[knowledge_graph] _auto_populate_teaching_notes error: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Iteration 2: Prerequisite Seeding + Strategy Feedback Loop
    # ------------------------------------------------------------------

    def _evaluate_prior_strategy_outcome(
        self,
        skill: str,
        topics: list[str],
        current_understood: list[str],
        current_gaps: list[str],
    ) -> str | None:
        """Evaluate whether the prior session's strategy improved outcomes.

        Called just before inserting a new session narrative. Looks up the most
        recent narrative for overlapping topics and records whether the prior
        next_session_strategy produced measurable improvement.

        Outcome classification:
            improved   — more concepts understood than missed this session
            partial    — roughly even understood vs. gaps
            unchanged  — more gaps than understood (or no understood data)
            no_prior   — no prior narrative found with a strategy

        Returns the outcome string, or None if not enough data.
        """
        if not topics:
            return None
        prior = self.get_last_session_narrative(skill=skill, topic=topics[0])
        if not prior or not prior.get("next_session_strategy") or not prior.get("narrative_id"):
            return None

        # Round 3: concept-anchored delta — measure improvement on the specific concepts
        # the prior strategy was trying to address, not aggregate session quality.
        prior_failures = prior.get("teaching_failures") or []
        if isinstance(prior_failures, str):
            try:
                prior_failures = json.loads(prior_failures)
            except Exception:
                prior_failures = []

        prior_failed_concepts = [
            (f.get("concept") or "").lower().strip()
            for f in prior_failures
            if isinstance(f, dict) and f.get("concept")
        ]

        if prior_failed_concepts:
            # Primary path: check how many of the prior-failed concepts are now understood
            understood_lower = [(c or "").lower().strip() for c in (current_understood or [])]
            recovered = sum(
                1 for fc in prior_failed_concepts
                if fc and any(fc in u or u in fc for u in understood_lower if u)
            )
            recovery_rate = recovered / len(prior_failed_concepts)
            outcome = "improved" if recovery_rate >= 0.5 else (
                "partial" if recovery_rate >= 0.25 else "unchanged"
            )
        else:
            # Fallback: no specific failure concepts logged in prior narrative;
            # use aggregate ratio as a coarser signal
            n_understood = len(current_understood or [])
            n_gaps = len(current_gaps or [])
            total = n_understood + n_gaps
            if total == 0:
                return None
            ratio = n_understood / total
            outcome = "improved" if ratio >= 0.7 else ("partial" if ratio >= 0.45 else "unchanged")

        try:
            with self.conn:
                self.conn.execute(
                    "UPDATE session_narratives SET strategy_outcome = ? WHERE narrative_id = ?",
                    (outcome, prior["narrative_id"]),
                )
        except Exception as exc:
            print(f"[knowledge_graph] _evaluate_prior_strategy_outcome error: {exc}", file=sys.stderr)

        return outcome

    def seed_prerequisites_from_cooccurrence(self, min_cooccurrence: int = 2) -> dict:
        """Auto-seed concept_relationships from co-occurring gaps.

        Two mechanisms:
        1. error_process='prerequisite_absent': the 'misconception' field names the
           missing prerequisite concept. Automatically add a prerequisite_of edge.
        2. Same-topic concept pairs both in 'unknown' status: likely confusable within
           their clinical context. Add confusable_with edge if not already present.

        Returns {"prerequisite_edges": N, "confusable_edges": M, "skipped": K}
        """
        now = datetime.now(timezone.utc).isoformat()
        prereq_added = 0
        confusable_added = 0
        skipped = 0

        try:
            # Mechanism 1: error_process='prerequisite_absent' → named prerequisite
            prereq_rows = self.conn.execute(
                """SELECT cm.concept_text, cm.misconception, t.canonical_name AS topic
                   FROM concept_mastery cm
                   JOIN topics t ON cm.topic_id = t.topic_id
                   WHERE cm.error_process = 'prerequisite_absent'
                     AND cm.misconception IS NOT NULL AND cm.misconception != ''""",
            ).fetchall()
            for row in prereq_rows:
                prereq_concept = row["misconception"].strip().lower()
                gap_concept = row["concept_text"].strip().lower()
                topic = row["topic"]
                if prereq_concept and gap_concept and prereq_concept != gap_concept:
                    existing = self.conn.execute(
                        """SELECT rel_id FROM concept_relationships
                           WHERE concept_a = ? AND concept_b = ? AND relationship = 'prerequisite_of'""",
                        (prereq_concept, gap_concept),
                    ).fetchone()
                    if not existing:
                        self._record_concept_relationship(
                            concept_a=prereq_concept,
                            concept_b=gap_concept,
                            relationship="prerequisite_of",
                            topic_a=topic,
                            topic_b=topic,
                            notes="auto-seeded from error_process=prerequisite_absent",
                            source="auto_cooccurrence",
                            now=now,
                        )
                        prereq_added += 1
                    else:
                        skipped += 1

            # Mechanism 2: same-topic concept pairs both unknown →  confusable_with
            same_topic_pairs = self.conn.execute(
                """SELECT a.concept_text AS ca, b.concept_text AS cb,
                          t.canonical_name AS topic
                   FROM concept_mastery a
                   JOIN concept_mastery b ON a.topic_id = b.topic_id AND a.concept_id < b.concept_id
                   JOIN topics t ON a.topic_id = t.topic_id
                   WHERE a.status IN ('unknown', 'due')
                     AND b.status IN ('unknown', 'due')
                     AND a.times_missed >= ? AND b.times_missed >= ?""",
                (min_cooccurrence, min_cooccurrence),
            ).fetchall()
            for row in same_topic_pairs:
                ca = row["ca"].strip().lower()
                cb = row["cb"].strip().lower()
                topic = row["topic"]
                existing = self.conn.execute(
                    """SELECT rel_id FROM concept_relationships
                       WHERE ((concept_a = ? AND concept_b = ?) OR (concept_a = ? AND concept_b = ?))
                         AND relationship = 'confusable_with'""",
                    (ca, cb, cb, ca),
                ).fetchone()
                if not existing:
                    self._record_concept_relationship(
                        concept_a=ca,
                        concept_b=cb,
                        relationship="confusable_with",
                        topic_a=topic,
                        topic_b=topic,
                        notes=f"co-occurrence: both missed {min_cooccurrence}+ times in same topic",
                        source="auto_cooccurrence",
                        now=now,
                    )
                    confusable_added += 1
                else:
                    skipped += 1

        except Exception as exc:
            print(f"[knowledge_graph] seed_prerequisites_from_cooccurrence error: {exc}", file=sys.stderr)

        return {"prerequisite_edges": prereq_added, "confusable_edges": confusable_added, "skipped": skipped}

    # ------------------------------------------------------------------
    # Iteration 3: ZPD Adaptive Difficulty Calibration
    # ------------------------------------------------------------------

    def recommend_difficulty_target(self, n_sessions: int = 5) -> dict:
        """Compute a Zone of Proximal Development recommendation from recent sessions.

        Analyzes the last N sessions with a recorded session_success_rate.
        ZPD thresholds (Schmidt's Challenge Point Framework):
            > 0.85 — too easy; push to deeper complexity (increase depth, add cross-topic)
            0.65–0.85 — in ZPD; maintain current difficulty
            < 0.65 — too hard; scaffold back to prerequisites

        Returns:
            {mean_success_rate, session_count, zpd_status, direction,
             recommended_depth, hint, domain_breakdown}
        """
        try:
            rows = self.conn.execute(
                """SELECT session_success_rate, depth_profile_json, topics_json, skill
                   FROM session_narratives
                   WHERE session_success_rate IS NOT NULL
                   ORDER BY session_ts DESC LIMIT ?""",
                (n_sessions,),
            ).fetchall()

            if not rows:
                return {
                    "status": "insufficient_data",
                    "session_count": 0,
                    "recommended_depth": 2,
                    "direction": "maintain",
                    "hint": "Not enough session data — run 2+ sessions with success rate logging.",
                }

            rates = [float(r["session_success_rate"]) for r in rows]
            mean_rate = sum(rates) / len(rates)

            # Trend: compare first half vs second half of window
            mid = len(rates) // 2
            if mid > 0:
                recent_mean = sum(rates[:mid]) / mid
                older_mean = sum(rates[mid:]) / (len(rates) - mid)
                trend = "improving" if recent_mean > older_mean + 0.05 else (
                    "declining" if recent_mean < older_mean - 0.05 else "stable"
                )
            else:
                trend = "stable"

            if mean_rate > 0.85:
                direction = "increase"
                zpd_status = "too_easy"
                recommended_depth = 3
                hint = (
                    f"Mean success rate {mean_rate:.0%} is above ZPD ceiling — material is too easy. "
                    f"Push to depth 3: surgical decision-making, edge cases, cross-domain transfer."
                )
            elif mean_rate < 0.65:
                direction = "decrease"
                zpd_status = "too_hard"
                recommended_depth = 1
                hint = (
                    f"Mean success rate {mean_rate:.0%} is below ZPD floor — material is too hard. "
                    f"Scaffold back: address prerequisites, build mechanism before application."
                )
            else:
                direction = "maintain"
                zpd_status = "optimal"
                recommended_depth = 2
                hint = (
                    f"Mean success rate {mean_rate:.0%} is in the optimal ZPD range (65–85%). "
                    f"Maintain current depth and complexity — learning is happening here."
                )

            return {
                "mean_success_rate": round(mean_rate, 2),
                "session_count": len(rates),
                "zpd_status": zpd_status,
                "direction": direction,
                "recommended_depth": recommended_depth,
                "trend": trend,
                "hint": hint,
            }

        except Exception as exc:
            print(f"[knowledge_graph] recommend_difficulty_target error: {exc}", file=sys.stderr)
            return {"status": "error", "error": str(exc)}

    def learning_velocity(self, domain: str | None = None, n_sessions: int = 10) -> dict:
        """Compute per-domain confidence change rate over recent study events.

        'Velocity' is the mean signed confidence delta per session for tracked topics
        in each domain. Positive = improving; negative = declining (decay outpacing study).

        Stagnation signal: |velocity| < 0.005 across 5+ sessions = study mode change needed.

        Returns:
            {domains: [{domain, velocity, signal_count, stagnating, status}],
             overall_velocity, sessions_analyzed}
        """
        try:
            now = datetime.now(timezone.utc)
            cutoff = (now - timedelta(days=n_sessions * 3)).isoformat()  # approx window

            query = """
                SELECT ct.domain,
                       AVG(se.confidence_delta) AS mean_delta,
                       COUNT(*)                  AS signal_count
                FROM signal_events se
                JOIN topics t ON se.topic_id = t.topic_id
                LEFT JOIN curriculum_topics ct ON t.curriculum_id = ct.curriculum_id
                WHERE se.timestamp > ?
                  AND se.signal_type IN ('study_session', 'correct_recall', 'incorrect_recall',
                                         'weakness_identified', 'partial_recall', 'lecture_received')
            """
            params: list = [cutoff]
            if domain:
                query += " AND LOWER(COALESCE(ct.domain, t.category)) LIKE ?"
                params.append(f"%{domain.lower()}%")
            query += " GROUP BY COALESCE(ct.domain, t.category) ORDER BY ABS(mean_delta) DESC"

            rows = self.conn.execute(query, params).fetchall()

            domain_results = []
            overall_deltas = []
            for row in rows:
                d = row["domain"] or "(uncategorised)"
                vel = round(float(row["mean_delta"] or 0), 4)
                cnt = row["signal_count"] or 0
                stagnating = abs(vel) < 0.005 and cnt >= 5
                status = "declining" if vel < -0.01 else ("improving" if vel > 0.01 else "stagnant")
                domain_results.append({
                    "domain": d,
                    "velocity": vel,
                    "signal_count": cnt,
                    "stagnating": stagnating,
                    "status": status,
                })
                overall_deltas.extend([vel] * cnt)

            overall = round(sum(overall_deltas) / len(overall_deltas), 4) if overall_deltas else 0.0

            return {
                "domains": domain_results,
                "overall_velocity": overall,
                "sessions_analyzed": n_sessions,
            }

        except Exception as exc:
            print(f"[knowledge_graph] learning_velocity error: {exc}", file=sys.stderr)
            return {"domains": [], "overall_velocity": 0.0, "sessions_analyzed": n_sessions}

    # ------------------------------------------------------------------
    # Iteration 4: Blind Spot Detection + Topic Adjacency
    # ------------------------------------------------------------------

    def auto_seed_topic_adjacency(self) -> dict:
        """Seed topic_adjacency from ACGME milestone + domain groupings.

        Topics sharing the same ACGME milestone (preferred) or same domain (fallback)
        are clinically adjacent — studying one without the other is a blind spot risk.
        Only pairs where at least one topic has encounter_count > 0 are included
        (no point surfacing adjacency for topics the learner has never touched at all).

        Returns {"seeded": N, "skipped": M}
        """
        now = datetime.now(timezone.utc).isoformat()
        seeded = 0
        skipped = 0
        try:
            # Group by ACGME milestone (preferred) — topics in same milestone are adjacent
            # Join via curriculum_id (correct linkage — canonical_name differs from topic_name)
            subdomain_rows = self.conn.execute(
                """SELECT ct1.topic_name AS ta, ct2.topic_name AS tb, ct1.domain
                   FROM curriculum_topics ct1
                   JOIN curriculum_topics ct2
                     ON COALESCE(NULLIF(ct1.subdomain,''), ct1.acgme_milestone, ct1.domain)
                        = COALESCE(NULLIF(ct2.subdomain,''), ct2.acgme_milestone, ct2.domain)
                     AND ct1.curriculum_id < ct2.curriculum_id
                   LEFT JOIN topics t1 ON t1.curriculum_id = ct1.curriculum_id
                   LEFT JOIN topics t2 ON t2.curriculum_id = ct2.curriculum_id
                   WHERE COALESCE(t1.encounter_count,0) + COALESCE(t2.encounter_count,0) > 0
                   LIMIT 2000"""
            ).fetchall()

            for row in subdomain_rows:
                ta = row["ta"].strip().lower()
                tb = row["tb"].strip().lower()
                if not ta or not tb:
                    continue
                existing = self.conn.execute(
                    "SELECT adj_id FROM topic_adjacency WHERE (topic_a = ? AND topic_b = ?) OR (topic_a = ? AND topic_b = ?)",
                    (ta, tb, tb, ta),
                ).fetchone()
                if existing:
                    skipped += 1
                    continue
                with self.conn:
                    self.conn.execute(
                        """INSERT INTO topic_adjacency (topic_a, topic_b, domain, adjacency_strength, source, created_ts)
                           VALUES (?, ?, ?, 0.7, 'curriculum_milestone', ?)""",
                        (ta, tb, row["domain"] or "", now),
                    )
                seeded += 1

        except Exception as exc:
            print(f"[knowledge_graph] auto_seed_topic_adjacency error: {exc}", file=sys.stderr)

        return {"seeded": seeded, "skipped": skipped}

    def detect_unknown_unknowns(self, query: str, n: int = 5) -> list[dict]:
        """Surface curriculum topics adjacent to the query that have never been touched.

        These are the blind spots the learner doesn't know they have: topics in the same
        ACGME milestone/subdomain that co-occur clinically but haven't been studied yet.

        For each matched topic, checks if any adjacent topic in topic_adjacency or in the
        same curriculum subdomain has encounter_count = 0.

        Returns list of dicts:
            {topic, domain, subdomain, priority, acgme_milestone, adjacency_source, adjacent_to}
        """
        try:
            raw_topics = self.extract_topics_from_query(query)
            if len(raw_topics) <= 1:
                _extra = self._fuzzy_find_topics_in_query(query)
                for et in _extra:
                    norm = self._normalize_topic(et)
                    if norm not in [self._normalize_topic(r) for r in raw_topics]:
                        raw_topics.append(et)

            # Find matching curriculum topics for the query using fuzzy text match on topic_name
            matched_curriculum = []
            for raw in raw_topics:
                canonical = self._normalize_topic(raw)
                # Match against display_name (which stores the natural language version)
                rows = self.conn.execute(
                    """SELECT ct.topic_name, ct.subdomain, ct.domain, ct.acgme_milestone,
                              ct.curriculum_id
                       FROM curriculum_topics ct
                       WHERE LOWER(ct.display_name) LIKE ?
                          OR LOWER(ct.topic_name) LIKE ?
                       LIMIT 3""",
                    (f"%{canonical}%", f"%{canonical.replace(' ', '_')}%"),
                ).fetchall()
                matched_curriculum.extend(rows)
                # Also try matching via the topics table (via curriculum_id)
                t_row = self._find_topic(canonical)
                if t_row and t_row.get("curriculum_id"):
                    ct_row2 = self.conn.execute(
                        "SELECT * FROM curriculum_topics WHERE curriculum_id = ?",
                        (t_row["curriculum_id"],),
                    ).fetchone()
                    if ct_row2:
                        matched_curriculum.append(ct_row2)

            # Deduplicate by curriculum_id
            seen_cids: set[int] = set()
            deduped_curriculum = []
            for r in matched_curriculum:
                cid = r["curriculum_id"] if isinstance(r, dict) else r["curriculum_id"]
                if cid not in seen_cids:
                    seen_cids.add(cid)
                    deduped_curriculum.append(r)
            matched_curriculum = deduped_curriculum

            if not matched_curriculum:
                return []

            # For each matched topic, find adjacent topics never studied
            results: list[dict] = []
            seen: set[str] = set()

            for ct_row in matched_curriculum:
                # Use milestone > domain as proximity grouping
                group_val = (ct_row["acgme_milestone"] or "").strip() or (ct_row["domain"] or "").strip()
                group_col = "acgme_milestone" if (ct_row["acgme_milestone"] or "").strip() else "domain"
                if not group_val:
                    continue

                adjacent_rows = self.conn.execute(
                    f"""SELECT ct2.topic_name, ct2.display_name, ct2.domain, ct2.subdomain,
                               ct2.priority, ct2.acgme_milestone,
                               COALESCE(t.encounter_count, 0) AS enc
                       FROM curriculum_topics ct2
                       LEFT JOIN topics t ON t.curriculum_id = ct2.curriculum_id
                       WHERE ct2.{group_col} = ? AND ct2.curriculum_id != ?
                         AND COALESCE(t.encounter_count, 0) = 0
                       ORDER BY ct2.priority ASC
                       LIMIT 10""",
                    (group_val, ct_row["curriculum_id"]),
                ).fetchall()

                for adj in adjacent_rows:
                    tn = adj["topic_name"]
                    if tn in seen:
                        continue
                    seen.add(tn)
                    display = adj["display_name"] or tn
                    results.append({
                        "topic": display,
                        "topic_slug": tn,
                        "domain": adj["domain"] or "",
                        "subdomain": adj["subdomain"] or "",
                        "priority": adj["priority"] or 2,
                        "acgme_milestone": adj["acgme_milestone"] or "",
                        "adjacency_source": group_col,
                        "adjacent_to": ct_row["topic_name"],
                    })

            # Sort by priority (1=most important first)
            results.sort(key=lambda x: x["priority"])
            return results[:n]

        except Exception as exc:
            print(f"[knowledge_graph] detect_unknown_unknowns error: {exc}", file=sys.stderr)
            return []

    # Cognitive theme keywords for misconception clustering
    _CLUSTER_KEYWORDS: dict[str, list[str]] = {
        "mechanism_gap": ["mechanism", "pathway", "physiology", "pathophysiology", "biology",
                          "receptor", "cascade", "process", "how", "why", "causes"],
        "context_misapplication": ["context", "setting", "scenario", "condition", "patient",
                                   "apply", "confusion", "confus", "distinct", "difference"],
        "threshold_anchor": ["threshold", "value", "dose", "number", "level", "range",
                             "mmhg", "mg", "kg", "ml", "percent", "%", "units", "measure"],
        "anatomical_ambiguity": ["anatomy", "structure", "location", "border", "adjacent",
                                 "relation", "landmark", "space", "vessel", "nerve", "tract"],
        "classification_mismatch": ["grade", "stage", "class", "type", "category", "system",
                                    "criterion", "criteria", "classification", "scale"],
        "temporal_confusion": ["timing", "sequence", "order", "first", "before", "after",
                               "step", "phase", "day", "hour", "week", "interval"],
    }

    def misconception_clusters(self) -> list[dict]:
        """Group root_cause descriptions by cognitive theme using keyword matching.

        Returns a clustered view of why the learner's errors occur — reveals whether
        gaps stem from a single underlying cognitive deficit (high-leverage intervention)
        or scattered content gaps (require individual remediation per concept).

        Returns list of dicts sorted by concept_count DESC:
            {cluster, label, concept_count, sample_root_causes, concepts, intervention}
        """
        try:
            rows = self.conn.execute(
                """SELECT cm.concept_text, cm.root_cause, cm.error_process,
                          t.canonical_name AS topic, t.category
                   FROM concept_mastery cm
                   JOIN topics t ON cm.topic_id = t.topic_id
                   WHERE cm.status IN ('unknown', 'due')
                     AND cm.root_cause IS NOT NULL AND cm.root_cause != ''""",
            ).fetchall()

            clusters: dict[str, list[dict]] = {k: [] for k in self._CLUSTER_KEYWORDS}
            clusters["other"] = []

            for row in rows:
                rc = (row["root_cause"] or "").lower()
                matched = False
                for cluster, keywords in self._CLUSTER_KEYWORDS.items():
                    if any(kw in rc for kw in keywords):
                        clusters[cluster].append({
                            "concept": row["concept_text"],
                            "topic": row["topic"],
                            "root_cause": row["root_cause"],
                            "error_process": row["error_process"] or "",
                        })
                        matched = True
                        break
                if not matched:
                    clusters["other"].append({
                        "concept": row["concept_text"],
                        "topic": row["topic"],
                        "root_cause": row["root_cause"],
                        "error_process": row["error_process"] or "",
                    })

            _labels = {
                "mechanism_gap": "Mechanistic understanding gaps",
                "context_misapplication": "Context/application mismatches",
                "threshold_anchor": "Numerical anchor errors",
                "anatomical_ambiguity": "Anatomical confusion",
                "classification_mismatch": "Classification system errors",
                "temporal_confusion": "Timing/sequencing errors",
                "other": "Uncategorised root causes",
            }
            _interventions = {
                "mechanism_gap": "Teach the biological pathway first; derive all management from it.",
                "context_misapplication": "Drill context-switching: same concept, different patient scenarios.",
                "threshold_anchor": "Rapid-fire value recall drill; make these automatic before reasoning.",
                "anatomical_ambiguity": "Side-by-side anatomical diagrams; enforce landmark naming.",
                "classification_mismatch": "One system at a time; explicit side-by-side comparison table.",
                "temporal_confusion": "Timeline visualization for each sequence; narrate steps aloud.",
                "other": "Individual review of each root cause — no single intervention applies.",
            }

            results = []
            for cluster, entries in clusters.items():
                if not entries:
                    continue
                sample = [e["root_cause"][:80] for e in entries[:3]]
                results.append({
                    "cluster": cluster,
                    "label": _labels.get(cluster, cluster),
                    "concept_count": len(entries),
                    "concepts": [e["concept"] for e in entries[:10]],
                    "sample_root_causes": sample,
                    "intervention": _interventions.get(cluster, ""),
                })

            results.sort(key=lambda x: x["concept_count"], reverse=True)
            return results

        except Exception as exc:
            print(f"[knowledge_graph] misconception_clusters error: {exc}", file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    # Iteration 4: Retroactive topic specificity backfill utility
    # ------------------------------------------------------------------

    def backfill_topic_specificity(self) -> dict:
        """Backfill specificity_level and clinical_context for existing topics.

        For the 671 existing topics with specificity_level=1, run
        validate_topic_specificity() and update in-place. Does not rename topics
        or orphan signal_events — only updates metadata columns.

        Returns {"updated": N, "already_specific": M}
        """
        updated = 0
        already_specific = 0
        try:
            rows = self.conn.execute(
                "SELECT topic_id, canonical_name FROM topics WHERE specificity_level = 1"
            ).fetchall()
            for row in rows:
                result = self.validate_topic_specificity(row["canonical_name"])
                level = result["specificity_level"]
                if level > 1:
                    # Extract clinical context: text after the first "in ", "for ", "post-", etc.
                    lower = row["canonical_name"].lower()
                    context = ""
                    for marker in [" in ", " for ", " after ", " post-", " following ",
                                   " during ", " with ", " vs ", " versus "]:
                        idx = lower.find(marker)
                        if idx >= 0:
                            context = row["canonical_name"][idx + len(marker):].strip()
                            break
                    with self.conn:
                        self.conn.execute(
                            "UPDATE topics SET specificity_level = ?, clinical_context = ? WHERE topic_id = ?",
                            (level, context, row["topic_id"]),
                        )
                    updated += 1
                else:
                    already_specific += 1  # still level 1 by assessment
            self.conn.commit()
        except Exception as exc:
            print(f"[knowledge_graph] backfill_topic_specificity error: {exc}", file=sys.stderr)
        return {"updated": updated, "already_specific": already_specific}

    # ------------------------------------------------------------------
    # Obsidian Redesign — Error Atlas, Concept Stubs, ACGME Readiness
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_short_concept_name(concept_text: str) -> str:
        """Extract a short display name from a full concept description.

        Priority:
        1. ALL-CAPS abbreviation inside parentheses (2–6 chars), e.g. (CSW)
        2. First word if it is an ALL-CAPS abbreviation (2–6 chars)
        3. First 3 significant words (stopwords stripped), title-cased
        """
        # 1. Abbreviation in parens
        m = re.search(r'\(([A-Z]{2,6})\)', concept_text)
        if m:
            return m.group(1)
        # 2. First word looks like an abbreviation
        first = concept_text.split()[0].strip('(),;:') if concept_text.split() else ""
        if re.match(r'^[A-Z]{2,6}$', first):
            return first
        # 3. First 3 significant words
        _STOP = {'the', 'a', 'an', 'of', 'in', 'for', 'and', 'or', 'at', 'vs',
                 'to', 'is', 'are', 'was', 'with', 'by', 'from', 'on', 'after',
                 'during', 'following', 'post', 'pre'}
        words = [w.strip('(),;:—-') for w in concept_text.split()]
        sig = [w for w in words if w and w.lower() not in _STOP][:3]
        result = ' '.join(sig)
        # Title-case but preserve existing capitalisation where possible
        return result if result else concept_text[:20]

    @staticmethod
    def _stub_filename(display_name: str) -> str:
        """Sanitize a curriculum display_name into an Obsidian-safe filename."""
        name = display_name
        name = re.sub(r':', ' -', name)          # colon → dash
        name = re.sub(r'[/\\]', ' or ', name)    # slash → "or"
        name = name.replace('&', 'and')
        name = re.sub(r'[—–]', '-', name)        # em/en dash → hyphen
        name = re.sub(r'[^\w\s\-\(\)]', '', name)  # strip remaining special chars
        name = re.sub(r'\s+', ' ', name).strip()
        if len(name) > 100:
            name = name[:97] + '...'
        return name + '.md'

    @staticmethod
    def _domain_to_tag(domain: str) -> str:
        """Convert a domain name to a lowercase hyphenated tag."""
        tag = domain.lower()
        tag = re.sub(r'[—–&]', '-', tag)
        tag = re.sub(r'[^\w\s\-]', '', tag)
        tag = re.sub(r'\s+', '-', tag.strip())
        tag = re.sub(r'-+', '-', tag)
        # Shorten long milestone names
        _MAP = {
            'medical-knowledge--neuroanatomy-and-neuroimaging': 'medical-knowledge-neuroanatomy',
            'medical-knowledge--neurosciences-neuropathology-and-neurology': 'medical-knowledge-neurosciences',
            'surgical-treatment-of-epilepsy-and-movement-disorders': 'epilepsy-movement-disorders',
            'pain-and-peripheral-nerve-disorders': 'pain-peripheral-nerve',
            'pediatric-neurological-surgery': 'pediatric',
            'critical-care--general-neurosurgery': 'critical-care',
        }
        return _MAP.get(tag, tag)

    def generate_error_atlas(self) -> list[dict]:
        """Export all confusable pairs for Error Atlas vault generation.

        Merges confusion_matrix.json + concept_relationships WHERE relationship =
        'confusable_with'. For each pair queries concept_mastery for any logged
        misconceptions matching either concept (case-insensitive substring).

        Returns list of dicts:
          slug, short_a, short_b, concept_a, concept_b, disambiguation_axis,
          source, first_added, times_confused, misconceptions_a, misconceptions_b
        """
        pairs: list[dict] = []
        seen: set[frozenset] = set()  # dedup by (normalized_a, normalized_b)

        # ── Source 1: confusion_matrix.json ──
        cm_path = BASE_DIR / "data" / "confusion_matrix.json"
        if cm_path.exists():
            try:
                raw = json.loads(cm_path.read_text(encoding="utf-8"))
                for p in raw:
                    ca = p.get("concept_a", "")
                    cb = p.get("concept_b", "")
                    key = frozenset([ca.lower()[:40], cb.lower()[:40]])
                    if key in seen:
                        continue
                    seen.add(key)
                    pairs.append({
                        "concept_a": ca,
                        "concept_b": cb,
                        "disambiguation_axis": p.get("disambiguation_axis", ""),
                        "source": p.get("source", "manual"),
                        "first_added": str(p.get("first_added", ""))[:10],
                    })
            except Exception as exc:
                print(f"[generate_error_atlas] confusion_matrix.json error: {exc}", file=sys.stderr)

        # ── Source 2: concept_relationships (confusable_with) ──
        try:
            rows = self.conn.execute(
                """SELECT concept_a, concept_b, notes, source, created_ts
                   FROM concept_relationships WHERE relationship = 'confusable_with'"""
            ).fetchall()
            for row in rows:
                ca, cb = row["concept_a"], row["concept_b"]
                key = frozenset([ca.lower()[:40], cb.lower()[:40]])
                if key in seen:
                    continue
                seen.add(key)
                pairs.append({
                    "concept_a": ca,
                    "concept_b": cb,
                    "disambiguation_axis": row["notes"] or "",
                    "source": row["source"] or "kg",
                    "first_added": str(row["created_ts"] or "")[:10],
                })
        except Exception as exc:
            print(f"[generate_error_atlas] concept_relationships error: {exc}", file=sys.stderr)

        # ── Enrich each pair with short names, slug, misconception records ──
        result = []
        for p in pairs:
            short_a = self._extract_short_concept_name(p["concept_a"])
            short_b = self._extract_short_concept_name(p["concept_b"])
            slug_raw = f"{short_a}_vs_{short_b}".lower().replace(" ", "_")
            slug = re.sub(r'[^\w]', '', slug_raw)

            # Query concept_mastery for misconceptions matching either concept
            misconceptions_a: list[dict] = []
            misconceptions_b: list[dict] = []
            times_confused = 0
            try:
                # Use first significant word as search key (avoid over-broad matches)
                key_a = short_a.split()[0].lower() if short_a.split() else ""
                key_b = short_b.split()[0].lower() if short_b.split() else ""
                if key_a:
                    rows_a = self.conn.execute(
                        """SELECT concept_text, misconception, times_missed, last_updated
                           FROM concept_mastery
                           WHERE LOWER(misconception) LIKE ? AND times_missed > 0
                           ORDER BY times_missed DESC LIMIT 3""",
                        (f"%{key_a}%",)
                    ).fetchall()
                    misconceptions_a = [
                        {"concept": r["concept_text"], "misconception": r["misconception"],
                         "times_missed": r["times_missed"], "last_updated": str(r["last_updated"] or "")[:10]}
                        for r in rows_a
                    ]
                    times_confused += sum(r["times_missed"] for r in rows_a)
                if key_b:
                    rows_b = self.conn.execute(
                        """SELECT concept_text, misconception, times_missed, last_updated
                           FROM concept_mastery
                           WHERE LOWER(misconception) LIKE ? AND times_missed > 0
                           ORDER BY times_missed DESC LIMIT 3""",
                        (f"%{key_b}%",)
                    ).fetchall()
                    misconceptions_b = [
                        {"concept": r["concept_text"], "misconception": r["misconception"],
                         "times_missed": r["times_missed"], "last_updated": str(r["last_updated"] or "")[:10]}
                        for r in rows_b
                    ]
                    times_confused += sum(r["times_missed"] for r in rows_b)
            except Exception:
                pass

            result.append({
                "slug": slug,
                "short_a": short_a,
                "short_b": short_b,
                "concept_a": p["concept_a"],
                "concept_b": p["concept_b"],
                "disambiguation_axis": p["disambiguation_axis"],
                "source": p["source"],
                "first_added": p["first_added"],
                "times_confused": times_confused,
                "misconceptions_a": misconceptions_a,
                "misconceptions_b": misconceptions_b,
            })

        return result

    def export_concept_stubs(self, only_studied: bool = False) -> list[dict]:
        """Export curriculum topics for Obsidian concept stub generation.

        Returns one dict per curriculum topic with all data needed to write a stub
        file. Uses GROUP BY curriculum_id + MAX() aggregation to handle cases where
        multiple topics rows join to the same curriculum_id (KG normalisation artefact).

        Args:
            only_studied: If True, return only topics with encounter_count > 0.
        """
        _DEPTH_LABELS = {0: "not_studied", 1: "surface", 2: "mechanistic",
                         3: "decision-making", 4: "expert", 5: "mastery"}
        _PRIORITY_LABELS = {1: "core", 2: "advanced", 3: "specialty"}

        # Load confusion_matrix.json once for confusable pair matching
        cm_path = BASE_DIR / "data" / "confusion_matrix.json"
        confusion_pairs: list[dict] = []
        if cm_path.exists():
            try:
                confusion_pairs = json.loads(cm_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        where = "WHERE 1=1"
        if only_studied:
            where = "HAVING MAX(COALESCE(t.encounter_count, 0)) > 0"

        try:
            rows = self.conn.execute(
                f"""SELECT ct.curriculum_id,
                           ct.topic_name   AS slug,
                           ct.display_name AS title,
                           ct.domain,
                           ct.acgme_milestone,
                           ct.pgy_target,
                           ct.priority,
                           MAX(COALESCE(t.confidence, 0.0))     AS confidence,
                           MAX(COALESCE(t.encounter_count, 0))  AS encounter_count,
                           MAX(COALESCE(t.depth, 0))            AS depth,
                           MAX(t.last_seen)                     AS last_seen
                    FROM curriculum_topics ct
                    LEFT JOIN topics t ON t.curriculum_id = ct.curriculum_id
                    GROUP BY ct.curriculum_id
                    {where if only_studied else ''}
                    ORDER BY ct.domain, ct.pgy_target, ct.priority"""
            ).fetchall()
        except Exception as exc:
            print(f"[export_concept_stubs] query error: {exc}", file=sys.stderr)
            return []

        # Apply only_studied filter post-query if not in HAVING clause
        if only_studied:
            rows = [r for r in rows if (r["encounter_count"] or 0) > 0]

        result = []
        for row in rows:
            enc = row["encounter_count"] or 0
            conf = round(float(row["confidence"] or 0.0), 4)
            depth = int(row["depth"] or 0)
            pgy = int(row["pgy_target"] or 1)
            priority = int(row["priority"] or 2)
            title = row["title"] or row["slug"] or ""

            # Status
            if enc == 0:
                status = "not_studied"
            elif conf >= 0.15 and depth >= 2:
                status = "known"
            else:
                status = "gap"

            # Confusable atlas entries: any pair whose concept_a or concept_b
            # contains the slug as a case-insensitive substring
            atlas_entries: list[str] = []
            slug_lower = (row["slug"] or "").lower().replace("_", " ")
            for cp in confusion_pairs:
                ca_lower = (cp.get("concept_a") or "").lower()
                cb_lower = (cp.get("concept_b") or "").lower()
                # Match if any word from the slug appears in either concept
                slug_words = [w for w in slug_lower.split() if len(w) > 4]
                if any(w in ca_lower or w in cb_lower for w in slug_words):
                    sa = self._extract_short_concept_name(cp.get("concept_a", ""))
                    sb = self._extract_short_concept_name(cp.get("concept_b", ""))
                    entry = f"{sa} vs {sb}"
                    if entry not in atlas_entries:
                        atlas_entries.append(entry)

            result.append({
                "filename": self._stub_filename(title),
                "title": title,
                "slug": row["slug"] or "",
                "domain": row["domain"] or "",
                "domain_tag": self._domain_to_tag(row["domain"] or ""),
                "acgme_milestone": row["acgme_milestone"] or "",
                "pgy_target": pgy,
                "priority": priority,
                "priority_label": _PRIORITY_LABELS.get(priority, "advanced"),
                "studied": enc > 0,
                "confidence": conf,
                "depth": depth,
                "depth_label": _DEPTH_LABELS.get(depth, "not_studied"),
                "encounter_count": enc,
                "last_studied": str(row["last_seen"] or "")[:10] or None,
                "status": status,
                "confusable_atlas_entries": atlas_entries,
            })

        return result

    def acgme_readiness(self, pgy: int | None = None) -> dict:
        """Generate ACGME readiness data for the given PGY year.

        Filters curriculum_topics WHERE pgy_target <= pgy and aggregates by domain.
        Reads data/pgy_config.json for the default PGY year when pgy is None.

        Returns structured dict with per-domain breakdowns and per-topic study status.
        """
        # Determine PGY year
        if pgy is None:
            config_path = BASE_DIR / "data" / "pgy_config.json"
            try:
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
                pgy = int(cfg.get("current_pgy", 1))
            except Exception:
                pgy = 1

        _DEPTH_LABELS = {0: "Not studied", 1: "Surface", 2: "Mechanistic",
                         3: "Decision-making", 4: "Expert", 5: "Mastery"}

        try:
            rows = self.conn.execute(
                """SELECT ct.curriculum_id, ct.domain, ct.acgme_milestone,
                          ct.display_name, ct.topic_name, ct.priority,
                          ct.pgy_target,
                          MAX(COALESCE(t.confidence, 0.0))    AS confidence,
                          MAX(COALESCE(t.encounter_count, 0)) AS encounter_count,
                          MAX(COALESCE(t.depth, 0))           AS depth,
                          MAX(t.last_seen)                    AS last_seen
                   FROM curriculum_topics ct
                   LEFT JOIN topics t ON t.curriculum_id = ct.curriculum_id
                   WHERE ct.pgy_target <= ?
                   GROUP BY ct.curriculum_id
                   ORDER BY ct.domain, confidence DESC""",
                (pgy,)
            ).fetchall()
        except Exception as exc:
            print(f"[acgme_readiness] query error: {exc}", file=sys.stderr)
            return {"current_pgy": pgy, "total_in_scope": 0, "domains": [], "error": str(exc)}

        # Aggregate
        total_in_scope = len(rows)
        topics_touched = sum(1 for r in rows if (r["encounter_count"] or 0) > 0)
        topics_at_target = sum(
            1 for r in rows
            if (r["confidence"] or 0) >= 0.15 and (r["depth"] or 0) >= 2
        )
        topics_never_studied = total_in_scope - topics_touched

        # Group by domain (preserve ordering of first occurrence)
        from collections import OrderedDict
        domain_map: dict[str, dict] = OrderedDict()
        for row in rows:
            domain = row["domain"] or "General"
            if domain not in domain_map:
                domain_map[domain] = {
                    "domain": domain,
                    "acgme_milestone": row["acgme_milestone"] or "",
                    "total_topics": 0,
                    "topics_touched": 0,
                    "topics_at_target": 0,
                    "coverage_pct": 0.0,
                    "avg_confidence": 0.0,
                    "_conf_sum": 0.0,
                    "_conf_count": 0,
                    "topics": [],
                }
            d = domain_map[domain]
            d["total_topics"] += 1
            enc = row["encounter_count"] or 0
            conf = float(row["confidence"] or 0.0)
            depth = int(row["depth"] or 0)
            studied = enc > 0
            at_target = conf >= 0.15 and depth >= 2

            if studied:
                d["topics_touched"] += 1
                d["_conf_sum"] += conf
                d["_conf_count"] += 1
            if at_target:
                d["topics_at_target"] += 1

            # Build stub filename for wikilink
            title = row["display_name"] or row["topic_name"] or ""
            stub_filename = self._stub_filename(title).replace('.md', '')

            d["topics"].append({
                "display_name": title,
                "slug": row["topic_name"] or "",
                "pgy_target": int(row["pgy_target"] or 1),
                "priority": int(row["priority"] or 2),
                "studied": studied,
                "confidence": round(conf, 4),
                "depth": depth,
                "depth_label": _DEPTH_LABELS.get(depth, "Not studied"),
                "encounter_count": enc,
                "last_studied": str(row["last_seen"] or "")[:10] or None,
                "at_target": at_target,
                "concept_stub": f"Concepts/{stub_filename}",
            })

        # Finalize per-domain stats
        domains = []
        for d in domain_map.values():
            total = d["total_topics"]
            touched = d["topics_touched"]
            d["coverage_pct"] = round(touched / total * 100, 1) if total > 0 else 0.0
            d["avg_confidence"] = round(d["_conf_sum"] / d["_conf_count"], 4) if d["_conf_count"] > 0 else 0.0
            del d["_conf_sum"], d["_conf_count"]
            # Sort topics: studied first (by confidence desc), then unstudied
            d["topics"].sort(key=lambda t: (-int(t["studied"]), -t["confidence"]))
            domains.append(d)

        # Sort domains by coverage_pct ascending (most-needed first)
        domains.sort(key=lambda d: d["coverage_pct"])

        return {
            "current_pgy": pgy,
            "total_in_scope": total_in_scope,
            "topics_at_target": topics_at_target,
            "topics_touched": topics_touched,
            "topics_never_studied": topics_never_studied,
            "coverage_pct": round(topics_at_target / total_in_scope * 100, 1) if total_in_scope > 0 else 0.0,
            "domains": domains,
        }


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
    curriculum_id   INTEGER,
    stability_factor REAL DEFAULT 1.0,
    difficulty      REAL DEFAULT 0.5
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

-- Document study sessions (1:1 with Study Material vault documents)
-- doc_path is vault-relative: e.g. "Study Material/vasospasm_management_20260325.md"
CREATE TABLE IF NOT EXISTS document_sessions (
    doc_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_path            TEXT NOT NULL UNIQUE,
    doc_type            TEXT NOT NULL DEFAULT 'unknown',
    session_count       INTEGER DEFAULT 0,
    first_studied       TEXT,
    last_studied        TEXT,
    total_concepts      INTEGER DEFAULT 0,
    concepts_covered    TEXT DEFAULT '[]',
    concepts_understood TEXT DEFAULT '[]',
    concepts_missed     TEXT DEFAULT '[]',
    coverage_pct        REAL DEFAULT 0.0,
    session_notes       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_doc_sessions_path ON document_sessions(doc_path);

-- Session narratives — forward-looking teaching notes persisted after every learning session.
-- next_session_strategy is the highest-value field: the agent's directive for the NEXT session.
CREATE TABLE IF NOT EXISTS session_narratives (
    narrative_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_ts            TEXT NOT NULL,
    skill                 TEXT NOT NULL,
    topics_json           TEXT DEFAULT '[]',
    summary               TEXT DEFAULT '',
    teaching_successes    TEXT DEFAULT '[]',
    teaching_failures     TEXT DEFAULT '[]',
    next_session_strategy TEXT DEFAULT '',
    key_confusions_json   TEXT DEFAULT '[]',
    depth_profile_json    TEXT DEFAULT '{}',
    duration_turns        INTEGER DEFAULT 0,
    linked_signal_ids     TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_narratives_skill ON session_narratives(skill);
CREATE INDEX IF NOT EXISTS idx_narratives_ts ON session_narratives(session_ts);

-- Concept relationships — prerequisite graph and confusable pairs integrated into the DB.
-- Supersedes confusion_matrix.json for new entries; old entries can be migrated via
-- the migrate_confusion_matrix CLI command.
-- relationship: 'prerequisite_of' | 'confusable_with' | 'extends' | 'differentiates_from'
CREATE TABLE IF NOT EXISTS concept_relationships (
    rel_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_a    TEXT NOT NULL,
    topic_a      TEXT DEFAULT '',
    concept_b    TEXT NOT NULL,
    topic_b      TEXT DEFAULT '',
    relationship TEXT NOT NULL,
    strength     REAL DEFAULT 0.5,
    notes        TEXT DEFAULT '',
    source       TEXT DEFAULT '',
    created_ts   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rel_concept_a ON concept_relationships(concept_a);
CREATE INDEX IF NOT EXISTS idx_rel_concept_b ON concept_relationships(concept_b);
CREATE INDEX IF NOT EXISTS idx_rel_type ON concept_relationships(relationship);

-- Topic adjacency — clinical co-occurrence adjacency for blind spot detection.
-- Populated by auto_seed_topic_adjacency() from curriculum milestone groupings.
CREATE TABLE IF NOT EXISTS topic_adjacency (
    adj_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_a            TEXT NOT NULL,
    topic_b            TEXT NOT NULL,
    domain             TEXT DEFAULT '',
    adjacency_strength REAL DEFAULT 0.5,
    source             TEXT DEFAULT '',  -- 'curriculum_milestone' | 'co_occurrence' | 'manual'
    created_ts         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_adj_a ON topic_adjacency(topic_a);
CREATE INDEX IF NOT EXISTS idx_adj_b ON topic_adjacency(topic_b);
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
    p_lb.add_argument("--calibration", default="", help='JSON list of calibration signals: [{"concept":"...","response_confidence":"high|low","correct":true|false}]')

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

    # cognitive_patterns (Refinement #2 — process-level error detection)
    subparsers.add_parser("cognitive_patterns", help="Detect recurring cognitive error types across topics (JSON)")

    # calibration_profile (Refinement #1 — confidence calibration)
    subparsers.add_parser("calibration_profile", help="Compute confidence calibration profile from bootcamp data (JSON)")

    # confusable_pairs (Refinement #3 — proactive discrimination)
    cp_parser = subparsers.add_parser("confusable_pairs", help="Query confusable concept pairs from confusion matrix (JSON)")
    cp_parser.add_argument("--topic", default="", help="Filter pairs by topic (substring match)")

    # doc_status — read document study state
    p_ds = subparsers.add_parser("doc_status", help="Get study status for a Study Material document (JSON output)")
    p_ds.add_argument("doc_path", type=str, help="Vault-relative path, e.g. 'Study Material/vasospasm_20260325.md'")

    # ── Redesign Phase: new subcommands ──

    # concept_review_queue — SRS-scheduled concepts due for review
    crq_parser = subparsers.add_parser("concept_review_queue",
        help="Concepts due for SM-2 spaced review (JSON output)")
    crq_parser.add_argument("--n", type=int, default=10, help="Max concepts to return")
    crq_parser.add_argument("--domain", default=None, help="Filter by curriculum domain")

    # log_session_narrative — persist teaching narrative at session end
    p_sn = subparsers.add_parser("log_session_narrative",
        help="Persist a session-level teaching narrative with next-session strategy")
    p_sn.add_argument("--skill", required=True, help="Skill that produced this session")
    p_sn.add_argument("--topics", required=True,
        help="Comma-separated topic names covered")
    p_sn.add_argument("--summary", default="", help="1-2 sentence session recap")
    p_sn.add_argument("--teaching-failures", default="",
        help='JSON list: [{"concept":"...","attempted":"...","why_failed":"..."}]')
    p_sn.add_argument("--teaching-successes", default="",
        help='JSON list of strings describing what worked')
    p_sn.add_argument("--strategy", default="", dest="next_session_strategy",
        help="Forward directive for the NEXT session on these topics")
    p_sn.add_argument("--key-confusions", default="",
        help='JSON list: [{"concept_a":"...","concept_b":"...","disambiguation_axis":"..."}]')
    p_sn.add_argument("--depth-profile", default="",
        help='JSON dict: {"topic": depth_achieved}')
    p_sn.add_argument("--turns", type=int, default=0, dest="duration_turns",
        help="Number of interaction turns in session")
    p_sn.add_argument("--session-success-rate", type=float, default=None, dest="session_success_rate",
        help="Session success rate 0.0–1.0 (understood / total concepts). Used for ZPD tracking.")

    # last_session_narrative — retrieve most recent session narrative
    p_lsn = subparsers.add_parser("last_session_narrative",
        help="Retrieve most recent session narrative, optionally filtered (JSON output)")
    p_lsn.add_argument("--skill", default=None, help="Filter by skill")
    p_lsn.add_argument("--topic", default=None, help="Filter by topic (substring)")

    # blocking_gaps — gaps with prerequisite chains
    p_bg = subparsers.add_parser("blocking_gaps",
        help="Show gaps with unmet prerequisite concepts (JSON output)")
    p_bg.add_argument("--topic", required=True, help="Topic name to check")

    # concept_chain — prerequisite + extension chain for a concept
    p_cc = subparsers.add_parser("concept_chain",
        help="Show prerequisite and extension chain for a concept (JSON output)")
    p_cc.add_argument("--concept", required=True, help="Concept text to look up")
    p_cc.add_argument("--topic", default=None, help="Topic context (optional)")

    # add_concept_relationship — add a relationship between two concepts
    p_acr = subparsers.add_parser("add_concept_relationship",
        help="Add a relationship between two concepts (prerequisite, confusable, etc.)")
    p_acr.add_argument("--a", required=True, dest="concept_a", help="First concept")
    p_acr.add_argument("--b", required=True, dest="concept_b", help="Second concept")
    p_acr.add_argument("--type", required=True, dest="relationship",
        choices=["prerequisite_of", "confusable_with", "extends", "differentiates_from"],
        help="Relationship type")
    p_acr.add_argument("--topic-a", default="", help="Topic for concept A (optional)")
    p_acr.add_argument("--topic-b", default="", help="Topic for concept B (optional)")
    p_acr.add_argument("--notes", default="", help="Disambiguation axis or notes")
    p_acr.add_argument("--strength", type=float, default=0.5, help="Relationship strength 0-1")

    # topic_specificity_check — validate topic name granularity
    p_tsc = subparsers.add_parser("topic_specificity_check",
        help="Validate topic name specificity (JSON output)")
    p_tsc.add_argument("topic_name", type=str, help="Topic name to check")

    # fine_grained_gaps — concept-level gaps with root_cause + error_process
    p_fgg = subparsers.add_parser("fine_grained_gaps",
        help="Concept-level gaps with root_cause and error_process (JSON output)")
    p_fgg.add_argument("--top", type=int, default=10, help="Max gaps to return")
    p_fgg.add_argument("--domain", default=None, help="Filter by domain")

    # migrate_confusion_matrix — one-time migration from JSON to DB
    subparsers.add_parser("migrate_confusion_matrix",
        help="Migrate confusion_matrix.json into concept_relationships table (idempotent)")

    # ── Iteration 2: Prerequisite seeding ──
    subparsers.add_parser("seed_prerequisites",
        help="Auto-seed prerequisite + confusable relationships from gap co-occurrence (JSON output)")

    # ── Iteration 3: ZPD + learning velocity ──
    subparsers.add_parser("difficulty_target",
        help="ZPD-based difficulty recommendation from recent session success rates (JSON output)")

    p_lv = subparsers.add_parser("learning_velocity",
        help="Per-domain confidence change rate over recent sessions (JSON output)")
    p_lv.add_argument("--domain", default=None, help="Filter by domain")
    p_lv.add_argument("--n", type=int, default=10, help="Number of sessions to analyze")

    # ── Iteration 4: Blind spot detection ──
    p_uu = subparsers.add_parser("unknown_unknowns",
        help="Adjacent curriculum topics never studied (blind spot detection, JSON output)")
    p_uu.add_argument("--topic", required=True, help="Topic or query to find blind spots adjacent to")
    p_uu.add_argument("--n", type=int, default=5, help="Max results")

    subparsers.add_parser("misconception_clusters",
        help="Group root_cause descriptions by cognitive theme (JSON output)")

    subparsers.add_parser("seed_topic_adjacency",
        help="Seed topic_adjacency table from curriculum milestone groupings (idempotent)")

    subparsers.add_parser("backfill_specificity",
        help="Backfill specificity_level and clinical_context for all existing topics (JSON output)")

    subparsers.add_parser("backfill_topic_fingerprints",
        help="Backfill topic_fingerprint for existing session_narratives (Round 3, idempotent)")

    # ── Obsidian Redesign: Error Atlas, Concept Stubs, ACGME Readiness ──

    subparsers.add_parser("generate_error_atlas",
        help="Export confusable pairs for Error Atlas vault generation (JSON output)")

    p_ecs = subparsers.add_parser("export_concept_stubs",
        help="Export curriculum topics for Obsidian concept stub generation (JSON output)")
    p_ecs.add_argument("--only-studied", action="store_true",
        help="Return only topics with encounter_count > 0")

    p_ar = subparsers.add_parser("acgme_readiness",
        help="ACGME readiness data for current PGY year (JSON output)")
    p_ar.add_argument("--pgy", type=int, default=None,
        help="PGY year to filter to (default: reads data/pgy_config.json, falls back to 1)")

    # log_doc_progress — upsert document study progress
    p_ldp = subparsers.add_parser("log_doc_progress", help="Upsert document study progress (heartbeat + session-end)")
    p_ldp.add_argument("--doc", required=True, metavar="DOC_PATH",
                        help="Vault-relative path to the Study Material document")
    p_ldp.add_argument("--doc-type", default="unknown",
                        help="Source type: report, operative-guide, study-material, other")
    p_ldp.add_argument("--covered", default="",
                        help="Comma-separated concept/question IDs covered this session")
    p_ldp.add_argument("--understood", default="",
                        help="Comma-separated concept/question IDs confirmed correct")
    p_ldp.add_argument("--missed", default="",
                        help='JSON list: [{"concept":"...","error_type":"...","misconception":"..."}] or comma-separated strings')
    p_ldp.add_argument("--coverage-pct", type=float, default=0.0, dest="coverage_pct",
                        help="Cumulative coverage percentage (0–100)")
    p_ldp.add_argument("--total-concepts", type=int, default=0, dest="total_concepts",
                        help="Total concepts/questions in the document")

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

            # Parse calibration signals if provided [Refinement #1]
            if args.calibration:
                try:
                    cal_data = json.loads(args.calibration)
                    if isinstance(cal_data, list) and cal_data:
                        meta["calibration"] = cal_data
                except json.JSONDecodeError:
                    print("Warning: --calibration must be valid JSON, ignoring", file=sys.stderr)

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

            cal_count = len(meta.get("calibration", []))
            cal_msg = f", {cal_count} calibration signal(s)" if cal_count else ""
            print(f"Logged {len(topics)} topic(s) and {len(weaknesses)} weakness(es) from bootcamp module '{args.module}'{cal_msg}")

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
            recs = kg.generate_recommendations(
                n=args.top,
                rotation_filter=args.rotation,
                apply_decay_first=True,
            )
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

        elif args.command == "cognitive_patterns":
            data = kg.detect_cognitive_patterns()
            print(json.dumps({"patterns": data, "count": len(data)}, indent=2, default=str))

        elif args.command == "calibration_profile":
            data = kg.compute_calibration_profile()
            print(json.dumps(data, indent=2, default=str))

        elif args.command == "confusable_pairs":
            data = kg.get_confusable_pairs(topic=args.topic)
            print(json.dumps({"pairs": data, "count": len(data)}, indent=2, default=str))

        elif args.command == "doc_status":
            data = kg.get_doc_status(args.doc_path)
            print(json.dumps(data, indent=2, default=str))

        elif args.command == "log_doc_progress":
            covered = [c.strip() for c in args.covered.split(",") if c.strip()] if args.covered else []
            understood = [c.strip() for c in args.understood.split(",") if c.strip()] if args.understood else []
            missed: list = []
            if args.missed:
                try:
                    missed = json.loads(args.missed)
                except json.JSONDecodeError:
                    missed = [c.strip() for c in args.missed.split(",") if c.strip()]
            kg.log_doc_progress(
                doc_path=args.doc,
                doc_type=args.doc_type,
                covered=covered,
                understood=understood,
                missed=missed,
                coverage_pct=args.coverage_pct,
                total_concepts=args.total_concepts,
            )
            print(
                f"Logged doc progress: {args.doc} | "
                f"{args.coverage_pct:.0f}% coverage | "
                f"{len(understood)} understood | {len(missed)} missed"
            )

        # ── Redesign Phase: new command handlers ──

        elif args.command == "concept_review_queue":
            data = kg.concept_review_queue_srs(n=args.n, domain=args.domain)
            print(json.dumps({"due_concepts": data, "count": len(data)}, indent=2, default=str))

        elif args.command == "log_session_narrative":
            topics = [t.strip() for t in args.topics.split(",") if t.strip()]
            teaching_failures = []
            if args.teaching_failures:
                try:
                    teaching_failures = json.loads(args.teaching_failures)
                except json.JSONDecodeError:
                    print("Warning: --teaching-failures must be valid JSON, ignoring", file=sys.stderr)
            teaching_successes = []
            if args.teaching_successes:
                try:
                    teaching_successes = json.loads(args.teaching_successes)
                except json.JSONDecodeError:
                    teaching_successes = [s.strip() for s in args.teaching_successes.split("|") if s.strip()]
            key_confusions = []
            if args.key_confusions:
                try:
                    key_confusions = json.loads(args.key_confusions)
                except json.JSONDecodeError:
                    print("Warning: --key-confusions must be valid JSON, ignoring", file=sys.stderr)
            depth_profile = {}
            if args.depth_profile:
                try:
                    depth_profile = json.loads(args.depth_profile)
                except json.JSONDecodeError:
                    print("Warning: --depth-profile must be valid JSON, ignoring", file=sys.stderr)
            nid = kg.log_session_narrative(
                skill=args.skill,
                topics=topics,
                summary=args.summary,
                teaching_successes=teaching_successes,
                teaching_failures=teaching_failures,
                next_session_strategy=args.next_session_strategy,
                key_confusions=key_confusions,
                depth_profile=depth_profile,
                duration_turns=args.duration_turns,
                session_success_rate=getattr(args, "session_success_rate", None),
            )
            print(f"Logged session narrative (id={nid}) for skill='{args.skill}', {len(topics)} topic(s)")

        elif args.command == "last_session_narrative":
            data = kg.get_last_session_narrative(skill=args.skill, topic=args.topic)
            if data:
                print(json.dumps(data, indent=2, default=str))
            else:
                print(json.dumps({"status": "none_found"}, indent=2))

        elif args.command == "blocking_gaps":
            data = kg.get_blocking_gaps(args.topic)
            print(json.dumps({"blocking_gaps": data, "count": len(data)}, indent=2, default=str))

        elif args.command == "concept_chain":
            data = kg.concept_chain(args.concept, topic_name=args.topic)
            print(json.dumps(data, indent=2, default=str))

        elif args.command == "add_concept_relationship":
            kg.add_concept_relationship(
                concept_a=args.concept_a,
                concept_b=args.concept_b,
                relationship=args.relationship,
                topic_a=args.topic_a,
                topic_b=args.topic_b,
                strength=args.strength,
                notes=args.notes,
                source="manual",
            )
            print(f"Added relationship: '{args.concept_a}' {args.relationship} '{args.concept_b}'")

        elif args.command == "topic_specificity_check":
            data = kg.validate_topic_specificity(args.topic_name)
            print(json.dumps(data, indent=2, default=str))

        elif args.command == "fine_grained_gaps":
            data = kg.fine_grained_gaps(top=args.top, domain=args.domain)
            print(json.dumps({"gaps": data, "count": len(data)}, indent=2, default=str))

        elif args.command == "migrate_confusion_matrix":
            result = kg.migrate_confusion_matrix()
            print(f"Migration complete: {result.get('migrated', 0)} pairs migrated, "
                  f"{result.get('skipped', 0)} skipped (already present)")
            if result.get("error"):
                print(f"Error: {result['error']}", file=sys.stderr)

        # ── Iteration 2: Prerequisite seeding ──
        elif args.command == "seed_prerequisites":
            result = kg.seed_prerequisites_from_cooccurrence()
            print(json.dumps(result, indent=2))

        # ── Iteration 3: ZPD + learning velocity ──
        elif args.command == "difficulty_target":
            data = kg.recommend_difficulty_target()
            print(json.dumps(data, indent=2, default=str))

        elif args.command == "learning_velocity":
            data = kg.learning_velocity(domain=args.domain, n_sessions=args.n)
            print(json.dumps(data, indent=2, default=str))

        # ── Iteration 4: Blind spot detection ──
        elif args.command == "unknown_unknowns":
            data = kg.detect_unknown_unknowns(query=args.topic, n=args.n)
            print(json.dumps({"unknown_unknowns": data, "count": len(data)}, indent=2, default=str))

        elif args.command == "misconception_clusters":
            data = kg.misconception_clusters()
            print(json.dumps({"clusters": data, "count": len(data)}, indent=2, default=str))

        elif args.command == "seed_topic_adjacency":
            result = kg.auto_seed_topic_adjacency()
            print(json.dumps(result, indent=2))

        elif args.command == "backfill_specificity":
            result = kg.backfill_topic_specificity()
            print(json.dumps(result, indent=2))

        elif args.command == "backfill_topic_fingerprints":
            result = kg.backfill_topic_fingerprints()
            print(json.dumps(result, indent=2))

        # ── Obsidian Redesign commands ──

        elif args.command == "generate_error_atlas":
            data = kg.generate_error_atlas()
            print(json.dumps(data, indent=2, default=str))

        elif args.command == "export_concept_stubs":
            data = kg.export_concept_stubs(only_studied=args.only_studied)
            print(json.dumps(data, indent=2, default=str))

        elif args.command == "acgme_readiness":
            data = kg.acgme_readiness(pgy=args.pgy)
            print(json.dumps(data, indent=2, default=str))

    finally:
        kg.close()


if __name__ == "__main__":
    main()
