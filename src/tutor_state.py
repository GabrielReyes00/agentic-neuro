"""Token-bounded tutor state for routine study-review turns.

The rich learner model remains available through audit and node-recall.  This
module selects the smallest actionable subset needed to ask or repair one
question while keeping explicit pointers to the full knowledge map.
"""

from __future__ import annotations

from typing import Any


TUTOR_STATE_VERSION = "tutor_state_v1"
ACTIVE_NODE_CAP = 8
QUEUE_CAP = 5
NEARBY_NODE_CAP = 3
EVIDENCE_CAP = 3


def _list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _compact_trace(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "claim_result_id",
        "tested_claim",
        "learner_claim",
        "demonstrated_edge",
        "misconception",
        "missing_edge",
        "corrected_rule",
        "clinical_consequence",
        "prior_teaching_intervention",
        "cognitive_op",
        "answer_mode",
        "confidence_observed",
        "independence",
        "reasoning_depth",
        "safety_impact",
        "operation_demonstrated",
        "verification_status",
    )
    return {key: value[key] for key in keys if value.get(key) not in (None, "", [], {})}


def _compact_node(node: dict[str, Any]) -> dict[str, object]:
    keys = (
        "concept_id",
        "concept",
        "tier",
        "role",
        "exposure_status",
        "knowledge_state",
        "mastery_depth",
        "safety_critical",
        "active_misconception",
        "artifact_native",
        "artifact_presence",
        "active_prerequisite_gaps",
        "semantic_competitors",
        "last_miss_cognitive_op",
        "stuck_probe_count",
    )
    return {key: node[key] for key in keys if node.get(key) not in (None, "", [], {}, False)}


def _node_rank(node: dict[str, Any], targets: list[str]) -> tuple[object, ...]:
    name = str(node.get("concept") or "")
    target_rank = next(
        (idx for idx, target in enumerate(targets) if str(target).lower() == name.lower()),
        len(targets) + 1,
    )
    state_rank = {
        "missed": 0,
        "regressed": 1,
        "partially_repaired": 2,
        "repaired_same_session": 3,
        "untested": 4,
        "passed": 5,
    }.get(str(node.get("knowledge_state") or ""), 6)
    return (
        target_rank,
        0 if node.get("artifact_native") else 1,
        0 if node.get("active_misconception") else 1,
        0 if node.get("safety_critical") else 1,
        state_rank,
        name,
    )


def _learner_profile(conn: Any | None) -> dict[str, object]:
    if conn is None:
        return {}
    try:
        row = conn.execute("SELECT * FROM learner_profile WHERE id = 1").fetchone()
    except Exception:
        return {}
    if row is None:
        return {}
    import json

    def parsed(field: str, fallback: object) -> object:
        try:
            return json.loads(row[field] or "")
        except (TypeError, ValueError):
            return fallback

    return {
        "current_pgy": row["current_pgy"],
        "active_service": row["active_service"] or "",
        "expected_responsibilities": parsed("expected_responsibilities_json", []),
        "domain_expectations": parsed("domain_expectations_json", {}),
        "interpretation": (
            "PGY and service set expected responsibility only; observed concept-specific "
            "performance sets scaffolding and mastery."
        ),
    }


def _compact_anki(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, object] = {}
    for key in ("status", "macro_counts", "avoid_direct_quiz"):
        if value.get(key) not in (None, "", [], {}):
            result[key] = value[key]
    for key in ("atomic_focus", "atomic_scaffolds", "atomic_primes"):
        rows = _list(value.get(key))
        if rows:
            result[key] = rows[:2]
    return result


def build_tutor_state(
    brief: dict[str, Any],
    *,
    startup_meta: dict[str, Any],
    profile: str,
    session_id: str = "",
    conn: Any | None = None,
) -> dict[str, object]:
    """Build the routine, high-signal state shown to the tutoring agent."""
    plan = dict(brief.get("sequential_teaching_plan") or {})
    raw_targets = plan.get("target_concepts")
    targets = [str(item) for item in raw_targets] if isinstance(raw_targets, list) else []
    raw_map = _list(brief.get("knowledge_map"))
    ranked_map = sorted(raw_map, key=lambda item: _node_rank(item, targets))
    active_nodes = [_compact_node(item) for item in ranked_map[:ACTIVE_NODE_CAP]]
    active_target = active_nodes[0] if active_nodes else {}

    open_first = _list(brief.get("open_first"))
    recent_repairs = _list(brief.get("recent_repairs"))
    doc_priorities = _list(brief.get("teaching_priorities"))
    evidence_rows = doc_priorities or [*open_first, *recent_repairs]
    evidence: list[dict[str, object]] = []
    for item in evidence_rows[:EVIDENCE_CAP]:
        row: dict[str, object] = {
            key: item[key]
            for key in ("claim_state_id", "id", "source", "concept", "priority", "state", "next_action", "action")
            if item.get(key) not in (None, "", [], {})
        }
        trace = _compact_trace(item.get("memory_trace"))
        if trace:
            row["memory_trace"] = trace
        evidence.append(row)

    alignment = brief.get("artifact_alignment")
    artifact = dict(alignment) if isinstance(alignment, dict) else {}
    nearby = _list(brief.get("contextual_frontier"))[:NEARBY_NODE_CAP]
    nearby_nodes = [
        {
            key: item[key]
            for key in (
                "candidate_id",
                "concept",
                "relationship",
                "relevance_reason",
                "recommended_use",
                "source_surface",
                "score",
            )
            if item.get(key) not in (None, "", [], {})
        }
        for item in nearby
    ]

    interrupts = plan.get("interrupts") if isinstance(plan.get("interrupts"), dict) else {}
    decision_inputs = plan.get("decision_inputs") if isinstance(plan.get("decision_inputs"), dict) else {}
    phase = str(plan.get("current_phase") or plan.get("mode") or "orient")
    queue = targets[:QUEUE_CAP]
    map_omitted = max(0, len(raw_map) - len(active_nodes))
    declared_omitted = brief.get("knowledge_map_omitted")
    if isinstance(declared_omitted, dict):
        map_omitted += int(declared_omitted.get("count", 0) or 0)

    state: dict[str, object] = {
        "schema_version": TUTOR_STATE_VERSION,
        "session_id": session_id,
        "lifecycle": {
            "node": "teach",
            "allowed_next": ["teach", "paused", "close"],
        },
        "scope": {
            "profile": profile,
            "topic": startup_meta.get("resolved_topic") or startup_meta.get("requested_topic") or "",
            "doc_path": startup_meta.get("requested_doc") or "",
            "document_primary": profile == "doc",
        },
        "phase_controller": {
            "recommended_phase": phase,
            "mode": plan.get("mode") or "",
            "interrupts": interrupts or {},
            "decision_inputs": decision_inputs or {},
            "override_policy": (
                "Hard safety, active-gap, due-retention, and provenance constraints are binding. "
                "Otherwise the phase is a recommendation; a tutor override must be logged with reason."
            ),
        },
        "active_target": active_target,
        "target_queue": queue,
        "learner_evidence": evidence,
        "knowledge_map": {
            "status": brief.get("knowledge_map_status") or "",
            "provenance": brief.get("knowledge_map_provenance") or "",
            "total_nodes": len(raw_map) + int(
                declared_omitted.get("count", 0) if isinstance(declared_omitted, dict) else 0
            ),
            "active_nodes": active_nodes,
            "omitted_nodes": map_omitted,
            "drilldown": "Use node-recall for one selected inventory concept; use audit profile only for learner-model audit.",
        },
        "context_expansion": {
            "nearby_nodes": nearby_nodes,
            "policy": (
                "artifact core -> blocking prerequisite -> confuser/discriminator -> "
                "clinical or operative consequence -> one-hop transfer"
            ),
            "maximum_hops": 1,
            "second_hop_requires_named_bridge": True,
        },
        "learner_profile": _learner_profile(conn),
        "anki_advisory": _compact_anki(brief.get("anki_overlay")),
        "source_verification": {
            "verify_after_commitment": [
                "dose",
                "threshold",
                "timing",
                "reversal",
                "classification",
                "guideline-dependent conduct",
                "controversy",
            ],
        },
        "response_contract": {
            "first_turn": "one answerable clinical question without hints",
            "after_commitment": (
                "verdict -> preserved edge -> missing/false edge -> causal model -> "
                "clinical consequence -> nearest alternative -> compression rule -> near transfer"
            ),
        },
    }
    if artifact:
        state["artifact_alignment"] = artifact
    if brief.get("alignment_proposals"):
        state["alignment_proposals"] = _list(brief.get("alignment_proposals"))[:3]
    if brief.get("resolution_warning"):
        state["resolution_warning"] = brief["resolution_warning"]
        state["resolution_candidates"] = _list(brief.get("resolution_candidates"))[:3]
    return state


def tutor_state_payload(
    payload: dict[str, Any],
    *,
    startup_meta: dict[str, Any],
    profile: str,
    session_id: str = "",
    conn: Any | None = None,
) -> dict[str, object]:
    brief = payload.get("planning_brief")
    if not isinstance(brief, dict):
        brief = {}
    return {
        "startup_recall": startup_meta,
        "tutor_state": build_tutor_state(
            brief,
            startup_meta=startup_meta,
            profile=profile,
            session_id=session_id,
            conn=conn,
        ),
        "retrieval_guidance": {
            "policy": "just_in_time_tutor_state",
            "full_policy_computed_before_compaction": True,
            "pre_question_expansion_allowed": bool(startup_meta.get("routing_required")),
            "audit_profile_available": True,
        },
    }
