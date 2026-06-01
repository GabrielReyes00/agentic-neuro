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

STOPWORDS = frozenset(
    "the a an of in for with and or to on by is at as it its from that this "
    "after before per via vs versus during over under into onto management"
    .split()
)

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
"""


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
    _backfill_memory_schedule(conn)


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
        "SELECT id, canonical_slug, display_name, domain FROM topics ORDER BY canonical_slug"
    ).fetchall()
    duplicate_topics: list[dict[str, object]] = []
    for idx, left in enumerate(topics):
        for right in topics[idx + 1:]:
            metrics = _topic_overlap(left["display_name"], right["display_name"])
            if int(metrics["overlap"]) < 2:
                continue
            if float(metrics["containment"]) < 0.75 and float(metrics["f1"]) < 0.72:
                continue
            duplicate_topics.append({
                "source_topic": left["canonical_slug"],
                "target_topic": right["canonical_slug"],
                "source_domain": left["domain"],
                "target_domain": right["domain"],
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
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
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
) -> sqlite3.Row | None:
    exact = conn.execute(
        """SELECT id, claim_slug, claim_text, state, reason, difficulty, stability
           FROM claim_state
           WHERE topic_id = ? AND claim_slug = ?
           ORDER BY last_seen_ts DESC LIMIT 1""",
        (topic_id, claim_slug),
    ).fetchone()
    if exact:
        return exact

    expected_edge = agent_signal.get("expected_answer_edge", "")
    candidate_tokens = _tokens(" ".join((claim_text, expected_edge, corrected_rule)))
    if len(candidate_tokens) < 5:
        return None
    if not expected_edge and len(_tokens(corrected_rule)) < 5:
        return None
    rows = conn.execute(
        """SELECT id, claim_slug, claim_text, state, reason, difficulty, stability
           FROM claim_state
           WHERE topic_id = ?
           ORDER BY last_seen_ts DESC LIMIT 30""",
        (topic_id,),
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
) -> int:
    claim_text = _derive_claim(concept=concept, tested_claim=tested_claim, corrected_rule=corrected_rule, correction=correction)
    claim_slug = _slug(claim_text)
    learner = learner_claim.strip() or _first_sentence(answer, "No learner answer captured.")
    missing = missing_edge.strip()
    fixed_rule = corrected_rule.strip() or correction.strip()
    consequence = clinical_consequence.strip()
    retest = retest_prompt_shape.strip() or f"Use a new vignette testing {concept} without repeating the original wording."
    if score < 2 and not missing:
        missing = misconception.strip() or _first_sentence(correction)
    if score < 2 and not consequence:
        consequence = "Future review should target this missing edge because it changes management or discrimination."
    gap_type = _normalize_gap_type(error_type, score, missing)
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
        )
    if existing and existing["claim_slug"] != claim_slug:
        claim_slug = existing["claim_slug"]
    conn.execute(
        """INSERT INTO claim_results
           (exchange_id, topic_id, concept_id, claim_slug, claim_text, score, gap_type,
            learner_claim, missing_edge, corrected_rule, clinical_consequence,
            retest_prompt_shape, learning_operation, agent_signal_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                   last_seen_ts = ?, next_due_ts = ?, difficulty = ?, stability = ?, reason = ?
               WHERE id = ?""",
            (claim_text, state, priority, gap_type, result_id, result_id, now, next_due_ts, difficulty, stability, reason, state_id),
        )
    else:
        conn.execute(
            """INSERT INTO claim_state
               (topic_id, concept_id, claim_slug, claim_text, state, priority, gap_type,
                last_result_id, source_result_id, last_seen_ts, next_due_ts, difficulty, stability, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (topic_id, concept_id, claim_slug, claim_text, state, priority, gap_type, result_id, result_id, now, next_due_ts, difficulty, stability, reason),
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
) -> int:
    if strict_telemetry:
        _validate_strict_telemetry(
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
            doc_path, skill, source_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        ),
    )
    exchange_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    # Artifact-anchor skills record the exchange (for provenance/discoverability)
    # but do not create a claim_result/claim_state — the learner has not been
    # tested on this content, so it must not register as known or as an open gap.
    if skill not in ARTIFACT_ANCHOR_SKILLS:
        _log_claim_result(
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
        )
    conn.commit()
    return exchange_id


def log_exchange_claims(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    topic: str,
    question: str,
    answer: str,
    claims: list[dict[str, object]],
    doc_path: str = "",
    skill: str = "",
    turn: int | None = None,
    ts: str | None = None,
    teaching_intent: str = "",
    expected_answer_edge: str = "",
    coverage_role: str = "",
    source_section: str = "",
    source_anchor: str = "",
    curriculum_unit: str = "",
    answer_mode: str = "",
    confidence_observed: str = "",
    teaching_move: str = "",
) -> int:
    """Log one raw Q/A exchange with multiple assessed claim results."""
    if not claims:
        raise ValueError("claims must contain at least one claim")
    now = ts or datetime.now(timezone.utc).isoformat()
    first_concept = str(claims[0].get("concept") or "multi-claim exchange")
    first_correction = str(claims[0].get("correction") or claims[0].get("corrected_rule") or "")
    resolution = resolve_topic(conn, topic, doc_path)
    topic_id = _ensure_topic(conn, resolution, doc_path)
    exchange_concept_id = _ensure_concept(conn, topic_id, resolution.slug, first_concept, question, first_correction)
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
        "claim_count": str(len(claims)),
    }
    conn.execute(
        """INSERT INTO exchanges
           (session_id, ts, turn, topic_id, concept_id, raw_question, raw_answer,
            doc_path, skill, source_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            now,
            turn,
            topic_id,
            exchange_concept_id,
            question,
            answer,
            doc_path,
            skill,
            json.dumps(source, sort_keys=True),
        ),
    )
    exchange_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    # Artifact-anchor skills record the exchange only; no learner claim state.
    if skill in ARTIFACT_ANCHOR_SKILLS:
        conn.commit()
        return exchange_id
    for claim in claims:
        concept = str(claim.get("concept") or first_concept)
        correction = str(claim.get("correction") or "")
        corrected_rule = str(claim.get("corrected_rule") or "")
        concept_id = _ensure_concept(conn, topic_id, resolution.slug, concept, question, correction or corrected_rule)
        claim_signal = {k: v for k, v in source.items() if v}
        claim_signal.update({
            k: str(claim[k])
            for k in ("teaching_intent", "expected_answer_edge", "coverage_role", "source_section", "source_anchor", "curriculum_unit", "answer_mode", "confidence_observed", "teaching_move")
            if k in claim and claim[k]
        })
        repairs = claim.get("repairs_claim_state_ids") or ()
        repairs_tuple = tuple(int(x) for x in repairs) if isinstance(repairs, (list, tuple)) else ()
        match_id = claim.get("match_claim_state_id")
        _log_claim_result(
            conn,
            exchange_id=exchange_id,
            topic_id=topic_id,
            concept_id=concept_id,
            topic_slug=resolution.slug,
            concept=concept,
            score=int(claim.get("correct", claim.get("score", 2))),
            error_type=str(claim.get("error_type") or ""),
            answer=answer,
            correction=correction,
            misconception=str(claim.get("misconception") or ""),
            tested_claim=str(claim.get("tested_claim") or ""),
            learner_claim=str(claim.get("learner_claim") or ""),
            missing_edge=str(claim.get("missing_edge") or ""),
            corrected_rule=corrected_rule,
            clinical_consequence=str(claim.get("clinical_consequence") or ""),
            retest_prompt_shape=str(claim.get("retest_prompt_shape") or ""),
            learning_operation=str(claim.get("learning_operation") or ""),
            agent_signal=claim_signal,
            now=now,
            agent_priority=str(claim.get("priority") or ""),
            match_claim_state_id=int(match_id) if match_id is not None else None,
            force_new_claim=bool(claim.get("force_new_claim", False)),
            repairs_claim_state_ids=repairs_tuple,
        )
    conn.commit()
    return exchange_id


def end_session(conn: sqlite3.Connection, *, session_id: str, summary: str, next_strategy: str, ended: str | None = None, stats_json: str = "{}") -> dict[str, object]:
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
    # Artifact-anchor skills still get a session_handoff card so /study-review can
    # discover the file; the card's text (agent-authored) states it is generated
    # and not yet reviewed. Only quick-answer suppresses the card entirely.
    if session_row and session_row["primary_topic_id"] and not is_low_stakes_reference:
        _upsert_session_card(conn, int(session_row["primary_topic_id"]), session_id, summary, next_strategy, now)
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


def _upsert_session_card(conn: sqlite3.Connection, topic_id: int, session_id: str, summary: str, next_strategy: str, now: str) -> None:
    existing = conn.execute(
        """SELECT id FROM retrieval_cards
           WHERE topic_id = ? AND claim_state_id IS NULL AND card_type = 'session_handoff'
           ORDER BY updated_ts DESC LIMIT 1""",
        (topic_id,),
    ).fetchone()
    payload = json.dumps({"session_id": session_id}, sort_keys=True)
    if existing:
        conn.execute(
            """UPDATE retrieval_cards
               SET status = 'active', priority = 'medium', summary = ?, next_action = ?,
                   evidence_result_id = NULL, updated_ts = ?, detail_json = ?
               WHERE id = ?""",
            (_compact_text(summary), _compact_text(next_strategy), now, payload, existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO retrieval_cards
               (topic_id, claim_state_id, card_type, status, priority, summary, next_action,
                evidence_result_id, updated_ts, detail_json)
               VALUES (?, NULL, 'session_handoff', 'active', 'medium', ?, ?, NULL, ?, ?)""",
            (topic_id, _compact_text(summary), _compact_text(next_strategy), now, payload),
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


def _due_claims_for_summary(
    conn: sqlite3.Connection,
    *,
    topic_id: int | None,
    limit: int,
    exclude_claim_state_ids: set[int] | None = None,
) -> list[dict[str, object]]:
    where = "WHERE COALESCE(cs.next_due_ts, '') != '' AND cs.next_due_ts <= ?"
    params: list[object] = [datetime.now(timezone.utc).isoformat()]
    if topic_id is not None:
        where += " AND cs.topic_id = ?"
        params.append(topic_id)
    if exclude_claim_state_ids:
        placeholders = ",".join("?" * len(exclude_claim_state_ids))
        where += f" AND cs.id NOT IN ({placeholders})"
        params.extend(sorted(exclude_claim_state_ids))
    rows = conn.execute(
        f"""SELECT cs.id, cs.claim_text, cs.state, cs.priority, cs.last_seen_ts,
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
    return " ".join(parts)


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
) -> str:
    limit = max(0, limit)
    scaffold_limit = max(0, scaffold_limit)
    topic_filter = ""
    params: list[str | int] = []
    resolved_topic_id: int | None = None
    if topic:
        resolution = resolve_topic(conn, topic)
        topic_row = conn.execute("SELECT id FROM topics WHERE canonical_slug = ?", (resolution.slug,)).fetchone()
        if not topic_row:
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
            return json.dumps(base, indent=2)
        resolved_topic_id = int(topic_row["id"])
        topic_filter = "AND rc.topic_id = ?"
        params.append(resolved_topic_id)

    counts = {
        row["card_type"]: int(row["n"])
        for row in conn.execute(
            f"""SELECT rc.card_type, COUNT(*) AS n
                FROM retrieval_cards rc
                WHERE rc.status = 'active' {topic_filter}
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
           WHERE rc.status = 'active' {topic_filter}"""
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
        ),
    }

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

    return json.dumps(payload, indent=2)


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
    return json.dumps(rows, indent=2)


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

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    conn = _get_db()
    try:
        if args.command == "resolve-topic":
            print(json.dumps(resolve_topic(conn, args.topic, args.doc).__dict__, indent=2))
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
            )
            print(f"OK exchange_id={exchange_id}")
        elif args.command == "end-session":
            result = end_session(conn, session_id=args.session, summary=args.summary, next_strategy=args.next_strategy, stats_json=args.stats_json)
            if args.as_json:
                print(json.dumps(result, indent=2))
            else:
                print("OK session closed")
        elif args.command == "summary":
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
                )
            )
        elif args.command == "status":
            print(status(conn))
        elif args.command == "identity-audit":
            print(json.dumps(identity_audit(conn), indent=2))
        elif args.command == "telemetry-audit":
            print(json.dumps(_telemetry_profile_for_summary(conn, topic_id=None), indent=2))
        elif args.command == "merge-topics":
            print(json.dumps(
                merge_topics(
                    conn,
                    source_topic=args.from_topic,
                    target_topic=args.into_topic,
                    apply=args.apply,
                ),
                indent=2,
            ))
        elif args.command == "record-shadow-check":
            print(json.dumps(
                record_shadow_rule_check(
                    conn,
                    shadow_rule_id=args.rule_id,
                    claim_result_id=args.claim_result_id,
                    context_label=args.context_label,
                    check_type=args.check_type,
                    outcome=args.outcome,
                    apply=args.apply,
                ),
                indent=2,
            ))
        elif args.command == "load-reference-graph":
            print(json.dumps(
                load_reference_graph_file(conn, Path(args.input), apply=args.apply),
                indent=2,
            ))
        elif args.command == "curation-status":
            print(json.dumps(curation_status(conn), indent=2))
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
                print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
                sys.exit(2)
            # Curation and maintenance bookkeeping fire together: the same pass that
            # synthesizes curated memory also surfaces topic-identity and telemetry
            # audits, so they cannot silently fall stale. One invocation, one packet.
            packet["maintenance"] = {
                "identity_audit": identity_audit(conn),
                "telemetry_audit": _telemetry_profile_for_summary(conn, topic_id=None),
            }
            print(json.dumps(packet, indent=2))
        elif args.command == "apply-curation":
            if args.stdin:
                raw = sys.stdin.read()
            else:
                raw = Path(args.input_path).read_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(json.dumps({"ok": False, "error": f"invalid JSON: {exc}"}, indent=2), file=sys.stderr)
                sys.exit(2)
            try:
                result = apply_curation_payload(conn, payload)
            except CurationError as exc:
                print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
                sys.exit(2)
            print(json.dumps(result, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
