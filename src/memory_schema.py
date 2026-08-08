"""SQLite schema authority for the claim-centered learner-memory store."""

from __future__ import annotations

try:
    from service_memory import SERVICE_SCHEMA_SQL
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from .service_memory import SERVICE_SCHEMA_SQL


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
    binding_match_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT '',
    UNIQUE(topic_id, canonical_slug),
    FOREIGN KEY(topic_id) REFERENCES topics(id)
);
CREATE INDEX IF NOT EXISTS idx_memory_concepts_topic ON concepts(topic_id);

CREATE TABLE IF NOT EXISTS artifact_maps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_path TEXT NOT NULL UNIQUE,
    topic_id INTEGER,
    artifact_title TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    schema_version TEXT NOT NULL DEFAULT 'artifact_map_v1',
    map_status TEXT NOT NULL DEFAULT 'complete',
    created_by TEXT NOT NULL DEFAULT 'agent',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(topic_id) REFERENCES topics(id)
);
CREATE INDEX IF NOT EXISTS idx_artifact_maps_topic ON artifact_maps(topic_id);

CREATE TABLE IF NOT EXISTS artifact_map_concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_map_id INTEGER NOT NULL,
    artifact_concept TEXT NOT NULL,
    inventory_concept_id TEXT NOT NULL DEFAULT '',
    mapping_status TEXT NOT NULL DEFAULT 'unresolved',
    confidence TEXT NOT NULL DEFAULT 'low',
    role TEXT NOT NULL DEFAULT 'mentioned',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    source_sections_json TEXT NOT NULL DEFAULT '[]',
    source_anchors_json TEXT NOT NULL DEFAULT '[]',
    section_hashes_json TEXT NOT NULL DEFAULT '{}',
    learning_objectives_json TEXT NOT NULL DEFAULT '[]',
    prerequisites_json TEXT NOT NULL DEFAULT '[]',
    confusers_json TEXT NOT NULL DEFAULT '[]',
    consequences_json TEXT NOT NULL DEFAULT '[]',
    transfer_targets_json TEXT NOT NULL DEFAULT '[]',
    source_provenance_json TEXT NOT NULL DEFAULT '{}',
    unresolved_reason TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    ordinal INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(artifact_map_id) REFERENCES artifact_maps(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_artifact_map_concepts_map ON artifact_map_concepts(artifact_map_id);
CREATE INDEX IF NOT EXISTS idx_artifact_map_concepts_inventory ON artifact_map_concepts(inventory_concept_id);

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

CREATE TABLE IF NOT EXISTS anki_card_decisions (
    exchange_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN (
        'enqueue',
        'skip_routine_correct',
        'skip_equivalent',
        'skip_low_value',
        'skip_not_durable',
        'defer_unavailable'
    )),
    rationale TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(exchange_id) REFERENCES exchanges(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_anki_card_decisions_session
    ON anki_card_decisions(session_id);

-- One idempotent envelope per learner turn.  The legacy exchanges and
-- claim_results tables remain the longitudinal evidence authority; this table
-- makes a multi-claim turn retry-safe and preserves the exact typed payload an
-- agent submitted.
CREATE TABLE IF NOT EXISTS turn_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    exchange_id INTEGER NOT NULL UNIQUE,
    schema_version TEXT NOT NULL DEFAULT 'turn_assessment_v1',
    request_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(exchange_id) REFERENCES exchanges(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_turn_assessments_session
    ON turn_assessments(session_id);

-- Higher-resolution grading dimensions are deliberately separate from
-- claim_results.  This preserves every existing query and schedule while
-- allowing pending/ungraded claims and richer expert-performance evidence.
CREATE TABLE IF NOT EXISTS claim_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id INTEGER NOT NULL,
    claim_result_id INTEGER UNIQUE,
    inventory_concept_id TEXT NOT NULL DEFAULT '',
    concept TEXT NOT NULL,
    assessment_status TEXT NOT NULL DEFAULT 'graded'
        CHECK(assessment_status IN ('graded', 'pending_adjudication')),
    accuracy INTEGER CHECK(accuracy IN (0, 1, 2) OR accuracy IS NULL),
    independence TEXT NOT NULL DEFAULT '',
    reasoning_depth TEXT NOT NULL DEFAULT '',
    safety_impact TEXT NOT NULL DEFAULT '',
    operation_demonstrated TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(exchange_id) REFERENCES exchanges(id) ON DELETE CASCADE,
    FOREIGN KEY(claim_result_id) REFERENCES claim_results(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_claim_assessments_exchange
    ON claim_assessments(exchange_id);
CREATE INDEX IF NOT EXISTS idx_claim_assessments_inventory
    ON claim_assessments(inventory_concept_id);
CREATE INDEX IF NOT EXISTS idx_claim_assessments_status
    ON claim_assessments(assessment_status);

-- The outer workflow lifecycle is intentionally small.  Fine-grained
-- ORIENT/DEEPEN/CONNECT policy remains in policy_events and the knowledge map.
CREATE TABLE IF NOT EXISTS study_runtime_sessions (
    session_id TEXT PRIMARY KEY,
    lifecycle_node TEXT NOT NULL DEFAULT 'prepare'
        CHECK(lifecycle_node IN ('prepare', 'teach', 'paused', 'close', 'done', 'failed')),
    profile TEXT NOT NULL DEFAULT '',
    topic_id INTEGER,
    doc_path TEXT NOT NULL DEFAULT '',
    tutor_state_version TEXT NOT NULL DEFAULT 'tutor_state_v1',
    started_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    closed_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(topic_id) REFERENCES topics(id)
);

-- PGY is an expectation context, never a mastery assertion.  Domain-specific
-- entrustment evidence remains in the learner map and claim assessments.
CREATE TABLE IF NOT EXISTS learner_profile (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    current_pgy INTEGER,
    active_service TEXT NOT NULL DEFAULT '',
    expected_responsibilities_json TEXT NOT NULL DEFAULT '[]',
    domain_expectations_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT ''
);
INSERT OR IGNORE INTO learner_profile (id, current_pgy) VALUES (1, 1);

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
    demonstrated_edge TEXT NOT NULL DEFAULT '',
    misconception_text TEXT NOT NULL DEFAULT '',
    missing_edge TEXT NOT NULL DEFAULT '',
    corrected_rule TEXT NOT NULL DEFAULT '',
    clinical_consequence TEXT NOT NULL DEFAULT '',
    retest_prompt_shape TEXT NOT NULL DEFAULT '',
    teaching_intervention TEXT NOT NULL DEFAULT '',
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
-- concept_id is the most-queried filter after topic (per-concept aggregation,
-- relations, surfaces); without these every WHERE concept_id=? was a full scan.
CREATE INDEX IF NOT EXISTS idx_memory_claim_results_concept ON claim_results(concept_id);
CREATE INDEX IF NOT EXISTS idx_memory_claim_results_topic_concept ON claim_results(topic_id, concept_id);

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
-- (concept_id, state) serves WHERE concept_id=? [prefix] and concept+state filters
-- directly instead of scanning the low-selectivity state index. (topic_id,
-- next_due_ts) serves the spaced-retrieval scheduler's due-window range + order.
CREATE INDEX IF NOT EXISTS idx_memory_claim_state_concept_state ON claim_state(concept_id, state);
CREATE INDEX IF NOT EXISTS idx_memory_claim_state_due ON claim_state(topic_id, next_due_ts);

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

CREATE TABLE IF NOT EXISTS shift_debrief_review_candidates (
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
CREATE INDEX IF NOT EXISTS idx_shift_debrief_candidates_status ON shift_debrief_review_candidates(status);
CREATE INDEX IF NOT EXISTS idx_shift_debrief_candidates_topic ON shift_debrief_review_candidates(topic_id);
CREATE INDEX IF NOT EXISTS idx_shift_debrief_candidates_concept ON shift_debrief_review_candidates(concept_id);
CREATE INDEX IF NOT EXISTS idx_shift_debrief_candidates_service_scope
    ON shift_debrief_review_candidates(status, origin, rotation_id);

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
    inventory_concept_id TEXT,
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

-- Per-local-concept mastery rollup. Canonical inventory-level consumers must
-- aggregate all local topic/document envelopes by inventory_concept_id; see
-- _canonical_mastery_rows(). This view remains the compatibility surface for
-- consumers that intentionally need one row per learner concept.
DROP VIEW IF EXISTS v_concept_mastery;
CREATE VIEW v_concept_mastery AS
SELECT
    c.id AS concept_id,
    c.topic_id,
    c.inventory_concept_id,
    c.display_name,
    (SELECT MAX(CASE WHEN cs.priority IN ('urgent','high') THEN 1 ELSE 0 END)
       FROM claim_state cs WHERE cs.concept_id = c.id AND cs.origin = 'assessed') AS safety_critical,
    (SELECT COUNT(*) FROM claim_results cr
       WHERE cr.concept_id = c.id AND cr.origin = 'assessed') AS attempts,
    (SELECT COUNT(*) FROM claim_results cr
       WHERE cr.concept_id = c.id AND cr.origin = 'assessed' AND cr.score >= 2) AS successes,
    (SELECT COUNT(*) FROM claim_state cs
       WHERE cs.concept_id = c.id AND cs.origin = 'assessed'
         AND cs.state IN ('missed','partially_repaired','regressed')) AS open_gaps,
    (SELECT MAX(cr.created_at) FROM claim_results cr
       WHERE cr.concept_id = c.id AND cr.origin = 'assessed') AS last_seen_ts,
    (SELECT MIN(NULLIF(cs.next_due_ts, '')) FROM claim_state cs
       WHERE cs.concept_id = c.id AND cs.origin = 'assessed') AS next_due_ts,
    (SELECT ROUND(AVG(cs.stability), 3) FROM claim_state cs
       WHERE cs.concept_id = c.id AND cs.origin = 'assessed') AS avg_stability,
    (SELECT cr.score FROM claim_results cr
       WHERE cr.concept_id = c.id AND cr.origin = 'assessed'
       ORDER BY cr.created_at DESC, cr.id DESC LIMIT 1) AS last_score,
    -- Recency-weighted (decaying-memory) success rate: the success ratio over the
    -- most recent 3 assessed attempts, so a concept the learner has clearly turned
    -- around is no longer dragged by stale early failures (the "perma-novice" bug).
    (SELECT ROUND(CAST(SUM(CASE WHEN w.score >= 2 THEN 1 ELSE 0 END) AS REAL) / COUNT(*), 3)
       FROM (SELECT cr.score FROM claim_results cr
              WHERE cr.concept_id = c.id AND cr.origin = 'assessed'
              ORDER BY cr.created_at DESC, cr.id DESC LIMIT 3) w) AS recent_success_rate
FROM concepts c;

"""
SCHEMA_SQL += SERVICE_SCHEMA_SQL
