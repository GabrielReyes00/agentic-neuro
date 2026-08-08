"""Typed, retry-safe, multi-claim learner-turn assessment.

This is the canonical write path for study-review.  Legacy ``log-answer`` stays
available for compatibility, while this module commits the raw exchange,
claim-level learner state, grading dimensions, policy event, and Anki decision
in one SQLite transaction.  The filesystem session map is updated only after
that transaction commits and is therefore always a rebuildable projection.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "turn_assessment_v1"
VALID_STATUS = frozenset({"graded", "pending_adjudication"})
VALID_INDEPENDENCE = frozenset({"unaided", "prompted", "after_hint", "after_teaching", "self_corrected"})
VALID_REASONING_DEPTH = frozenset({"unknown", "factual", "relational", "causal", "transfer"})
VALID_SAFETY_IMPACT = frozenset({"none", "low", "moderate", "high", "critical"})
VALID_VERIFICATION = frozenset({"not_required", "required", "verified", "unverified", "conflicting"})


class TurnAssessmentError(ValueError):
    """Typed assessment payload is invalid or unsafe to persist."""


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise TurnAssessmentError(f"missing required field: {key}")
    return value


def _optional_text(payload: dict[str, Any], key: str) -> str:
    return str(payload.get(key) or "").strip()


def _validate_claim(raw: object, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TurnAssessmentError(f"claims[{index}] must be an object")
    claim = dict(raw)
    claim["concept"] = _required_text(claim, "concept")
    status = _optional_text(claim, "assessment_status") or "graded"
    if status not in VALID_STATUS:
        raise TurnAssessmentError(f"claims[{index}].assessment_status is invalid: {status}")
    claim["assessment_status"] = status
    if status == "graded":
        accuracy = claim.get("accuracy")
        if not isinstance(accuracy, int) or accuracy not in {0, 1, 2}:
            raise TurnAssessmentError(f"claims[{index}].accuracy must be 0, 1, or 2")
        claim["tested_claim"] = _required_text(claim, "tested_claim")
        independence = _optional_text(claim, "independence") or _optional_text(claim, "answer_mode")
        if independence not in VALID_INDEPENDENCE:
            raise TurnAssessmentError(
                f"claims[{index}].independence must be one of {sorted(VALID_INDEPENDENCE)}"
            )
        claim["independence"] = independence
        reasoning_depth = _optional_text(claim, "reasoning_depth") or "unknown"
        if reasoning_depth not in VALID_REASONING_DEPTH:
            raise TurnAssessmentError(
                f"claims[{index}].reasoning_depth must be one of {sorted(VALID_REASONING_DEPTH)}"
            )
        claim["reasoning_depth"] = reasoning_depth
        safety_impact = _optional_text(claim, "safety_impact") or "none"
        if safety_impact not in VALID_SAFETY_IMPACT:
            raise TurnAssessmentError(
                f"claims[{index}].safety_impact must be one of {sorted(VALID_SAFETY_IMPACT)}"
            )
        claim["safety_impact"] = safety_impact
        verification = _optional_text(claim, "verification_status") or "not_required"
        if verification not in VALID_VERIFICATION:
            raise TurnAssessmentError(
                f"claims[{index}].verification_status must be one of {sorted(VALID_VERIFICATION)}"
            )
        claim["verification_status"] = verification
        if verification == "required":
            raise TurnAssessmentError(
                f"claims[{index}] requires source verification before graded persistence; "
                "use unverified only when the unresolved uncertainty is explicitly preserved"
            )
    else:
        claim["accuracy"] = None
        claim["independence"] = _optional_text(claim, "independence")
        claim["reasoning_depth"] = _optional_text(claim, "reasoning_depth") or "unknown"
        claim["safety_impact"] = _optional_text(claim, "safety_impact") or "none"
        claim["verification_status"] = _optional_text(claim, "verification_status") or "unverified"
        if not _optional_text(claim, "adjudication_reason"):
            raise TurnAssessmentError(
                f"claims[{index}].adjudication_reason is required when assessment_status=pending_adjudication"
            )
    return claim


def validate_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TurnAssessmentError("turn assessment must be a JSON object")
    data = dict(payload)
    version = _optional_text(data, "schema_version") or SCHEMA_VERSION
    if version != SCHEMA_VERSION:
        raise TurnAssessmentError(f"unsupported turn assessment schema: {version}")
    data["schema_version"] = version
    data["idempotency_key"] = _required_text(data, "idempotency_key")
    data["session_id"] = _required_text(data, "session_id")
    data["topic"] = _required_text(data, "topic")
    data["question"] = _required_text(data, "question")
    data["answer"] = _required_text(data, "answer")
    raw_claims = data.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise TurnAssessmentError("claims must be a non-empty list")
    data["claims"] = [_validate_claim(raw, idx) for idx, raw in enumerate(raw_claims)]
    decision = data.get("card_decision")
    if not isinstance(decision, dict):
        raise TurnAssessmentError("card_decision is required for every assessed learner turn")
    if not _optional_text(decision, "decision"):
        raise TurnAssessmentError("card_decision.decision is required")
    return data


def _runtime_row(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM study_runtime_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()


def _initial_session_map(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    topic: str,
    doc_path: str,
) -> dict[str, Any] | None:
    import session_map

    existing = session_map.load(session_id)
    if existing is not None:
        return existing
    projection = session_map.build_inventory_projection(
        topic=topic,
        doc_path=doc_path,
        memory_db=_main_db_path(conn),
    )
    if not projection:
        return None
    return session_map.create_from_projection(
        projection,
        session_id=session_id,
        profile="doc" if doc_path else "memory",
        doc_path=doc_path,
        learner_topics=[topic],
    )


def _main_db_path(conn: sqlite3.Connection):
    from pathlib import Path

    for row in conn.execute("PRAGMA database_list").fetchall():
        if str(row[1]) == "main" and str(row[2] or ""):
            return Path(str(row[2]))
    raise TurnAssessmentError("learner database has no resolvable main path")


def _insert_exchange(
    conn: sqlite3.Connection,
    *,
    engine: Any,
    payload: dict[str, Any],
    topic_id: int,
    concept_id: int,
    now: str,
) -> int:
    session_id = str(payload["session_id"])
    turn = payload.get("turn")
    if turn is None:
        turn = int(
            conn.execute(
                "SELECT COUNT(*) FROM exchanges WHERE session_id = ?", (session_id,)
            ).fetchone()[0]
        ) + 1
    source = {
        "assessment_schema": SCHEMA_VERSION,
        "claim_count": len(payload["claims"]),
        "source_sensitive": any(
            str(claim.get("verification_status") or "") in {"verified", "unverified", "conflicting"}
            for claim in payload["claims"]
        ),
    }
    conn.execute(
        """INSERT INTO exchanges
           (session_id, ts, turn, topic_id, concept_id, raw_question, raw_answer,
            doc_path, skill, source_json, origin, rotation_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'study-review', ?, 'assessed', NULL)""",
        (
            session_id,
            now,
            int(turn),
            topic_id,
            concept_id,
            str(payload["question"]),
            str(payload["answer"]),
            _optional_text(payload, "doc_path"),
            json.dumps(source, sort_keys=True),
        ),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def _policy_payload(plan: dict[str, Any]) -> dict[str, object]:
    keep = (
        "mode",
        "current_phase",
        "interrupts",
        "target_concepts",
        "pedagogical_directives",
        "socratic_choice_directives",
        "teaching_priority",
        "artifact_native_targets",
        "map_context_targets",
        "decision_inputs",
        "orient_menu",
        "orient_skip",
        "probe_feedback",
    )
    return {key: plan[key] for key in keep if plan.get(key) not in (None, "", [], {})}


def assess_turn(
    conn: sqlite3.Connection,
    payload: object,
    *,
    engine: Any,
) -> dict[str, object]:
    """Persist one learner response and all independently assessed claims."""
    data = validate_payload(payload)
    existing = conn.execute(
        "SELECT result_json FROM turn_assessments WHERE idempotency_key = ?",
        (data["idempotency_key"],),
    ).fetchone()
    if existing is not None:
        result = json.loads(existing["result_json"] or "{}")
        result["idempotent_replay"] = True
        return result

    runtime = _runtime_row(conn, str(data["session_id"]))
    if runtime is not None and str(runtime["lifecycle_node"]) not in {"prepare", "teach"}:
        raise TurnAssessmentError(
            f"session {data['session_id']} is in lifecycle node {runtime['lifecycle_node']!r}, not teach"
        )

    doc_path = _optional_text(data, "doc_path")
    session_data = _initial_session_map(
        conn,
        session_id=str(data["session_id"]),
        topic=str(data["topic"]),
        doc_path=doc_path,
    )
    now = _optional_text(data, "timestamp") or datetime.now(timezone.utc).isoformat()
    resolution = engine.resolve_topic(conn, str(data["topic"]), doc_path)
    topic_id = engine._ensure_topic(conn, resolution, doc_path)

    claim_results: list[dict[str, object]] = []
    pending: list[dict[str, object]] = []
    plan: dict[str, Any] = {}
    progress: dict[str, int] = {}
    map_warning = ""

    first_claim = data["claims"][0]
    first_concept_id = engine._ensure_concept(
        conn,
        topic_id,
        resolution.slug,
        str(first_claim["concept"]),
        str(data["question"]),
        _optional_text(first_claim, "corrected_rule") or _optional_text(first_claim, "correction"),
        _optional_text(first_claim, "inventory_concept_id"),
    )

    try:
        with conn:
            engine._ensure_session(
                conn,
                str(data["session_id"]),
                now,
                "study-review",
                topic_id,
                doc_path,
            )
            exchange_id = _insert_exchange(
                conn,
                engine=engine,
                payload=data,
                topic_id=topic_id,
                concept_id=first_concept_id,
                now=now,
            )

            last_result_id: int | None = None
            for idx, claim in enumerate(data["claims"]):
                concept = str(claim["concept"])
                inventory_id = _optional_text(claim, "inventory_concept_id")
                concept_id = (
                    first_concept_id
                    if idx == 0
                    else engine._ensure_concept(
                        conn,
                        topic_id,
                        resolution.slug,
                        concept,
                        str(data["question"]),
                        _optional_text(claim, "corrected_rule") or _optional_text(claim, "correction"),
                        inventory_id,
                    )
                )
                if claim["assessment_status"] == "pending_adjudication":
                    evidence = {
                        "adjudication_reason": _optional_text(claim, "adjudication_reason"),
                        "source_needed": _optional_text(claim, "source_needed"),
                    }
                    conn.execute(
                        """INSERT INTO claim_assessments
                           (exchange_id, claim_result_id, inventory_concept_id, concept,
                            assessment_status, accuracy, independence, reasoning_depth,
                            safety_impact, operation_demonstrated, verification_status,
                            evidence_json, created_at)
                           VALUES (?, NULL, ?, ?, 'pending_adjudication', NULL, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            exchange_id,
                            inventory_id,
                            concept,
                            _optional_text(claim, "independence"),
                            _optional_text(claim, "reasoning_depth"),
                            _optional_text(claim, "safety_impact"),
                            _optional_text(claim, "operation_demonstrated"),
                            _optional_text(claim, "verification_status"),
                            json.dumps(evidence, sort_keys=True),
                            now,
                        ),
                    )
                    pending.append({"concept": concept, **evidence})
                    continue

                score = int(claim["accuracy"])
                answer_mode = _optional_text(claim, "answer_mode") or _optional_text(claim, "independence")
                teaching_move = _optional_text(claim, "teaching_move") or "other"
                confidence = _optional_text(claim, "confidence_observed") or "medium"
                # The typed API records the clinically meaningful edges instead
                # of forcing callers to duplicate them as legacy telemetry.  A
                # false stated belief is conceptual confusion; an otherwise
                # incomplete answer is an omission.  Explicit callers can still
                # choose a more specific controlled gap type.
                error_type = _optional_text(claim, "error_type")
                if score < 2 and not error_type:
                    error_type = (
                        "conceptual_confusion"
                        if _optional_text(claim, "misconception")
                        else "omission"
                    )
                if bool(data.get("strict_telemetry", True)):
                    engine._validate_strict_telemetry(
                        concept=concept,
                        score=score,
                        error_type=error_type,
                        misconception=_optional_text(claim, "misconception"),
                        demonstrated_edge=_optional_text(claim, "demonstrated_edge"),
                        missing_edge=_optional_text(claim, "missing_edge"),
                        corrected_rule=_optional_text(claim, "corrected_rule"),
                        correction=_optional_text(claim, "correction"),
                        tested_claim=_optional_text(claim, "tested_claim"),
                        answer_mode=answer_mode,
                        confidence_observed=confidence,
                        teaching_move=teaching_move,
                    )
                operation = engine._learning_operation(
                    concept,
                    _optional_text(claim, "tested_claim"),
                    _optional_text(claim, "learning_operation"),
                )
                source = {
                    "teaching_intent": _optional_text(claim, "teaching_intent"),
                    "expected_answer_edge": _optional_text(claim, "expected_answer_edge"),
                    "coverage_role": _optional_text(claim, "coverage_role"),
                    "source_section": _optional_text(claim, "source_section"),
                    "source_anchor": _optional_text(claim, "source_anchor"),
                    "curriculum_unit": _optional_text(claim, "curriculum_unit"),
                    "answer_mode": answer_mode,
                    "confidence_observed": confidence,
                    "teaching_move": teaching_move,
                    "cognitive_op": operation,
                    "cognitive_op_source": "explicit" if _optional_text(claim, "learning_operation") else "inferred",
                    "reasoning_depth": _optional_text(claim, "reasoning_depth"),
                    "safety_impact": _optional_text(claim, "safety_impact"),
                    "verification_status": _optional_text(claim, "verification_status"),
                }
                result_id = engine._log_claim_result(
                    conn,
                    exchange_id=exchange_id,
                    session_id=str(data["session_id"]),
                    topic_id=topic_id,
                    concept_id=concept_id,
                    topic_slug=resolution.slug,
                    concept=concept,
                    score=score,
                    error_type=error_type,
                    answer=str(data["answer"]),
                    correction=_optional_text(claim, "correction"),
                    misconception=_optional_text(claim, "misconception"),
                    tested_claim=_optional_text(claim, "tested_claim"),
                    learner_claim=_optional_text(claim, "learner_claim"),
                    demonstrated_edge=_optional_text(claim, "demonstrated_edge"),
                    missing_edge=_optional_text(claim, "missing_edge"),
                    corrected_rule=_optional_text(claim, "corrected_rule"),
                    clinical_consequence=_optional_text(claim, "clinical_consequence"),
                    retest_prompt_shape=_optional_text(claim, "retest_prompt_shape"),
                    teaching_intervention=_optional_text(claim, "teaching_intervention"),
                    learning_operation=operation,
                    agent_signal={key: str(value) for key, value in source.items() if value not in (None, "")},
                    now=now,
                    agent_priority=_optional_text(claim, "priority"),
                    match_claim_state_id=(
                        int(claim["match_claim_state_id"])
                        if claim.get("match_claim_state_id") is not None
                        else None
                    ),
                    force_new_claim=bool(claim.get("new_claim")),
                    repairs_claim_state_ids=tuple(int(item) for item in claim.get("repairs_claim_state_ids", [])),
                    inventory_concept_id=inventory_id,
                )
                last_result_id = result_id
                conn.execute(
                    """INSERT INTO claim_assessments
                       (exchange_id, claim_result_id, inventory_concept_id, concept,
                        assessment_status, accuracy, independence, reasoning_depth,
                        safety_impact, operation_demonstrated, verification_status,
                        evidence_json, created_at)
                       VALUES (?, ?, ?, ?, 'graded', ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        exchange_id,
                        result_id,
                        inventory_id,
                        concept,
                        score,
                        _optional_text(claim, "independence"),
                        _optional_text(claim, "reasoning_depth"),
                        _optional_text(claim, "safety_impact"),
                        _optional_text(claim, "operation_demonstrated") or operation,
                        _optional_text(claim, "verification_status"),
                        json.dumps(
                            {
                                "demonstrated_edge": _optional_text(claim, "demonstrated_edge"),
                                "missing_edge": _optional_text(claim, "missing_edge"),
                                "corrected_rule": _optional_text(claim, "corrected_rule"),
                            },
                            sort_keys=True,
                        ),
                        now,
                    ),
                )
                if inventory_id:
                    import session_map

                    session_map.promote_inventory_binding(
                        conn,
                        learner_concept_id=concept_id,
                        inventory_concept_id=inventory_id,
                    )
                claim_results.append(
                    {
                        "claim_result_id": result_id,
                        "concept": concept,
                        "inventory_concept_id": inventory_id,
                        "accuracy": score,
                        "reasoning_depth": _optional_text(claim, "reasoning_depth"),
                    }
                )

                if session_data is not None:
                    import session_map

                    gap_type = engine._normalize_gap_type(
                        _optional_text(claim, "error_type"),
                        score,
                        _optional_text(claim, "missing_edge"),
                    )
                    session_data, _ = session_map.patch_after_log(
                        session_data,
                        inventory_concept_id=inventory_id,
                        concept_text=concept,
                        correct=score,
                        exchange_id=exchange_id,
                        coverage_role=_optional_text(claim, "coverage_role"),
                        learner_concept_id=concept_id,
                        cognitive_op=operation,
                        gap_type=gap_type,
                        observed_at=now,
                    )

            if session_data is not None:
                import session_map

                plan = session_map.compute_policy_from_session(
                    session_data,
                    conn,
                    topic_id=topic_id,
                    topic_slug=resolution.slug,
                )
                session_data["last_plan"] = plan
                progress = session_map.session_progress(session_data)
            else:
                plan = engine._current_policy_for_topic(
                    conn, topic_id=topic_id, topic_slug=resolution.slug
                )

            if plan:
                engine._record_policy_event(
                    conn,
                    session_id=str(data["session_id"]),
                    event_type="turn",
                    topic_id=topic_id,
                    plan=plan,
                    claim_result_id=last_result_id,
                    probe_meta={
                        "claim_result_ids": [row["claim_result_id"] for row in claim_results],
                        "graded_claims": len(claim_results),
                        "pending_claims": len(pending),
                    },
                    now=now,
                )

            decision = data["card_decision"]
            from card_decisions import record_anki_card_decision

            card = record_anki_card_decision(
                conn,
                session_id=str(data["session_id"]),
                exchange_id=exchange_id,
                decision=_required_text(decision, "decision"),
                rationale=_optional_text(decision, "rationale"),
                commit=False,
            )
            conn.execute(
                """INSERT INTO study_runtime_sessions
                   (session_id, lifecycle_node, profile, topic_id, doc_path,
                    tutor_state_version, started_at, updated_at)
                   VALUES (?, 'teach', ?, ?, ?, 'tutor_state_v1', ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                     lifecycle_node='teach', profile=excluded.profile,
                     topic_id=excluded.topic_id, doc_path=excluded.doc_path,
                     updated_at=excluded.updated_at""",
                (
                    str(data["session_id"]),
                    "doc" if doc_path else "memory",
                    topic_id,
                    doc_path,
                    now,
                    now,
                ),
            )
            result: dict[str, object] = {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "session_id": data["session_id"],
                "exchange_id": exchange_id,
                "claim_results": claim_results,
                "pending_adjudication": pending,
                "card_decision": card,
                "policy": _policy_payload(plan),
                "session_progress": progress,
                "idempotent_replay": False,
            }
            conn.execute(
                """INSERT INTO turn_assessments
                   (idempotency_key, session_id, exchange_id, schema_version,
                    request_json, result_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["idempotency_key"],
                    data["session_id"],
                    exchange_id,
                    SCHEMA_VERSION,
                    json.dumps(data, sort_keys=True, separators=(",", ":")),
                    json.dumps(result, sort_keys=True, separators=(",", ":")),
                    now,
                ),
            )
    except sqlite3.IntegrityError as exc:
        replay = conn.execute(
            "SELECT result_json FROM turn_assessments WHERE idempotency_key = ?",
            (data["idempotency_key"],),
        ).fetchone()
        if replay is not None:
            result = json.loads(replay["result_json"] or "{}")
            result["idempotent_replay"] = True
            return result
        raise TurnAssessmentError(f"turn assessment transaction failed: {exc}") from exc

    if session_data is not None:
        try:
            import session_map

            session_map.write(str(data["session_id"]), session_data)
        except Exception as exc:  # DB is authoritative; a later startup can rebuild.
            map_warning = f"session map deferred rebuild: {exc}"
    result["session_map"] = {
        "status": "committed_projection" if not map_warning else "deferred_rebuild",
        "warning": map_warning,
    }
    return result
