#!/usr/bin/env python3
"""Claim-centered learner memory ledger.

This is the active study memory layer. It is designed around a small staged
interface for agents:

1. exchanges preserve raw Q/A evidence.
2. claim_results capture one assessed cognitive claim per exchange.
3. claim_state is the compact learner model.
4. state_events preserve history.
5. retrieval_cards are the agent-facing triage surface.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memory_operations import (
    CurationError,
    apply_curation_payload,
    build_curation_candidates,
    curated_summaries_for_summary,
    curation_status,
    graph_signals_for_summary,
    mark_session_counted,
    shadow_rule_signals_for_summary,
)
from reference_graph import (
    context_graph_focus_for_summary,
    ensure_reference_graph_schema,
    load_reference_graph_file,
)
from service_memory import (
    SERVICE_SCHEMA_SQL,
    current_rotation,
    end_rotation,
    list_rotations,
    service_for_rotation as _service_for_rotation,
    service_recall,
    service_rubric_view,
    site_for_rotation as _site_for_rotation,
    start_rotation,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "study_memory.db"
LOW_STAKES_REFERENCE_SKILLS = frozenset({"quick-answer"})
LOW_STAKES_TEACHING_INTENTS = frozenset({"quick_answer_reference"})

# Skills that produce a vault artifact rather than testing the learner. Their
# log-answer call is a discoverability anchor only: it records that the file
# exists and when, but must NOT create durable claim_state (the learner has not
# reviewed the content yet — that happens later via /study-review pointed at the
# file). They never count toward the curation threshold and are not curation
# evidence (no learner performance to synthesize).
ARTIFACT_ANCHOR_SKILLS = frozenset({"generate-report", "intraoperative-guide", "brain-dump"})

# Skills whose ended sessions must NOT advance the rolling curation counter.
# quick-answer is low-stakes reference; study-material/grand-rounds are
# generative skills (drill/rehearsal are incidental, not the purpose);
# artifact-anchor skills never represent a review session at all. Study-material
# and grand-rounds drill answers remain eligible curation *evidence* — only the
# trigger counter is suppressed.
CURATION_EXCLUDED_SKILLS = (
    LOW_STAKES_REFERENCE_SKILLS
    | ARTIFACT_ANCHOR_SKILLS
    | frozenset({"study-material", "grand-rounds"})
)

VALID_GAP_TYPES = frozenset({
    "conceptual_confusion",
    "numerical_recall",
    "cross_contamination",
    "application_failure",
    "reasoning_gap",
    "omission",
})
VALID_ANSWER_MODES = frozenset({"unaided", "prompted", "after_hint", "after_teaching", "self_corrected"})
VALID_CONFIDENCE_OBSERVATIONS = frozenset({"low", "medium", "high", "hesitant", "fluent"})
VALID_TEACHING_MOVES = frozenset({
    "changed_frame_retest",
    "contrastive_drill",
    "initial_probe",
    "mechanism_first",
    "order_set",
    "other",
    "premortem",
    "visual_probe",
})
MAX_CONCEPT_LABEL_CHARS = 140
MAX_CONCEPT_LABEL_WORDS = 16

STOPWORDS = frozenset(
    "the a an of in for with and or to on by is at as it its from that this "
    "after before per via vs versus during over under into onto management"
    .split()
)


def _json_dumps(payload: object, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(payload, indent=2)
    return json.dumps(payload, separators=(",", ":"))


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    parent_topic_id INTEGER,
    primary_doc_path TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(parent_topic_id) REFERENCES topics(id)
);

CREATE TABLE IF NOT EXISTS topic_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
    alias TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT 'resolver',
    confidence REAL NOT NULL DEFAULT 1.0,
    FOREIGN KEY(topic_id) REFERENCES topics(id)
);
CREATE INDEX IF NOT EXISTS idx_memory_topic_aliases_topic ON topic_aliases(topic_id);

CREATE TABLE IF NOT EXISTS topic_redirects (
    alias_slug TEXT PRIMARY KEY,
    target_topic_id INTEGER NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(target_topic_id) REFERENCES topics(id)
);

CREATE TABLE IF NOT EXISTS concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
    canonical_slug TEXT NOT NULL,
    display_name TEXT NOT NULL,
    inventory_concept_id TEXT,
    created_at TEXT NOT NULL DEFAULT '',
    UNIQUE(topic_id, canonical_slug),
    FOREIGN KEY(topic_id) REFERENCES topics(id)
);
CREATE INDEX IF NOT EXISTS idx_memory_concepts_topic ON concepts(topic_id);

CREATE TABLE IF NOT EXISTS concept_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'agent',
    confidence REAL NOT NULL DEFAULT 1.0,
    UNIQUE(concept_id, alias),
    FOREIGN KEY(concept_id) REFERENCES concepts(id)
);
CREATE INDEX IF NOT EXISTS idx_memory_concept_aliases_alias ON concept_aliases(alias);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    started TEXT NOT NULL,
    ended TEXT DEFAULT '',
    skill TEXT DEFAULT '',
    primary_topic_id INTEGER,
    doc_path TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    next_strategy TEXT DEFAULT '',
    stats_json TEXT DEFAULT '{}',
    FOREIGN KEY(primary_topic_id) REFERENCES topics(id)
);

CREATE TABLE IF NOT EXISTS session_topics (
    session_id TEXT NOT NULL,
    topic_id INTEGER NOT NULL,
    PRIMARY KEY(session_id, topic_id),
    FOREIGN KEY(topic_id) REFERENCES topics(id)
);

CREATE TABLE IF NOT EXISTS exchanges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    turn INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    concept_id INTEGER NOT NULL,
    raw_question TEXT NOT NULL,
    raw_answer TEXT NOT NULL,
    doc_path TEXT DEFAULT '',
    skill TEXT DEFAULT '',
    source_json TEXT NOT NULL DEFAULT '{}',
    origin TEXT NOT NULL DEFAULT 'assessed',
    rotation_id INTEGER,
    FOREIGN KEY(topic_id) REFERENCES topics(id),
    FOREIGN KEY(concept_id) REFERENCES concepts(id)
);
CREATE INDEX IF NOT EXISTS idx_memory_exchanges_session ON exchanges(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_exchanges_topic ON exchanges(topic_id);

CREATE TABLE IF NOT EXISTS claim_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    concept_id INTEGER NOT NULL,
    claim_slug TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    score INTEGER NOT NULL CHECK(score IN (0, 1, 2)),
    gap_type TEXT DEFAULT '',
    learner_claim TEXT NOT NULL DEFAULT '',
    missing_edge TEXT NOT NULL DEFAULT '',
    corrected_rule TEXT NOT NULL DEFAULT '',
    clinical_consequence TEXT NOT NULL DEFAULT '',
    retest_prompt_shape TEXT NOT NULL DEFAULT '',
    learning_operation TEXT NOT NULL DEFAULT '',
    agent_signal_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'assessed',
    rotation_id INTEGER,
    inventory_concept_id TEXT,
    FOREIGN KEY(exchange_id) REFERENCES exchanges(id),
    FOREIGN KEY(topic_id) REFERENCES topics(id),
    FOREIGN KEY(concept_id) REFERENCES concepts(id)
);
CREATE INDEX IF NOT EXISTS idx_memory_claim_results_exchange ON claim_results(exchange_id);
CREATE INDEX IF NOT EXISTS idx_memory_claim_results_topic ON claim_results(topic_id);
CREATE INDEX IF NOT EXISTS idx_memory_claim_results_score ON claim_results(score);

CREATE TABLE IF NOT EXISTS claim_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
    concept_id INTEGER NOT NULL,
    claim_slug TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    state TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    gap_type TEXT DEFAULT '',
    last_result_id INTEGER,
    source_result_id INTEGER,
    last_seen_ts TEXT NOT NULL DEFAULT '',
    next_due_ts TEXT DEFAULT '',
    difficulty REAL NOT NULL DEFAULT 0.3,
    stability REAL NOT NULL DEFAULT 1.0,
    reason TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'assessed',
    rotation_id INTEGER,
    UNIQUE(topic_id, concept_id, claim_slug),
    FOREIGN KEY(topic_id) REFERENCES topics(id),
    FOREIGN KEY(concept_id) REFERENCES concepts(id),
    FOREIGN KEY(last_result_id) REFERENCES claim_results(id),
    FOREIGN KEY(source_result_id) REFERENCES claim_results(id)
);
CREATE INDEX IF NOT EXISTS idx_memory_claim_state_state ON claim_state(state);
CREATE INDEX IF NOT EXISTS idx_memory_claim_state_priority ON claim_state(priority);
CREATE INDEX IF NOT EXISTS idx_memory_claim_state_topic ON claim_state(topic_id);

CREATE TABLE IF NOT EXISTS state_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_state_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    result_id INTEGER,
    ts TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(claim_state_id) REFERENCES claim_state(id),
    FOREIGN KEY(result_id) REFERENCES claim_results(id)
);
CREATE INDEX IF NOT EXISTS idx_memory_state_events_state ON state_events(claim_state_id);

CREATE TABLE IF NOT EXISTS repair_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_state_id INTEGER NOT NULL,
    source_result_id INTEGER NOT NULL,
    gap_type TEXT NOT NULL DEFAULT '',
    teaching_move TEXT NOT NULL DEFAULT '',
    started_ts TEXT NOT NULL,
    repaired_result_id INTEGER,
    repaired_ts TEXT NOT NULL DEFAULT '',
    retention_result_id INTEGER,
    retention_ts TEXT NOT NULL DEFAULT '',
    transfer_result_id INTEGER,
    transfer_ts TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'immediate_repair', 'retained', 'transferred', 'regressed')),
    FOREIGN KEY(claim_state_id) REFERENCES claim_state(id),
    FOREIGN KEY(source_result_id) REFERENCES claim_results(id),
    FOREIGN KEY(repaired_result_id) REFERENCES claim_results(id),
    FOREIGN KEY(retention_result_id) REFERENCES claim_results(id),
    FOREIGN KEY(transfer_result_id) REFERENCES claim_results(id)
);
CREATE INDEX IF NOT EXISTS idx_repair_episodes_claim ON repair_episodes(claim_state_id);
CREATE INDEX IF NOT EXISTS idx_repair_episodes_move ON repair_episodes(teaching_move);
CREATE INDEX IF NOT EXISTS idx_repair_episodes_status ON repair_episodes(status);

CREATE TABLE IF NOT EXISTS retrieval_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL,
    claim_state_id INTEGER,
    card_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    priority TEXT NOT NULL DEFAULT 'medium',
    summary TEXT NOT NULL DEFAULT '',
    next_action TEXT NOT NULL DEFAULT '',
    evidence_result_id INTEGER,
    updated_ts TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(topic_id, claim_state_id, card_type),
    FOREIGN KEY(topic_id) REFERENCES topics(id),
    FOREIGN KEY(claim_state_id) REFERENCES claim_state(id),
    FOREIGN KEY(evidence_result_id) REFERENCES claim_results(id)
);
CREATE INDEX IF NOT EXISTS idx_memory_retrieval_topic ON retrieval_cards(topic_id);
CREATE INDEX IF NOT EXISTS idx_memory_retrieval_priority ON retrieval_cards(priority);
CREATE INDEX IF NOT EXISTS idx_memory_retrieval_status ON retrieval_cards(status);

CREATE TABLE IF NOT EXISTS brain_dump_review_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT '',
    topic_id INTEGER NOT NULL,
    concept_id INTEGER NOT NULL,
    doc_path TEXT NOT NULL,
    candidate_slug TEXT NOT NULL,
    prompt TEXT NOT NULL DEFAULT '',
    claim_text TEXT NOT NULL DEFAULT '',
    provenance_tier TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'assessed',
    rotation_id INTEGER,
    convention INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'reviewed', 'dismissed')),
    reviewed_claim_state_id INTEGER,
    reviewed_result_id INTEGER,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(doc_path, topic_id, concept_id, candidate_slug),
    FOREIGN KEY(topic_id) REFERENCES topics(id),
    FOREIGN KEY(concept_id) REFERENCES concepts(id),
    FOREIGN KEY(reviewed_claim_state_id) REFERENCES claim_state(id),
    FOREIGN KEY(reviewed_result_id) REFERENCES claim_results(id)
);
CREATE INDEX IF NOT EXISTS idx_brain_dump_candidates_status ON brain_dump_review_candidates(status);
CREATE INDEX IF NOT EXISTS idx_brain_dump_candidates_topic ON brain_dump_review_candidates(topic_id);
CREATE INDEX IF NOT EXISTS idx_brain_dump_candidates_concept ON brain_dump_review_candidates(concept_id);

CREATE TABLE IF NOT EXISTS curation_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    sessions_since_last_curation INTEGER NOT NULL DEFAULT 0,
    last_curation_ts TEXT NOT NULL DEFAULT '',
    last_curation_version INTEGER NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO curation_state (id) VALUES (1);

CREATE TABLE IF NOT EXISTS curation_counted_sessions (
    session_id TEXT PRIMARY KEY,
    counted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS memory_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL DEFAULT '',
    summary_type TEXT NOT NULL CHECK(summary_type IN ('thematic', 'proficiency_map')),
    topic_id INTEGER,
    concept_id INTEGER,
    content TEXT NOT NULL,
    importance_score REAL NOT NULL DEFAULT 0.5 CHECK(importance_score >= 0 AND importance_score <= 1),
    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'superseded', 'deprecated')),
    CHECK (
        (topic_id IS NOT NULL AND concept_id IS NULL) OR
        (topic_id IS NULL AND concept_id IS NOT NULL) OR
        (topic_id IS NULL AND concept_id IS NULL)
    ),
    FOREIGN KEY(topic_id) REFERENCES topics(id),
    FOREIGN KEY(concept_id) REFERENCES concepts(id)
);
CREATE INDEX IF NOT EXISTS idx_memory_summaries_status ON memory_summaries(status);
CREATE INDEX IF NOT EXISTS idx_memory_summaries_topic ON memory_summaries(topic_id);
CREATE INDEX IF NOT EXISTS idx_memory_summaries_concept ON memory_summaries(concept_id);
CREATE INDEX IF NOT EXISTS idx_memory_summaries_importance ON memory_summaries(importance_score DESC);

CREATE TABLE IF NOT EXISTS memory_summary_evidence (
    summary_id INTEGER NOT NULL,
    claim_result_id INTEGER NOT NULL,
    PRIMARY KEY(summary_id, claim_result_id),
    FOREIGN KEY(summary_id) REFERENCES memory_summaries(id),
    FOREIGN KEY(claim_result_id) REFERENCES claim_results(id)
);

CREATE TABLE IF NOT EXISTS concept_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_concept_id INTEGER NOT NULL,
    target_concept_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL CHECK(relation_type IN ('confused_with', 'prerequisite')),
    strength REAL NOT NULL DEFAULT 0.5 CHECK(strength >= 0 AND strength <= 1),
    evidence_summary_id INTEGER,
    origin TEXT NOT NULL DEFAULT 'curated' CHECK(origin IN ('curated', 'model_proposed')),
    rationale TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(source_concept_id != target_concept_id),
    UNIQUE(source_concept_id, target_concept_id, relation_type),
    FOREIGN KEY(source_concept_id) REFERENCES concepts(id),
    FOREIGN KEY(target_concept_id) REFERENCES concepts(id),
    FOREIGN KEY(evidence_summary_id) REFERENCES memory_summaries(id)
);
CREATE INDEX IF NOT EXISTS idx_concept_relationships_source ON concept_relationships(source_concept_id);
CREATE INDEX IF NOT EXISTS idx_concept_relationships_target ON concept_relationships(target_concept_id);
CREATE INDEX IF NOT EXISTS idx_concept_relationships_type ON concept_relationships(relation_type);

CREATE TABLE IF NOT EXISTS concept_relationship_evidence (
    relationship_id INTEGER NOT NULL,
    claim_result_id INTEGER NOT NULL,
    PRIMARY KEY(relationship_id, claim_result_id),
    FOREIGN KEY(relationship_id) REFERENCES concept_relationships(id),
    FOREIGN KEY(claim_result_id) REFERENCES claim_results(id)
);

CREATE TABLE IF NOT EXISTS shadow_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    false_rule TEXT NOT NULL,
    corrected_rule TEXT NOT NULL,
    clinical_consequence TEXT NOT NULL,
    probe_shape TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium' CHECK(severity IN ('low', 'medium', 'high', 'urgent')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'repaired', 'extinguished', 'regressed')),
    evidence_summary_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(false_rule, corrected_rule),
    FOREIGN KEY(evidence_summary_id) REFERENCES memory_summaries(id)
);
CREATE INDEX IF NOT EXISTS idx_shadow_rules_status ON shadow_rules(status);
CREATE INDEX IF NOT EXISTS idx_shadow_rules_severity ON shadow_rules(severity);

CREATE TABLE IF NOT EXISTS shadow_rule_bindings (
    shadow_rule_id INTEGER NOT NULL,
    concept_id INTEGER NOT NULL,
    binding_type TEXT NOT NULL DEFAULT 'trigger' CHECK(binding_type IN ('trigger', 'contrast', 'context')),
    PRIMARY KEY(shadow_rule_id, concept_id, binding_type),
    FOREIGN KEY(shadow_rule_id) REFERENCES shadow_rules(id),
    FOREIGN KEY(concept_id) REFERENCES concepts(id)
);

CREATE TABLE IF NOT EXISTS shadow_rule_evidence (
    shadow_rule_id INTEGER NOT NULL,
    claim_result_id INTEGER NOT NULL,
    PRIMARY KEY(shadow_rule_id, claim_result_id),
    FOREIGN KEY(shadow_rule_id) REFERENCES shadow_rules(id),
    FOREIGN KEY(claim_result_id) REFERENCES claim_results(id)
);

CREATE TABLE IF NOT EXISTS shadow_rule_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_rule_id INTEGER NOT NULL,
    claim_result_id INTEGER NOT NULL,
    context_label TEXT NOT NULL,
    check_type TEXT NOT NULL CHECK(check_type IN ('changed_frame', 'transfer')),
    outcome TEXT NOT NULL CHECK(outcome IN ('pass', 'fail')),
    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(shadow_rule_id, claim_result_id, context_label, check_type),
    FOREIGN KEY(shadow_rule_id) REFERENCES shadow_rules(id),
    FOREIGN KEY(claim_result_id) REFERENCES claim_results(id)
);
CREATE INDEX IF NOT EXISTS idx_shadow_rule_checks_rule ON shadow_rule_checks(shadow_rule_id);

CREATE TABLE IF NOT EXISTS policy_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT '',
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK(event_type IN ('startup', 'turn')),
    topic_id INTEGER,
    mode TEXT NOT NULL,
    phase TEXT NOT NULL,
    interrupts_json TEXT NOT NULL DEFAULT '{}',
    inputs_json TEXT NOT NULL DEFAULT '{}',
    plan_json TEXT NOT NULL DEFAULT '{}',
    claim_result_id INTEGER,
    FOREIGN KEY(topic_id) REFERENCES topics(id),
    FOREIGN KEY(claim_result_id) REFERENCES claim_results(id)
);
CREATE INDEX IF NOT EXISTS idx_policy_events_session ON policy_events(session_id);
CREATE INDEX IF NOT EXISTS idx_policy_events_topic ON policy_events(topic_id);

"""
SCHEMA_SQL += SERVICE_SCHEMA_SQL


@dataclass(frozen=True)
class TopicResolution:
    slug: str
    display_name: str
    domain: str
    aliases: tuple[str, ...]
    confidence: float = 0.85


def _get_db(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    ensure_reference_graph_schema(conn)
    _migrate_schema(conn)
    conn.commit()
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply additive migrations for existing SQLite databases."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(claim_state)")}
    if "difficulty" not in columns:
        conn.execute("ALTER TABLE claim_state ADD COLUMN difficulty REAL NOT NULL DEFAULT 0.3")
    if "stability" not in columns:
        conn.execute("ALTER TABLE claim_state ADD COLUMN stability REAL NOT NULL DEFAULT 1.0")
    # Provenance discriminator for the service-rotation learning layer. Existing rows
    # backfill to 'assessed' so the formal lens (and every pre-existing query that reads
    # claim_state) is unchanged; service-origin gaps are added with origin='service'.
    for table in ("claim_state", "claim_results", "exchanges"):
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "origin" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN origin TEXT NOT NULL DEFAULT 'assessed'")
        if "rotation_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN rotation_id INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_claim_state_origin ON claim_state(origin)")
    # Mark model-originated graph edges distinctly so native-knowledge discovery
    # is auditable and never silently overwrites evidence-backed learner-graph
    # structure (see "The Landscape Is A Skeleton, Not A Ceiling" in adaptive-teaching-doctrine.md). Pre-existing edges backfill to 'curated'.
    rel_cols = {row["name"] for row in conn.execute("PRAGMA table_info(concept_relationships)")}
    if "origin" not in rel_cols:
        conn.execute(
            "ALTER TABLE concept_relationships ADD COLUMN origin TEXT NOT NULL DEFAULT 'curated'"
        )
    if "rationale" not in rel_cols:
        conn.execute(
            "ALTER TABLE concept_relationships ADD COLUMN rationale TEXT NOT NULL DEFAULT ''"
        )
    # Full teaching-plan snapshot per policy event so the per-turn `policy=` line
    # can carry target concepts and directives, not just mode/phase/interrupts.
    policy_cols = {row["name"] for row in conn.execute("PRAGMA table_info(policy_events)")}
    if "plan_json" not in policy_cols:
        conn.execute("ALTER TABLE policy_events ADD COLUMN plan_json TEXT NOT NULL DEFAULT '{}'")
    for table in ("claim_results", "concepts"):
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "inventory_concept_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN inventory_concept_id TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_concepts_inventory ON concepts(inventory_concept_id)"
    )
    _backfill_memory_schedule(conn)
    _normalize_session_cards(conn)


def _normalize_session_cards(conn: sqlite3.Connection) -> None:
    """Separate legacy artifact anchors and keep one active card per handoff class."""
    rows = conn.execute(
        """SELECT rc.id, rc.card_type, rc.detail_json, s.skill
             FROM retrieval_cards rc
             LEFT JOIN sessions s
               ON s.session_id = json_extract(rc.detail_json, '$.session_id')
            WHERE rc.claim_state_id IS NULL
              AND rc.card_type = 'session_handoff'"""
    ).fetchall()
    for row in rows:
        if row["skill"] in ARTIFACT_ANCHOR_SKILLS:
            conn.execute(
                "UPDATE retrieval_cards SET card_type = 'artifact_anchor', priority = 'low' WHERE id = ?",
                (int(row["id"]),),
            )
    groups = conn.execute(
        """SELECT topic_id, card_type
             FROM retrieval_cards
            WHERE claim_state_id IS NULL
              AND card_type IN ('session_handoff', 'artifact_anchor')
            GROUP BY topic_id, card_type"""
    ).fetchall()
    for group in groups:
        cards = conn.execute(
            """SELECT id
                 FROM retrieval_cards
                WHERE topic_id = ? AND claim_state_id IS NULL AND card_type = ?
                ORDER BY updated_ts DESC, id DESC""",
            (int(group["topic_id"]), group["card_type"]),
        ).fetchall()
        for stale in cards[1:]:
            conn.execute("UPDATE retrieval_cards SET status = 'inactive' WHERE id = ?", (int(stale["id"]),))


def _backfill_memory_schedule(conn: sqlite3.Connection) -> None:
    """Seed due dates for pre-scheduler rows without overwriting live updates."""
    rows = conn.execute(
        """SELECT id, state, priority, last_seen_ts
           FROM claim_state
           WHERE COALESCE(next_due_ts, '') = ''"""
    ).fetchall()
    for row in rows:
        last_seen = _parse_ts(row["last_seen_ts"]) or datetime.now(timezone.utc)
        state = row["state"]
        priority = row["priority"]
        if state in {"missed", "partially_repaired", "regressed"}:
            stability = 0.75
        elif state == "repaired_same_session":
            stability = 2.0
        else:
            stability = 14.0 if priority == "low" else 7.0
        delay = max(0.1, stability * _priority_delay_factor(priority))
        conn.execute(
            """UPDATE claim_state
               SET stability = ?, difficulty = COALESCE(difficulty, 0.3),
                   next_due_ts = ?
               WHERE id = ? AND COALESCE(next_due_ts, '') = ''""",
            (round(stability, 3), (last_seen + timedelta(days=delay)).isoformat(), int(row["id"])),
        )


def _normalize(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^\w\s\-/]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokens(text: str) -> set[str]:
    normalized = _normalize(text).replace("-", " ").replace("/", " ")
    return {w for w in normalized.split() if w not in STOPWORDS and len(w) > 1}


def _slug(text: str) -> str:
    out = _normalize(text).replace("/", " ").replace("-", " ")
    out = re.sub(r"\s+", "-", out).strip("-")
    return out or "uncategorized"


def _display(text: str) -> str:
    keep_upper = {"tbi", "evd", "sah", "ich", "dci", "icp", "cpp", "avm", "mri", "ct", "cta", "dsa"}
    return " ".join(w.upper() if w in keep_upper else w.capitalize() for w in _normalize(text.replace("-", " ")).split())


def _controlled_value(value: str) -> str:
    return _normalize(value).replace(" ", "_").replace("-", "_")


def _validate_strict_telemetry(
    *,
    concept: str,
    score: int,
    error_type: str,
    misconception: str,
    missing_edge: str,
    corrected_rule: str,
    correction: str,
    tested_claim: str,
    answer_mode: str,
    confidence_observed: str,
    teaching_move: str,
) -> None:
    """Reject underspecified assessment telemetry when an agent opts into strict mode."""
    # A meaningful claim must be reconstructable, otherwise _derive_claim falls back
    # to boilerplate ("Apply <concept> ...") and the stored claim_state carries no
    # testable content. Required for every assessed exchange, not just misses.
    if not (tested_claim.strip() or corrected_rule.strip() or correction.strip()):
        raise ValueError(
            "strict telemetry requires tested_claim (or corrected_rule/correction) "
            "so the stored claim is a real testable statement, not boilerplate"
        )
    concept_words = concept.strip().split()
    if len(concept.strip()) > MAX_CONCEPT_LABEL_CHARS or len(concept_words) > MAX_CONCEPT_LABEL_WORDS:
        raise ValueError(
            "strict telemetry requires a succinct concept label "
            f"(<= {MAX_CONCEPT_LABEL_WORDS} words and <= {MAX_CONCEPT_LABEL_CHARS} characters); "
            "store the full clinical rule in tested_claim"
        )
    controlled = {
        "answer_mode": (_controlled_value(answer_mode), VALID_ANSWER_MODES),
        "confidence_observed": (_controlled_value(confidence_observed), VALID_CONFIDENCE_OBSERVATIONS),
        "teaching_move": (_controlled_value(teaching_move), VALID_TEACHING_MOVES),
    }
    for field, (value, allowed) in controlled.items():
        if value not in allowed:
            raise ValueError(f"strict telemetry requires {field} in {sorted(allowed)}, got {value or '[empty]'!r}")
    if score < 2:
        gap = _controlled_value(error_type)
        if gap not in VALID_GAP_TYPES:
            raise ValueError(f"strict telemetry requires error_type in {sorted(VALID_GAP_TYPES)} for score < 2")
        if not (missing_edge.strip() or misconception.strip()):
            raise ValueError("strict telemetry requires missing_edge or misconception for score < 2")
        if not (corrected_rule.strip() or correction.strip()):
            raise ValueError("strict telemetry requires corrected_rule or correction for score < 2")


def _doc_alias(doc_path: str) -> str:
    return _normalize(Path(doc_path).stem.replace("_", " ")) if doc_path else ""


def _doc_family_alias(doc_path: str) -> str:
    """Normalize versioned report paths so one artifact family keeps one topic identity."""
    alias = _doc_alias(doc_path)
    return re.sub(r"\s+v\d+$", "", alias).strip()


def _topic_row_for_doc_family(conn: sqlite3.Connection, doc_path: str) -> sqlite3.Row | None:
    family = _doc_family_alias(doc_path)
    if not family:
        return None
    rows = conn.execute(
        """SELECT t.*,
                  (SELECT COUNT(*) FROM claim_results cr WHERE cr.topic_id = t.id) AS claim_result_count
             FROM topics t
            WHERE COALESCE(t.primary_doc_path, '') != ''"""
    ).fetchall()
    matches = [row for row in rows if _doc_family_alias(str(row["primary_doc_path"])) == family]
    if not matches:
        return None
    matches.sort(
        key=lambda row: (
            -int(row["claim_result_count"] or 0),
            1 if re.search(r"_v\d+\.md$", str(row["primary_doc_path"]), re.IGNORECASE) else 0,
            int(row["id"]),
        )
    )
    return matches[0]


CURRICULUM_CATALOG_PATH = DATA_DIR / "acgme_curriculum.json"
# F1 floor for accepting a catalog title as the canonical topic. Below this (or
# with fewer than CATALOG_MIN_OVERLAP shared tokens) we return None and let
# resolve_topic fall back to a low-confidence generic slug — the explicit signal
# that the agent should disambiguate rather than accept a weak guess.
CATALOG_MATCH_FLOOR = 0.5
CATALOG_MIN_OVERLAP = 2
CATALOG_SHORT_HINT_CONTAINMENT_FLOOR = 0.75
CATALOG_SHORT_HINT_COVERAGE_FLOOR = 0.2
_CATALOG_CACHE: list[tuple[str, str, set[str]]] | None = None

# Topic matching keeps clinically meaningful words (management, grading, etc.)
# that the global STOPWORDS set strips — those words are exactly what
# distinguishes "tbi management" from "tbi imaging". Only true function words are
# removed here.
TOPIC_STOPWORDS = frozenset(
    "the a an of in for with and or to on by is at as it its from that this "
    "after before per via vs versus during over under into onto".split()
)

CONTEXT_GENERIC_TOKENS = frozenset({
    "acute", "anterior", "care", "classification", "critical", "management",
    "medical", "posterior", "surgical",
})
SCOUT_GENERIC_TOKENS = CONTEXT_GENERIC_TOKENS | frozenset({
    "above", "baseline", "clinical", "decompression", "definitive", "emergencies",
    "edema", "first", "lesion", "line", "management", "mmhg", "neurologic",
    "hypotension", "iv", "norepinephrine", "occur", "patient", "perfusion",
    "phenylephrine", "preserve", "prevent", "pressure", "reflex", "target", "than",
    "timing", "treat", "vasogenic",
})


def _topic_tokens(text: str) -> set[str]:
    normalized = _normalize(text).replace("-", " ").replace("/", " ")
    return {w for w in normalized.split() if w not in TOPIC_STOPWORDS and len(w) > 1}


def _topic_overlap(left: str, right: str) -> dict[str, object]:
    left_tokens = _topic_tokens(left)
    right_tokens = _topic_tokens(right)
    shared = left_tokens & right_tokens
    overlap = len(shared)
    containment = overlap / max(1, min(len(left_tokens), len(right_tokens)))
    f1 = 2 * overlap / max(1, len(left_tokens) + len(right_tokens))
    return {
        "shared_tokens": sorted(shared),
        "overlap": overlap,
        "containment": round(containment, 3),
        "f1": round(f1, 3),
    }


def _related_topic_matches_for_hint(
    conn: sqlite3.Connection,
    topic_hint: str,
    *,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Return existing learner topics whose tracked concepts overlap an unresolved hint."""
    hint_tokens = _topic_tokens(topic_hint)
    if not hint_tokens:
        return []
    rows = conn.execute(
        """SELECT t.canonical_slug AS topic, t.display_name AS topic_name,
                  c.display_name AS concept, cs.state, cs.priority, cs.claim_text
             FROM claim_state cs
             JOIN topics t ON t.id = cs.topic_id
             JOIN concepts c ON c.id = cs.concept_id"""
    ).fetchall()
    by_topic: dict[str, dict[str, object]] = {}
    for row in rows:
        text = f"{row['topic']} {row['topic_name']} {row['concept']} {row['claim_text']}"
        matched = hint_tokens & _topic_tokens(text)
        if not matched:
            continue
        topic = str(row["topic"])
        item = by_topic.setdefault(topic, {
            "topic": topic,
            "topic_name": row["topic_name"],
            "matched_tokens": set(),
            "matching_concepts": [],
        })
        item["matched_tokens"].update(matched)  # type: ignore[union-attr]
        concepts = item["matching_concepts"]
        if len(concepts) < 3:  # type: ignore[arg-type]
            concepts.append({  # type: ignore[union-attr]
                "concept": row["concept"],
                "state": row["state"],
                "priority": row["priority"],
            })
    out = []
    for item in by_topic.values():
        matched_tokens = sorted(item["matched_tokens"])  # type: ignore[arg-type]
        out.append({
            **item,
            "matched_tokens": matched_tokens,
            "overlap": len(matched_tokens),
            "next_action": "Use agent judgment to choose the best existing topic anchor, then rerun topic-scoped recall.",
        })
    out.sort(key=lambda item: (-int(item["overlap"]), str(item["topic"])))
    return out[: max(0, limit)]


# Migration path: study topics that existed under the previous hardcoded resolver
# keep resolving to their established canonical slugs so historical learner state
# is never fragmented. This is a small compatibility seed consulted before the
# catalog; the catalog handles the long tail of new topics. Production already
# stores these as topic_aliases, so this also covers fresh-DB / novel-phrasing.
LEGACY_TOPIC_SEED: tuple[tuple[tuple[str, ...], TopicResolution], ...] = (
    (("hypertension", "blood pressure", "bp"), TopicResolution(
        "hypertension-management-neuro-emergencies", "Hypertension Management in Neuro Emergencies",
        "vascular", ("hypertension management", "neuro icu hypertension", "bp management neuro icu",
                     "htn neuro icu", "hypertension management in neuro emergencies"), 0.95)),
    (("tbi", "traumatic brain injury"), TopicResolution(
        "tbi-management", "TBI Management", "trauma",
        ("tbi management", "traumatic brain injury management", "severe tbi"), 0.95)),
    (("evd", "external ventricular"), TopicResolution(
        "evd-management-icu", "EVD Management in ICU", "critical-care",
        ("evd management in icu", "external ventricular drain management", "evd management"), 0.95)),
    (("vasospasm", "dci"), TopicResolution(
        "sah-vasospasm-management", "SAH Vasospasm Management", "vascular",
        ("vasospasm after sah", "subarachnoid hemorrhage vasospasm", "dci management",
         "cerebral vasospasm management", "sah vasospasm management"), 0.9)),
    (("sah", "subarachnoid"), TopicResolution(
        "sah-management", "SAH Management", "vascular",
        ("sah management", "subarachnoid hemorrhage management", "aneurysmal subarachnoid hemorrhage"), 0.85)),
    (("long tract", "dcml", "spinothalamic", "corticospinal"), TopicResolution(
        "long-tracts", "Long Tracts", "anatomy",
        ("long tracts", "dcml", "spinothalamic tract", "corticospinal tract"), 0.9)),
    (("neuroimaging", "traumatic tap", "xanthochromia"), TopicResolution(
        "neuroimaging-sah-hemorrhage", "Neuroimaging SAH and Hemorrhage", "imaging",
        ("neuroimaging lab 2", "traumatic tap vs sah", "sah stroke imaging vascular"), 0.85)),
)


def _resolve_legacy_seed(hay: str) -> TopicResolution | None:
    """Migration path: map historical study-topic phrasings to established slugs."""
    normalized = _normalize(hay)
    hay_tokens = _topic_tokens(hay)
    for triggers, resolution in LEGACY_TOPIC_SEED:
        for trig in triggers:
            if " " in trig:
                if trig in normalized:
                    return resolution
            elif trig in hay_tokens:
                return resolution
    return None


def _resolve_exact_legacy_seed(hay: str) -> TopicResolution | None:
    """Preserve established slugs for exact legacy topic names and aliases only."""
    normalized = _normalize(hay)
    hay_tokens = _topic_tokens(hay)
    for _triggers, resolution in LEGACY_TOPIC_SEED:
        candidates = {
            _normalize(resolution.display_name),
            _normalize(resolution.slug.replace("-", " ")),
            *(_normalize(alias) for alias in resolution.aliases),
        }
        for candidate in candidates:
            if not candidate:
                continue
            candidate_tokens = _topic_tokens(candidate)
            if normalized == candidate:
                return resolution
            if hay_tokens and (hay_tokens == candidate_tokens or hay_tokens <= candidate_tokens):
                return resolution
    return None


def _domain_from_catalog(domain_name: str) -> str:
    """Map a verbose catalog domain string to a compact §4 domain tag."""
    hay = _normalize(domain_name)
    table = (
        ("vascular", "vascular"), ("spine", "spine"), ("tumor", "tumor"),
        ("trauma", "trauma"), ("functional", "functional"), ("pediatric", "pediatric"),
        ("peripheral nerve", "peripheral-nerve"), ("anatomy", "anatomy"),
        ("neuroimaging", "imaging"), ("imaging", "imaging"), ("critical care", "critical-care"),
    )
    for needle, tag in table:
        if needle in hay:
            return tag
    return "general"


def _load_curriculum_catalog() -> list[tuple[str, str, set[str]]]:
    """Return cached [(title, domain_tag, title_tokens)] from the ACGME catalog."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    out: list[tuple[str, str, set[str]]] = []
    try:
        data = json.loads(CURRICULUM_CATALOG_PATH.read_text())
        for milestone in data.get("milestones", {}).values():
            for topic in milestone.get("topics", []):
                title = str(topic.get("title") or "").strip()
                if not title:
                    continue
                out.append((title, _domain_from_catalog(str(topic.get("domain") or "")), _topic_tokens(title)))
    except (OSError, json.JSONDecodeError):
        out = []
    _CATALOG_CACHE = out
    return out


def _catalog_match(hint_tokens: set[str]) -> tuple[float, str, str] | None:
    """Return best catalog match as (confidence, title, domain_tag), if reliable."""
    if len(hint_tokens) < CATALOG_MIN_OVERLAP:
        return None
    best: tuple[float, float, int, str, str] | None = None
    for title, domain_tag, title_tokens in _load_curriculum_catalog():
        if not title_tokens:
            continue
        overlap = len(hint_tokens & title_tokens)
        if overlap < CATALOG_MIN_OVERLAP:
            continue
        containment = overlap / len(hint_tokens)
        coverage = overlap / len(title_tokens)
        f1 = 2 * containment * coverage / (containment + coverage)
        reliable = f1 >= CATALOG_MATCH_FLOOR or (
            containment >= CATALOG_SHORT_HINT_CONTAINMENT_FLOOR
            and coverage >= CATALOG_SHORT_HINT_COVERAGE_FLOOR
        )
        if not reliable:
            continue
        confidence = min(0.9, 0.55 + (f1 * 0.3) + (coverage * 0.1))
        candidate = (confidence, f1, overlap, title, domain_tag)
        if best is None or candidate[:3] > best[:3]:
            best = candidate
    if best is None:
        return None
    confidence, _f1, _overlap, title, domain_tag = best
    return (round(confidence, 3), title, domain_tag)


def _resolve_topic_patterns(hay: str) -> TopicResolution | None:
    """Resolve a topic hint through legacy aliases, then ACGME catalog.

    Replaces the previous hardcoded if/elif chain. Resolution order:
      1. Exact legacy seed — established study topics keep their canonical slugs
         when the hint is the old topic name/alias.
      2. Catalog — data-driven match against curriculum titles, requiring both a
         minimum shared-token count and an F1 floor so a single generic token
         cannot over-match a long, unrelated title. Title coverage is scored too,
         not just hint containment, which kills the "{tbi} -> long CT title" bug.
      3. Broad legacy fallback — only after the catalog declines the hint, so
         "tbi ct" can resolve to a TBI imaging title instead of generic TBI.
    A weak match returns None so resolve_topic falls back to a low-confidence
    generic slug — the explicit signal that the agent should disambiguate.
    """
    seeded = _resolve_exact_legacy_seed(hay)
    if seeded:
        return seeded
    hint_tokens = _topic_tokens(hay)
    catalog = _catalog_match(hint_tokens)
    if catalog:
        confidence, title, domain_tag = catalog
        return TopicResolution(
            _slug(title),
            _display(title),
            domain_tag,
            (_normalize(title),),
            confidence,
        )
    return _resolve_legacy_seed(hay)


def resolve_topic(conn: sqlite3.Connection, topic_hint: str, doc_path: str = "") -> TopicResolution:
    hint = _normalize(topic_hint)
    doc_alias = _doc_alias(doc_path)
    doc_family_row = _topic_row_for_doc_family(conn, doc_path)
    doc_family_overlap = _topic_overlap(hint, _doc_family_alias(doc_path)) if hint and doc_path else {"overlap": 0}
    if doc_family_row and (not hint or int(doc_family_overlap["overlap"]) >= 2):
        aliases = tuple(r["alias"] for r in conn.execute("SELECT alias FROM topic_aliases WHERE topic_id = ?", (doc_family_row["id"],)))
        return TopicResolution(doc_family_row["canonical_slug"], doc_family_row["display_name"], doc_family_row["domain"], aliases, 1.0)
    if hint:
        row = conn.execute(
            """SELECT t.* FROM topic_redirects r
               JOIN topics t ON t.id = r.target_topic_id
               WHERE r.alias_slug = ?""",
            (_slug(hint),),
        ).fetchone()
        if row:
            aliases = tuple(r["alias"] for r in conn.execute("SELECT alias FROM topic_aliases WHERE topic_id = ?", (row["id"],)))
            return TopicResolution(row["canonical_slug"], row["display_name"], row["domain"], aliases, 1.0)
        row = conn.execute(
            "SELECT t.* FROM topic_aliases a JOIN topics t ON t.id = a.topic_id WHERE a.alias = ?",
            (hint,),
        ).fetchone()
        if row:
            aliases = tuple(r["alias"] for r in conn.execute("SELECT alias FROM topic_aliases WHERE topic_id = ?", (row["id"],)))
            return TopicResolution(row["canonical_slug"], row["display_name"], row["domain"], aliases, 1.0)
        row = conn.execute("SELECT * FROM topics WHERE canonical_slug = ?", (_slug(hint),)).fetchone()
        if row:
            aliases = tuple(r["alias"] for r in conn.execute("SELECT alias FROM topic_aliases WHERE topic_id = ?", (row["id"],)))
            return TopicResolution(row["canonical_slug"], row["display_name"], row["domain"], aliases, 1.0)
        resolution = _resolve_topic_patterns(hint)
        if resolution:
            return resolution
    if doc_alias:
        row = conn.execute(
            "SELECT t.* FROM topic_aliases a JOIN topics t ON t.id = a.topic_id WHERE a.alias = ?",
            (doc_alias,),
        ).fetchone()
        if row:
            aliases = tuple(r["alias"] for r in conn.execute("SELECT alias FROM topic_aliases WHERE topic_id = ?", (row["id"],)))
            return TopicResolution(row["canonical_slug"], row["display_name"], row["domain"], aliases, 1.0)
        resolution = _resolve_topic_patterns(doc_alias)
        if resolution:
            return resolution
    base = hint or doc_alias or "uncategorized memory"
    return TopicResolution(_slug(base), _display(base), "general", (base,), 0.65)


def _ensure_topic(conn: sqlite3.Connection, resolution: TopicResolution, doc_path: str = "") -> int:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO topics
           (canonical_slug, display_name, domain, primary_doc_path, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (resolution.slug, resolution.display_name, resolution.domain, doc_path or "", now),
    )
    if doc_path:
        conn.execute(
            "UPDATE topics SET primary_doc_path = COALESCE(NULLIF(primary_doc_path, ''), ?) WHERE canonical_slug = ?",
            (doc_path, resolution.slug),
        )
    topic_id = int(conn.execute("SELECT id FROM topics WHERE canonical_slug = ?", (resolution.slug,)).fetchone()[0])
    aliases = set(resolution.aliases) | {resolution.slug.replace("-", " "), _normalize(resolution.display_name)}
    if doc_path:
        aliases.add(_doc_alias(doc_path))
    for alias in aliases:
        if alias:
            conn.execute(
                "INSERT OR IGNORE INTO topic_aliases (topic_id, alias, source, confidence) VALUES (?, ?, ?, ?)",
                (topic_id, _normalize(alias), "resolver", resolution.confidence),
            )
    return topic_id


def identity_audit(conn: sqlite3.Connection) -> dict[str, object]:
    """Return reviewable topic and claim-state identity collision candidates."""
    topics = conn.execute(
        "SELECT id, canonical_slug, display_name, domain, primary_doc_path FROM topics ORDER BY canonical_slug"
    ).fetchall()
    duplicate_topics: list[dict[str, object]] = []
    for idx, left in enumerate(topics):
        for right in topics[idx + 1:]:
            metrics = _topic_overlap(left["display_name"], right["display_name"])
            shared_doc_family = bool(
                left["primary_doc_path"]
                and right["primary_doc_path"]
                and _doc_family_alias(str(left["primary_doc_path"])) == _doc_family_alias(str(right["primary_doc_path"]))
            )
            if int(metrics["overlap"]) < 2:
                continue
            if not shared_doc_family and float(metrics["containment"]) < 0.75 and float(metrics["f1"]) < 0.72:
                continue
            duplicate_topics.append({
                "source_topic": left["canonical_slug"],
                "target_topic": right["canonical_slug"],
                "source_domain": left["domain"],
                "target_domain": right["domain"],
                "shared_doc_family": shared_doc_family,
                **metrics,
            })
    duplicate_topics.sort(
        key=lambda item: (-float(item["containment"]), -float(item["f1"]), str(item["source_topic"]))
    )
    duplicate_claim_states = [
        {
            "topic": row["topic"],
            "concept_id": int(row["concept_id"]),
            "concept": row["concept"],
            "claim_state_count": int(row["claim_state_count"]),
            "claim_state_ids": [int(value) for value in str(row["claim_state_ids"]).split(",")],
        }
        for row in conn.execute(
            """SELECT t.canonical_slug AS topic, cs.concept_id, c.display_name AS concept,
                      COUNT(*) AS claim_state_count, GROUP_CONCAT(cs.id) AS claim_state_ids
                 FROM claim_state cs
                 JOIN topics t ON t.id = cs.topic_id
                 JOIN concepts c ON c.id = cs.concept_id
                GROUP BY cs.topic_id, cs.concept_id
               HAVING COUNT(*) > 1
                ORDER BY claim_state_count DESC, topic, concept"""
        ).fetchall()
    ]
    return {
        "counts": {
            "topics": len(topics),
            "duplicate_topic_candidates": len(duplicate_topics),
            "duplicate_claim_state_candidates": len(duplicate_claim_states),
        },
        "duplicate_topic_candidates": duplicate_topics,
        "duplicate_claim_state_candidates": duplicate_claim_states,
        "guardrail": "Review candidates manually. merge-topics is dry-run unless --apply is explicit and refuses concept collisions.",
    }


def _exact_topic_row(conn: sqlite3.Connection, topic_slug_or_alias: str) -> sqlite3.Row | None:
    hint = _normalize(topic_slug_or_alias)
    row = conn.execute("SELECT * FROM topics WHERE canonical_slug = ?", (_slug(hint),)).fetchone()
    if row:
        return row
    return conn.execute(
        """SELECT t.* FROM topic_aliases a
           JOIN topics t ON t.id = a.topic_id
           WHERE a.alias = ?""",
        (hint,),
    ).fetchone()


def merge_topics(
    conn: sqlite3.Connection,
    *,
    source_topic: str,
    target_topic: str,
    apply: bool = False,
) -> dict[str, object]:
    """Consolidate an exact source topic into an exact target topic after review."""
    source = _exact_topic_row(conn, source_topic)
    target = _exact_topic_row(conn, target_topic)
    if source is None:
        raise ValueError(f"source topic not found by exact slug or alias: {source_topic!r}")
    if target is None:
        raise ValueError(f"target topic not found by exact slug or alias: {target_topic!r}")
    source_id = int(source["id"])
    target_id = int(target["id"])
    if source_id == target_id:
        raise ValueError("source and target resolve to the same topic")
    collisions = [
        row["canonical_slug"]
        for row in conn.execute(
            """SELECT sc.canonical_slug
                 FROM concepts sc
                 JOIN concepts tc
                   ON tc.topic_id = ? AND tc.canonical_slug = sc.canonical_slug
                WHERE sc.topic_id = ?
                ORDER BY sc.canonical_slug""",
            (target_id, source_id),
        ).fetchall()
    ]
    counts = {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (source_id,)).fetchone()[0])
        for table, column in (
            ("concepts", "topic_id"),
            ("sessions", "primary_topic_id"),
            ("session_topics", "topic_id"),
            ("exchanges", "topic_id"),
            ("claim_results", "topic_id"),
            ("claim_state", "topic_id"),
            ("retrieval_cards", "topic_id"),
            ("memory_summaries", "topic_id"),
        )
    }
    result: dict[str, object] = {
        "source_topic": source["canonical_slug"],
        "target_topic": target["canonical_slug"],
        "apply_requested": apply,
        "blocked": bool(collisions),
        "concept_collisions": collisions,
        "affected_rows": counts,
    }
    if collisions:
        result["guardrail"] = "Merge refused: reconcile same-slug concept collisions explicitly before applying."
        return result
    if not apply:
        result["guardrail"] = "Dry run only. Re-run with --apply after reviewing affected_rows."
        return result

    aliases = [
        row["alias"] for row in conn.execute("SELECT alias FROM topic_aliases WHERE topic_id = ?", (source_id,)).fetchall()
    ]
    try:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN")
        conn.execute("UPDATE concepts SET topic_id = ? WHERE topic_id = ?", (target_id, source_id))
        for table, column in (
            ("sessions", "primary_topic_id"),
            ("exchanges", "topic_id"),
            ("claim_results", "topic_id"),
            ("claim_state", "topic_id"),
            ("retrieval_cards", "topic_id"),
            ("memory_summaries", "topic_id"),
        ):
            conn.execute(f"UPDATE {table} SET {column} = ? WHERE {column} = ?", (target_id, source_id))
        conn.execute(
            """INSERT OR IGNORE INTO session_topics (session_id, topic_id)
               SELECT session_id, ? FROM session_topics WHERE topic_id = ?""",
            (target_id, source_id),
        )
        conn.execute("DELETE FROM session_topics WHERE topic_id = ?", (source_id,))
        conn.execute("UPDATE topics SET parent_topic_id = ? WHERE parent_topic_id = ?", (target_id, source_id))
        conn.execute("DELETE FROM topic_aliases WHERE topic_id = ?", (source_id,))
        for alias in aliases:
            conn.execute(
                "INSERT OR IGNORE INTO topic_aliases (topic_id, alias, source, confidence) VALUES (?, ?, 'topic_merge', 1.0)",
                (target_id, alias),
            )
        conn.execute(
            """INSERT INTO topic_redirects (alias_slug, target_topic_id, reason)
               VALUES (?, ?, ?)
               ON CONFLICT(alias_slug) DO UPDATE SET target_topic_id = excluded.target_topic_id, reason = excluded.reason""",
            (source["canonical_slug"], target_id, f"merged into {target['canonical_slug']}"),
        )
        conn.execute("DELETE FROM topics WHERE id = ?", (source_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    result["applied"] = True
    return result


def record_shadow_rule_check(
    conn: sqlite3.Connection,
    *,
    shadow_rule_id: int,
    claim_result_id: int,
    context_label: str,
    check_type: str,
    outcome: str,
    apply: bool = False,
) -> dict[str, object]:
    """Record a reviewed probe result and enforce the shadow-rule extinction threshold."""
    if check_type not in {"changed_frame", "transfer"}:
        raise ValueError("check_type must be changed_frame or transfer")
    if outcome not in {"pass", "fail"}:
        raise ValueError("outcome must be pass or fail")
    if not context_label.strip():
        raise ValueError("context_label must be a non-empty changed-frame context")
    rule = conn.execute("SELECT id, status FROM shadow_rules WHERE id = ?", (shadow_rule_id,)).fetchone()
    if rule is None:
        raise ValueError(f"unknown shadow_rule_id={shadow_rule_id}")
    claim = conn.execute("SELECT id, score FROM claim_results WHERE id = ?", (claim_result_id,)).fetchone()
    if claim is None:
        raise ValueError(f"unknown claim_result_id={claim_result_id}")
    score = int(claim["score"])
    if outcome == "pass" and score != 2:
        raise ValueError("a passing shadow-rule check requires claim_result score=2")
    if outcome == "fail" and score >= 2:
        raise ValueError("a failing shadow-rule check requires claim_result score < 2")
    result: dict[str, object] = {
        "shadow_rule_id": shadow_rule_id,
        "claim_result_id": claim_result_id,
        "context_label": context_label.strip(),
        "check_type": check_type,
        "outcome": outcome,
        "apply_requested": apply,
    }
    if not apply:
        result["guardrail"] = "Dry run only. Re-run with --apply after confirming the probe metadata."
        return result
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO shadow_rule_checks
           (shadow_rule_id, claim_result_id, context_label, check_type, outcome, checked_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (shadow_rule_id, claim_result_id, context_label.strip(), check_type, outcome, now),
    )
    if outcome == "fail":
        status_value = "regressed"
    else:
        counts = conn.execute(
            """SELECT
                   SUM(CASE WHEN check_type = 'changed_frame' AND outcome = 'pass' THEN 1 ELSE 0 END) AS changed_frames,
                   COUNT(DISTINCT CASE WHEN check_type = 'transfer' AND outcome = 'pass' THEN context_label END) AS transfer_contexts
               FROM shadow_rule_checks WHERE shadow_rule_id = ?""",
            (shadow_rule_id,),
        ).fetchone()
        changed_frames = int(counts["changed_frames"] or 0)
        transfer_contexts = int(counts["transfer_contexts"] or 0)
        status_value = "extinguished" if changed_frames >= 1 and transfer_contexts >= 2 else "repaired"
        result["passed_changed_frames"] = changed_frames
        result["passed_transfer_contexts"] = transfer_contexts
    conn.execute(
        "UPDATE shadow_rules SET status = ?, updated_at = ? WHERE id = ?",
        (status_value, now, shadow_rule_id),
    )
    conn.commit()
    result["applied"] = True
    result["status"] = status_value
    result["extinction_guardrail"] = "Extinction requires >=1 changed-frame pass and >=2 distinct transfer-context passes."
    return result


def _ensure_concept(conn: sqlite3.Connection, topic_id: int, topic_slug: str, concept: str, question: str = "", correction: str = "") -> int:
    now = datetime.now(timezone.utc).isoformat()
    slug = _slug(concept)
    conn.execute(
        """INSERT OR IGNORE INTO concepts
           (topic_id, canonical_slug, display_name, created_at)
           VALUES (?, ?, ?, ?)""",
        (topic_id, slug, _normalize(concept), now),
    )
    concept_id = int(conn.execute(
        "SELECT id FROM concepts WHERE topic_id = ? AND canonical_slug = ?",
        (topic_id, slug),
    ).fetchone()[0])
    conn.execute(
        "INSERT OR IGNORE INTO concept_aliases (concept_id, alias, source, confidence) VALUES (?, ?, ?, ?)",
        (concept_id, _normalize(concept), "agent", 1.0),
    )
    return concept_id


def _first_sentence(text: str, fallback: str = "") -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if not clean:
        return fallback
    match = re.search(r"(.{1,240}?[.!?])\s", clean + " ")
    return match.group(1) if match else clean[:240]


def _normalize_gap_type(error_type: str, score: int, missing_edge: str) -> str:
    et = _normalize(error_type).replace(" ", "_").replace("-", "_")
    if et in VALID_GAP_TYPES:
        return et
    if score == 0:
        return "reasoning_gap"
    if score == 1:
        return "omission" if missing_edge else "reasoning_gap"
    return ""


def _learning_operation(concept: str, question: str, explicit: str = "") -> str:
    if explicit:
        return _normalize(explicit).replace(" ", "_")
    hay = _normalize(f"{concept} {question}")
    if any(x in hay for x in ("what map", "dose", "target", "threshold", "how fast", "mg", "mmhg", "mcg")):
        return "quantification"
    if any(x in hay for x in ("for each", "distinguish", " vs ", "same sbp", "different", "contrast")):
        return "discrimination"
    if any(x in hay for x in ("first", "sequence", "next 5 minutes", "order")):
        return "sequencing"
    if any(x in hay for x in ("why", "equation", "physiologic", "mechanism")):
        return "mechanism"
    return "transfer"


VALID_PRIORITIES = frozenset({"urgent", "high", "medium", "low"})


def _normalize_priority(value: str) -> str:
    """Return a valid agent-asserted priority, or '' to defer to the heuristic."""
    v = _normalize(value).replace(" ", "").replace("-", "")
    return v if v in VALID_PRIORITIES else ""


def _priority(topic_slug: str, claim_text: str, gap_type: str, score: int) -> str:
    hay = _normalize(f"{topic_slug} {claim_text} {gap_type}")
    if score < 2 and any(x in hay for x in ("herniation", "cushing", "icp", "cpp", "vasospasm", "dci", "stroke", "ich")):
        return "urgent"
    if score == 0 or gap_type in {"application_failure", "cross_contamination", "numerical_recall"}:
        return "high"
    if score == 1:
        return "medium"
    return "low"


def _claim_state_for_score(
    score: int,
    existing_state: str | None = None,
    teaching_intent: str = "",
) -> tuple[str, str]:
    if existing_state == "durable" and score < 2:
        return "regressed", "regressed"
    if score == 0:
        return "missed", "missed"
    if score == 1:
        return "partially_repaired", "partial"
    if teaching_intent == "retention_check" and existing_state in {
        "missed",
        "partially_repaired",
        "repaired_same_session",
        "regressed",
    }:
        return "durable", "retention_passed"
    if existing_state in {"missed", "partially_repaired", "repaired_same_session", "regressed"}:
        return "repaired_same_session", "repaired"
    return "durable", "confirmed"


def _parse_ts(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _priority_delay_factor(priority: str) -> float:
    return {"urgent": 0.45, "high": 0.7, "medium": 1.0, "low": 1.35}.get(priority, 1.0)


def _update_memory_schedule(
    *,
    score: int,
    state: str,
    priority: str,
    existing: sqlite3.Row | None,
    now: str,
) -> tuple[float, float, str]:
    """Return DSR-lite difficulty, stability-days, and next due timestamp.

    This is intentionally simple and deterministic. It gives the claim layer the
    same shape as spaced-repetition scheduling without pretending sparse n=1
    data can support a fully fit FSRS model.
    """
    previous_difficulty = float(existing["difficulty"]) if existing and "difficulty" in existing.keys() else 0.3
    previous_stability = float(existing["stability"]) if existing and "stability" in existing.keys() else 1.0
    difficulty = min(1.0, max(0.05, previous_difficulty + {0: 0.18, 1: 0.08, 2: -0.06}[score]))
    if score == 0:
        stability = max(0.25, min(previous_stability * 0.45, 1.0))
    elif score == 1:
        stability = max(0.75, min(previous_stability * 0.8, 2.0))
    elif state == "repaired_same_session":
        stability = max(1.5, previous_stability * 1.35)
    elif state == "durable":
        stability = max(3.0, previous_stability * (2.2 - difficulty))
    else:
        stability = max(1.0, previous_stability)
    delay_days = max(0.1, stability * _priority_delay_factor(priority))
    due = (_parse_ts(now) or datetime.now(timezone.utc)) + timedelta(days=delay_days)
    return round(difficulty, 3), round(stability, 3), due.isoformat()


def _retrievability(last_seen_ts: str, stability: float, as_of: datetime | None = None) -> float:
    last = _parse_ts(last_seen_ts)
    if last is None:
        return 0.0
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    elapsed_days = max(0.0, (now - last).total_seconds() / 86400.0)
    return round(math.exp(-elapsed_days / max(float(stability or 0.1), 0.1)), 3)


def _ensure_session(conn: sqlite3.Connection, session_id: str, started: str, skill: str, topic_id: int, doc_path: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO sessions
           (session_id, started, skill, primary_topic_id, doc_path)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, started, skill, topic_id, doc_path),
    )
    conn.execute("INSERT OR IGNORE INTO session_topics (session_id, topic_id) VALUES (?, ?)", (session_id, topic_id))
    if doc_path:
        conn.execute(
            "UPDATE sessions SET doc_path = COALESCE(NULLIF(doc_path, ''), ?) WHERE session_id = ?",
            (doc_path, session_id),
        )


def _upsert_retrieval_card(
    conn: sqlite3.Connection,
    *,
    topic_id: int,
    claim_state_id: int,
    card_type: str,
    priority: str,
    summary: str,
    next_action: str,
    evidence_result_id: int,
    updated_ts: str,
    detail: dict[str, str | int | float] | None = None,
) -> None:
    status = "active"
    conn.execute(
        """INSERT INTO retrieval_cards
           (topic_id, claim_state_id, card_type, status, priority, summary, next_action,
            evidence_result_id, updated_ts, detail_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(topic_id, claim_state_id, card_type) DO UPDATE SET
             status = excluded.status,
             priority = excluded.priority,
             summary = excluded.summary,
             next_action = excluded.next_action,
             evidence_result_id = excluded.evidence_result_id,
             updated_ts = excluded.updated_ts,
             detail_json = excluded.detail_json""",
        (
            topic_id,
            claim_state_id,
            card_type,
            status,
            priority,
            _compact_text(summary),
            _compact_text(next_action),
            evidence_result_id,
            updated_ts,
            json.dumps(detail or {}, sort_keys=True),
        ),
    )


def _deactivate_other_cards(conn: sqlite3.Connection, claim_state_id: int, keep_card_type: str) -> None:
    conn.execute(
        "UPDATE retrieval_cards SET status = 'inactive' WHERE claim_state_id = ? AND card_type != ?",
        (claim_state_id, keep_card_type),
    )


def _derive_claim(
    *,
    concept: str,
    tested_claim: str,
    corrected_rule: str,
    correction: str,
) -> str:
    return (
        tested_claim.strip()
        or corrected_rule.strip()
        or correction.strip()
        or f"Apply {concept.strip()} in a clinical or study vignette."
    )


def _compact_text(text: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= limit:
        return text
    cut = text[:limit].rstrip()
    sentence_end = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(": "))
    if sentence_end >= max(80, int(limit * 0.55)):
        return cut[: sentence_end + 1].strip()
    return cut.rstrip(" ,;:.") + "..."


def _claim_match_score(existing: sqlite3.Row, candidate_text: str, expected_edge: str, corrected_rule: str) -> float:
    existing_text = " ".join((existing["claim_text"] or "", existing["reason"] or ""))
    existing_tokens = _tokens(existing_text)
    candidate_tokens = _tokens(" ".join((candidate_text, expected_edge, corrected_rule)))
    if not existing_tokens or not candidate_tokens:
        return 0.0
    overlap = len(existing_tokens & candidate_tokens)
    containment = overlap / max(1, min(len(existing_tokens), len(candidate_tokens)))
    jaccard = overlap / max(1, len(existing_tokens | candidate_tokens))
    return max(containment, jaccard)


def _find_matching_claim_state(
    conn: sqlite3.Connection,
    *,
    topic_id: int,
    claim_slug: str,
    claim_text: str,
    corrected_rule: str,
    agent_signal: dict[str, str],
    origin: str = "assessed",
    claim_slug_prefix: str = "",
) -> sqlite3.Row | None:
    # Matching is scoped to the same provenance: a service-origin gap never binds
    # to an assessed claim (or vice versa), even when they share a topic and tokens.
    exact = conn.execute(
        """SELECT id, claim_slug, claim_text, state, reason, difficulty, stability
           FROM claim_state
           WHERE topic_id = ? AND claim_slug = ? AND origin = ?
           ORDER BY last_seen_ts DESC LIMIT 1""",
        (topic_id, claim_slug, origin),
    ).fetchone()
    if exact:
        return exact

    expected_edge = agent_signal.get("expected_answer_edge", "")
    candidate_tokens = _tokens(" ".join((claim_text, expected_edge, corrected_rule)))
    if len(candidate_tokens) < 5:
        return None
    if not expected_edge and len(_tokens(corrected_rule)) < 5:
        return None
    params: list[object] = [topic_id, origin]
    prefix_filter = ""
    if claim_slug_prefix:
        prefix_filter = " AND claim_slug LIKE ?"
        params.append(f"{claim_slug_prefix}%")
    rows = conn.execute(
        f"""SELECT id, claim_slug, claim_text, state, reason, difficulty, stability
            FROM claim_state
            WHERE topic_id = ? AND origin = ?{prefix_filter}
            ORDER BY last_seen_ts DESC LIMIT 30""",
        params,
    ).fetchall()
    best: tuple[float, sqlite3.Row] | None = None
    for row in rows:
        score = _claim_match_score(row, claim_text, expected_edge, corrected_rule)
        if score >= 0.62 and (best is None or score > best[0]):
            best = (score, row)
    return best[1] if best else None


def _record_repair_episode_transition(
    conn: sqlite3.Connection,
    *,
    claim_state_id: int,
    result_id: int,
    score: int,
    gap_type: str,
    event: str,
    teaching_intent: str,
    teaching_move: str,
    now: str,
) -> None:
    move = _controlled_value(teaching_move)
    if score < 2:
        conn.execute(
            """UPDATE repair_episodes SET status = 'regressed'
               WHERE claim_state_id = ? AND status IN ('active', 'immediate_repair', 'retained')""",
            (claim_state_id,),
        )
        conn.execute(
            """INSERT INTO repair_episodes
               (claim_state_id, source_result_id, gap_type, teaching_move, started_ts)
               VALUES (?, ?, ?, ?, ?)""",
            (claim_state_id, result_id, gap_type, move, now),
        )
        return
    episode = conn.execute(
        """SELECT id FROM repair_episodes
           WHERE claim_state_id = ? AND status IN ('active', 'immediate_repair', 'retained')
           ORDER BY id DESC LIMIT 1""",
        (claim_state_id,),
    ).fetchone()
    if episode is None:
        return
    episode_id = int(episode["id"])
    if teaching_intent == "transfer_check":
        conn.execute(
            """UPDATE repair_episodes
                  SET transfer_result_id = ?, transfer_ts = ?, status = 'transferred'
                WHERE id = ?""",
            (result_id, now, episode_id),
        )
    elif teaching_intent == "retention_check" or event == "retention_passed":
        conn.execute(
            """UPDATE repair_episodes
                  SET retention_result_id = ?, retention_ts = ?, status = 'retained'
                WHERE id = ?""",
            (result_id, now, episode_id),
        )
    else:
        conn.execute(
            """UPDATE repair_episodes
                  SET repaired_result_id = ?, repaired_ts = ?, status = 'immediate_repair',
                      teaching_move = CASE WHEN ? != '' THEN ? ELSE teaching_move END
                WHERE id = ?""",
            (result_id, now, move, move, episode_id),
        )


def _log_claim_result(
    conn: sqlite3.Connection,
    *,
    exchange_id: int,
    topic_id: int,
    concept_id: int,
    topic_slug: str,
    concept: str,
    score: int,
    error_type: str,
    answer: str,
    correction: str,
    misconception: str,
    tested_claim: str,
    learner_claim: str,
    missing_edge: str,
    corrected_rule: str,
    clinical_consequence: str,
    retest_prompt_shape: str,
    learning_operation: str,
    agent_signal: dict[str, str],
    now: str,
    agent_priority: str = "",
    match_claim_state_id: int | None = None,
    force_new_claim: bool = False,
    repairs_claim_state_ids: tuple[int, ...] = (),
    origin: str = "assessed",
    rotation_id: int | None = None,
    service_slug: str = "",
    site_slug: str = "",
    convention: bool = False,
    inventory_concept_id: str = "",
) -> int:
    claim_text = _derive_claim(concept=concept, tested_claim=tested_claim, corrected_rule=corrected_rule, correction=correction)
    claim_slug = _slug(claim_text)
    # Service-origin claims live in a separate identity namespace so they never
    # collide with assessed claims on UNIQUE(topic_id, concept_id, claim_slug) and
    # never bind to them. Conventions are (service x site) local practice, tagged so
    # the service lens can keep them from carrying to another site.
    claim_slug_prefix = ""
    if origin == "service":
        if convention:
            claim_slug_prefix = f"svc-{service_slug}-{site_slug}-convention-"
        else:
            claim_slug_prefix = f"svc-{service_slug}-"
        claim_slug = f"{claim_slug_prefix}{claim_slug}"
    learner = learner_claim.strip() or _first_sentence(answer, "No learner answer captured.")
    missing = missing_edge.strip()
    fixed_rule = corrected_rule.strip() or correction.strip()
    consequence = clinical_consequence.strip()
    retest = retest_prompt_shape.strip() or f"Use a new vignette testing {concept} without repeating the original wording."
    if score < 2 and not missing:
        missing = misconception.strip() or _first_sentence(correction)
    if score < 2 and not consequence:
        consequence = "Future review should target this missing edge because it changes management or discrimination."
    gap_type = "convention" if convention else _normalize_gap_type(error_type, score, missing)
    # Claim identity is the agent's call when it knows. The agent assesses whether
    # this answer revisits a tracked claim or opens a new one — token overlap
    # cannot reliably make that distinction. Resolution order:
    #   1. force_new_claim  -> always a new claim_state (agent says "this is new")
    #   2. match_claim_state_id -> bind to the exact claim the agent named
    #   3. neither asserted -> fall back to the token matcher (legacy heuristic)
    if force_new_claim:
        existing = None
    elif match_claim_state_id is not None:
        existing = conn.execute(
            """SELECT id, claim_slug, claim_text, state, reason, difficulty, stability
               FROM claim_state WHERE id = ? AND topic_id = ?""",
            (int(match_claim_state_id), topic_id),
        ).fetchone()
        if existing is None:
            raise ValueError(
                f"match_claim_state_id={match_claim_state_id} not found under topic_id={topic_id}"
            )
    else:
        existing = _find_matching_claim_state(
            conn,
            topic_id=topic_id,
            claim_slug=claim_slug,
            claim_text=claim_text,
            corrected_rule=fixed_rule,
            agent_signal=agent_signal,
            origin=origin,
            claim_slug_prefix=claim_slug_prefix,
        )
    if existing and existing["claim_slug"] != claim_slug:
        claim_slug = existing["claim_slug"]
    conn.execute(
        """INSERT INTO claim_results
           (exchange_id, topic_id, concept_id, claim_slug, claim_text, score, gap_type,
            learner_claim, missing_edge, corrected_rule, clinical_consequence,
            retest_prompt_shape, learning_operation, agent_signal_json, created_at,
            origin, rotation_id, inventory_concept_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            exchange_id,
            topic_id,
            concept_id,
            claim_slug,
            claim_text,
            score,
            gap_type,
            learner,
            missing,
            fixed_rule,
            consequence,
            retest,
            _learning_operation(concept, claim_text, learning_operation),
            json.dumps(agent_signal, sort_keys=True),
            now,
            origin,
            rotation_id,
            inventory_concept_id or None,
        ),
    )
    result_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    teaching_intent = _normalize(agent_signal.get("teaching_intent", "")).replace(" ", "_")
    if teaching_intent in LOW_STAKES_TEACHING_INTENTS:
        return result_id
    state, event = _claim_state_for_score(score, existing["state"] if existing else None, teaching_intent)
    # Priority decides what the next session sees first. The agent, having just
    # judged the clinical stakes of this exact miss in context, sets it directly.
    # The keyword heuristic is only a fallback for when the agent does not assert.
    priority = _normalize_priority(agent_priority) or _priority(topic_slug, claim_text, gap_type, score)
    if state == "repaired_same_session" and priority == "low":
        priority = "medium"
    reason = missing or fixed_rule or learner
    difficulty, stability, next_due_ts = _update_memory_schedule(
        score=score,
        state=state,
        priority=priority,
        existing=existing,
        now=now,
    )
    if existing:
        state_id = int(existing["id"])
        conn.execute(
            """UPDATE claim_state
               SET claim_text = ?, state = ?, priority = ?, gap_type = ?,
                   last_result_id = ?, source_result_id = COALESCE(source_result_id, ?),
                   last_seen_ts = ?, next_due_ts = ?, difficulty = ?, stability = ?, reason = ?,
                   rotation_id = COALESCE(?, rotation_id)
               WHERE id = ?""",
            (claim_text, state, priority, gap_type, result_id, result_id, now, next_due_ts, difficulty, stability, reason, rotation_id, state_id),
        )
    else:
        conn.execute(
            """INSERT INTO claim_state
               (topic_id, concept_id, claim_slug, claim_text, state, priority, gap_type,
                last_result_id, source_result_id, last_seen_ts, next_due_ts, difficulty, stability, reason,
                origin, rotation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (topic_id, concept_id, claim_slug, claim_text, state, priority, gap_type, result_id, result_id, now, next_due_ts, difficulty, stability, reason, origin, rotation_id),
        )
        state_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        "INSERT INTO state_events (claim_state_id, event_type, result_id, ts, detail) VALUES (?, ?, ?, ?, ?)",
        (state_id, event, result_id, now, reason),
    )
    _record_repair_episode_transition(
        conn,
        claim_state_id=state_id,
        result_id=result_id,
        score=score,
        gap_type=gap_type,
        event=event,
        teaching_intent=teaching_intent,
        teaching_move=agent_signal.get("teaching_move", ""),
        now=now,
    )
    if state in {"missed", "partially_repaired", "repaired_same_session", "regressed"}:
        card_type = "must_retest" if state in {"missed", "partially_repaired", "regressed"} else "recent_repair"
        _deactivate_other_cards(conn, state_id, card_type)
        next_action = retest if state != "repaired_same_session" else "Run a delayed retention check before treating this repair as durable."
        summary = f"{state}: {missing or fixed_rule or claim_text}"
        _upsert_retrieval_card(
            conn,
            topic_id=topic_id,
            claim_state_id=state_id,
            card_type=card_type,
            priority=priority,
            summary=summary,
            next_action=next_action,
            evidence_result_id=result_id,
            updated_ts=now,
            detail={"claim": claim_text, "consequence": consequence},
        )
    elif state == "durable":
        _deactivate_other_cards(conn, state_id, "scaffold")
        _apply_asserted_repairs(
            conn,
            topic_id=topic_id,
            result_id=result_id,
            repairs_claim_state_ids=repairs_claim_state_ids,
            now=now,
        )
        _upsert_retrieval_card(
            conn,
            topic_id=topic_id,
            claim_state_id=state_id,
            card_type="scaffold",
            priority="low",
            summary=f"Durable scaffold: {claim_text}",
            next_action="Use as scaffold; avoid direct re-drill unless stale or contradicted.",
            evidence_result_id=result_id,
            updated_ts=now,
            detail={"learner_claim": learner},
        )
    return result_id


def _apply_asserted_repairs(
    conn: sqlite3.Connection,
    *,
    topic_id: int,
    result_id: int,
    repairs_claim_state_ids: tuple[int, ...],
    now: str,
) -> None:
    """Flip the open claims the agent explicitly named as repaired by this answer.

    Previously this was inferred from token overlap (>=0.35), which silently
    marked unrelated claims repaired just because they shared words. Repair is a
    judgment about whether *this* correct answer actually demonstrates mastery of
    *that* open claim — only the agent, having seen the answer, can assert it. The
    agent passes the specific claim_state ids; we flip only those, and only when
    they are genuinely open under this topic.
    """
    for raw_id in repairs_claim_state_ids:
        row = conn.execute(
            """SELECT id, claim_text, difficulty, stability FROM claim_state
               WHERE id = ? AND topic_id = ?
                 AND state IN ('missed', 'partially_repaired', 'regressed')""",
            (int(raw_id), topic_id),
        ).fetchone()
        if row is None:
            # Not open (or wrong topic): ignore rather than fabricate a transition.
            continue
        rationale = "Agent asserted this open claim was repaired by a related correct answer."
        difficulty, stability, next_due_ts = _update_memory_schedule(
            score=2,
            state="repaired_same_session",
            priority="medium",
            existing=row,
            now=now,
        )
        conn.execute(
            """UPDATE claim_state
               SET state = 'repaired_same_session', priority = 'medium',
                   last_result_id = ?, last_seen_ts = ?, next_due_ts = ?,
                   difficulty = ?, stability = ?, reason = ?
               WHERE id = ?""",
            (result_id, now, next_due_ts, difficulty, stability, rationale, row["id"]),
        )
        _deactivate_other_cards(conn, row["id"], "recent_repair")
        conn.execute(
            "INSERT INTO state_events (claim_state_id, event_type, result_id, ts, detail) VALUES (?, ?, ?, ?, ?)",
            (row["id"], "asserted_repair", result_id, now, rationale),
        )
        _record_repair_episode_transition(
            conn,
            claim_state_id=int(row["id"]),
            result_id=result_id,
            score=2,
            gap_type="",
            event="asserted_repair",
            teaching_intent="",
            teaching_move="",
            now=now,
        )
        _upsert_retrieval_card(
            conn,
            topic_id=topic_id,
            claim_state_id=row["id"],
            card_type="recent_repair",
            priority="medium",
            summary=f"Related repair: {row['claim_text']}",
            next_action="Run a delayed retention check before treating this repair as durable.",
            evidence_result_id=result_id,
            updated_ts=now,
            detail={"rationale": rationale},
        )


def log_answer(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    topic: str,
    concept: str,
    question: str,
    answer: str,
    correct: int,
    correction: str = "",
    error_type: str = "",
    misconception: str = "",
    doc_path: str = "",
    skill: str = "",
    turn: int | None = None,
    ts: str | None = None,
    tested_claim: str = "",
    learner_claim: str = "",
    missing_edge: str = "",
    corrected_rule: str = "",
    clinical_consequence: str = "",
    retest_prompt_shape: str = "",
    learning_operation: str = "",
    teaching_intent: str = "",
    expected_answer_edge: str = "",
    coverage_role: str = "",
    source_section: str = "",
    source_anchor: str = "",
    curriculum_unit: str = "",
    answer_mode: str = "",
    confidence_observed: str = "",
    teaching_move: str = "",
    strict_telemetry: bool = False,
    agent_priority: str = "",
    match_claim_state_id: int | None = None,
    force_new_claim: bool = False,
    repairs_claim_state_ids: tuple[int, ...] = (),
    origin: str = "assessed",
    rotation_id: int | None = None,
    competency_target: str = "",
    convention: bool = False,
    brain_dump_candidate_id: int | None = None,
    inventory_concept_id: str = "",
) -> int:
    if skill == "study-review" and origin == "assessed" and not inventory_concept_id:
        try:
            from session_map import bootstrap_session_map, lexical_match_inventory_id, load as load_session_map  # noqa: PLC0415
            smap = load_session_map(session_id) or bootstrap_session_map(
                conn, session_id=session_id, topic=topic, doc_path=doc_path, skill=skill,
            )
            if smap:
                matched, _ = lexical_match_inventory_id(concept, smap)
                if matched:
                    inventory_concept_id = matched
                    print(
                        f"WARN inventory_concept_id inferred={matched}; pass --inventory-concept-id explicitly",
                        file=sys.stderr,
                    )
        except Exception:
            pass
    if strict_telemetry:
        _validate_strict_telemetry(
            concept=concept,
            score=correct,
            error_type=error_type,
            misconception=misconception,
            missing_edge=missing_edge,
            corrected_rule=corrected_rule,
            correction=correction,
            tested_claim=tested_claim,
            answer_mode=answer_mode,
            confidence_observed=confidence_observed,
            teaching_move=teaching_move,
        )
    now = ts or datetime.now(timezone.utc).isoformat()
    # Default the rotation context from the active rotation when service-origin and
    # no rotation was explicitly supplied, so /service-log stays a one-line capture.
    if origin == "service" and rotation_id is None:
        active = conn.execute("SELECT id FROM rotations WHERE active = 1 ORDER BY id DESC LIMIT 1").fetchone()
        if active:
            rotation_id = int(active["id"])
    service_row = _service_for_rotation(conn, rotation_id) if (origin == "service" and rotation_id) else None
    site_row = _site_for_rotation(conn, rotation_id) if (origin == "service" and rotation_id) else None
    if origin == "service" and (rotation_id is None or service_row is None or site_row is None):
        raise ValueError(
            "service-origin memory requires an active or explicit valid rotation; "
            "run rotation-start or pass --rotation"
        )
    service_slug = service_row["slug"] if service_row else ""
    site_slug = site_row["slug"] if site_row else ""
    resolution = resolve_topic(conn, topic, doc_path)
    topic_id = _ensure_topic(conn, resolution, doc_path)
    concept_id = _ensure_concept(conn, topic_id, resolution.slug, concept, question, correction)
    _ensure_session(conn, session_id, now, skill, topic_id, doc_path)
    if turn is None:
        turn = int(conn.execute("SELECT COUNT(*) FROM exchanges WHERE session_id = ?", (session_id,)).fetchone()[0]) + 1
    source = {
        "teaching_intent": teaching_intent,
        "expected_answer_edge": expected_answer_edge,
        "coverage_role": coverage_role,
        "source_section": source_section,
        "source_anchor": source_anchor,
        "curriculum_unit": curriculum_unit,
        "answer_mode": answer_mode,
        "confidence_observed": confidence_observed,
        "teaching_move": teaching_move,
    }
    conn.execute(
        """INSERT INTO exchanges
           (session_id, ts, turn, topic_id, concept_id, raw_question, raw_answer,
            doc_path, skill, source_json, origin, rotation_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            now,
            turn,
            topic_id,
            concept_id,
            question,
            answer,
            doc_path,
            skill,
            json.dumps(source, sort_keys=True),
            origin,
            rotation_id,
        ),
    )
    exchange_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    # Artifact-anchor skills record the exchange (for provenance/discoverability)
    # but do not create a claim_result/claim_state — the learner has not been
    # tested on this content, so it must not register as known or as an open gap.
    if skill not in ARTIFACT_ANCHOR_SKILLS:
        result_id = _log_claim_result(
            conn,
            exchange_id=exchange_id,
            topic_id=topic_id,
            concept_id=concept_id,
            topic_slug=resolution.slug,
            concept=concept,
            score=correct,
            error_type=error_type,
            answer=answer,
            correction=correction,
            misconception=misconception,
            tested_claim=tested_claim,
            learner_claim=learner_claim,
            missing_edge=missing_edge,
            corrected_rule=corrected_rule,
            clinical_consequence=clinical_consequence,
            retest_prompt_shape=retest_prompt_shape,
            learning_operation=learning_operation,
            agent_priority=agent_priority,
            match_claim_state_id=match_claim_state_id,
            force_new_claim=force_new_claim,
            repairs_claim_state_ids=repairs_claim_state_ids,
            agent_signal={k: v for k, v in source.items() if v},
            now=now,
            origin=origin,
            rotation_id=rotation_id,
            service_slug=service_slug,
            site_slug=site_slug,
            convention=convention,
            inventory_concept_id=inventory_concept_id,
        )
        if inventory_concept_id:
            promote_inventory_binding = None
            try:
                from session_map import promote_inventory_binding  # noqa: PLC0415
            except ImportError:
                promote_inventory_binding = None
            if promote_inventory_binding:
                promote_inventory_binding(
                    conn,
                    learner_concept_id=concept_id,
                    inventory_concept_id=inventory_concept_id,
                )
        if brain_dump_candidate_id is not None or doc_path.startswith("Brain Dumps/"):
            _mark_brain_dump_candidate_reviewed(
                conn,
                result_id=result_id,
                candidate_id=brain_dump_candidate_id,
                topic_id=topic_id,
                concept_id=concept_id,
                doc_path=doc_path,
                now=now,
            )
        if origin == "assessed":
            # Recompute policy from the session knowledge map when available.
            try:
                plan, progress = _policy_after_log_answer(
                    conn,
                    session_id=session_id,
                    topic_id=topic_id,
                    topic_slug=resolution.slug,
                    doc_path=doc_path,
                    skill=skill,
                    inventory_concept_id=inventory_concept_id,
                    concept=concept,
                    correct=correct,
                    exchange_id=exchange_id,
                    coverage_role=coverage_role,
                    learner_concept_id=concept_id,
                )
                _record_policy_event(
                    conn,
                    session_id=session_id,
                    event_type="turn",
                    topic_id=topic_id,
                    plan=plan,
                    claim_result_id=result_id,
                    now=now,
                )
                if progress:
                    print("session_progress=" + _json_dumps(progress))
            except Exception as exc:
                print(f"WARN policy_event_failed: {exc}", file=sys.stderr)
    if competency_target and service_row:
        # Touching a rubric target during service learning advances it off 'open'.
        conn.execute(
            """UPDATE competency_targets SET status = 'developing'
               WHERE service_id = ? AND slug = ? AND status = 'open'""",
            (int(service_row["id"]), _slug(competency_target)),
        )
    conn.commit()
    return exchange_id


def end_session(conn: sqlite3.Connection, *, session_id: str, summary: str, next_strategy: str, ended: str | None = None, stats_json: str = "{}") -> dict[str, object]:
    try:
        from session_map import delete as delete_session_map, load as load_session_map, session_progress  # noqa: PLC0415
        smap = load_session_map(session_id)
        if smap:
            try:
                audit = json.loads(stats_json) if stats_json.strip() else {}
            except (ValueError, TypeError):
                audit = {}
            if not isinstance(audit, dict):
                audit = {}
            audit.setdefault("session_progress", session_progress(smap))
            if smap.get("scope"):
                audit.setdefault("inventory_scope", smap["scope"])
            stats_json = _json_dumps(audit)
        delete_session_map(session_id)
    except Exception as exc:
        print(f"WARN session_map_cleanup_failed: {exc}", file=sys.stderr)
    now = ended or datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO sessions
           (session_id, started, ended, summary, next_strategy, stats_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, now, now, summary, next_strategy, stats_json),
    )
    conn.execute(
        "UPDATE sessions SET ended = ?, summary = ?, next_strategy = ?, stats_json = ? WHERE session_id = ?",
        (now, summary, next_strategy, stats_json, session_id),
    )
    session_row = conn.execute(
        "SELECT primary_topic_id, skill FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    session_skill = session_row["skill"] if session_row else ""
    is_low_stakes_reference = session_skill in LOW_STAKES_REFERENCE_SKILLS
    is_artifact_anchor = session_skill in ARTIFACT_ANCHOR_SKILLS
    excluded_from_count = session_skill in CURATION_EXCLUDED_SKILLS
    # Artifact anchors remain discoverable without competing with learner handoffs.
    if session_row and session_row["primary_topic_id"] and not is_low_stakes_reference:
        card_type = "artifact_anchor" if is_artifact_anchor else "session_handoff"
        _upsert_session_card(conn, int(session_row["primary_topic_id"]), session_id, summary, next_strategy, now, card_type=card_type)
    newly_counted = False if excluded_from_count else mark_session_counted(conn, session_id, now)
    conn.commit()
    status_payload = curation_status(conn)
    return {
        "ok": True,
        "session_id": session_id,
        "newly_counted": newly_counted,
        "excluded_from_curation_count": excluded_from_count,
        "artifact_anchor": is_artifact_anchor,
        "curation": status_payload,
    }


def _upsert_session_card(
    conn: sqlite3.Connection,
    topic_id: int,
    session_id: str,
    summary: str,
    next_strategy: str,
    now: str,
    *,
    card_type: str = "session_handoff",
) -> None:
    if card_type not in {"session_handoff", "artifact_anchor"}:
        raise ValueError(f"unsupported session card type: {card_type!r}")
    existing = conn.execute(
        """SELECT id FROM retrieval_cards
           WHERE topic_id = ? AND claim_state_id IS NULL AND card_type = ?
           ORDER BY updated_ts DESC LIMIT 1""",
        (topic_id, card_type),
    ).fetchone()
    payload = json.dumps({"session_id": session_id}, sort_keys=True)
    priority = "low" if card_type == "artifact_anchor" else "medium"
    if existing:
        conn.execute(
            """UPDATE retrieval_cards
               SET status = 'active', priority = ?, summary = ?, next_action = ?,
                   evidence_result_id = NULL, updated_ts = ?, detail_json = ?
               WHERE id = ?""",
            (priority, _compact_text(summary), _compact_text(next_strategy), now, payload, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO retrieval_cards
               (topic_id, claim_state_id, card_type, status, priority, summary, next_action,
                evidence_result_id, updated_ts, detail_json)
               VALUES (?, NULL, ?, 'active', ?, ?, ?, NULL, ?, ?)""",
            (topic_id, card_type, priority, _compact_text(summary), _compact_text(next_strategy), now, payload),
        )
    conn.execute(
        """UPDATE retrieval_cards
              SET status = 'inactive'
            WHERE topic_id = ? AND claim_state_id IS NULL AND card_type = ?
              AND id != ?""",
        (topic_id, card_type, int(existing["id"]) if existing else int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])),
    )


def _retrieval_card_payload(row: sqlite3.Row) -> dict[str, str | None]:
    return {
        "topic": row["topic"],
        "type": row["card_type"],
        "priority": row["priority"],
        "state": row["state"],
        "claim_state_id": row["claim_state_id"],
        "concept_id": row["concept_id"],
        "concept": row["concept"],
        "claim": row["claim_text"],
        "summary": row["summary"],
        "next_action": row["next_action"],
    }


def _candidate_claim_slug(concept: str, claim_text: str, prompt: str) -> str:
    return _slug(claim_text.strip() or prompt.strip() or concept.strip())


def add_brain_dump_candidate(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    topic: str,
    concept: str,
    doc_path: str,
    prompt: str,
    claim_text: str,
    provenance_tier: str = "",
    origin: str = "assessed",
    rotation_id: int | None = None,
    convention: bool = False,
    detail: dict[str, object] | None = None,
    ts: str | None = None,
) -> int:
    if not doc_path.startswith("Brain Dumps/"):
        raise ValueError("brain-dump candidates must use a Brain Dumps/<Title>.md doc path")
    if origin not in {"assessed", "service"}:
        raise ValueError("origin must be assessed or service")
    now = ts or datetime.now(timezone.utc).isoformat()
    if origin == "service" and rotation_id is None:
        active = conn.execute("SELECT id FROM rotations WHERE active = 1 ORDER BY id DESC LIMIT 1").fetchone()
        if active:
            rotation_id = int(active["id"])
    service_row = _service_for_rotation(conn, rotation_id) if (origin == "service" and rotation_id) else None
    site_row = _site_for_rotation(conn, rotation_id) if (origin == "service" and rotation_id) else None
    if origin == "service" and (rotation_id is None or service_row is None or site_row is None):
        raise ValueError(
            "service-origin brain-dump candidates require an active or explicit valid rotation"
        )
    resolution = resolve_topic(conn, topic, doc_path)
    topic_id = _ensure_topic(conn, resolution, doc_path)
    concept_id = _ensure_concept(conn, topic_id, resolution.slug, concept, prompt, "")
    candidate_slug = _candidate_claim_slug(concept, claim_text, prompt)
    payload = json.dumps(detail or {}, sort_keys=True)
    conn.execute(
        """INSERT INTO brain_dump_review_candidates
           (session_id, topic_id, concept_id, doc_path, candidate_slug, prompt,
            claim_text, provenance_tier, origin, rotation_id, convention, status,
            created_at, updated_at, detail_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
           ON CONFLICT(doc_path, topic_id, concept_id, candidate_slug) DO UPDATE SET
             session_id = excluded.session_id,
             prompt = excluded.prompt,
             claim_text = excluded.claim_text,
             provenance_tier = excluded.provenance_tier,
             origin = excluded.origin,
             rotation_id = excluded.rotation_id,
             convention = excluded.convention,
             status = CASE
               WHEN brain_dump_review_candidates.status = 'reviewed' THEN 'reviewed'
               ELSE 'pending'
             END,
             updated_at = excluded.updated_at,
             detail_json = excluded.detail_json""",
        (
            session_id,
            topic_id,
            concept_id,
            doc_path,
            candidate_slug,
            _compact_text(prompt, 500),
            _compact_text(claim_text, 500),
            provenance_tier,
            origin,
            rotation_id,
            1 if convention else 0,
            now,
            now,
            payload,
        ),
    )
    row = conn.execute(
        """SELECT id FROM brain_dump_review_candidates
           WHERE doc_path = ? AND topic_id = ? AND concept_id = ? AND candidate_slug = ?""",
        (doc_path, topic_id, concept_id, candidate_slug),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def _brain_dump_candidates_for_summary(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
    limit: int,
    status: str = "pending",
) -> list[dict[str, object]]:
    topic_filter = ""
    params: list[object] = [status]
    if topic_id is not None:
        topic_filter = "AND b.topic_id = ?"
        params.append(topic_id)
    rows = conn.execute(
        f"""SELECT b.id, b.doc_path, b.prompt, b.claim_text, b.provenance_tier,
                  b.origin, b.rotation_id, b.convention, b.status, b.updated_at,
                  t.canonical_slug AS topic, c.display_name AS concept
             FROM brain_dump_review_candidates b
             JOIN topics t ON t.id = b.topic_id
             JOIN concepts c ON c.id = b.concept_id
            WHERE b.status = ? {topic_filter}
            ORDER BY CASE b.origin WHEN 'service' THEN 1 ELSE 0 END,
                     b.updated_at DESC
            LIMIT ?""",
        [*params, max(0, limit)],
    ).fetchall()
    return [
        {
            "candidate_id": int(row["id"]),
            "type": "brain_dump_review_candidate",
            "topic": row["topic"],
            "concept": row["concept"],
            "claim": row["claim_text"] or row["prompt"],
            "doc": row["doc_path"],
            "provenance_tier": row["provenance_tier"],
            "origin": row["origin"],
            "rotation_id": row["rotation_id"],
            "convention": bool(row["convention"]),
            "status": row["status"],
            "updated_ts": row["updated_at"],
            "weight": "low",
            "next_action": "Offer a Socratic probe; do not infer learner state until Gabriel answers.",
        }
        for row in rows
    ]


def _mark_brain_dump_candidate_reviewed(
    conn: sqlite3.Connection,
    *,
    result_id: int,
    candidate_id: int | None = None,
    topic_id: int | None = None,
    concept_id: int | None = None,
    doc_path: str = "",
    now: str,
) -> None:
    state = conn.execute(
        "SELECT id FROM claim_state WHERE last_result_id = ?",
        (result_id,),
    ).fetchone()
    if state is None:
        return
    claim_state_id = int(state["id"])
    if candidate_id is not None:
        conn.execute(
            """UPDATE brain_dump_review_candidates
                  SET status = 'reviewed',
                      reviewed_claim_state_id = ?,
                      reviewed_result_id = ?,
                      reviewed_at = ?,
                      updated_at = ?
                WHERE id = ?""",
            (claim_state_id, result_id, now, now, int(candidate_id)),
        )
        return
    if doc_path.startswith("Brain Dumps/") and topic_id is not None and concept_id is not None:
        conn.execute(
            """UPDATE brain_dump_review_candidates
                  SET status = 'reviewed',
                      reviewed_claim_state_id = ?,
                      reviewed_result_id = ?,
                      reviewed_at = ?,
                      updated_at = ?
                WHERE status = 'pending'
                  AND doc_path = ?
                  AND topic_id = ?
                  AND concept_id = ?""",
            (claim_state_id, result_id, now, now, doc_path, topic_id, concept_id),
        )


def _due_claims_for_summary(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
    limit: int,
    exclude_claim_state_ids: set[int] | None = None,
) -> list[dict[str, object]]:
    where = ("WHERE COALESCE(cs.next_due_ts, '') != '' AND cs.next_due_ts <= ?"
             " AND (cs.origin IS NULL OR cs.origin = 'assessed')")
    params: list[object] = [datetime.now(timezone.utc).isoformat()]
    if topic_id is not None:
        where += " AND cs.topic_id = ?"
        params.append(topic_id)
    if exclude_claim_state_ids:
        placeholders = ",".join("?" * len(exclude_claim_state_ids))
        where += f" AND cs.id NOT IN ({placeholders})"
        params.extend(sorted(exclude_claim_state_ids))
    rows = conn.execute(
        f"""SELECT cs.id, cs.concept_id, cs.claim_text, cs.state, cs.priority, cs.last_seen_ts,
                   cs.next_due_ts, cs.difficulty, cs.stability,
                   t.canonical_slug AS topic, c.display_name AS concept
              FROM claim_state cs
              JOIN topics t ON t.id = cs.topic_id
              JOIN concepts c ON c.id = cs.concept_id
              {where}
              ORDER BY CASE cs.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                       cs.next_due_ts ASC
              LIMIT ?""",
        [*params, max(0, limit)],
    ).fetchall()
    return [
        {
            "claim_state_id": int(r["id"]),
            "concept_id": int(r["concept_id"]),
            "topic": r["topic"],
            "concept": r["concept"],
            "claim": r["claim_text"],
            "state": r["state"],
            "priority": r["priority"],
            "next_due_ts": r["next_due_ts"],
            "difficulty": round(float(r["difficulty"]), 3),
            "stability": round(float(r["stability"]), 3),
            "retrievability": _retrievability(r["last_seen_ts"], float(r["stability"])),
            "next_action": "Run a changed-frame retention check before relying on this scaffold.",
        }
        for r in rows
    ]


def _confidence_bucket(value: str) -> str:
    v = _normalize(value).replace("-", "_")
    if not v:
        return ""
    if any(token in v for token in ("high", "fluent", "confident")):
        return "high"
    if any(token in v for token in ("low", "hesitant", "uncertain", "unsure")):
        return "low"
    return "medium"


def _calibration_profile_for_summary(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
    limit: int,
) -> dict[str, object]:
    where = "WHERE COALESCE(ex.skill, '') != 'quick-answer'"
    params: list[object] = []
    if topic_id is not None:
        where += " AND cr.topic_id = ?"
        params.append(topic_id)
    rows = conn.execute(
        f"""SELECT cr.id, cr.score, cr.claim_text, cr.created_at,
                   ex.source_json, t.canonical_slug AS topic, c.display_name AS concept
              FROM claim_results cr
              JOIN exchanges ex ON ex.id = cr.exchange_id
              JOIN topics t ON t.id = cr.topic_id
              JOIN concepts c ON c.id = cr.concept_id
              {where}
              ORDER BY cr.created_at DESC""",
        params,
    ).fetchall()
    buckets: dict[str, dict[str, float | int]] = {
        "high": {"count": 0, "misses": 0, "avg_score": 0.0},
        "medium": {"count": 0, "misses": 0, "avg_score": 0.0},
        "low": {"count": 0, "misses": 0, "avg_score": 0.0},
    }
    score_totals = {"high": 0.0, "medium": 0.0, "low": 0.0}
    high_confidence_misses: list[dict[str, object]] = []
    for row in rows:
        try:
            source = json.loads(row["source_json"] or "{}")
        except json.JSONDecodeError:
            source = {}
        bucket = _confidence_bucket(str(source.get("confidence_observed") or ""))
        if not bucket:
            continue
        score = int(row["score"])
        buckets[bucket]["count"] = int(buckets[bucket]["count"]) + 1
        buckets[bucket]["misses"] = int(buckets[bucket]["misses"]) + (1 if score < 2 else 0)
        score_totals[bucket] += score / 2
        if bucket == "high" and score < 2 and len(high_confidence_misses) < limit:
            high_confidence_misses.append({
                "claim_result_id": int(row["id"]),
                "topic": row["topic"],
                "concept": row["concept"],
                "claim": row["claim_text"],
                "score": score,
                "created_at": row["created_at"],
                "teaching_note": "High-confidence miss: prioritize a precise correction and changed-frame retest.",
            })
    for bucket, data in buckets.items():
        count = int(data["count"])
        data["avg_score"] = round(score_totals[bucket] / count, 3) if count else None
        data["miss_rate"] = round(int(data["misses"]) / count, 3) if count else None
    return {
        "buckets": buckets,
        "high_confidence_misses": high_confidence_misses,
    }


def _operation_profile_for_summary(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
    limit: int,
) -> list[dict[str, object]]:
    where = "WHERE COALESCE(cr.learning_operation, '') != '' AND COALESCE(ex.skill, '') != 'quick-answer'"
    params: list[object] = []
    if topic_id is not None:
        where += " AND cr.topic_id = ?"
        params.append(topic_id)
    rows = conn.execute(
        f"""SELECT COALESCE(NULLIF(t.domain, ''), 'general') AS domain,
                   cr.learning_operation AS operation,
                   COUNT(*) AS n,
                   SUM(CASE WHEN cr.score < 2 THEN 1 ELSE 0 END) AS misses,
                   AVG(cr.score) AS avg_score,
                   SUM(CASE WHEN cs.state IN ('missed','partially_repaired','regressed') THEN 1 ELSE 0 END) AS open_gaps
              FROM claim_results cr
              JOIN exchanges ex ON ex.id = cr.exchange_id
              JOIN topics t ON t.id = cr.topic_id
              LEFT JOIN claim_state cs ON cs.last_result_id = cr.id
              {where}
              GROUP BY domain, operation
              HAVING n >= 2
              ORDER BY (misses * 1.0 / n) DESC, open_gaps DESC, n DESC
              LIMIT ?""",
        [*params, max(0, limit)],
    ).fetchall()
    return [
        {
            "domain": r["domain"],
            "operation": r["operation"],
            "attempts": int(r["n"]),
            "misses": int(r["misses"] or 0),
            "miss_rate": round(float(r["misses"] or 0) / max(1, int(r["n"])), 3),
            "mastery_estimate": round(float(r["avg_score"] or 0) / 2, 3),
            "open_gaps": int(r["open_gaps"] or 0),
            "teaching_note": f"Bias probes toward {r['operation']} in {r['domain']} until this vector improves.",
        }
        for r in rows
    ]


def _catalog_coverage_for_summary(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
    limit: int,
) -> dict[str, object]:
    domain_filter = ""
    if topic_id is not None:
        row = conn.execute("SELECT domain FROM topics WHERE id = ?", (topic_id,)).fetchone()
        domain_filter = row["domain"] if row else ""
    covered_rows = conn.execute(
        """SELECT t.canonical_slug, t.display_name, t.domain, COUNT(cr.id) AS attempts
             FROM topics t
             JOIN claim_results cr ON cr.topic_id = t.id
             JOIN exchanges ex ON ex.id = cr.exchange_id
             WHERE COALESCE(ex.skill, '') != 'quick-answer'
             GROUP BY t.id"""
    ).fetchall()
    covered = {
        row["canonical_slug"]: {
            "title": row["display_name"],
            "domain": row["domain"],
            "attempts": int(row["attempts"]),
            "tokens": _topic_tokens(row["display_name"]),
        }
        for row in covered_rows
    }
    catalog = [
        (title, domain, tokens)
        for title, domain, tokens in _load_curriculum_catalog()
        if not domain_filter or domain == domain_filter
    ]
    frontier: list[dict[str, object]] = []
    blind_spots: list[dict[str, object]] = []
    tested = 0
    high_yield_terms = {
        "emergency", "management", "trauma", "sah", "aneurysm", "hydrocephalus",
        "stroke", "ich", "spine", "cord", "icu", "ct", "herniation", "airway",
    }
    # Coverage is tiered by token overlap against covered learner topics, the same
    # signal blind_spots already used. Strong overlap (>= CATALOG_MIN_OVERLAP shared
    # meaningful tokens) means the catalog topic is effectively tested; a single
    # shared token means adjacent-but-untested (frontier); zero overlap on a
    # high-yield topic is a blind spot. Exact-slug equality always counts as tested.
    for title, domain, tokens in catalog:
        slug = _slug(title)
        best_overlap = 0
        best_neighbor = ""
        for row in covered.values():
            overlap = len(tokens & row["tokens"])
            if overlap > best_overlap:
                best_overlap = overlap
                best_neighbor = str(row["title"])
        if slug in covered or best_overlap >= CATALOG_MIN_OVERLAP:
            tested += 1
            continue
        item = {
            "topic": slug,
            "title": _display(title),
            "domain": domain,
            "nearest_tested_topic": best_neighbor,
            "readiness_score": round(min(1.0, best_overlap / 4), 3),
            "reason": "untested catalog topic adjacent to covered material" if best_overlap == 1 else "high-yield catalog topic with no direct learner evidence",
        }
        if best_overlap == 1:
            frontier.append(item)
        elif tokens & high_yield_terms:
            blind_spots.append(item)
    frontier.sort(key=lambda x: (-float(x["readiness_score"]), str(x["title"])))
    blind_spots.sort(key=lambda x: (str(x["domain"]), str(x["title"])))
    return {
        "catalog_topics": len(catalog),
        "tested_catalog_topics": tested,
        "frontier_candidates": frontier[:limit],
        "blind_spots": blind_spots[:limit],
    }


def _shadow_queue_for_summary(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
    limit: int,
    include_brain_dump_candidates: bool = False,
) -> list[dict[str, object]]:
    topic_filter = ""
    params: list[object] = []
    if topic_id is not None:
        topic_filter = "AND cr.topic_id = ?"
        params.append(topic_id)
    quick_rows = conn.execute(
        f"""SELECT cr.id, cr.claim_text, cr.created_at, t.canonical_slug AS topic,
                   c.display_name AS concept
              FROM claim_results cr
              JOIN exchanges ex ON ex.id = cr.exchange_id
              JOIN topics t ON t.id = cr.topic_id
              JOIN concepts c ON c.id = cr.concept_id
              WHERE ex.skill = 'quick-answer'
                AND NOT EXISTS (
                    SELECT 1 FROM claim_state cs
                    WHERE cs.topic_id = cr.topic_id AND cs.concept_id = cr.concept_id
                )
                {topic_filter}
              ORDER BY cr.created_at DESC
              LIMIT ?""",
        [*params, max(0, limit)],
    ).fetchall()
    items = [
        {
            "type": "quick_answer_interest",
            "topic": row["topic"],
            "concept": row["concept"],
            "claim": row["claim_text"],
            "source_id": int(row["id"]),
            "updated_ts": row["created_at"],
            "weight": "low",
            "next_action": "Ask one lightweight probe later; do not treat as mastery or a miss.",
        }
        for row in quick_rows
    ]
    artifact_skills = tuple(sorted(ARTIFACT_ANCHOR_SKILLS))
    placeholders = ",".join("?" * len(artifact_skills))
    artifact_filter = ""
    artifact_params: list[object] = [*artifact_skills]
    if topic_id is not None:
        artifact_filter = "AND ex.topic_id = ?"
        artifact_params.append(topic_id)
    artifact_rows = conn.execute(
        f"""SELECT ex.id, ex.ts, ex.skill, ex.raw_question, t.canonical_slug AS topic,
                   c.display_name AS concept
              FROM exchanges ex
              JOIN topics t ON t.id = ex.topic_id
              JOIN concepts c ON c.id = ex.concept_id
              WHERE ex.skill IN ({placeholders}) {artifact_filter}
                AND NOT EXISTS (
                    SELECT 1
                      FROM exchanges review
                     WHERE review.topic_id = ex.topic_id
                       AND review.ts > ex.ts
                       AND EXISTS (
                           SELECT 1
                             FROM claim_results reviewed_claim
                            WHERE reviewed_claim.exchange_id = review.id
                       )
                )
              ORDER BY ex.ts DESC
              LIMIT ?""",
        [*artifact_params, max(0, limit)],
    ).fetchall()
    items.extend(
        {
            "type": "artifact_review_anchor",
            "topic": row["topic"],
            "concept": row["concept"],
            "claim": row["raw_question"],
            "source_id": int(row["id"]),
            "updated_ts": row["ts"],
            "weight": "low",
            "next_action": f"Use study-review to test the generated {row['skill']} artifact before inferring learner state.",
        }
        for row in artifact_rows
    )
    if include_brain_dump_candidates:
        items.extend(
            _brain_dump_candidates_for_summary(
                conn,
                topic_id=topic_id,
                limit=max(0, limit),
                status="pending",
            )
        )
    items.sort(key=lambda x: str(x["updated_ts"]), reverse=True)
    return items[:limit]


def _teaching_move_profile_for_summary(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
    limit: int,
) -> list[dict[str, object]]:
    where = "WHERE COALESCE(ex.skill, '') != 'quick-answer'"
    params: list[object] = []
    if topic_id is not None:
        where += " AND cr.topic_id = ?"
        params.append(topic_id)
    rows = conn.execute(
        f"""SELECT ex.source_json, cr.score
              FROM claim_results cr
              JOIN exchanges ex ON ex.id = cr.exchange_id
              {where}
              ORDER BY cr.created_at DESC""",
        params,
    ).fetchall()
    stats: dict[str, dict[str, int | float]] = {}
    for row in rows:
        try:
            source = json.loads(row["source_json"] or "{}")
        except json.JSONDecodeError:
            source = {}
        move = _normalize(str(source.get("teaching_move") or "")).replace(" ", "_")
        if not move:
            continue
        score = int(row["score"])
        bucket = stats.setdefault(move, {"attempts": 0, "score_total": 0.0, "misses": 0, "strong": 0})
        bucket["attempts"] = int(bucket["attempts"]) + 1
        bucket["score_total"] = float(bucket["score_total"]) + score / 2
        bucket["misses"] = int(bucket["misses"]) + (1 if score < 2 else 0)
        bucket["strong"] = int(bucket["strong"]) + (1 if score == 2 else 0)
    out = []
    for move, data in stats.items():
        attempts = int(data["attempts"])
        out.append({
            "teaching_move": move,
            "attempts": attempts,
            "mastery_after_move": round(float(data["score_total"]) / max(1, attempts), 3),
            "miss_rate": round(int(data["misses"]) / max(1, attempts), 3),
            "strong_answers": int(data["strong"]),
        })
    out.sort(key=lambda x: (-float(x["mastery_after_move"]), -int(x["attempts"]), str(x["teaching_move"])))
    return out[:limit]


def _telemetry_profile_for_summary(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
) -> dict[str, object]:
    where = "WHERE COALESCE(ex.skill, '') != 'quick-answer'"
    params: list[object] = []
    if topic_id is not None:
        where += " AND cr.topic_id = ?"
        params.append(topic_id)
    rows = conn.execute(
        f"""SELECT cr.score, cr.gap_type, ex.source_json
              FROM claim_results cr
              JOIN exchanges ex ON ex.id = cr.exchange_id
              {where}""",
        params,
    ).fetchall()
    fields = ("answer_mode", "confidence_observed", "teaching_move")
    populated = {field: 0 for field in fields}
    violations = {field: 0 for field in fields}
    allowed = {
        "answer_mode": VALID_ANSWER_MODES,
        "confidence_observed": VALID_CONFIDENCE_OBSERVATIONS,
        "teaching_move": VALID_TEACHING_MOVES,
    }
    miss_metadata_complete = 0
    misses = 0
    for row in rows:
        try:
            source = json.loads(row["source_json"] or "{}")
        except json.JSONDecodeError:
            source = {}
        for field in fields:
            value = _controlled_value(str(source.get(field) or ""))
            if value:
                populated[field] += 1
                if value not in allowed[field]:
                    violations[field] += 1
        if int(row["score"]) < 2:
            misses += 1
            if row["gap_type"]:
                miss_metadata_complete += 1
    total = len(rows)
    return {
        "assessed_claim_results": total,
        "field_completeness": {
            field: {
                "populated": populated[field],
                "rate": round(populated[field] / max(1, total), 3),
                "controlled_value_violations": violations[field],
            }
            for field in fields
        },
        "miss_gap_type_completeness": {
            "misses": misses,
            "populated": miss_metadata_complete,
            "rate": round(miss_metadata_complete / max(1, misses), 3),
        },
        "guardrail": "Use --strict-telemetry for assessed learning exchanges. Historical gaps remain visible but are not treated as clean efficacy evidence.",
    }


def _tutor_efficacy_profile_for_summary(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
    limit: int,
) -> list[dict[str, object]]:
    where = "WHERE COALESCE(re.teaching_move, '') != ''"
    params: list[object] = []
    if topic_id is not None:
        where += " AND cs.topic_id = ?"
        params.append(topic_id)
    rows = conn.execute(
        f"""SELECT re.teaching_move, COUNT(*) AS attempts,
                   SUM(CASE WHEN re.repaired_result_id IS NOT NULL THEN 1 ELSE 0 END) AS immediate_repairs,
                   SUM(CASE WHEN re.retention_result_id IS NOT NULL THEN 1 ELSE 0 END) AS retention_passes,
                   SUM(CASE WHEN re.transfer_result_id IS NOT NULL THEN 1 ELSE 0 END) AS transfer_passes,
                   SUM(CASE WHEN re.status = 'regressed' THEN 1 ELSE 0 END) AS regressions
              FROM repair_episodes re
              JOIN claim_state cs ON cs.id = re.claim_state_id
              {where}
             GROUP BY re.teaching_move
             ORDER BY retention_passes DESC, transfer_passes DESC, immediate_repairs DESC, attempts DESC
             LIMIT ?""",
        [*params, max(0, limit)],
    ).fetchall()
    return [
        {
            "teaching_move": row["teaching_move"],
            "attempts": int(row["attempts"]),
            "immediate_repairs": int(row["immediate_repairs"] or 0),
            "retention_passes": int(row["retention_passes"] or 0),
            "transfer_passes": int(row["transfer_passes"] or 0),
            "regressions": int(row["regressions"] or 0),
            "evidence_level": "directional" if int(row["attempts"]) >= 3 and int(row["retention_passes"] or 0) >= 2 else "insufficient",
            "directive": (
                "Use as a directional preference, not a mandatory route."
                if int(row["attempts"]) >= 3 and int(row["retention_passes"] or 0) >= 2
                else "Collect more delayed-retention evidence before preferring this teaching move."
            ),
        }
        for row in rows
    ]


def _context_focus_for_summary(
    *,
    context: str,
    due_claims: list[dict[str, object]],
    coverage_frontier: dict[str, object],
    shadow_queue: list[dict[str, object]],
    limit: int,
) -> list[dict[str, object]]:
    tokens = _topic_tokens(context)
    if not tokens:
        return []
    candidates: list[dict[str, object]] = []

    def add_candidate(surface: str, item: dict[str, object], text: str) -> None:
        matched = tokens & _topic_tokens(text)
        if not matched:
            return
        specific = matched - CONTEXT_GENERIC_TOKENS
        if len(matched) < 2 and not specific:
            return
        candidates.append({
            "surface": surface,
            "overlap": len(matched),
            "specific_overlap": len(specific),
            "matched_tokens": sorted(matched),
            "item": item,
        })

    for item in due_claims:
        text = " ".join(str(item.get(k, "")) for k in ("topic", "concept", "claim"))
        add_candidate("due_claims", item, text)
    for surface_name in ("frontier_candidates", "blind_spots"):
        for item in coverage_frontier.get(surface_name, []):
            if not isinstance(item, dict):
                continue
            text = " ".join(str(item.get(k, "")) for k in ("topic", "title", "domain"))
            add_candidate(surface_name, item, text)
    for item in shadow_queue:
        text = " ".join(str(item.get(k, "")) for k in ("topic", "concept", "claim"))
        add_candidate("shadow_queue", item, text)
    candidates.sort(key=lambda x: (-int(x["specific_overlap"]), -int(x["overlap"]), str(x["surface"])))
    return [
        {
            "surface": c["surface"],
            "context_overlap": int(c["overlap"]),
            "context_specific_overlap": int(c["specific_overlap"]),
            "matched_tokens": c["matched_tokens"],
            "item": c["item"],
        }
        for c in candidates[:limit]
    ]


def _scouting_candidates_for_summary(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
    topic: str,
    cards: list[dict[str, object]],
    due_claims: list[dict[str, object]],
    graph_signals: list[dict[str, object]],
    context_graph_focus: list[dict[str, object]],
    limit: int,
) -> list[dict[str, object]]:
    """Generate bounded neighboring-foundation candidates for agent validation."""
    if topic_id is None:
        return []
    focus_text = " ".join(
        [
            topic,
            *(
                " ".join(str(card.get(key, "")) for key in ("concept", "claim", "summary"))
                for card in cards
            ),
        ]
    )
    focus_tokens = _topic_tokens(focus_text)
    seen: set[tuple[str, str]] = set()
    candidates: list[dict[str, object]] = []

    def add(
        *,
        source: str,
        candidate_key: str,
        topic_slug: str,
        concept: str,
        relationship: str,
        rationale: str,
        evidence: dict[str, object],
        score: float,
        recommended_use: str,
    ) -> None:
        key = (source, candidate_key)
        if key in seen:
            return
        seen.add(key)
        candidates.append({
            "candidate_id": f"{source}:{candidate_key}",
            "source_surface": source,
            "topic": topic_slug,
            "concept": concept,
            "relationship": relationship,
            "relevance_reason": rationale,
            "evidence": evidence,
            "score": round(score, 3),
            "recommended_use": recommended_use,
            "agent_validation_required": True,
        })

    for signal in graph_signals:
        add(
            source="learner_graph",
            candidate_key=str(signal["relationship_id"]),
            topic_slug=topic,
            concept=str(signal["to_concept"]),
            relationship=str(signal["relation_type"]),
            rationale=(
                "Evidence-backed learner graph neighbor of an active retest concept; "
                f"direction={signal['direction']}."
            ),
            evidence={
                "relationship_id": signal["relationship_id"],
                "from_concept_id": signal["from_concept_id"],
                "to_concept_id": signal["to_concept_id"],
                "strength": signal["strength"],
            },
            score=100 + float(signal["strength"]),
            recommended_use="Validate as a prerequisite or bounded discrimination probe before weaving it into the review.",
        )

    for path in context_graph_focus:
        hops = int(path.get("hops", 0))
        matched_context_tokens = list(path.get("matched_context_tokens", []))
        if hops == 0 and len(matched_context_tokens) < 3:
            continue
        add(
            source="reviewed_reference_graph",
            candidate_key=str(path["node_key"]),
            topic_slug=topic,
            concept=str(path["node_label"]),
            relationship="reviewed_context_seed" if hops == 0 else "reviewed_context_path",
            rationale=(
                "Reviewed clinical graph seed matched the requested report and active learner-state context."
                if hops == 0
                else "Reviewed clinical graph path from the requested report and active learner-state context."
            ),
            evidence={
                "node_key": path["node_key"],
                "node_type": path["node_type"],
                "hops": hops,
                "path_weight": path["path_weight"],
                "matched_context_tokens": matched_context_tokens,
                "path": path["path"],
            },
            score=80 + float(path["path_weight"]) + (len(path.get("matched_context_tokens", [])) / 10),
            recommended_use="Validate that this path is central to the current report section before probing it.",
        )

    active_claim_ids = {
        int(card["claim_state_id"])
        for card in cards
        if card.get("claim_state_id") is not None
    }
    due_claim_ids = {int(item["claim_state_id"]) for item in due_claims}
    rows = conn.execute(
        """SELECT cs.id, cs.claim_text, cs.state, cs.priority,
                  t.canonical_slug AS topic, c.display_name AS concept
             FROM claim_state cs
            JOIN topics t ON t.id = cs.topic_id
            JOIN concepts c ON c.id = cs.concept_id
            WHERE cs.topic_id = ?
              AND (cs.origin IS NULL OR cs.origin = 'assessed')
              AND cs.state IN ('durable', 'repaired_same_session')
            ORDER BY CASE cs.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                     cs.last_seen_ts DESC""",
        (topic_id,),
    ).fetchall()
    for row in rows:
        claim_state_id = int(row["id"])
        if claim_state_id in active_claim_ids or claim_state_id in due_claim_ids:
            continue
        add(
            source="same_topic_scaffold",
            candidate_key=str(claim_state_id),
            topic_slug=str(row["topic"]),
            concept=str(row["concept"]),
            relationship="report_local_foundation",
            rationale="Confirmed report-local knowledge that may serve as a transfer premise for an active gap.",
            evidence={
                "claim_state_id": claim_state_id,
                "state": row["state"],
                "priority": row["priority"],
                "claim": row["claim_text"],
            },
            score=60,
            recommended_use="Use only if it sharpens transfer or exposes a missing foundation; do not re-drill by default.",
        )

    rows = conn.execute(
        """SELECT cs.id, cs.claim_text, cs.state, cs.priority,
                  t.canonical_slug AS topic, c.display_name AS concept
             FROM claim_state cs
            JOIN topics t ON t.id = cs.topic_id
            JOIN concepts c ON c.id = cs.concept_id
            WHERE cs.topic_id != ?
              AND (cs.origin IS NULL OR cs.origin = 'assessed')
              AND cs.state IN ('missed', 'partially_repaired', 'regressed', 'durable', 'repaired_same_session')
            ORDER BY CASE cs.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                     cs.last_seen_ts DESC""",
        (topic_id,),
    ).fetchall()
    for row in rows:
        matched = focus_tokens & _topic_tokens(f"{row['topic']} {row['concept']} {row['claim_text']}")
        specific = {
            token for token in matched
            if token.isalpha() and len(token) >= 4 and token not in SCOUT_GENERIC_TOKENS
        }
        if len(specific) < 2:
            continue
        add(
            source="cross_topic_overlap",
            candidate_key=str(row["id"]),
            topic_slug=str(row["topic"]),
            concept=str(row["concept"]),
            relationship="candidate_foundation_or_transfer",
            rationale=f"Cross-topic learner-state overlap on: {', '.join(sorted(matched))}.",
            evidence={
                "claim_state_id": int(row["id"]),
                "state": row["state"],
                "priority": row["priority"],
                "claim": row["claim_text"],
                "matched_tokens": sorted(matched),
            },
            score=40 + len(specific) + (len(matched) / 10),
            recommended_use="Agent must verify the clinical connection and curriculum scope before using this candidate.",
        )

    candidates.sort(key=lambda item: (-float(item["score"]), str(item["concept"])))
    return candidates[: max(0, limit)]


def _verbatim_misconceptions(
    conn: sqlite3.Connection,
    concept_id: int,
    *,
    limit: int = 2,
    answer_limit: int = 180,
    misconception_limit: int = 140,
) -> list[dict[str, str]]:
    rows = conn.execute(
        """SELECT DISTINCT ex.raw_answer, cr.missing_edge
           FROM claim_results cr
           JOIN exchanges ex ON ex.id = cr.exchange_id
           WHERE cr.concept_id = ? AND cr.score < 2
             AND COALESCE(cr.origin, 'assessed') = 'assessed'
             AND COALESCE(ex.origin, 'assessed') = 'assessed'
             AND COALESCE(ex.skill, '') != 'quick-answer'
             AND (COALESCE(ex.raw_answer, '') != '' OR COALESCE(cr.missing_edge, '') != '')
           ORDER BY cr.id DESC LIMIT ?""",
        (concept_id, max(0, limit)),
    ).fetchall()
    res = []
    for r in rows:
        item = {}
        if r["raw_answer"]:
            item["verbatim"] = _compact_text(r["raw_answer"], answer_limit)
        if r["missing_edge"]:
            item["misconception"] = _compact_text(r["missing_edge"], misconception_limit)
        if item:
            res.append(item)
    return res


def _claim_state_repair_stats(conn: sqlite3.Connection, claim_state_id: int) -> dict[str, int]:
    rows = conn.execute(
        """SELECT event_type, COUNT(*) as n
           FROM state_events
           WHERE claim_state_id = ?
           GROUP BY event_type""",
        (claim_state_id,),
    ).fetchall()
    counts = {r["event_type"]: int(r["n"]) for r in rows}
    failures = counts.get("missed", 0) + counts.get("regressed", 0) + counts.get("partial", 0)
    repairs = counts.get("repaired", 0) + counts.get("asserted_repair", 0) + counts.get("retention_passed", 0)
    return {
        "failures": failures,
        "repairs": repairs,
    }


MISCONCEPTION_GAP_TYPES = frozenset({"conceptual_confusion", "cross_contamination"})
OPEN_GAP_STATES = frozenset({"missed", "partially_repaired", "regressed"})
POLICY_MODE_FOR_PHASE = {
    "phase_1_clear_fog": "orient",
    "phase_2_recalibrate_gaps": "deepen",
    "phase_3_force_connections": "connect",
}


def _concept_relations(conn: sqlite3.Connection, cid: int) -> dict[str, list[str]]:
    """Return prerequisite and confused-with neighbors for a concept from the learner graph."""
    rows = conn.execute(
        """SELECT cr.relation_type, cr.source_concept_id, cr.target_concept_id,
                  c_src.display_name AS source_name, c_tgt.display_name AS target_name
           FROM concept_relationships cr
           JOIN concepts c_src ON c_src.id = cr.source_concept_id
           JOIN concepts c_tgt ON c_tgt.id = cr.target_concept_id
           WHERE cr.source_concept_id = ? OR cr.target_concept_id = ?""",
        (cid, cid),
    ).fetchall()
    prereqs = []
    competitors = []
    for r in rows:
        rel = r["relation_type"]
        src_id = int(r["source_concept_id"])
        tgt_id = int(r["target_concept_id"])
        if rel == "prerequisite":
            if tgt_id == cid:
                prereqs.append(r["source_name"])
        elif rel == "confused_with":
            other_name = r["target_name"] if src_id == cid else r["source_name"]
            competitors.append(other_name)
    res: dict[str, list[str]] = {}
    if prereqs:
        res["prerequisites"] = prereqs
    if competitors:
        res["semantic_competitors"] = competitors
    return res


def _active_prereq_gaps(conn: sqlite3.Connection, cid: int) -> list[str]:
    """Return prerequisite concepts of `cid` that currently have open assessed gaps."""
    rows = conn.execute(
        """SELECT c_src.display_name
           FROM concept_relationships cr
           JOIN concepts c_src ON c_src.id = cr.source_concept_id
           JOIN claim_state cs ON cs.concept_id = cr.source_concept_id
           WHERE cr.target_concept_id = ? AND cr.relation_type = 'prerequisite'
             AND cs.state IN ('missed', 'partially_repaired', 'regressed')
             AND (cs.origin IS NULL OR cs.origin = 'assessed')""",
        (cid,),
    ).fetchall()
    return [r["display_name"] for r in rows]


def _build_schema_map(conn: sqlite3.Connection, topic_slug: str) -> list[dict[str, object]]:
    """Deterministic per-concept exposure/mastery map for a topic from the learner model."""
    topic_row = conn.execute("SELECT id FROM topics WHERE canonical_slug = ?", (topic_slug,)).fetchone()
    if not topic_row:
        return []
    topic_id = int(topic_row[0])
    concepts_rows = conn.execute(
        "SELECT id, display_name, canonical_slug FROM concepts WHERE topic_id = ?",
        (topic_id,),
    ).fetchall()
    # Formal lens only: service-origin captures are sealed out of the formal
    # schema map and never drive the deterministic teaching policy.
    attempts_rows = conn.execute(
        """SELECT concept_id, COUNT(*) as cnt, SUM(CASE WHEN score >= 2.0 THEN 1 ELSE 0 END) as success_cnt
           FROM claim_results
           WHERE topic_id = ? AND origin = 'assessed'
           GROUP BY concept_id""",
        (topic_id,),
    ).fetchall()
    attempts_map = {r[0]: (r[1], r[2]) for r in attempts_rows}
    state_rows = conn.execute(
        """SELECT concept_id, state, priority, stability, gap_type
           FROM claim_state
           WHERE topic_id = ? AND origin = 'assessed'""",
        (topic_id,),
    ).fetchall()
    concept_claims: dict[int, list[dict[str, object]]] = {}
    for r in state_rows:
        concept_claims.setdefault(r[0], []).append({
            "state": r[1],
            "priority": r[2],
            "stability": r[3],
            "gap_type": r[4],
        })
    state_priority = {
        "missed": 0,
        "partially_repaired": 1,
        "regressed": 2,
        "repaired_same_session": 3,
        "passed": 4,
    }
    schema_map: list[dict[str, object]] = []
    for c_row in concepts_rows:
        cid = int(c_row[0])
        c_display = str(c_row[1])
        relations = _concept_relations(conn, cid)
        prereqs = relations.get("prerequisites", [])
        competitors = relations.get("semantic_competitors", [])
        active_gaps = _active_prereq_gaps(conn, cid)
        att_cnt, succ_cnt = attempts_map.get(cid, (0, 0))
        sqlite_rate = round(succ_cnt / att_cnt, 3) if att_cnt > 0 else 0.0
        claims = concept_claims.get(cid, [])
        worst_state = None
        worst_val = 999
        safety_critical = False
        active_misconception = False
        avg_stability = 1.0
        if claims:
            stabilities = [cl["stability"] for cl in claims if cl["stability"] is not None]
            avg_stability = sum(stabilities) / len(stabilities) if stabilities else 1.0
            for cl in claims:
                st = cl["state"]
                if cl["priority"] in ("urgent", "high"):
                    safety_critical = True
                if st in OPEN_GAP_STATES and str(cl.get("gap_type") or "") in MISCONCEPTION_GAP_TYPES:
                    active_misconception = True
                if st in state_priority and state_priority[st] < worst_val:
                    worst_val = state_priority[st]
                    worst_state = st
        if att_cnt == 0:
            exposure_status = "unexposed"
        elif att_cnt == 1 or avg_stability < 2.0 or sqlite_rate < 0.6:
            exposure_status = "exposed_superficial"
        else:
            exposure_status = "exposed_deep"
        schema_map.append({
            "concept_id": cid,
            "concept": c_display,
            "exposure_status": exposure_status,
            "knowledge_state": worst_state or "untested",
            "attempts_count": att_cnt,
            "sqlite_success_rate": sqlite_rate,
            "anki_reviews_count": 0,
            "anki_success_rate": 0.0,
            "prerequisites": prereqs,
            "active_prerequisite_gaps": active_gaps,
            "semantic_competitors": competitors,
            "safety_critical": safety_critical,
            "active_misconception": active_misconception,
        })
    return schema_map


def _compute_teaching_policy(
    schema_map: list[dict[str, object]],
    *,
    due_claims: list[dict[str, object]] | tuple = (),
    shadow_rule_signals: list[dict[str, object]] | tuple = (),
) -> dict[str, object]:
    """Deterministic pedagogical policy: macro phase plus interrupt overlays.

    The phase (orient -> deepen -> connect) is a pure function of the schema map.
    REMEDIATE and CONSOLIDATE are interrupts, not phases: they are detectable at
    any time from misconception flags / shadow rules and from due claims, and
    they overlay the current phase rather than replacing it. The agent chooses
    teaching moves within this policy; it never chooses the phase.
    """
    if not schema_map:
        return {}
    unexposed_concepts = [c for c in schema_map if c["exposure_status"] == "unexposed"]
    gap_or_superficial = [
        c for c in schema_map
        if c["exposure_status"] == "exposed_superficial" or c["knowledge_state"] in OPEN_GAP_STATES
    ]
    if unexposed_concepts:
        phase = "phase_1_clear_fog"
        desc = "Superficial clinical introductions to unexposed concepts to clear the fog of war and build a schema map."
        targets = [c["concept"] for c in unexposed_concepts]
        directives = [
            "Start with brief, superficial clinical introductions to unexposed concepts.",
            "At boundaries, present a 'lay of the land' menu to invite Gabriel to pick his entry point.",
            "Keep questions high-level (e.g. clinical presentations, initial imaging, common options) before drilling deep mechanisms.",
        ]
        socratic_choice = "Present a clear 'lay of the land' choice listing remaining unexposed concepts, letting the user direct the focus."
    elif gap_or_superficial:
        phase = "phase_2_recalibrate_gaps"
        desc = "Deepen understanding of active gaps and superficial concepts using mechanistic Socratic drills."
        targets = [c["concept"] for c in gap_or_superficial]
        directives = [
            "Drill deep mechanisms, thresholds, and clinical discriminators for active gaps.",
            "Prioritize prerequisite concepts before their dependent concepts.",
            "Contrast semantic competitors if confused.",
        ]
        socratic_choice = "Invite the user to choose which specific gap or concept they want to deep-dive into next, or recommend a prerequisite gap."
    else:
        phase = "phase_3_force_connections"
        desc = "Synthesize connections and test transfer reasoning across deep, stable concepts."
        targets = [c["concept"] for c in schema_map]
        directives = [
            "Ask multi-concept clinical cases requiring complex sequencing or management trade-offs.",
            "Force transfer reasoning under changed acuity or clinical settings.",
            "Encourage oral-board-style defense of clinical decisions.",
        ]
        socratic_choice = "Ask the user to choose a complex scenario type (e.g., intraoperative complication, post-op complication firefight) to test their synthesis."

    remediate = {str(c["concept"]) for c in schema_map if c.get("active_misconception")}
    for rule in shadow_rule_signals:
        if not isinstance(rule, dict) or str(rule.get("status") or "active") not in ("active", "regressed"):
            continue
        for binding in rule.get("bindings", []) or []:
            if isinstance(binding, dict) and binding.get("binding_type") == "trigger" and binding.get("concept"):
                remediate.add(str(binding["concept"]))
    consolidate = [
        {
            "concept": item.get("concept"),
            "claim_state_id": item.get("claim_state_id"),
            "retrievability": item.get("retrievability"),
        }
        for item in due_claims
        if isinstance(item, dict)
    ]
    if remediate:
        directives.append(
            "REMEDIATE interrupt: re-teach the flagged misconception concepts before introducing new material, "
            "then retest each with a changed clinical frame."
        )
    if consolidate:
        directives.append(
            "CONSOLIDATE interrupt: interleave brief spaced-retrieval probes for the due claims listed in "
            "interrupts.consolidate before extending into new content."
        )
    return {
        "current_phase": phase,
        "mode": POLICY_MODE_FOR_PHASE[phase],
        "phase_description": desc,
        "target_concepts": targets,
        "pedagogical_directives": directives,
        "socratic_choice_directives": socratic_choice,
        "interrupts": {
            "remediate": sorted(remediate),
            "consolidate": consolidate,
        },
        "decision_inputs": {
            "concepts_total": len(schema_map),
            "unexposed": len(unexposed_concepts),
            "gap_or_superficial": len(gap_or_superficial),
            "remediate_flags": len(remediate),
            "due_claims": len(consolidate),
        },
    }


def _record_policy_event(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    event_type: str,
    topic_id: int | None,
    plan: dict[str, object],
    claim_result_id: int | None = None,
    now: str | None = None,
) -> None:
    """Append an auditable policy mode/transition event derived from deterministic state."""
    if not plan:
        return
    conn.execute(
        """INSERT INTO policy_events
           (session_id, ts, event_type, topic_id, mode, phase, interrupts_json, inputs_json, plan_json, claim_result_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            now or datetime.now(timezone.utc).isoformat(),
            event_type,
            topic_id,
            str(plan.get("mode") or ""),
            str(plan.get("current_phase") or ""),
            _json_dumps(plan.get("interrupts") or {}),
            _json_dumps(plan.get("decision_inputs") or {}),
            _json_dumps(plan),
            claim_result_id,
        ),
    )


def _current_policy_for_topic(
    conn: sqlite3.Connection,
    *,
    topic_id: int,
    topic_slug: str,
) -> dict[str, object]:
    """Recompute the deterministic teaching policy from current learner state."""
    schema_map = _build_schema_map(conn, topic_slug)
    if not schema_map:
        return {}
    due = _due_claims_for_summary(conn, topic_id=topic_id, limit=8)
    concept_ids = [int(c["concept_id"]) for c in schema_map if c.get("concept_id") is not None]
    shadows = shadow_rule_signals_for_summary(conn, relevant_concept_ids=concept_ids, limit=4)
    return _compute_teaching_policy(schema_map, due_claims=due, shadow_rule_signals=shadows)


def _policy_after_log_answer(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    topic_id: int,
    topic_slug: str,
    doc_path: str,
    skill: str,
    inventory_concept_id: str,
    concept: str,
    correct: int,
    exchange_id: int,
    coverage_role: str,
    learner_concept_id: int,
) -> tuple[dict[str, object], dict[str, int]]:
    """Patch session knowledge map and return the next-turn policy."""
    from session_map import (  # noqa: PLC0415
        bootstrap_session_map,
        compute_policy_from_session,
        load as load_session_map,
        patch_after_log,
        session_progress,
        write as write_session_map,
    )

    data = load_session_map(session_id)
    if data is None:
        data = bootstrap_session_map(
            conn,
            session_id=session_id,
            topic=topic_slug,
            doc_path=doc_path,
            skill=skill,
        )
    if data:
        data, delta = patch_after_log(
            data,
            inventory_concept_id=inventory_concept_id,
            concept_text=concept,
            correct=correct,
            exchange_id=exchange_id,
            coverage_role=coverage_role,
            learner_concept_id=learner_concept_id,
        )
        write_session_map(session_id, data)
        if delta == "unbound":
            plan = _current_policy_for_topic(conn, topic_id=topic_id, topic_slug=topic_slug)
        else:
            plan = compute_policy_from_session(data, conn, topic_id=topic_id, topic_slug=topic_slug)
        return plan, session_progress(data)
    plan = _current_policy_for_topic(conn, topic_id=topic_id, topic_slug=topic_slug)
    return plan, {}


def _integrate_inventory_knowledge_map(
    conn: sqlite3.Connection,
    brief: dict[str, object],
    *,
    topic: str,
    doc_path: str,
    profile: str,
    session_id: str = "",
) -> None:
    """Replace SQLite-only schema map with inventory-grounded knowledge_map."""
    from session_map import (  # noqa: PLC0415
        apply_artifact_priority,
        build_inventory_projection,
        create_from_projection,
        write as write_session_map,
    )

    projection = build_inventory_projection(topic=topic, doc_path=doc_path, memory_db=DB_PATH)
    if not projection:
        return
    knowledge_map = list(projection.get("knowledge_map") or [])
    if not knowledge_map:
        brief["knowledge_map_status"] = "empty_no_inventory_scope"
        return
    teaching_plan = dict(projection.get("sequential_teaching_plan") or {})
    teaching_plan = apply_artifact_priority(
        teaching_plan,
        knowledge_map,
        profile=profile,
        doc_path=doc_path,
    )
    brief["knowledge_map"] = knowledge_map
    brief["knowledge_map_status"] = "ok"
    brief["sequential_teaching_plan"] = teaching_plan
    brief["inventory_unmatched_learner_concepts"] = projection.get("unmatched_learner_concepts", [])
    brief["inventory_counts"] = projection.get("counts", {})
    if profile == "doc" and doc_path:
        brief["document_priority"] = "requested_doc_primary"
        brief["teaching_priority"] = "artifact_primary"
    if session_id:
        session_data = create_from_projection(
            projection,
            session_id=session_id,
            profile=profile,
            doc_path=doc_path,
            learner_topics=[topic] if topic else [],
        )
        write_session_map(session_id, session_data)


def _planning_brief_for_summary(
    conn: sqlite3.Connection | None,
    *,
    topic_slug: str | None = None,
    cards: list[dict[str, object]],
    curated_summaries: list[dict[str, object]],
    graph_signals: list[dict[str, object]],
    shadow_rule_signals: list[dict[str, object]],
    due_claims: list[dict[str, object]],
    calibration_profile: dict[str, object],
    operation_profile: list[dict[str, object]],
    teaching_move_profile: list[dict[str, object]],
    telemetry_profile: dict[str, object],
    tutor_efficacy_profile: list[dict[str, object]],
    coverage_frontier: dict[str, object],
    contextual_frontier: list[dict[str, object]],
    low_confidence_leads: list[dict[str, object]],
) -> dict[str, object]:
    """Return a first-read tutor brief while preserving raw evidence surfaces."""
    session_topic = topic_slug

    def compact_card(card: dict[str, object]) -> dict[str, object]:
        state_id = card.get("claim_state_id")
        concept_id = card.get("concept_id")
        card_topic = card.get("topic")
        res = {
            "claim_state_id": state_id,
            "concept_id": concept_id,
            "concept": card.get("concept"),
            "priority": card.get("priority"),
            "state": card.get("state"),
            "summary": card.get("summary"),
            "next_action": card.get("next_action"),
        }
        if card_topic and card_topic != session_topic:
            res["topic"] = card_topic
        if conn and state_id is not None:
            res["repair_velocity"] = _claim_state_repair_stats(conn, int(state_id))
        if conn and concept_id is not None:
            res["historical_misconceptions"] = _verbatim_misconceptions(conn, int(concept_id))
            relations = _concept_relations(conn, int(concept_id))
            if "prerequisites" in relations:
                res["prerequisites"] = relations["prerequisites"]
                active_gaps = _active_prereq_gaps(conn, int(concept_id))
                if active_gaps:
                    res["active_prerequisite_gaps"] = active_gaps
            if "semantic_competitors" in relations:
                res["semantic_competitors"] = relations["semantic_competitors"]
        return res

    def compact_due(item: dict[str, object]) -> dict[str, object]:
        state_id = item.get("claim_state_id")
        concept_id = item.get("concept_id")
        item_topic = item.get("topic")
        res = {
            "claim_state_id": state_id,
            "concept_id": concept_id,
            "concept": item.get("concept"),
            "priority": item.get("priority"),
            "retrievability": item.get("retrievability"),
            "next_action": item.get("next_action"),
        }
        if item_topic and item_topic != session_topic:
            res["topic"] = item_topic
        if conn and state_id is not None:
            res["repair_velocity"] = _claim_state_repair_stats(conn, int(state_id))
        if conn and concept_id is not None:
            res["historical_misconceptions"] = _verbatim_misconceptions(conn, int(concept_id))
            relations = _concept_relations(conn, int(concept_id))
            if "prerequisites" in relations:
                res["prerequisites"] = relations["prerequisites"]
                active_gaps = _active_prereq_gaps(conn, int(concept_id))
                if active_gaps:
                    res["active_prerequisite_gaps"] = active_gaps
            if "semantic_competitors" in relations:
                res["semantic_competitors"] = relations["semantic_competitors"]
        return res

    def compact_high_confidence_miss(item: dict[str, object]) -> dict[str, object]:
        return {
            "claim_result_id": item.get("claim_result_id"),
            "concept": item.get("concept"),
            "score": item.get("score"),
            "teaching_note": item.get("teaching_note"),
        }

    def compact_operation(item: dict[str, object]) -> dict[str, object]:
        return {
            "domain": item.get("domain"),
            "operation": item.get("operation"),
            "attempts": item.get("attempts"),
            "miss_rate": item.get("miss_rate"),
            "open_gaps": item.get("open_gaps"),
            "teaching_note": item.get("teaching_note"),
        }

    def compact_frontier(item: dict[str, object]) -> dict[str, object]:
        return {
            "candidate_id": item.get("candidate_id"),
            "source_surface": item.get("source_surface"),
            "concept": item.get("concept"),
            "relationship": item.get("relationship"),
            "reason": item.get("relevance_reason"),
            "agent_validation_required": True,
        }

    def compact_pattern(item: dict[str, object]) -> dict[str, object]:
        return {
            "summary_type": item.get("summary_type"),
            "content": item.get("content"),
            "importance_score": item.get("importance_score"),
        }

    def compact_shadow_rule(item: dict[str, object]) -> dict[str, object]:
        return {
            "shadow_rule_id": item.get("shadow_rule_id"),
            "false_rule": item.get("false_rule"),
            "corrected_rule": item.get("corrected_rule"),
            "clinical_consequence": item.get("clinical_consequence"),
            "probe_shape": item.get("probe_shape"),
            "bindings": item.get("bindings"),
        }

    def compact_efficacy(item: dict[str, object]) -> dict[str, object]:
        return {
            "teaching_move": item.get("teaching_move"),
            "attempts": item.get("attempts"),
            "retention_passes": item.get("retention_passes"),
            "transfer_passes": item.get("transfer_passes"),
            "regressions": item.get("regressions"),
            "evidence_level": item.get("evidence_level"),
        }

    def compact_move_profile(item: dict[str, object]) -> dict[str, object]:
        return {
            "teaching_move": item.get("teaching_move"),
            "attempts": item.get("attempts"),
            "mastery_after_move": item.get("mastery_after_move"),
            "miss_rate": item.get("miss_rate"),
        }

    handoffs = [card for card in cards if card.get("type") == "session_handoff"]
    must_retest = [card for card in cards if card.get("type") == "must_retest"]
    repairs = [card for card in cards if card.get("type") == "recent_repair"]
    high_confidence_misses = list(calibration_profile.get("high_confidence_misses", []))
    weak_operations = [
        item for item in operation_profile
        if float(item.get("miss_rate", 0) or 0) > 0
    ]

    # Topological dependency sorting: adjust priority of must_retest cards based on prerequisites
    must_retest_cids = {int(card.get("concept_id")) for card in must_retest if card.get("concept_id") is not None}
    prereq_adjustments: dict[int, float] = {}
    if conn:
        for cid in must_retest_cids:
            dependents = conn.execute(
                """SELECT target_concept_id FROM concept_relationships
                   WHERE source_concept_id = ? AND relation_type = 'prerequisite'""",
                (cid,)
            ).fetchall()
            for dep in dependents:
                dep_id = int(dep[0])
                if dep_id in must_retest_cids:
                    # cid is a prerequisite for a dependent concept that is also due
                    prereq_adjustments[cid] = prereq_adjustments.get(cid, 0.0) + 10.0
                    prereq_adjustments[dep_id] = prereq_adjustments.get(dep_id, 0.0) - 10.0

    priority_map = {"urgent": 4.0, "high": 3.0, "medium": 2.0, "low": 1.0}
    for card in must_retest:
        cid = card.get("concept_id")
        base_priority = priority_map.get(str(card.get("priority")), 0.0)
        if cid is not None:
            adj = prereq_adjustments.get(int(cid), 0.0)
            card["adjusted_priority"] = base_priority + adj
        else:
            card["adjusted_priority"] = base_priority

    must_retest.sort(key=lambda x: (-x.get("adjusted_priority", 0.0), -float(x.get("updated_ts", 0.0) or 0.0) if x.get("updated_ts") else 0))

    # Build knowledge map and deterministic teaching policy (SQLite fallback;
    # startup-recall replaces with inventory-grounded map when available).
    knowledge_map: list[dict[str, object]] = []
    teaching_plan: dict[str, object] = {}
    knowledge_map_status = "no_topic"
    if conn and session_topic:
        try:
            knowledge_map = _build_schema_map(conn, session_topic)
            knowledge_map_status = "ok" if knowledge_map else "empty_no_learner_concepts"
        except Exception as exc:
            knowledge_map = []
            knowledge_map_status = f"error: {exc}"
            print(f"WARN knowledge_map_failed: {exc}", file=sys.stderr)
    if knowledge_map:
        teaching_plan = _compute_teaching_policy(
            knowledge_map,
            due_claims=due_claims,
            shadow_rule_signals=shadow_rule_signals,
        )

    return {
        "read_first": True,
        "knowledge_map": knowledge_map,
        "knowledge_map_status": knowledge_map_status,
        "sequential_teaching_plan": teaching_plan,
        "handoff": {
            "topic": handoffs[0].get("topic"),
            "summary": handoffs[0].get("summary"),
            "next_action": handoffs[0].get("next_action"),
        } if handoffs else {},
        "open_first": [compact_card(card) for card in must_retest],
        "recent_repairs": [compact_card(card) for card in repairs],
        "known_scaffolds_due": [compact_due(item) for item in due_claims],
        "domain_patterns": [compact_pattern(item) for item in curated_summaries],
        "misconception_rules": [compact_shadow_rule(item) for item in shadow_rule_signals],
        "coverage_frontier": coverage_frontier,
        "contextual_frontier": [compact_frontier(item) for item in contextual_frontier],
        "low_confidence_leads": [compact_card(card) for card in low_confidence_leads],
        "question_design_bias": {
            "high_confidence_misses": [compact_high_confidence_miss(item) for item in high_confidence_misses],
            "weak_operations": [compact_operation(item) for item in weak_operations],
            "teaching_move_observations": [compact_move_profile(item) for item in teaching_move_profile],
            "tutor_efficacy": [compact_efficacy(item) for item in tutor_efficacy_profile],
        },
        "diagnostics": {
            "learner_graph_signal_count": len(graph_signals),
            "assessed_claim_results": telemetry_profile.get("assessed_claim_results", 0),
        },
        "agent_validation_checkpoint": {
            "required_before_teaching": True,
            "task": (
                "Review contextual_frontier candidates and accept only 1-3 that are clinically central, "
                "scope-compatible with the requested document, and likely to explain an active gap or deepen transfer. "
                "Reject tangential neighbors. The frontier informs question design; it never overrides urgent open_first items."
            ),
            "record_in_internal_note": [
                "accepted candidate ids and why they matter",
                "rejected candidate ids that are tangential or weakly supported",
                "the first question and which learner-state signal justifies it",
            ],
        },
    }


def _refine_brief_with_anki(brief: dict[str, object], anki_profile: dict[str, object]) -> None:
    schema_map = brief.get("knowledge_map")
    if not isinstance(schema_map, list) or not schema_map:
        return
    
    # Get all concept rollup entries from full_concept_rollup if it exists, else concept_rollup
    rollup = anki_profile.get("full_concept_rollup") or anki_profile.get("concept_rollup", [])
    if not isinstance(rollup, list):
        return
        
    # Build a lookup of Anki stats by normalized concept name (using slug)
    anki_stats = {}
    for item in rollup:
        if isinstance(item, dict) and "concept" in item:
            c_name = item["concept"]
            revs = item.get("reviews_count", 0)
            rate = item.get("success_rate", 0.0)
            anki_stats[_slug(c_name)] = (revs, rate)
            
    # Update schema map
    for entry in schema_map:
        c_name = entry.get("concept", "")
        slug_name = _slug(c_name)
        if slug_name in anki_stats:
            revs, rate = anki_stats[slug_name]
            entry["anki_reviews_count"] = revs
            entry["anki_success_rate"] = rate
            
            # Refine exposure status using Anki stats
            exp_status = entry.get("exposure_status", "unexposed")
            if exp_status == "unexposed" and revs > 0:
                if revs <= 2 or rate < 0.6:
                    entry["exposure_status"] = "exposed_superficial"
                else:
                    entry["exposure_status"] = "exposed_deep"
            elif exp_status == "exposed_superficial" and revs > 2 and rate >= 0.6:
                entry["exposure_status"] = "exposed_deep"
                
    # Recompute the deterministic policy over the Anki-refined knowledge map.
    # Anki is advisory only: it adjusts exposure status above, never claim
    # state. Interrupt inputs (due claims, shadow rules) are unchanged by Anki,
    # so pass them through for accurate decision_inputs audit counters.
    prior_plan = brief.get("sequential_teaching_plan")
    due_claims: list[dict[str, object]] = []
    shadow_rule_signals: list[dict[str, object]] = []
    if isinstance(prior_plan, dict):
        interrupts = prior_plan.get("interrupts")
        if isinstance(interrupts, dict) and isinstance(interrupts.get("consolidate"), list):
            due_claims = [item for item in interrupts["consolidate"] if isinstance(item, dict)]
    raw_shadows = brief.get("misconception_rules", [])
    if isinstance(raw_shadows, list):
        shadow_rule_signals = [item for item in raw_shadows if isinstance(item, dict)]
    plan = _compute_teaching_policy(
        schema_map,
        due_claims=due_claims,
        shadow_rule_signals=shadow_rule_signals,
    )
    if isinstance(prior_plan, dict) and prior_plan.get("interrupts"):
        plan["interrupts"] = prior_plan["interrupts"]
        prior_inputs = prior_plan.get("decision_inputs")
        if isinstance(prior_inputs, dict) and isinstance(plan.get("decision_inputs"), dict):
            # Interrupt lists are authoritative; keep audit counters aligned with them.
            plan["decision_inputs"]["due_claims"] = prior_inputs.get(
                "due_claims", plan["decision_inputs"].get("due_claims", 0)
            )
            plan["decision_inputs"]["remediate_flags"] = prior_inputs.get(
                "remediate_flags", plan["decision_inputs"].get("remediate_flags", 0)
            )
        for directive in prior_plan.get("pedagogical_directives", []) or []:
            if (
                isinstance(directive, str)
                and directive.startswith(("REMEDIATE interrupt", "CONSOLIDATE interrupt"))
                and directive not in plan["pedagogical_directives"]
            ):
                plan["pedagogical_directives"].append(directive)
        for key in ("teaching_priority", "artifact_native_targets", "map_context_targets"):
            if key in prior_plan:
                plan[key] = prior_plan[key]
    brief["sequential_teaching_plan"] = plan


SCHEMA_MAP_COMPACT_CAP = 40
TARGET_CONCEPTS_COMPACT_CAP = 25
_EXPOSURE_COMPACT_ORDER = {"exposed_superficial": 0, "unexposed": 1, "exposed_deep": 2}
_STATE_COMPACT_SEVERITY = {
    "missed": 0,
    "regressed": 1,
    "partially_repaired": 2,
    "repaired_same_session": 3,
    "untested": 4,
}


def _compact_schema_map(
    schema_map: list[dict[str, object]],
    cap: int = SCHEMA_MAP_COMPACT_CAP,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Cap the emitted schema map deterministically, keeping the highest-signal entries.

    The teaching policy is always computed from the FULL map before this cap is
    applied; truncation only bounds what the startup payload carries.
    """
    if len(schema_map) <= cap:
        return list(schema_map), {}

    def sort_key(c: dict[str, object]) -> tuple:
        return (
            0 if c.get("active_misconception") else 1,
            0 if c.get("safety_critical") else 1,
            _STATE_COMPACT_SEVERITY.get(str(c.get("knowledge_state")), 5),
            _EXPOSURE_COMPACT_ORDER.get(str(c.get("exposure_status")), 3),
            str(c.get("concept", "")),
        )

    ranked = sorted(schema_map, key=sort_key)
    kept = ranked[:cap]
    omitted = ranked[cap:]
    breakdown: dict[str, int] = {}
    for c in omitted:
        key = str(c.get("exposure_status"))
        breakdown[key] = breakdown.get(key, 0) + 1
    return kept, {
        "count": len(omitted),
        "by_exposure_status": breakdown,
        "note": "teaching plan was computed from the full map before truncation",
    }


def _compact_doc_review_payload(
    payload: dict[str, object],
    *,
    startup_meta: dict[str, object],
) -> dict[str, object]:
    """Collapse rich learner-model surfaces into a fast doc-review startup brief."""
    brief = payload.get("planning_brief") if isinstance(payload.get("planning_brief"), dict) else {}
    assert isinstance(brief, dict)

    def top_list(key: str, cap: int) -> list[dict[str, object]]:
        raw = brief.get(key, [])
        if not isinstance(raw, list):
            return []
        return [item for item in raw[:cap] if isinstance(item, dict)]

    def compact_card(item: dict[str, object], source: str) -> dict[str, object]:
        res = {
            "source": source,
            "id": item.get("claim_state_id"),
            "concept": item.get("concept"),
            "priority": item.get("priority"),
            "state": item.get("state"),
            "action": item.get("next_action"),
        }
        if "repair_velocity" in item:
            res["repair_velocity"] = item["repair_velocity"]
        if "historical_misconceptions" in item:
            res["historical_misconceptions"] = item["historical_misconceptions"]
        if "prerequisites" in item:
            res["prerequisites"] = item["prerequisites"]
        if "active_prerequisite_gaps" in item:
            res["active_prerequisite_gaps"] = item["active_prerequisite_gaps"]
        if "semantic_competitors" in item:
            res["semantic_competitors"] = item["semantic_competitors"]
        return res

    def compact_frontier(item: dict[str, object]) -> dict[str, object]:
        return {
            "candidate_id": item.get("candidate_id"),
            "source_surface": item.get("source_surface"),
            "concept": item.get("concept"),
            "relationship": item.get("relationship"),
            "reason": item.get("relevance_reason"),
            "agent_validation_required": True,
        }

    def compact_pattern(item: dict[str, object]) -> dict[str, object]:
        return {
            "summary_type": item.get("summary_type"),
            "content": item.get("content"),
            "importance_score": item.get("importance_score"),
        }

    open_first = top_list("open_first", 5)
    recent_repairs = top_list("recent_repairs", 2)
    known_scaffolds_due = top_list("known_scaffolds_due", 2)
    contextual_frontier = top_list("contextual_frontier", 2)
    domain_patterns = top_list("domain_patterns", 1)
    misconception_rules = top_list("misconception_rules", 1)

    teaching_priorities = [
        *(compact_card(item, "open_gap") for item in open_first),
        *(compact_card(item, "recent_repair") for item in recent_repairs),
        *(compact_card(item, "stale_scaffold") for item in known_scaffolds_due),
    ]
    bias = brief.get("question_design_bias") if isinstance(brief.get("question_design_bias"), dict) else {}
    assert isinstance(bias, dict)
    compact_bias = {
        "high_confidence_misses": top_list_from(bias, "high_confidence_misses", 2),
        "weak_operations": top_list_from(bias, "weak_operations", 2),
    }

    counts = payload.get("counts", {})
    omitted = payload.get("omitted", {})
    source_guidance = payload.get("retrieval_guidance", {})
    deferred_high_signal_counts = (
        source_guidance.get("omitted_high_signal", {})
        if isinstance(source_guidance, dict)
        else {}
    )
    retrieval_guidance = {
        "scope": "topic",
        "is_truncated": bool(omitted),
        "deferred_high_signal_counts": deferred_high_signal_counts,
        "policy": "doc_primary_compact",
        "pre_question_expansion_allowed": False,
        "expand_when": "only if compact startup is incoherent, routing blocks teaching, or the learner explicitly asks for an audit",
    }

    doc_brief = {
        "read_first": True,
        "profile": "doc_review_compact",
        "document_priority": "requested_doc_primary",
        "resolution_warning": brief.get("resolution_warning", ""),
        "resolution_candidates": top_list("resolution_candidates", 5),
        "handoff": brief.get("handoff", {}),
        "teaching_priorities": teaching_priorities,
        "domain_patterns": [compact_pattern(item) for item in domain_patterns],
        "misconception_rules": misconception_rules,
        "contextual_frontier": [compact_frontier(item) for item in contextual_frontier],
        "question_design_bias": compact_bias,
        "deferred_evidence": {
            "counts": deferred_high_signal_counts,
            "teaching_use": "awareness only during startup; do not fetch before the first question",
        },
        "agent_validation_checkpoint": {
            "required_before_teaching": bool(contextual_frontier),
            "task": "Accept only compact contextual candidates central to the requested document.",
        },
        "fallback": {
            "when_to_expand": "blocked_or_explicit_audit_only",
            "audit_profile_available": True,
        },
    }
    raw_knowledge_map = brief.get("knowledge_map", [])
    if not isinstance(raw_knowledge_map, list):
        raw_knowledge_map = []
    capped_knowledge_map, knowledge_map_omitted = _compact_schema_map(raw_knowledge_map)
    doc_brief["knowledge_map"] = capped_knowledge_map
    if knowledge_map_omitted:
        doc_brief["knowledge_map_omitted"] = knowledge_map_omitted
    if brief.get("knowledge_map_status"):
        doc_brief["knowledge_map_status"] = brief["knowledge_map_status"]
    if brief.get("document_priority"):
        doc_brief["document_priority"] = brief["document_priority"]
    if brief.get("teaching_priority"):
        doc_brief["teaching_priority"] = brief["teaching_priority"]
    plan = brief.get("sequential_teaching_plan", {})
    if (
        isinstance(plan, dict)
        and isinstance(plan.get("target_concepts"), list)
        and len(plan["target_concepts"]) > TARGET_CONCEPTS_COMPACT_CAP
    ):
        plan = dict(plan)
        targets = list(plan["target_concepts"])
        plan["target_concepts"] = targets[:TARGET_CONCEPTS_COMPACT_CAP]
        plan["target_concepts_omitted"] = len(targets) - TARGET_CONCEPTS_COMPACT_CAP
    doc_brief["sequential_teaching_plan"] = plan
    if isinstance(brief.get("anki_overlay"), dict):
        doc_brief["anki_overlay"] = brief["anki_overlay"]
    return {
        "startup_recall": startup_meta,
        "planning_brief": doc_brief,
        "counts": counts,
        "omitted": omitted,
        "retrieval_guidance": retrieval_guidance,
    }


def top_list_from(container: dict[str, object], key: str, cap: int) -> list[dict[str, object]]:
    raw = container.get(key, [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw[:cap] if isinstance(item, dict)]


def _summary_command(
    *,
    topic: str,
    limit: int,
    scaffold_limit: int,
    include_global_scaffolds: bool = False,
    include_curated: bool = False,
    include_due: bool = False,
    include_model: bool = False,
    context: str = "",
    brief_only: bool = False,
) -> str:
    parts = ["python3 src/study_memory.py summary"]
    if topic:
        parts.append(f'--topic "{topic}"')
    parts.append(f"--limit {limit}")
    parts.append(f"--scaffold-limit {scaffold_limit}")
    if include_global_scaffolds:
        parts.append("--include-global-scaffolds")
    if include_curated:
        parts.append("--include-curated")
    if include_due:
        parts.append("--include-due")
    if include_model:
        parts.append("--include-model")
    if context:
        safe_context = context.replace('"', "'")
        parts.append(f'--context "{safe_context}"')
    if brief_only:
        parts.append("--brief-only")
    return " ".join(parts)


def _startup_recall_command(
    *,
    topic: str,
    doc_path: str = "",
    global_mode: bool = False,
    context: str = "",
    profile: str = "audit",
) -> str:
    parts = ["python3 src/study_memory.py startup-recall"]
    if global_mode:
        parts.append("--global")
    elif topic:
        parts.append(f'--topic "{topic}"')
    if doc_path:
        parts.append(f'--doc "{doc_path}"')
    if context:
        safe_context = context.replace('"', "'")
        parts.append(f'--context "{safe_context}"')
    if profile:
        parts.append(f"--profile {profile}")
    return " ".join(parts)


def _planning_concepts_for_anki_overlay(brief: dict[str, object]) -> list[str]:
    concepts: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        text = str(value or "").strip()
        key = _normalize(text)
        if text and key and key not in seen:
            seen.add(key)
            concepts.append(text)

    for key in (
        "open_first",
        "recent_repairs",
        "known_scaffolds_due",
        "contextual_frontier",
        "low_confidence_leads",
        "teaching_priorities",
    ):
        raw = brief.get(key, [])
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, dict):
                add(item.get("concept"))
                add(item.get("topic"))
    return concepts[:12]


def _compact_anki_feedback_status(profile: dict[str, object]) -> dict[str, object]:
    status = {
        "status": profile.get("status", "unknown"),
        "scope": profile.get("scope", ""),
        "cards_examined": profile.get("cards_examined", 0),
    }
    if isinstance(profile.get("macro_counts"), dict):
        status["macro_counts"] = profile["macro_counts"]
    if isinstance(profile.get("topic_headlines"), list):
        status["topic_headline_count"] = len(profile["topic_headlines"])  # type: ignore[arg-type]
        status["topic_headlines"] = profile["topic_headlines"][:5]  # type: ignore[index]
    if profile.get("message"):
        status["message"] = profile.get("message")
    if profile.get("reason"):
        status["reason"] = profile.get("reason")
    return status


def _retrieval_guidance(
    *,
    topic: str,
    limit: int,
    scaffold_limit: int,
    counts: dict[str, int],
    omitted: dict[str, int],
    include_global_scaffolds: bool,
    include_curated: bool,
    include_due: bool = False,
    include_model: bool = False,
    context: str = "",
    brief_only: bool = False,
) -> dict[str, object]:
    high_signal_types = ("must_retest", "session_handoff", "recent_repair")
    omitted_high_signal = {k: omitted[k] for k in high_signal_types if omitted.get(k, 0)}
    suggested_commands: list[str] = []

    if omitted_high_signal:
        suggested_commands.append(
            _summary_command(
                topic=topic,
                limit=limit + sum(omitted_high_signal.values()),
                scaffold_limit=scaffold_limit,
                include_global_scaffolds=include_global_scaffolds,
                include_curated=include_curated,
                include_due=include_due,
                include_model=include_model,
                context=context,
                brief_only=brief_only,
            )
        )
    if topic and omitted.get("scaffold", 0):
        suggested_commands.append(
            _summary_command(
                topic=topic,
                limit=limit,
                scaffold_limit=min(counts.get("scaffold", scaffold_limit), max(scaffold_limit * 2, 4)),
                include_curated=include_curated,
                include_due=include_due,
                include_model=include_model,
                context=context,
                brief_only=brief_only,
            )
        )
    if not topic and omitted.get("scaffold", 0) and not include_global_scaffolds:
        suggested_commands.append(
            _summary_command(
                topic=topic,
                limit=limit,
                scaffold_limit=scaffold_limit,
                include_global_scaffolds=True,
                include_curated=include_curated,
                include_due=include_due,
                include_model=include_model,
                context=context,
                brief_only=brief_only,
            )
        )

    return {
        "scope": "topic" if topic else "global",
        "is_truncated": bool(omitted),
        "omitted_high_signal": omitted_high_signal,
        "default_policy": (
            "Compact first pass: must_retest/session_handoff/recent_repair are prioritized; "
            "scaffolds are capped because they are transfer premises, not primary drill targets."
        ),
        "expand_when": [
            "Expand immediately if omitted_high_signal is non-empty before designing a teaching plan.",
            "Expand scaffold_limit only when building a coverage map or transfer-question premises for this topic.",
            "For global retrieval, keep scaffolds suppressed unless explicitly selecting broad review targets.",
        ],
        "suggested_commands": suggested_commands,
    }


def retrieval_summary(
    conn: sqlite3.Connection,
    topic: str = "",
    limit: int = 8,
    scaffold_limit: int = 2,
    include_scaffolds: bool = True,
    include_global_scaffolds: bool = False,
    include_curated: bool = False,
    include_due: bool = False,
    include_model: bool = False,
    context: str = "",
    brief_only: bool = False,
    lens: str = "formal",
) -> str:
    if lens not in {"formal", "general"}:
        raise ValueError("retrieval_summary lens must be formal or general")
    limit = max(0, limit)
    scaffold_limit = max(0, scaffold_limit)
    topic_filter = ""
    params: list[str | int] = []
    resolved_topic_id: int | None = None
    resolved_topic_slug: str | None = None
    if topic:
        resolution = resolve_topic(conn, topic)
        resolved_topic_slug = resolution.slug
        topic_row = conn.execute("SELECT id FROM topics WHERE canonical_slug = ?", (resolution.slug,)).fetchone()
        if not topic_row:
            related_topics = _related_topic_matches_for_hint(conn, topic)
            base: dict[str, object] = {
                "cards": [],
                "counts": {},
                "omitted": {},
                "retrieval_guidance": {
                    "scope": "topic",
                    "is_truncated": False,
                    "omitted_high_signal": {},
                    "default_policy": "No resolved topic matched this query.",
                    "expand_when": ["Re-run with a more specific topic string or inspect topic aliases."],
                    "suggested_commands": [],
                },
            }
            if include_curated:
                base["curated_summaries"] = []
                base["graph_signals"] = []
                base["shadow_rule_signals"] = []
            if include_due:
                base["due_claims"] = []
            if include_model:
                base["calibration_profile"] = {"buckets": {}, "high_confidence_misses": []}
                base["operation_profile"] = []
                base["teaching_move_profile"] = []
                base["telemetry_profile"] = {}
                base["tutor_efficacy_profile"] = []
                base["coverage_frontier"] = {
                    "catalog_topics": 0,
                    "tested_catalog_topics": 0,
                    "frontier_candidates": [],
                    "blind_spots": [],
                }
                base["shadow_queue"] = []
                if context:
                    base["context_focus"] = []
                    base["context_graph_focus"] = []
                base["planning_brief"] = {
                    "read_first": True,
                    "resolution_warning": (
                        f"No stored learner topic resolved for {topic!r}. "
                        "Choose a related existing topic anchor or clarify the intended curriculum before teaching."
                    ),
                    "resolution_candidates": related_topics,
                    "handoff": {},
                    "open_first": [],
                    "recent_repairs": [],
                    "known_scaffolds_due": [],
                    "domain_patterns": [],
                    "misconception_rules": [],
                    "coverage_frontier": base["coverage_frontier"],
                    "contextual_frontier": [],
                    "low_confidence_leads": [],
                    "question_design_bias": {},
                    "diagnostics": {},
                    "agent_validation_checkpoint": {
                        "required_before_teaching": True,
                        "task": "Resolve the requested topic to the correct existing learner-state anchor before teaching.",
                        "record_in_internal_note": [
                            "selected existing topic anchor or clarification need",
                            "why the selected anchor matches the requested curriculum",
                        ],
                    },
                }
            if brief_only and "planning_brief" in base:
                base = {
                    "planning_brief": base["planning_brief"],
                    "counts": base["counts"],
                    "omitted": base["omitted"],
                    "retrieval_guidance": base["retrieval_guidance"],
                }
            return _json_dumps(base)
        resolved_topic_id = int(topic_row["id"])
        topic_filter = "AND rc.topic_id = ?"
        params.append(resolved_topic_id)

    counts = {
        row["card_type"]: int(row["n"])
        for row in conn.execute(
            f"""SELECT rc.card_type, COUNT(*) AS n
                FROM retrieval_cards rc
                LEFT JOIN claim_state cs ON cs.id = rc.claim_state_id
                WHERE rc.status = 'active' AND rc.card_type != 'artifact_anchor'
                  AND (cs.origin IS NULL OR cs.origin = 'assessed') {topic_filter}
                GROUP BY rc.card_type""",
            params,
        ).fetchall()
    }

    select_sql = f"""SELECT rc.card_type, rc.priority, rc.summary, rc.next_action,
                  rc.claim_state_id,
                  t.canonical_slug AS topic, cs.claim_text, cs.state,
                  cs.concept_id, c.display_name AS concept
           FROM retrieval_cards rc
           JOIN topics t ON t.id = rc.topic_id
           LEFT JOIN claim_state cs ON cs.id = rc.claim_state_id
           LEFT JOIN concepts c ON c.id = cs.concept_id
           WHERE rc.status = 'active' AND rc.card_type != 'artifact_anchor'
             AND (cs.origin IS NULL OR cs.origin = 'assessed') {topic_filter}"""
    order_sql = """ORDER BY CASE rc.priority
               WHEN 'urgent' THEN 0
               WHEN 'high' THEN 1
               WHEN 'medium' THEN 2
               ELSE 3
             END,
             CASE rc.card_type
               WHEN 'must_retest' THEN 0
               WHEN 'session_handoff' THEN 1
               WHEN 'recent_repair' THEN 2
               WHEN 'scaffold' THEN 3
               ELSE 4
             END,
             rc.updated_ts DESC
           LIMIT ?"""

    rows: list[sqlite3.Row] = []
    if limit:
        rows = conn.execute(
            f"{select_sql} AND rc.card_type != 'scaffold' {order_sql}",
            [*params, limit],
        ).fetchall()
        remaining = max(0, limit - len(rows))
        allow_scaffolds = include_scaffolds and (bool(topic) or include_global_scaffolds)
        scaffold_take = min(scaffold_limit, remaining) if allow_scaffolds else 0
        if scaffold_take:
            rows.extend(
                conn.execute(
                    f"{select_sql} AND rc.card_type = 'scaffold' {order_sql}",
                    [*params, scaffold_take],
                ).fetchall()
            )

    returned_counts: dict[str, int] = {}
    for row in rows:
        returned_counts[row["card_type"]] = returned_counts.get(row["card_type"], 0) + 1
    omitted = {
        card_type: max(0, count - returned_counts.get(card_type, 0))
        for card_type, count in counts.items()
        if count > returned_counts.get(card_type, 0)
    }

    payload: dict[str, object] = {
        "cards": [_retrieval_card_payload(row) for row in rows],
        "counts": counts,
        "omitted": omitted,
        "retrieval_guidance": _retrieval_guidance(
            topic=topic,
            limit=limit,
            scaffold_limit=scaffold_limit,
            counts=counts,
            omitted=omitted,
            include_global_scaffolds=include_global_scaffolds,
            include_curated=include_curated,
            include_due=include_due,
            include_model=include_model,
            context=context,
            brief_only=brief_only,
        ),
    }

    if include_model and lens == "general":
        brain_dump_candidates = _brain_dump_candidates_for_summary(
            conn,
            topic_id=resolved_topic_id,
            limit=max(4, limit),
            status="pending",
        )
        payload["brain_dump_review_candidates"] = brain_dump_candidates
        if brain_dump_candidates:
            counts["brain_dump_review_candidate"] = len(brain_dump_candidates)

    if include_curated:
        curated_limit = max(4, limit)
        returned_concept_ids: list[int] = []
        must_retest_concept_ids: list[int] = []
        MUST_RETEST_GRAPH_CAP = 3
        for row in rows:
            if row["claim_state_id"] is None or row["concept_id"] is None:
                continue
            cid = int(row["concept_id"])
            returned_concept_ids.append(cid)
            if (
                row["card_type"] == "must_retest"
                and len(must_retest_concept_ids) < MUST_RETEST_GRAPH_CAP
            ):
                must_retest_concept_ids.append(cid)
        payload["curated_summaries"] = curated_summaries_for_summary(
            conn,
            topic_id=resolved_topic_id,
            limit=curated_limit,
            relevant_concept_ids=returned_concept_ids,
        )
        payload["graph_signals"] = graph_signals_for_summary(
            conn,
            must_retest_concept_ids=must_retest_concept_ids,
        )
        payload["shadow_rule_signals"] = shadow_rule_signals_for_summary(
            conn,
            relevant_concept_ids=returned_concept_ids,
            limit=4,
        )

    if include_due or include_model:
        # Dedup against the active-open triage cards only: a claim already shown as
        # a must_retest or recent_repair card carries its own next_action, so its
        # decay signal is redundant. Scaffolds are intentionally not excluded -- a
        # decayed scaffold's retention-check signal lives in due_claims and serves a
        # different purpose than the scaffold-as-premise card.
        card_claim_state_ids = {
            int(row["claim_state_id"])
            for row in rows
            if row["claim_state_id"] is not None
            and row["card_type"] in ("must_retest", "recent_repair")
        }
        payload["due_claims"] = _due_claims_for_summary(
            conn,
            topic_id=resolved_topic_id,
            limit=max(4, limit),
            exclude_claim_state_ids=card_claim_state_ids,
        )
    if include_model:
        payload["calibration_profile"] = _calibration_profile_for_summary(
            conn,
            topic_id=resolved_topic_id,
            limit=max(4, limit),
        )
        payload["operation_profile"] = _operation_profile_for_summary(
            conn,
            topic_id=resolved_topic_id,
            limit=max(4, limit),
        )
        payload["teaching_move_profile"] = _teaching_move_profile_for_summary(
            conn,
            topic_id=resolved_topic_id,
            limit=max(4, limit),
        )
        payload["telemetry_profile"] = _telemetry_profile_for_summary(
            conn,
            topic_id=resolved_topic_id,
        )
        payload["tutor_efficacy_profile"] = _tutor_efficacy_profile_for_summary(
            conn,
            topic_id=resolved_topic_id,
            limit=max(4, limit),
        )
        # coverage_frontier is the ACGME global coverage map. It only makes sense
        # in memory-driven/global review (no chosen topic); during a topic-anchored
        # drill it is irrelevant noise, so it is emitted empty there.
        if resolved_topic_id is None:
            payload["coverage_frontier"] = _catalog_coverage_for_summary(
                conn,
                topic_id=None,
                limit=max(4, limit),
            )
        else:
            payload["coverage_frontier"] = {
                "catalog_topics": 0,
                "tested_catalog_topics": 0,
                "frontier_candidates": [],
                "blind_spots": [],
            }
        payload["shadow_queue"] = _shadow_queue_for_summary(
            conn,
            topic_id=resolved_topic_id,
            limit=max(4, limit),
            include_brain_dump_candidates=(lens == "general"),
        )
        if context:
            payload["context_focus"] = _context_focus_for_summary(
                context=context,
                due_claims=payload["due_claims"],  # type: ignore[arg-type]
                coverage_frontier=payload["coverage_frontier"],  # type: ignore[arg-type]
                shadow_queue=payload["shadow_queue"],  # type: ignore[arg-type]
                limit=max(4, limit),
            )
            payload["context_graph_focus"] = context_graph_focus_for_summary(
                conn,
                context=context,
                due_claims=payload["due_claims"],  # type: ignore[arg-type]
                limit=min(8, max(4, limit)),
                max_hops=2,
            )
        scouting_context = context or " ".join(
            [
                topic,
                *(
                    " ".join(str(card.get(key, "")) for key in ("concept", "claim", "summary"))
                    for card in payload["cards"]  # type: ignore[union-attr]
                ),
            ]
        )
        reviewed_paths = payload.get("context_graph_focus")
        if not isinstance(reviewed_paths, list):
            reviewed_paths = context_graph_focus_for_summary(
                conn,
                context=scouting_context,
                due_claims=payload["due_claims"],  # type: ignore[arg-type]
                limit=min(8, max(4, limit)),
                max_hops=2,
            )
        contextual_frontier = _scouting_candidates_for_summary(
            conn,
            topic_id=resolved_topic_id,
            topic=topic,
            cards=payload["cards"],  # type: ignore[arg-type]
            due_claims=payload["due_claims"],  # type: ignore[arg-type]
            graph_signals=payload.get("graph_signals", []),  # type: ignore[arg-type]
            context_graph_focus=reviewed_paths,
            limit=min(6, max(4, limit)),
        )
        payload["planning_brief"] = _planning_brief_for_summary(
            conn,
            topic_slug=resolved_topic_slug,
            cards=payload["cards"],  # type: ignore[arg-type]
            curated_summaries=payload.get("curated_summaries", []),  # type: ignore[arg-type]
            graph_signals=payload.get("graph_signals", []),  # type: ignore[arg-type]
            shadow_rule_signals=payload.get("shadow_rule_signals", []),  # type: ignore[arg-type]
            due_claims=payload["due_claims"],  # type: ignore[arg-type]
            calibration_profile=payload["calibration_profile"],  # type: ignore[arg-type]
            operation_profile=payload["operation_profile"],  # type: ignore[arg-type]
            teaching_move_profile=payload["teaching_move_profile"],  # type: ignore[arg-type]
            telemetry_profile=payload["telemetry_profile"],  # type: ignore[arg-type]
            tutor_efficacy_profile=payload["tutor_efficacy_profile"],  # type: ignore[arg-type]
            coverage_frontier=payload["coverage_frontier"],  # type: ignore[arg-type]
            contextual_frontier=contextual_frontier,
            low_confidence_leads=payload["shadow_queue"],  # type: ignore[arg-type]
        )

    if brief_only and "planning_brief" in payload:
        payload = {
            "planning_brief": payload["planning_brief"],
            "counts": payload["counts"],
            "omitted": payload["omitted"],
            "retrieval_guidance": payload["retrieval_guidance"],
        }
    return _json_dumps(payload)


def startup_recall(
    conn: sqlite3.Connection,
    *,
    topic: str = "",
    doc_path: str = "",
    global_mode: bool = False,
    limit: int | None = None,
    scaffold_limit: int | None = None,
    include_global_scaffolds: bool = False,
    context: str = "",
    lens: str = "formal",
    service: str = "",
    site: str = "",
    rotation_id: int | None = None,
    profile: str = "auto",
    session_id: str = "",
) -> str:
    """Return the deterministic first-read brief used by every learning workflow.

    lens='formal' is the standardized document surface and seals out
    service-origin material. lens='general' is for topic-only memory review and
    includes low-weight brain-dump review candidates. lens='service' delegates
    to the service lens, which leads with service-rotation gaps.
    """
    if lens == "service":
        return _json_dumps(
            json.loads(
                service_recall(
                    conn,
                    service=service or topic,
                    site=site,
                    rotation_id=rotation_id,
                    context=context,
                    limit=limit if limit is not None else 8,
                )
            )
        )
    if global_mode and (topic or doc_path):
        raise ValueError("startup-recall --global cannot be combined with --topic or --doc")
    if not global_mode and not (topic or doc_path):
        raise ValueError("startup-recall requires --topic, --doc, or --global")
    if profile not in {"auto", "doc", "memory", "audit"}:
        raise ValueError("startup-recall profile must be one of: auto, doc, memory, audit")
    if global_mode and profile == "doc":
        raise ValueError("startup-recall --profile doc cannot be combined with --global")

    requested_topic = topic
    resolved: TopicResolution | None = None
    recall_topic = ""
    if not global_mode:
        resolved = resolve_topic(conn, topic, doc_path)
        stored_topic = conn.execute(
            "SELECT 1 FROM topics WHERE canonical_slug = ?",
            (resolved.slug,),
        ).fetchone()
        recall_topic = resolved.slug if stored_topic else (topic or _doc_alias(doc_path))

    effective_profile = profile
    if profile == "auto":
        effective_profile = "doc" if (doc_path and not global_mode) else "memory"
    retrieval_lens = "formal" if effective_profile == "doc" else lens
    initial_limit = max(0, limit if limit is not None else (12 if global_mode else 8))
    final_limit = initial_limit
    resolved_scaffold_limit = max(
        0,
        scaffold_limit if scaffold_limit is not None else (0 if global_mode else 2),
    )
    expansions: list[dict[str, object]] = []

    while True:
        payload = json.loads(
            retrieval_summary(
                conn,
                topic=recall_topic,
                limit=final_limit,
                scaffold_limit=resolved_scaffold_limit,
                include_global_scaffolds=include_global_scaffolds,
                include_curated=True,
                include_model=True,
                context=context,
                brief_only=True,
                lens=retrieval_lens,
            )
        )
        omitted_high_signal = payload.get("retrieval_guidance", {}).get("omitted_high_signal", {})
        if effective_profile == "doc":
            break
        if not isinstance(omitted_high_signal, dict) or not omitted_high_signal:
            break
        if global_mode:
            break
        additional = sum(int(value) for value in omitted_high_signal.values())
        if additional <= 0:
            break
        next_limit = final_limit + additional
        expansions.append({
            "from_limit": final_limit,
            "to_limit": next_limit,
            "omitted_high_signal": omitted_high_signal,
        })
        final_limit = next_limit

    brief = payload.get("planning_brief", {})
    routing_required = bool(isinstance(brief, dict) and brief.get("resolution_warning"))
    if isinstance(brief, dict) and not routing_required and not global_mode and recall_topic:
        try:
            _integrate_inventory_knowledge_map(
                conn,
                brief,
                topic=recall_topic,
                doc_path=doc_path,
                profile=effective_profile,
                session_id=session_id,
            )
            payload["planning_brief"] = brief
        except Exception as exc:
            print(f"WARN inventory_integration_failed: {exc}", file=sys.stderr)
    deferred_high_signal = payload.get("retrieval_guidance", {}).get("omitted_high_signal", {})
    anki_feedback_status: dict[str, object] = {"status": "skipped", "reason": "not evaluated"}
    if routing_required:
        anki_feedback_status = {"status": "skipped", "reason": "topic unresolved"}
    else:
        try:
            from anki_feedback import build_session_anki_profile

            anki_profile = build_session_anki_profile(
                topic=recall_topic or requested_topic,
                resolved_topic=resolved.slug if resolved else "",
                doc_path=doc_path,
                context=context,
                global_mode=global_mode,
                profile=effective_profile,
                planning_concepts=(
                    _planning_concepts_for_anki_overlay(brief)
                    if isinstance(brief, dict)
                    else []
                ),
                keep_full_rollup=True,
            )
            if isinstance(anki_profile, dict):
                anki_feedback_status = _compact_anki_feedback_status(anki_profile)
                if not global_mode and isinstance(brief, dict):
                    _refine_brief_with_anki(brief, anki_profile)
                    # Clean up full_concept_rollup to prevent token bloat
                    if "full_concept_rollup" in anki_profile:
                        del anki_profile["full_concept_rollup"]
                    brief["anki_overlay"] = anki_profile
        except Exception as e:  # noqa: BLE001 - startup recall must remain available.
            anki_feedback_status = {"status": "error", "message": str(e)[:200]}

    if not global_mode and resolved and isinstance(brief, dict) and brief.get("sequential_teaching_plan"):
        # Auditable session-start policy event; failure must not block recall.
        try:
            topic_row = conn.execute(
                "SELECT id FROM topics WHERE canonical_slug = ?", (resolved.slug,)
            ).fetchone()
            _record_policy_event(
                conn,
                session_id=session_id,
                event_type="startup",
                topic_id=int(topic_row[0]) if topic_row else None,
                plan=brief["sequential_teaching_plan"],  # type: ignore[arg-type]
            )
            conn.commit()
        except Exception as exc:
            print(f"WARN policy_event_failed: {exc}", file=sys.stderr)

    payload["startup_recall"] = {
        "mode": "global" if global_mode else "topic",
        "requested_topic": requested_topic,
        "requested_doc": doc_path,
        "anki_feedback_status": anki_feedback_status,
        "resolved_topic": resolved.slug if resolved else "",
        "resolver_confidence": resolved.confidence if resolved else None,
        "profile": effective_profile,
        "initial_limit": initial_limit,
        "final_limit": final_limit,
        "auto_expanded": bool(expansions),
        "expansions": expansions,
        "expansion_policy": (
            "global_compact_then_topic_drilldown"
            if global_mode
            else "topic_complete_high_signal"
        ),
        "deferred_high_signal": deferred_high_signal if global_mode else {},
        "candidate_selection_required": global_mode,
        "routing_required": routing_required,
        "ready_to_teach": not routing_required and not global_mode,
        "pre_question_expansion_allowed": bool(
            routing_required or global_mode or effective_profile == "audit"
        ),
        "next_action": (
            "Select candidate topics from the compact global brief, then run topic-scoped startup-recall for each chosen topic before teaching."
            if global_mode
            else (
                "Validate a resolution candidate and rerun topic-scoped startup-recall before teaching."
                if routing_required
                else "Begin from the planning brief without audit expansion; ask one clinical question with at most one short orientation clause."
            )
        ),
    }
    if effective_profile == "doc":
        return _json_dumps(
            _compact_doc_review_payload(
                payload,
                startup_meta=payload["startup_recall"],  # type: ignore[arg-type]
            )
        )
    return _json_dumps(payload)


def status(conn: sqlite3.Connection) -> str:
    rows = {
        "topics": conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0],
        "concepts": conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0],
        "exchanges": conn.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0],
        "claim_results": conn.execute("SELECT COUNT(*) FROM claim_results").fetchone()[0],
        "claim_states": conn.execute("SELECT COUNT(*) FROM claim_state").fetchone()[0],
        "repair_episodes": conn.execute("SELECT COUNT(*) FROM repair_episodes").fetchone()[0],
        "shadow_rules": conn.execute("SELECT COUNT(*) FROM shadow_rules").fetchone()[0],
        "reference_nodes": conn.execute("SELECT COUNT(*) FROM reference_nodes").fetchone()[0],
        "reference_edges": conn.execute("SELECT COUNT(*) FROM reference_edges").fetchone()[0],
        "retrieval_cards": conn.execute("SELECT COUNT(*) FROM retrieval_cards").fetchone()[0],
        "must_retest": conn.execute("SELECT COUNT(*) FROM claim_state WHERE state IN ('missed','partially_repaired','regressed')").fetchone()[0],
        "recent_repairs": conn.execute("SELECT COUNT(*) FROM claim_state WHERE state = 'repaired_same_session'").fetchone()[0],
    }
    return _json_dumps(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Claim-centered study memory ledger")
    sub = parser.add_subparsers(dest="command")

    p_resolve = sub.add_parser("resolve-topic")
    p_resolve.add_argument("--topic", required=True)
    p_resolve.add_argument("--doc", default="")

    p_log = sub.add_parser("log-answer")
    p_log.add_argument("--session", required=True)
    p_log.add_argument("--topic", required=True)
    p_log.add_argument("--concept", required=True)
    p_log.add_argument("--question", required=True)
    p_log.add_argument("--answer", required=True)
    p_log.add_argument("--correct", type=int, choices=[0, 1, 2], required=True)
    p_log.add_argument("--correction", default="")
    p_log.add_argument("--error-type", default="")
    p_log.add_argument("--misconception", default="")
    p_log.add_argument("--doc", default="")
    p_log.add_argument("--skill", default="")
    p_log.add_argument("--tested-claim", default="")
    p_log.add_argument("--learner-claim", default="")
    p_log.add_argument("--missing-edge", default="")
    p_log.add_argument("--corrected-rule", default="")
    p_log.add_argument("--clinical-consequence", default="")
    p_log.add_argument("--retest-prompt-shape", default="")
    p_log.add_argument("--learning-operation", default="")
    p_log.add_argument("--teaching-intent", default="")
    p_log.add_argument("--expected-answer-edge", default="")
    p_log.add_argument("--coverage-role", default="")
    p_log.add_argument("--source-section", default="")
    p_log.add_argument("--source-anchor", default="")
    p_log.add_argument("--curriculum-unit", default="")
    p_log.add_argument("--answer-mode", default="")
    p_log.add_argument("--confidence-observed", default="")
    p_log.add_argument("--teaching-move", default="")
    p_log.add_argument("--strict-telemetry", action="store_true")
    p_log.add_argument("--priority", default="", help="Agent-asserted priority: urgent|high|medium|low (overrides heuristic)")
    p_log.add_argument("--match-claim-state-id", type=int, default=None, help="Bind this answer to an existing open claim (agent-asserted recurrence)")
    p_log.add_argument("--new-claim", action="store_true", help="Force a new claim_state even if a similar one exists")
    p_log.add_argument("--repairs-claim-state-ids", default="", help="Comma-separated open claim_state ids this correct answer repairs")
    p_log.add_argument("--origin", choices=["assessed", "service"], default="assessed", help="Provenance: 'service' for service-rotation learning (isolated from formal review)")
    p_log.add_argument("--rotation", type=int, default=None, help="Rotation id this service-origin answer belongs to (defaults to the active rotation)")
    p_log.add_argument("--competency-target", default="", help="Service competency_target slug this answer advances")
    p_log.add_argument("--convention", action="store_true", help="Mark as a (service x site) local convention rather than a portable clinical gap")
    p_log.add_argument("--brain-dump-candidate-id", type=int, default=None, help="Mark this pending brain-dump review candidate as reviewed by the logged answer")
    p_log.add_argument(
        "--inventory-concept-id",
        default="",
        help="Canonical inventory concept id for the probed concept (required for study-review when resolvable)",
    )

    p_end = sub.add_parser("end-session")
    p_end.add_argument("--session", required=True)
    p_end.add_argument("--summary", required=True)
    p_end.add_argument("--next-strategy", required=True)
    p_end.add_argument("--stats-json", default="{}")
    p_end.add_argument("--json", dest="as_json", action="store_true")

    p_summary = sub.add_parser("summary")
    p_summary.add_argument("--topic", default="")
    p_summary.add_argument("--limit", type=int, default=8)
    p_summary.add_argument("--scaffold-limit", type=int, default=2)
    p_summary.add_argument("--no-scaffolds", action="store_true")
    p_summary.add_argument("--include-global-scaffolds", action="store_true")
    p_summary.add_argument("--include-curated", action="store_true")
    p_summary.add_argument("--include-due", action="store_true")
    p_summary.add_argument("--include-model", action="store_true")
    p_summary.add_argument("--context", default="", help="Optional upcoming case/rotation/context string for relevance weighting")
    p_summary.add_argument("--brief-only", action="store_true", help="Return the synthesized planning brief plus truncation diagnostics")
    p_summary.add_argument("--lens", choices=["formal", "general", "service"], default="formal", help="formal doc/audit surface; general includes brain-dump review candidates; service routes to service memory")
    p_summary.add_argument("--service", default="", help="Service slug for --lens service")
    p_summary.add_argument("--site", default="", help="Site slug for --lens service convention scoping")
    p_summary.add_argument("--rotation", type=int, default=None, help="Rotation id for --lens service")

    p_rotation_start = sub.add_parser("rotation-start")
    p_rotation_start.add_argument("--service", required=True)
    p_rotation_start.add_argument("--site", required=True)
    p_rotation_start.add_argument("--pgy", type=int, default=None)
    p_rotation_start.add_argument("--block", default="")

    sub.add_parser("rotation-current")
    sub.add_parser("rotation-list")

    p_rotation_end = sub.add_parser("rotation-end")
    p_rotation_end.add_argument("--rotation", type=int, required=True)

    p_rubric = sub.add_parser("service-rubric")
    p_rubric.add_argument("--service", required=True)
    p_rubric.add_argument("--seed", action="store_true", help="Seed/refresh competency targets from the ACGME catalog domain slice")
    p_rubric.add_argument("--pgy", type=int, default=None, help="Restrict seeding to targets at or below this PGY")

    p_startup = sub.add_parser("startup-recall")
    p_startup.add_argument("--topic", default="")
    p_startup.add_argument("--doc", default="")
    p_startup.add_argument("--global", dest="global_mode", action="store_true")
    p_startup.add_argument("--limit", type=int, default=None)
    p_startup.add_argument("--scaffold-limit", type=int, default=None)
    p_startup.add_argument("--include-global-scaffolds", action="store_true")
    p_startup.add_argument("--context", default="", help="Optional upcoming case/rotation/context string for relevance weighting")
    p_startup.add_argument("--lens", choices=["formal", "general", "service"], default="formal", help="formal seals out service material; general includes brain-dump review candidates; service leads with rotation gaps")
    p_startup.add_argument("--service", default="", help="Service slug for --lens service (defaults to the active rotation)")
    p_startup.add_argument("--site", default="", help="Site slug for --lens service convention scoping")
    p_startup.add_argument("--rotation", type=int, default=None, help="Rotation id for --lens service")
    p_startup.add_argument(
        "--profile",
        choices=["auto", "doc", "memory", "audit"],
        default="auto",
        help="auto chooses compact doc review when --doc is present; audit returns the full rich startup surface",
    )
    p_startup.add_argument(
        "--session",
        default="",
        help="Session id; when set, writes the live knowledge map file for per-turn patching",
    )

    sub.add_parser("status")
    sub.add_parser("identity-audit")
    sub.add_parser("telemetry-audit")
    sub.add_parser("curation-status")

    p_merge_topics = sub.add_parser("merge-topics")
    p_merge_topics.add_argument("--from-topic", required=True)
    p_merge_topics.add_argument("--into-topic", required=True)
    p_merge_topics.add_argument("--apply", action="store_true")

    p_shadow_check = sub.add_parser("record-shadow-check")
    p_shadow_check.add_argument("--rule-id", type=int, required=True)
    p_shadow_check.add_argument("--claim-result-id", type=int, required=True)
    p_shadow_check.add_argument("--context-label", required=True)
    p_shadow_check.add_argument("--check-type", choices=["changed_frame", "transfer"], required=True)
    p_shadow_check.add_argument("--outcome", choices=["pass", "fail"], required=True)
    p_shadow_check.add_argument("--apply", action="store_true")

    p_reference_graph = sub.add_parser("load-reference-graph")
    p_reference_graph.add_argument("--input", required=True)
    p_reference_graph.add_argument("--apply", action="store_true")

    p_candidates = sub.add_parser("curate-candidates")
    p_candidates.add_argument("--mode", choices=["compact", "detailed"], default="compact")
    p_candidates.add_argument("--topic", default="")
    p_candidates.add_argument("--recent-sessions", type=int, default=5)
    p_candidates.add_argument("--limit", type=int, default=40)

    p_apply = sub.add_parser("apply-curation")
    p_apply_src = p_apply.add_mutually_exclusive_group(required=True)
    p_apply_src.add_argument("--input", dest="input_path", default=None, help="Path to apply payload JSON file")
    p_apply_src.add_argument("--stdin", action="store_true", help="Read apply payload from stdin")

    p_bd_add = sub.add_parser("brain-dump-candidate-add")
    p_bd_add.add_argument("--session", required=True)
    p_bd_add.add_argument("--topic", required=True)
    p_bd_add.add_argument("--concept", required=True)
    p_bd_add.add_argument("--doc", required=True)
    p_bd_add.add_argument("--prompt", required=True)
    p_bd_add.add_argument("--claim", default="")
    p_bd_add.add_argument("--provenance-tier", default="")
    p_bd_add.add_argument("--origin", choices=["assessed", "service"], default="assessed")
    p_bd_add.add_argument("--rotation", type=int, default=None)
    p_bd_add.add_argument("--convention", action="store_true")
    p_bd_add.add_argument("--detail-json", default="{}")

    p_bd_list = sub.add_parser("brain-dump-candidate-list")
    p_bd_list.add_argument("--topic", default="")
    p_bd_list.add_argument("--status", choices=["pending", "reviewed", "dismissed"], default="pending")
    p_bd_list.add_argument("--limit", type=int, default=20)

    p_bd_mark = sub.add_parser("brain-dump-candidate-mark")
    p_bd_mark.add_argument("--candidate-id", type=int, required=True)
    p_bd_mark.add_argument("--status", choices=["pending", "dismissed"], required=True)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    conn = _get_db()
    try:
        if args.command == "resolve-topic":
            print(_json_dumps(resolve_topic(conn, args.topic, args.doc).__dict__))
        elif args.command == "log-answer":
            exchange_id = log_answer(
                conn,
                session_id=args.session,
                topic=args.topic,
                concept=args.concept,
                question=args.question,
                answer=args.answer,
                correct=args.correct,
                correction=args.correction,
                error_type=args.error_type,
                misconception=args.misconception,
                doc_path=args.doc,
                skill=args.skill,
                tested_claim=args.tested_claim,
                learner_claim=args.learner_claim,
                missing_edge=args.missing_edge,
                corrected_rule=args.corrected_rule,
                clinical_consequence=args.clinical_consequence,
                retest_prompt_shape=args.retest_prompt_shape,
                learning_operation=args.learning_operation,
                teaching_intent=args.teaching_intent,
                expected_answer_edge=args.expected_answer_edge,
                coverage_role=args.coverage_role,
                source_section=args.source_section,
                source_anchor=args.source_anchor,
                curriculum_unit=args.curriculum_unit,
                answer_mode=args.answer_mode,
                confidence_observed=args.confidence_observed,
                teaching_move=args.teaching_move,
                strict_telemetry=args.strict_telemetry,
                agent_priority=args.priority,
                match_claim_state_id=args.match_claim_state_id,
                force_new_claim=args.new_claim,
                repairs_claim_state_ids=tuple(
                    int(x) for x in args.repairs_claim_state_ids.split(",") if x.strip()
                ),
                origin=args.origin,
                rotation_id=args.rotation,
                competency_target=args.competency_target,
                convention=args.convention,
                brain_dump_candidate_id=args.brain_dump_candidate_id,
                inventory_concept_id=args.inventory_concept_id,
            )
            print(f"OK exchange_id={exchange_id}")
            policy_row = conn.execute(
                """SELECT mode, phase, interrupts_json, plan_json FROM policy_events
                   WHERE session_id = ? ORDER BY id DESC LIMIT 1""",
                (args.session,),
            ).fetchone()
            if policy_row:
                try:
                    plan_snapshot = json.loads(policy_row["plan_json"] or "{}")
                except (ValueError, TypeError):
                    plan_snapshot = {}
                policy_payload: dict[str, object] = {
                    "mode": policy_row["mode"],
                    "phase": policy_row["phase"],
                    "interrupts": json.loads(policy_row["interrupts_json"] or "{}"),
                }
                # Carry the full plan so each turn is self-sufficient: the agent
                # does not need to retain the startup brief to obey the policy.
                for key in (
                    "target_concepts",
                    "pedagogical_directives",
                    "socratic_choice_directives",
                    "decision_inputs",
                ):
                    if key in plan_snapshot:
                        policy_payload[key] = plan_snapshot[key]
                targets = policy_payload.get("target_concepts")
                if isinstance(targets, list) and len(targets) > TARGET_CONCEPTS_COMPACT_CAP:
                    policy_payload["target_concepts"] = targets[:TARGET_CONCEPTS_COMPACT_CAP]
                    policy_payload["target_concepts_omitted"] = (
                        len(targets) - TARGET_CONCEPTS_COMPACT_CAP
                    )
                print("policy=" + _json_dumps(policy_payload))
            elif args.origin == "assessed":
                # Explicit signal instead of silence: the agent should keep the
                # current phase and surface the gap rather than guessing.
                print("policy_status=" + _json_dumps({
                    "status": "unavailable",
                    "reason": "no_policy_event_for_session",
                    "action": "continue current phase; rerun startup-recall if this persists",
                }))
        elif args.command == "end-session":
            result = end_session(conn, session_id=args.session, summary=args.summary, next_strategy=args.next_strategy, stats_json=args.stats_json)
            if args.as_json:
                print(_json_dumps(result))
            else:
                print("OK session closed")
        elif args.command == "summary":
            if args.lens == "service":
                print(_json_dumps(json.loads(service_recall(
                    conn,
                    service=args.service or args.topic,
                    site=args.site,
                    rotation_id=args.rotation,
                    context=args.context,
                    limit=args.limit,
                ))))
            else:
                print(
                    retrieval_summary(
                        conn,
                        topic=args.topic,
                        limit=args.limit,
                        scaffold_limit=args.scaffold_limit,
                        include_scaffolds=not args.no_scaffolds,
                        include_global_scaffolds=args.include_global_scaffolds,
                        include_curated=args.include_curated,
                        include_due=args.include_due,
                        include_model=args.include_model,
                        context=args.context,
                        brief_only=args.brief_only,
                        lens=args.lens,
                    )
                )
        elif args.command == "startup-recall":
            try:
                print(
                    startup_recall(
                        conn,
                        topic=args.topic,
                        doc_path=args.doc,
                        global_mode=args.global_mode,
                        limit=args.limit,
                        scaffold_limit=args.scaffold_limit,
                        include_global_scaffolds=args.include_global_scaffolds,
                        context=args.context,
                        lens=args.lens,
                        service=args.service,
                        site=args.site,
                        rotation_id=args.rotation,
                        profile=args.profile,
                        session_id=args.session,
                    )
                )
            except ValueError as exc:
                print(_json_dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
                sys.exit(2)
        elif args.command == "rotation-start":
            print(_json_dumps(start_rotation(
                conn, service=args.service, site=args.site, pgy=args.pgy, block_label=args.block)))
        elif args.command == "rotation-current":
            print(_json_dumps(current_rotation(conn) or {"active_rotation": None}))
        elif args.command == "rotation-list":
            print(_json_dumps(list_rotations(conn)))
        elif args.command == "rotation-end":
            print(_json_dumps(end_rotation(conn, rotation_id=args.rotation) or {"error": "rotation not found"}))
        elif args.command == "service-rubric":
            print(_json_dumps(service_rubric_view(conn, service=args.service, seed=args.seed, pgy=args.pgy)))
        elif args.command == "status":
            print(status(conn))
        elif args.command == "identity-audit":
            print(_json_dumps(identity_audit(conn)))
        elif args.command == "telemetry-audit":
            print(_json_dumps(_telemetry_profile_for_summary(conn, topic_id=None)))
        elif args.command == "merge-topics":
            print(_json_dumps(
                merge_topics(
                    conn,
                    source_topic=args.from_topic,
                    target_topic=args.into_topic,
                    apply=args.apply,
                )
            ))
        elif args.command == "record-shadow-check":
            print(_json_dumps(
                record_shadow_rule_check(
                    conn,
                    shadow_rule_id=args.rule_id,
                    claim_result_id=args.claim_result_id,
                    context_label=args.context_label,
                    check_type=args.check_type,
                    outcome=args.outcome,
                    apply=args.apply,
                )
            ))
        elif args.command == "load-reference-graph":
            print(_json_dumps(
                load_reference_graph_file(conn, Path(args.input), apply=args.apply),
            ))
        elif args.command == "curation-status":
            print(_json_dumps(curation_status(conn)))
        elif args.command == "brain-dump-candidate-add":
            try:
                detail = json.loads(args.detail_json or "{}")
            except json.JSONDecodeError as exc:
                print(_json_dumps({"ok": False, "error": f"invalid --detail-json: {exc}"}), file=sys.stderr)
                sys.exit(2)
            candidate_id = add_brain_dump_candidate(
                conn,
                session_id=args.session,
                topic=args.topic,
                concept=args.concept,
                doc_path=args.doc,
                prompt=args.prompt,
                claim_text=args.claim,
                provenance_tier=args.provenance_tier,
                origin=args.origin,
                rotation_id=args.rotation,
                convention=args.convention,
                detail=detail if isinstance(detail, dict) else {"value": detail},
            )
            print(_json_dumps({"ok": True, "candidate_id": candidate_id}))
        elif args.command == "brain-dump-candidate-list":
            topic_id = None
            if args.topic:
                resolution = resolve_topic(conn, args.topic)
                topic_row = conn.execute("SELECT id FROM topics WHERE canonical_slug = ?", (resolution.slug,)).fetchone()
                if topic_row:
                    topic_id = int(topic_row["id"])
                else:
                    print(_json_dumps([]))
                    return
            print(_json_dumps(
                _brain_dump_candidates_for_summary(
                    conn,
                    topic_id=topic_id,
                    limit=args.limit,
                    status=args.status,
                )
            ))
        elif args.command == "brain-dump-candidate-mark":
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """UPDATE brain_dump_review_candidates
                      SET status = ?, updated_at = ?
                    WHERE id = ? AND status != 'reviewed'""",
                (args.status, now, args.candidate_id),
            )
            conn.commit()
            print(_json_dumps({"ok": True, "candidate_id": args.candidate_id, "status": args.status}))
        elif args.command == "curate-candidates":
            try:
                packet = build_curation_candidates(
                    conn,
                    mode=args.mode,
                    topic=args.topic,
                    recent_sessions=args.recent_sessions,
                    limit=args.limit,
                )
            except CurationError as exc:
                print(_json_dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
                sys.exit(2)
            # Curation and maintenance bookkeeping fire together: the same pass that
            # synthesizes curated memory also surfaces topic-identity and telemetry
            # audits, so they cannot silently fall stale. One invocation, one packet.
            packet["maintenance"] = {
                "identity_audit": identity_audit(conn),
                "telemetry_audit": _telemetry_profile_for_summary(conn, topic_id=None),
            }
            print(_json_dumps(packet))
        elif args.command == "apply-curation":
            if args.stdin:
                raw = sys.stdin.read()
            else:
                raw = Path(args.input_path).read_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(_json_dumps({"ok": False, "error": f"invalid JSON: {exc}"}), file=sys.stderr)
                sys.exit(2)
            try:
                result = apply_curation_payload(conn, payload)
            except CurationError as exc:
                print(_json_dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
                sys.exit(2)
            print(_json_dumps(result))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
