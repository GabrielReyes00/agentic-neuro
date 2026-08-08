from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import session_map
import study_memory
from turn_assessment import TurnAssessmentError, assess_turn


def _payload(*, key: str = "s:1", claims: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema_version": "turn_assessment_v1",
        "idempotency_key": key,
        "session_id": "s",
        "topic": "subarachnoid hemorrhage",
        "question": "Separate DCI from angiographic vasospasm and state why it matters.",
        "answer": "DCI is clinical deterioration or infarction; vasospasm is arterial narrowing.",
        "strict_telemetry": True,
        "claims": claims
        or [
            {
                "concept": "Delayed cerebral ischemia",
                "inventory_concept_id": "vasc.sah.dci",
                "assessment_status": "graded",
                "accuracy": 2,
                "tested_claim": "DCI is not synonymous with angiographic vasospasm.",
                "learner_claim": "DCI is clinical while vasospasm is angiographic.",
                "independence": "unaided",
                "reasoning_depth": "relational",
                "safety_impact": "high",
                "verification_status": "verified",
                "learning_operation": "discrimination",
                "confidence_observed": "high",
                "teaching_move": "initial_probe",
                "teaching_intervention": "Compressed the distinction into a clinical-versus-angiographic rule.",
            }
        ],
        "card_decision": {
            "decision": "skip_routine_correct",
            "rationale": "Correct relational answer without a new durable card-worthy gap.",
        },
    }


@pytest.fixture()
def memory_db(monkeypatch: pytest.MonkeyPatch):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        monkeypatch.setattr(session_map, "SESSIONS_DIR", root / "maps")
        conn = study_memory._get_db(root / "study.db")
        yield conn
        conn.close()


def test_typed_turn_is_multi_claim_atomic_and_idempotent(memory_db) -> None:
    study_memory.startup_recall(
        memory_db,
        topic="subarachnoid hemorrhage",
        profile="tutor",
        session_id="s",
    )
    claims = list(_payload()["claims"])
    claims.append(
        {
            "concept": "Cerebral vasospasm",
            "inventory_concept_id": "vasc.sah.vasospasm",
            "assessment_status": "graded",
            "accuracy": 1,
            "tested_claim": "Angiographic vasospasm is arterial narrowing and does not alone define DCI.",
            "learner_claim": "Vasospasm is narrowing.",
            "demonstrated_edge": "Correctly identified arterial narrowing.",
            "missing_edge": "Did not state that narrowing alone does not define clinical DCI.",
            "corrected_rule": "Separate angiographic narrowing from the clinical syndrome of DCI.",
            "clinical_consequence": "Treatment and outcome assessment cannot use vessel caliber alone.",
            "independence": "unaided",
            "reasoning_depth": "factual",
            "safety_impact": "high",
            "verification_status": "verified",
            "learning_operation": "discrimination",
            "confidence_observed": "medium",
            "teaching_move": "contrastive_drill",
            "teaching_intervention": "Contrasted radiographic narrowing with clinical deterioration and infarction.",
        }
    )
    payload = _payload(claims=claims)
    first = assess_turn(memory_db, payload, engine=study_memory)
    replay = assess_turn(memory_db, payload, engine=study_memory)

    assert first["exchange_id"] == replay["exchange_id"]
    assert replay["idempotent_replay"] is True
    assert memory_db.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0] == 1
    assert memory_db.execute("SELECT COUNT(*) FROM claim_results").fetchone()[0] == 2
    assert memory_db.execute("SELECT COUNT(*) FROM claim_assessments").fetchone()[0] == 2
    assert memory_db.execute("SELECT COUNT(*) FROM turn_assessments").fetchone()[0] == 1
    assert memory_db.execute("SELECT COUNT(*) FROM anki_card_decisions").fetchone()[0] == 1
    assert study_memory.database_health(memory_db)["ok"] is True


def test_pending_adjudication_preserves_uncertainty_without_learner_state(memory_db) -> None:
    pending = [
        {
            "concept": "Nimodipine dosing",
            "inventory_concept_id": "vasc.sah.nimodipine",
            "assessment_status": "pending_adjudication",
            "adjudication_reason": "The stated dose requires source confirmation.",
            "source_needed": "Current primary aneurysmal SAH guidance.",
            "independence": "unaided",
            "reasoning_depth": "factual",
            "safety_impact": "critical",
            "verification_status": "unverified",
        }
    ]
    payload = _payload(key="s:pending", claims=pending)
    payload["card_decision"] = {
        "decision": "defer_unavailable",
        "rationale": "Do not create a card until the dose is adjudicated.",
    }
    result = assess_turn(memory_db, payload, engine=study_memory)

    assert result["claim_results"] == []
    assert len(result["pending_adjudication"]) == 1
    assert memory_db.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0] == 1
    assert memory_db.execute("SELECT COUNT(*) FROM claim_results").fetchone()[0] == 0
    assert memory_db.execute("SELECT COUNT(*) FROM claim_state").fetchone()[0] == 0
    row = memory_db.execute("SELECT assessment_status, accuracy FROM claim_assessments").fetchone()
    assert row["assessment_status"] == "pending_adjudication"
    assert row["accuracy"] is None


def test_invalid_claim_rejects_before_any_write(memory_db) -> None:
    payload = _payload()
    payload["claims"] = [*payload["claims"], {"concept": "Unsafe incomplete claim", "accuracy": 2}]
    with pytest.raises(TurnAssessmentError):
        assess_turn(memory_db, payload, engine=study_memory)
    assert memory_db.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0] == 0
    assert memory_db.execute("SELECT COUNT(*) FROM turn_assessments").fetchone()[0] == 0


def test_session_map_failure_does_not_roll_back_committed_database(memory_db) -> None:
    with mock.patch.object(session_map, "write", side_effect=OSError("disk full")):
        result = assess_turn(memory_db, _payload(), engine=study_memory)
    assert result["session_map"]["status"] == "deferred_rebuild"
    assert memory_db.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0] == 1
    assert memory_db.execute("SELECT COUNT(*) FROM claim_results").fetchone()[0] == 1


def test_tutor_profile_is_bounded_and_runtime_lifecycle_closes(memory_db) -> None:
    started = json.loads(
        study_memory.startup_recall(
            memory_db,
            topic="subarachnoid hemorrhage",
            profile="tutor",
            session_id="s",
        )
    )
    assert set(started) == {"startup_recall", "tutor_state", "retrieval_guidance"}
    assert started["tutor_state"]["schema_version"] == "tutor_state_v1"
    assert len(started["tutor_state"]["knowledge_map"]["active_nodes"]) <= 8
    assert memory_db.execute(
        "SELECT lifecycle_node FROM study_runtime_sessions WHERE session_id='s'"
    ).fetchone()[0] == "teach"

    assess_turn(memory_db, _payload(), engine=study_memory)
    integrity = study_memory.study_session_integrity(memory_db, session_id="s")
    assert integrity["ok"] is True
    closed = study_memory.close_session_from_payload(
        memory_db,
        {
            "session_id": "s",
            "summary": "Correctly discriminated DCI from angiographic vasospasm.",
            "next_strategy": "Retest vasc.sah.dci under a changed clinical frame.",
            "stats": {"priority_inventory_ids": ["vasc.sah.dci"]},
        },
    )
    assert closed["ok"] is True
    assert memory_db.execute(
        "SELECT lifecycle_node FROM study_runtime_sessions WHERE session_id='s'"
    ).fetchone()[0] == "done"
    assert session_map.load("s") is None


def test_study_review_rejects_service_local_memory_boundary(memory_db) -> None:
    with pytest.raises(ValueError, match="provenance-isolated"):
        study_memory.start_session_from_payload(
            memory_db,
            {
                "session_id": "service-s",
                "mode": "service",
                "topic": "vascular",
                "service": "vascular",
            },
        )
    assert memory_db.execute(
        "SELECT COUNT(*) FROM study_runtime_sessions WHERE session_id='service-s'"
    ).fetchone()[0] == 0
