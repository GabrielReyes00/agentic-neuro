#!/usr/bin/env python3
"""SQLite schema for the neurosurgery knowledge graph."""

from __future__ import annotations

SCHEMA_SQL = """
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

-- Append-only source-of-truth memory events.
-- Derived tables (signal_events, learning_exchanges, concept_mastery,
-- episode_summaries, LanceDB rows) should be rebuildable from this log.
CREATE TABLE IF NOT EXISTS memory_events (
    memory_event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    event_ts              TEXT NOT NULL,
    session_ts            TEXT NOT NULL,
    turn_number           INTEGER DEFAULT 0,
    skill                 TEXT NOT NULL,
    topic_id              INTEGER,
    concept_text          TEXT DEFAULT '',
    event_type            TEXT NOT NULL,       -- active_answer, passive_teaching, correction, session_start, session_end
    actor                 TEXT DEFAULT '',     -- user, agent, system
    content_text          TEXT DEFAULT '',
    payload_json          TEXT DEFAULT '{}',
    source                TEXT DEFAULT '',
    idempotency_key       TEXT DEFAULT '',
    derived_from_event_id INTEGER,
    derived_json          TEXT DEFAULT '{}',
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id),
    FOREIGN KEY (derived_from_event_id) REFERENCES memory_events(memory_event_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_events_session ON memory_events(session_ts, turn_number);
CREATE INDEX IF NOT EXISTS idx_memory_events_topic ON memory_events(topic_id);
CREATE INDEX IF NOT EXISTS idx_memory_events_type ON memory_events(event_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_event_key ON memory_events(idempotency_key) WHERE idempotency_key != '';

-- Explicit per-session memory consent/operating mode.
CREATE TABLE IF NOT EXISTS memory_sessions (
    session_ts      TEXT NOT NULL,
    skill           TEXT NOT NULL,
    topic_text      TEXT DEFAULT '',
    memory_enabled  INTEGER DEFAULT 0,
    consent_scope   TEXT DEFAULT '',
    status          TEXT DEFAULT 'active',
    started_ts      TEXT NOT NULL,
    ended_ts        TEXT,
    notes           TEXT DEFAULT '',
    PRIMARY KEY (session_ts, skill)
);
CREATE INDEX IF NOT EXISTS idx_memory_sessions_status ON memory_sessions(status);

-- Lightweight concept identity resolver.
-- Allows stable concept canonicalization without forcing every workflow to
-- hand-maintain long alias maps in prompts.
CREATE TABLE IF NOT EXISTS concept_aliases (
    alias_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alias             TEXT NOT NULL,
    canonical_concept TEXT NOT NULL,
    topic_id          INTEGER,
    source            TEXT DEFAULT '',
    created_ts        TEXT NOT NULL,
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_concept_alias ON concept_aliases(alias, topic_id) WHERE alias != '';

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
    source_kind         TEXT DEFAULT '',       -- review_material, generated_report, oral_board_case_seed, primary_source, unknown
    preferred_study_mode TEXT DEFAULT '',      -- rapid_review, deep_understanding, oral_boards, ask
    last_study_mode     TEXT DEFAULT '',
    pacing_goal         TEXT DEFAULT '',       -- throughput, mastery, exam_simulation
    mode_confidence     REAL DEFAULT 0.0,
    mode_reason         TEXT DEFAULT '',
    mode_updated_ts     TEXT,
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

-- Episodic memory: per-exchange learning content (Phase 7 — Lossless Memory)
-- One row per question-answer-correction cycle.  Captures the CONTENT that
-- signal_events currently discards: what the agent asked, what the user answered,
-- what the correction was, and which teaching approach was used.
CREATE TABLE IF NOT EXISTS learning_exchanges (
    exchange_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    session_ts        TEXT NOT NULL,
    turn_number       INTEGER NOT NULL,
    skill             TEXT NOT NULL,
    topic_id          INTEGER,
    concept_text      TEXT NOT NULL,
    domain            TEXT DEFAULT '',
    depth             INTEGER DEFAULT 1,

    question_text     TEXT NOT NULL,
    answer_text       TEXT NOT NULL,
    answer_correct    INTEGER NOT NULL DEFAULT 0,   -- 0=incorrect, 1=partial, 2=correct
    correction_text   TEXT DEFAULT '',

    error_type        TEXT DEFAULT '',
    misconception     TEXT DEFAULT '',
    root_cause        TEXT DEFAULT '',

    teaching_approach TEXT DEFAULT '',
    teaching_worked   INTEGER DEFAULT -1,           -- -1=unknown, 0=no, 1=yes
    retrieval_sources TEXT DEFAULT '',

    breakthrough      INTEGER DEFAULT 0,
    insight_text      TEXT DEFAULT '',

    signal_event_id   INTEGER,
    memory_event_id   INTEGER,
    narrative_id      INTEGER,
    lance_row_id      TEXT DEFAULT '',
    consolidated_at   TEXT,
    dedupe_key        TEXT DEFAULT '',

    FOREIGN KEY (topic_id) REFERENCES topics(topic_id),
    FOREIGN KEY (signal_event_id) REFERENCES signal_events(event_id),
    FOREIGN KEY (memory_event_id) REFERENCES memory_events(memory_event_id)
);
CREATE INDEX IF NOT EXISTS idx_xchg_session ON learning_exchanges(session_ts);
CREATE INDEX IF NOT EXISTS idx_xchg_topic ON learning_exchanges(topic_id);
CREATE INDEX IF NOT EXISTS idx_xchg_concept ON learning_exchanges(concept_text);
CREATE INDEX IF NOT EXISTS idx_xchg_correct ON learning_exchanges(answer_correct);
CREATE INDEX IF NOT EXISTS idx_xchg_error ON learning_exchanges(error_type);
CREATE INDEX IF NOT EXISTS idx_xchg_skill ON learning_exchanges(skill);

-- Episodic memory: session-level summaries optimised for agent retrieval.
-- Companion to session_narratives — that table stores forward-looking strategy;
-- this table stores backward-looking memory of what actually happened.
CREATE TABLE IF NOT EXISTS episode_summaries (
    summary_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_ts         TEXT NOT NULL,
    skill              TEXT NOT NULL,
    narrative_id       INTEGER,

    persistent_confusions TEXT DEFAULT '[]',
    effective_approaches  TEXT DEFAULT '[]',
    failed_approaches     TEXT DEFAULT '[]',

    exchange_count     INTEGER DEFAULT 0,
    correct_count      INTEGER DEFAULT 0,
    partial_count      INTEGER DEFAULT 0,
    incorrect_count    INTEGER DEFAULT 0,
    breakthrough_count INTEGER DEFAULT 0,

    memory_text        TEXT NOT NULL DEFAULT '',
    lance_row_id       TEXT DEFAULT '',
    source_exchange_ids TEXT DEFAULT '[]',
    source_memory_event_ids TEXT DEFAULT '[]',
    memory_hash        TEXT DEFAULT '',
    dedupe_key         TEXT DEFAULT '',

    FOREIGN KEY (narrative_id) REFERENCES session_narratives(narrative_id)
);
CREATE INDEX IF NOT EXISTS idx_episode_ts ON episode_summaries(session_ts);
CREATE INDEX IF NOT EXISTS idx_episode_skill ON episode_summaries(skill);

-- Concept evolution history — tracks how understanding changes over time.
-- One row per state change on a concept_mastery row. Forms a temporal chain
-- so the agent can see: "Gabriel first thought X, then corrected to Y,
-- then regressed to Z, then finally stabilized on W."
CREATE TABLE IF NOT EXISTS concept_evolution (
    evolution_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id     INTEGER NOT NULL,
    topic_id       INTEGER NOT NULL,
    timestamp      TEXT NOT NULL,

    -- Snapshot of state AT THIS POINT
    status         TEXT NOT NULL,
    error_type     TEXT DEFAULT '',
    misconception  TEXT DEFAULT '',
    remediation    TEXT DEFAULT '',
    times_confirmed INTEGER DEFAULT 0,
    times_missed   INTEGER DEFAULT 0,

    -- What caused this change
    trigger_type   TEXT NOT NULL,
    trigger_exchange_id INTEGER,
    trigger_signal_id   INTEGER,
    trigger_memory_event_id INTEGER,

    -- Evolution chain
    previous_status TEXT DEFAULT '',
    previous_misconception TEXT DEFAULT '',

    -- Natural language note
    evolution_note TEXT DEFAULT '',

    FOREIGN KEY (concept_id) REFERENCES concept_mastery(concept_id),
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id),
    FOREIGN KEY (trigger_exchange_id) REFERENCES learning_exchanges(exchange_id),
    FOREIGN KEY (trigger_signal_id) REFERENCES signal_events(event_id),
    FOREIGN KEY (trigger_memory_event_id) REFERENCES memory_events(memory_event_id)
);
CREATE INDEX IF NOT EXISTS idx_evo_concept ON concept_evolution(concept_id);
CREATE INDEX IF NOT EXISTS idx_evo_topic ON concept_evolution(topic_id);
CREATE INDEX IF NOT EXISTS idx_evo_ts ON concept_evolution(timestamp);

-- Memory V2: typed canonical memories over the append-only event log.
-- memory_events remains the raw source of truth; these rows are rebuildable
-- projections used for retrieval, temporal reasoning, and context packing.
CREATE TABLE IF NOT EXISTS memory_items (
    item_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    item_type             TEXT NOT NULL,       -- episode, semantic_fact, learner_state, teaching_policy, reflection, resource_link, core_profile, case_memory
    topic_id              INTEGER,
    concept_text          TEXT DEFAULT '',
    summary               TEXT NOT NULL DEFAULT '',
    details_json          TEXT DEFAULT '{}',
    importance            REAL DEFAULT 0.5,
    confidence            REAL DEFAULT 0.5,
    evidence_event_ids    TEXT DEFAULT '[]',
    evidence_exchange_ids TEXT DEFAULT '[]',
    source_table          TEXT DEFAULT '',
    source_id             INTEGER,
    valid_from            TEXT NOT NULL,
    valid_to              TEXT DEFAULT '',
    superseded_by         INTEGER,
    embedding_status      TEXT DEFAULT 'pending',
    created_ts            TEXT NOT NULL,
    updated_ts            TEXT NOT NULL,
    dedupe_key            TEXT DEFAULT '',
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id),
    FOREIGN KEY (superseded_by) REFERENCES memory_items(item_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_items_type ON memory_items(item_type);
CREATE INDEX IF NOT EXISTS idx_memory_items_topic ON memory_items(topic_id);
CREATE INDEX IF NOT EXISTS idx_memory_items_concept ON memory_items(concept_text);
CREATE INDEX IF NOT EXISTS idx_memory_items_valid ON memory_items(valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_memory_items_embedding ON memory_items(embedding_status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_items_dedupe ON memory_items(dedupe_key) WHERE dedupe_key != '';

-- Memory V2: temporal graph edges between memory items.
CREATE TABLE IF NOT EXISTS memory_edges (
    edge_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_item_id     INTEGER NOT NULL,
    target_item_id     INTEGER NOT NULL,
    edge_type          TEXT NOT NULL,       -- supports, contradicts, supersedes, caused_by, tests, teaches, confusable_with, prerequisite_of
    confidence         REAL DEFAULT 0.5,
    valid_from         TEXT NOT NULL,
    valid_to           TEXT DEFAULT '',
    evidence_event_ids TEXT DEFAULT '[]',
    created_ts         TEXT NOT NULL,
    updated_ts         TEXT NOT NULL,
    dedupe_key         TEXT DEFAULT '',
    FOREIGN KEY (source_item_id) REFERENCES memory_items(item_id),
    FOREIGN KEY (target_item_id) REFERENCES memory_items(item_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_edges_source ON memory_edges(source_item_id);
CREATE INDEX IF NOT EXISTS idx_memory_edges_target ON memory_edges(target_item_id);
CREATE INDEX IF NOT EXISTS idx_memory_edges_type ON memory_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_memory_edges_valid ON memory_edges(valid_from, valid_to);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_edges_dedupe ON memory_edges(dedupe_key) WHERE dedupe_key != '';

-- Memory V2: current inferred learner state. This is a derived, replayable
-- state table; temporal history remains in memory_items, memory_edges, and
-- concept_evolution.
CREATE TABLE IF NOT EXISTS learner_concept_state (
    state_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id                  INTEGER NOT NULL,
    concept_text              TEXT NOT NULL,
    mastery_prob              REAL DEFAULT 0.0,
    familiarity_prob          REAL DEFAULT 0.0,
    retention_half_life_days  REAL DEFAULT 1.0,
    difficulty                REAL DEFAULT 0.5,
    last_active_tested_at     TEXT,
    last_passive_exposed_at   TEXT,
    next_review_due           TEXT,
    dominant_misconception    TEXT DEFAULT '',
    root_cause                TEXT DEFAULT '',
    calibration_state         TEXT DEFAULT '',
    transfer_state            TEXT DEFAULT 'untested',
    evidence_event_ids        TEXT DEFAULT '[]',
    evidence_exchange_ids     TEXT DEFAULT '[]',
    last_updated              TEXT NOT NULL,
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id),
    UNIQUE(topic_id, concept_text)
);
CREATE INDEX IF NOT EXISTS idx_lcs_topic ON learner_concept_state(topic_id);
CREATE INDEX IF NOT EXISTS idx_lcs_concept ON learner_concept_state(concept_text);
CREATE INDEX IF NOT EXISTS idx_lcs_next_due ON learner_concept_state(next_review_due);
CREATE INDEX IF NOT EXISTS idx_lcs_mastery ON learner_concept_state(mastery_prob);

-- Memory V2: procedural teaching policy memory, conditioned by the learner's
-- domain/topic/concept/error context.
CREATE TABLE IF NOT EXISTS teaching_policy_stats (
    policy_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain                 TEXT DEFAULT '',
    topic_id               INTEGER,
    concept_text           TEXT DEFAULT '',
    error_type             TEXT DEFAULT '',
    teaching_approach      TEXT NOT NULL,
    success_count          INTEGER DEFAULT 0,
    failure_count          INTEGER DEFAULT 0,
    unknown_count          INTEGER DEFAULT 0,
    exposure_count         INTEGER DEFAULT 0,
    confidence             REAL DEFAULT 0.5,
    last_outcome           TEXT DEFAULT '',
    evidence_event_ids     TEXT DEFAULT '[]',
    evidence_exchange_ids  TEXT DEFAULT '[]',
    created_ts             TEXT NOT NULL,
    updated_ts             TEXT NOT NULL,
    dedupe_key             TEXT DEFAULT '',
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);
CREATE INDEX IF NOT EXISTS idx_policy_topic ON teaching_policy_stats(topic_id);
CREATE INDEX IF NOT EXISTS idx_policy_context ON teaching_policy_stats(domain, concept_text, error_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_policy_dedupe ON teaching_policy_stats(dedupe_key) WHERE dedupe_key != '';

-- Memory V2: retrieval traces for context-pack debugging and regression.
CREATE TABLE IF NOT EXISTS memory_retrieval_logs (
    retrieval_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ts           TEXT NOT NULL,
    query                TEXT NOT NULL DEFAULT '',
    topic_text           TEXT DEFAULT '',
    skill                TEXT DEFAULT '',
    intent               TEXT DEFAULT '',
    max_tokens           INTEGER DEFAULT 0,
    token_estimate       INTEGER DEFAULT 0,
    result_item_ids      TEXT DEFAULT '[]',
    result_exchange_ids  TEXT DEFAULT '[]',
    retrieval_json       TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_retrieval_logs_ts ON memory_retrieval_logs(created_ts);
CREATE INDEX IF NOT EXISTS idx_retrieval_logs_intent ON memory_retrieval_logs(intent);

-- Memory V2: local benchmark/regression cases.
CREATE TABLE IF NOT EXISTS memory_eval_cases (
    case_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    suite         TEXT NOT NULL DEFAULT 'local',
    name          TEXT NOT NULL,
    query         TEXT NOT NULL DEFAULT '',
    expected_json TEXT DEFAULT '{}',
    tags_json     TEXT DEFAULT '[]',
    created_ts    TEXT NOT NULL,
    updated_ts    TEXT NOT NULL,
    UNIQUE(suite, name)
);
CREATE INDEX IF NOT EXISTS idx_memory_eval_suite ON memory_eval_cases(suite);
"""
