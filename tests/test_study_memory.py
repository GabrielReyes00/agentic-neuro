from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import study_memory
from reference_graph import context_graph_focus_for_summary, load_reference_graph_payload


class StudyMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.memory_path = Path(self.tmp.name) / "study_memory.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _memory_conn(self) -> sqlite3.Connection:
        return study_memory._get_db(self.memory_path)

    def _log_scaffolds(self, conn: sqlite3.Connection, topic: str, count: int) -> None:
        for idx in range(count):
            study_memory.log_answer(
                conn,
                session_id=f"session-scaffold-{topic}-{idx}",
                topic=topic,
                concept=f"scaffold concept {idx}",
                question=f"Scaffold check {idx}?",
                answer="correct",
                correct=2,
                tested_claim=f"{topic} durable scaffold claim {idx}.",
                learner_claim="Correct.",
                corrected_rule="Durable.",
            )

    def test_partial_answer_creates_claim_state_and_retrieval_card(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="session-1",
                topic="hypertension management",
                concept="sah vasospasm norepinephrine units",
                question="What norepi dose units?",
                answer="0.05 mcg/kg/hr",
                correct=1,
                correction="Norepinephrine starts around 0.05-0.1 mcg/kg/min.",
                error_type="numerical_recall",
                tested_claim="Norepinephrine for SAH vasospasm is dosed in mcg/kg/min.",
                learner_claim="Used mcg/kg/hr.",
                missing_edge="norepinephrine unit mcg/kg/min",
                corrected_rule="Use mcg/kg/min, not mcg/kg/hr.",
                clinical_consequence="Wrong unit underdoses pressor support.",
                retest_prompt_shape="Ask for norepinephrine starting dose and units in SAH DCI.",
            )
            state = conn.execute(
                """SELECT cs.state, cs.priority, cs.reason, cr.score
                   FROM claim_state cs
                   JOIN claim_results cr ON cr.id = cs.last_result_id"""
            ).fetchone()
            self.assertEqual(state["state"], "partially_repaired")
            self.assertEqual(state["priority"], "urgent")
            self.assertIn("mcg/kg/min", state["reason"])
            self.assertEqual(state["score"], 1)
            summary = study_memory.retrieval_summary(conn, topic="hypertension management", limit=2)
            self.assertIn("must_retest", summary)
            self.assertIn("SAH DCI", summary)
        finally:
            conn.close()

    def test_quick_answer_logs_evidence_without_claim_state_or_curation_count(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="quick-1",
                topic="induced hypertension vasospasm",
                concept="pressor choice for induced hypertension",
                question="Which pressor is best for induced hypertension and why?",
                answer="Norepinephrine is usually preferred because it raises MAP with predictable alpha effect and less tachycardia than dopamine.",
                correct=2,
                skill="quick-answer",
                tested_claim="Norepinephrine is the default pressor for induced hypertension in DCI when cardiac profile allows.",
                learner_claim="Question-only exchange; no learner performance assessed.",
                learning_operation="mechanism",
                teaching_intent="quick_answer_reference",
                coverage_role="synthesis",
                answer_mode="after_teaching",
            )
            result = study_memory.end_session(
                conn,
                session_id="quick-1",
                summary="Answered a quick reference question about pressor selection for induced hypertension.",
                next_strategy="If revisited, test norepinephrine versus phenylephrine and dopamine in DCI vignettes.",
            )

            self.assertFalse(result["newly_counted"])
            self.assertTrue(result["excluded_from_curation_count"])
            self.assertEqual(result["curation"]["sessions_since_last_curation"], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_results").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_state").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM retrieval_cards").fetchone()[0], 0)
        finally:
            conn.close()

    def test_artifact_anchor_logs_discovery_without_claim_state_or_curation_count(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="report-1",
                topic="cerebral vasospasm management",
                concept="report coverage anchor",
                question="What is covered in the Cerebral Vasospasm report?",
                answer="Diagnosis, monitoring, nimodipine, induced hypertension, and endovascular rescue.",
                correct=2,
                skill="generate-report",
                doc_path="Reports/Cerebral Vasospasm Management.md",
            )
            result = study_memory.end_session(
                conn,
                session_id="report-1",
                summary="Cerebral vasospasm report written.",
                next_strategy="Use study-review to test vasospasm diagnosis and treatment sequencing.",
            )

            self.assertTrue(result["artifact_anchor"])
            self.assertTrue(result["excluded_from_curation_count"])
            self.assertFalse(result["newly_counted"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_results").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_state").fetchone()[0], 0)
            rows = conn.execute("SELECT card_type, summary FROM retrieval_cards").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["card_type"], "artifact_anchor")
            self.assertIn("report written", rows[0]["summary"])
        finally:
            conn.close()

    def test_brain_dump_is_artifact_anchor_until_later_review_tests_learning(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="brain-dump-1",
                topic="evd transport management",
                concept="brain dump artifact anchor",
                question="What service teaching was captured for EVD transport management?",
                answer="Captured a de-identified service lesson about drain management during transport.",
                correct=2,
                skill="brain-dump",
                doc_path="Brain Dumps/EVD Transport Management.md",
            )
            anchor_result = study_memory.end_session(
                conn,
                session_id="brain-dump-1",
                summary="De-identified EVD transport brain dump written.",
                next_strategy="Use study-review on Brain Dumps/EVD Transport Management.md to test pressure-gradient reasoning.",
            )

            self.assertTrue(anchor_result["artifact_anchor"])
            self.assertTrue(anchor_result["excluded_from_curation_count"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_results").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_state").fetchone()[0], 0)

            study_memory.log_answer(
                conn,
                session_id="review-brain-dump-1",
                topic="evd transport management",
                concept="pressure gradient transport risk",
                question="What mechanism makes uncontrolled CSF drainage hazardous during transport?",
                answer="I am not sure.",
                correct=0,
                correction="Rapid compartment pressure shifts can worsen tissue displacement risk.",
                error_type="reasoning_gap",
                skill="study-review",
                doc_path="Brain Dumps/EVD Transport Management.md",
                tested_claim="Uncontrolled CSF drainage can create harmful pressure shifts during transport.",
                learner_claim="Could not explain the mechanism.",
                missing_edge="pressure gradient mechanism",
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_results").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_state").fetchone()[0], 1)
        finally:
            conn.close()

    def test_artifact_anchor_does_not_compete_with_learning_handoff_retrieval(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="report-visibility",
                topic="evd management",
                concept="report coverage anchor",
                question="What is covered in the report?",
                answer="EVD management.",
                correct=2,
                skill="generate-report",
                doc_path="Reports/EVD Management in the ICU.md",
            )
            study_memory.end_session(
                conn,
                session_id="report-visibility",
                summary="Generated EVD report.",
                next_strategy="Review the EVD report.",
            )
            study_memory.log_answer(
                conn,
                session_id="review-visibility",
                topic="evd management",
                concept="evd leveling",
                question="Where do you level the EVD?",
                answer="Tragus.",
                correct=2,
                tested_claim="Level the EVD at the tragus.",
                doc_path="Reports/EVD Management in the ICU.md",
            )
            study_memory.end_session(
                conn,
                session_id="review-visibility",
                summary="Reviewed EVD leveling.",
                next_strategy="Retest leveling after transport.",
            )
            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="evd management",
                    include_model=True,
                )
            )
            handoffs = [card for card in payload["cards"] if card["type"] == "session_handoff"]
            self.assertEqual(len(handoffs), 1)
            self.assertEqual(handoffs[0]["summary"], "Reviewed EVD leveling.")
            self.assertNotIn("artifact_anchor", payload["counts"])
            self.assertFalse(any(item["type"] == "artifact_review_anchor" for item in payload["shadow_queue"]))
        finally:
            conn.close()

    def test_correct_after_gap_marks_repaired_same_session(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="session-2",
                topic="hypertension management",
                concept="icp safe antihypertensives",
                question="Why avoid nitroprusside?",
                answer="Maybe venodilation helps.",
                correct=0,
                correction="Nitroprusside vasodilates cerebral vessels and raises CBV/ICP.",
                error_type="conceptual_confusion",
                tested_claim="Nitroprusside and hydralazine raise ICP through cerebral vasodilation.",
                missing_edge="cerebral vasodilation raises cerebral blood volume and ICP",
            )
            study_memory.log_answer(
                conn,
                session_id="session-2",
                topic="hypertension management",
                concept="icp safe antihypertensives",
                question="Which agents are acceptable?",
                answer="Nicardipine and labetalol; avoid hydralazine and nitroprusside.",
                correct=2,
                tested_claim="Nitroprusside and hydralazine raise ICP through cerebral vasodilation.",
                learner_claim="Correctly separated acceptable and avoided agents.",
                corrected_rule="Use nicardipine/labetalol; avoid hydralazine/nitroprusside in ICP risk.",
            )
            state = conn.execute("SELECT state FROM claim_state").fetchone()
            self.assertEqual(state["state"], "repaired_same_session")
            events = [r["event_type"] for r in conn.execute("SELECT event_type FROM state_events ORDER BY id")]
            self.assertEqual(events, ["missed", "repaired"])
            summary = study_memory.retrieval_summary(conn, topic="hypertension management", limit=3)
            self.assertIn("recent_repair", summary)
            self.assertIn("delayed retention", summary)
        finally:
            conn.close()

    def test_same_claim_across_concept_labels_updates_one_state(self) -> None:
        conn = self._memory_conn()
        try:
            claim = "Secured SAH DCI uses MAP +20-40 and norepinephrine mcg/kg/min."
            study_memory.log_answer(
                conn,
                session_id="session-claim",
                topic="hypertension management",
                concept="sah vasospasm norepinephrine units",
                question="Dose units?",
                answer="mcg/kg/hr",
                correct=1,
                tested_claim=claim,
                missing_edge="norepinephrine unit mcg/kg/min",
                corrected_rule="Use mcg/kg/min.",
            )
            study_memory.log_answer(
                conn,
                session_id="session-claim",
                topic="hypertension management",
                concept="sah dci induced hypertension pressor order",
                question="Full order?",
                answer="MAP +20-40, norepi 0.05-0.1 mcg/kg/min.",
                correct=2,
                tested_claim=claim,
                learner_claim="Correctly gave MAP and norepinephrine units.",
                corrected_rule="Use MAP +20-40 and norepinephrine mcg/kg/min.",
            )
            rows = conn.execute("SELECT state, priority FROM claim_state").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["state"], "repaired_same_session")
            self.assertEqual(rows[0]["priority"], "medium")
            summary = json.loads(study_memory.retrieval_summary(conn, topic="hypertension management", limit=5))
            card_types = [card["type"] for card in summary["cards"]]
            self.assertIn("recent_repair", card_types)
            self.assertNotIn("must_retest", card_types)
        finally:
            conn.close()

    def test_near_duplicate_claim_uses_existing_claim_state(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="session-near-dup",
                topic="hypertension management",
                concept="sah dci induced hypertension",
                question="What is the MAP and pressor strategy?",
                answer="MAP +20-40 with norepi.",
                correct=2,
                tested_claim="Symptomatic SAH vasospasm/DCI should be treated with induced hypertension to MAP 20-40 above baseline using norepinephrine, dosed in mcg/kg/min.",
                corrected_rule="Use norepinephrine 0.05-0.1 mcg/kg/min to raise MAP 20-40 above baseline.",
                expected_answer_edge="MAP +20-40 over baseline; norepinephrine 0.05-0.1 mcg/kg/min",
            )
            study_memory.log_answer(
                conn,
                session_id="session-near-dup",
                topic="hypertension management",
                concept="secured sah dci induced hypertension norepinephrine",
                question="Retest the order.",
                answer="Raise MAP 20-40 with norepi 0.05-0.1 mcg/kg/min.",
                correct=2,
                tested_claim="Symptomatic secured SAH vasospasm/DCI should be treated with induced hypertension to MAP 20-40 above baseline using norepinephrine dosed in mcg/kg/min, titrated to neurologic response.",
                corrected_rule="For secured SAH DCI, raise MAP 20-40 above baseline with norepinephrine 0.05-0.1 mcg/kg/min.",
                expected_answer_edge="MAP +20-40 over baseline; norepinephrine 0.05-0.1 mcg/kg/min; titrate to exam",
                teaching_intent="retention_check",
            )
            states = conn.execute("SELECT claim_slug, claim_text, state FROM claim_state").fetchall()
            self.assertEqual(len(states), 1)
            self.assertEqual(states[0]["state"], "durable")
            slugs = [row["claim_slug"] for row in conn.execute("SELECT claim_slug FROM claim_results")]
            self.assertEqual(len(set(slugs)), 1)
        finally:
            conn.close()

    def test_agent_claim_state_controls_override_heuristics_when_asserted(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="session-agent-controls",
                topic="seizure prophylaxis in tbi",
                concept="levetiracetam prophylaxis duration",
                question="How long should post-TBI seizure prophylaxis continue?",
                answer="Indefinitely.",
                correct=0,
                error_type="numerical_recall",
                corrected_rule="Use 7 days of early post-traumatic seizure prophylaxis when indicated.",
                agent_priority="urgent",
            )
            first = conn.execute("SELECT id, priority FROM claim_state").fetchone()
            self.assertEqual(first["priority"], "urgent")

            study_memory.log_answer(
                conn,
                session_id="session-agent-controls",
                topic="seizure prophylaxis in tbi",
                concept="levetiracetam dosing duration",
                question="Retest the duration.",
                answer="Still unsure.",
                correct=0,
                corrected_rule="Use 7 days, not an indefinite course.",
                match_claim_state_id=int(first["id"]),
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_state").fetchone()[0], 1)

            study_memory.log_answer(
                conn,
                session_id="session-agent-controls",
                topic="seizure prophylaxis in tbi",
                concept="levetiracetam adverse effects counseling",
                question="Different target: what adverse effect matters?",
                answer="Irritability.",
                correct=2,
                tested_claim="Levetiracetam can cause irritability or mood effects relevant to counseling.",
                force_new_claim=True,
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_state").fetchone()[0], 2)

            study_memory.log_answer(
                conn,
                session_id="session-agent-controls",
                topic="seizure prophylaxis in tbi",
                concept="levetiracetam prophylaxis duration",
                question="Final repair: duration?",
                answer="Seven days.",
                correct=2,
                tested_claim="Use 7 days of early post-traumatic seizure prophylaxis when indicated.",
                repairs_claim_state_ids=(int(first["id"]),),
            )
            repaired = conn.execute("SELECT state FROM claim_state WHERE id = ?", (int(first["id"]),)).fetchone()
            self.assertEqual(repaired["state"], "repaired_same_session")
        finally:
            conn.close()

    def test_retention_check_promotes_repair_to_durable(self) -> None:
        conn = self._memory_conn()
        try:
            claim = "Secured SAH DCI uses MAP +20-40 and norepinephrine mcg/kg/min."
            study_memory.log_answer(
                conn,
                session_id="session-repair",
                topic="hypertension management",
                concept="sah norepi units",
                question="Units?",
                answer="mcg/kg/hr",
                correct=1,
                tested_claim=claim,
                missing_edge="norepinephrine unit mcg/kg/min",
                corrected_rule="Use mcg/kg/min.",
            )
            study_memory.log_answer(
                conn,
                session_id="session-repair",
                topic="hypertension management",
                concept="sah norepi units",
                question="Try again.",
                answer="mcg/kg/min",
                correct=2,
                tested_claim=claim,
                corrected_rule="Use mcg/kg/min.",
                teaching_intent="repair_after_miss",
            )
            study_memory.log_answer(
                conn,
                session_id="session-retention",
                topic="hypertension management",
                concept="sah norepi units",
                question="Delayed check: units?",
                answer="mcg/kg/min",
                correct=2,
                tested_claim=claim,
                corrected_rule="Use mcg/kg/min.",
                teaching_intent="retention_check",
            )
            state = conn.execute("SELECT state FROM claim_state").fetchone()
            self.assertEqual(state["state"], "durable")
            events = [r["event_type"] for r in conn.execute("SELECT event_type FROM state_events ORDER BY id")]
            self.assertEqual(events, ["partial", "repaired", "retention_passed"])
            summary = json.loads(study_memory.retrieval_summary(conn, topic="hypertension management", limit=5))
            card_types = [card["type"] for card in summary["cards"]]
            self.assertIn("scaffold", card_types)
            self.assertNotIn("recent_repair", card_types)
        finally:
            conn.close()

    def test_claim_state_records_schedule_and_due_surface(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="session-schedule",
                topic="evd management",
                concept="evd clamp trial failure",
                question="Clamp trial: ventricles enlarge but ICP stays 12; pass or fail?",
                answer="Fail because symptoms and ventriculomegaly matter.",
                correct=2,
                tested_claim="Clamp trial failure can occur from symptoms and ventriculomegaly even without sustained ICP elevation.",
                corrected_rule="Treat symptomatic ventriculomegaly as clamp failure even if ICP is not high.",
            )
            state = conn.execute(
                "SELECT next_due_ts, difficulty, stability FROM claim_state"
            ).fetchone()
            self.assertTrue(state["next_due_ts"])
            self.assertGreater(float(state["stability"]), 1.0)
            self.assertLess(float(state["difficulty"]), 0.3)

            past_due = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            conn.execute("UPDATE claim_state SET next_due_ts = ?, last_seen_ts = ?", (past_due, past_due))
            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="evd management",
                    limit=4,
                    include_due=True,
                )
            )
            self.assertEqual(len(payload["due_claims"]), 1)
            due = payload["due_claims"][0]
            self.assertEqual(due["topic"], "evd-management-icu")
            self.assertEqual(due["next_action"], "Run a changed-frame retention check before relying on this scaffold.")
            self.assertLess(due["retrievability"], 1.0)
        finally:
            conn.close()

    def test_existing_claim_states_get_due_backfill(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="session-backfill",
                topic="evd management",
                concept="evd infection risk",
                question="What EVD handling increases infection risk?",
                answer="Frequent breaks in the sterile system.",
                correct=2,
                tested_claim="Frequent EVD system access increases infection risk.",
                corrected_rule="Minimize sterile system breaks.",
            )
            conn.execute("UPDATE claim_state SET next_due_ts = ''")
            conn.commit()
        finally:
            conn.close()

        conn = self._memory_conn()
        try:
            due = conn.execute("SELECT next_due_ts, stability FROM claim_state").fetchone()
            self.assertTrue(due["next_due_ts"])
            self.assertGreater(float(due["stability"]), 0)
        finally:
            conn.close()

    def test_retrievability_accepts_legacy_timezone_naive_timestamp(self) -> None:
        retrievability = study_memory._retrievability(
            "2026-04-22T00:00:00",
            3.0,
            as_of=datetime(2026, 4, 23, tzinfo=timezone.utc),
        )
        self.assertGreater(retrievability, 0)
        self.assertLess(retrievability, 1)

    def test_model_summary_surfaces_calibration_and_operation_profile(self) -> None:
        conn = self._memory_conn()
        try:
            for idx in range(2):
                study_memory.log_answer(
                    conn,
                    session_id="session-model",
                    topic="evd management",
                    concept=f"evd troubleshooting sequence {idx}",
                    question=f"EVD stops draining at bedside: what is your step {idx}?",
                    answer="Flush toward the patient first.",
                    correct=0,
                    correction="First check level, clamp state, kinks, transducer, and patient position; do not flush toward the patient.",
                    error_type="sequencing",
                    tested_claim=f"EVD troubleshooting requires external system checks before invasive manipulation {idx}.",
                    missing_edge="bedside troubleshooting sequence before invasive flushing",
                    learning_operation="sequencing",
                    confidence_observed="fluent",
                    answer_mode="unaided",
                    teaching_move="order_set",
                    force_new_claim=True,
                )
            study_memory.log_answer(
                conn,
                session_id="session-model",
                topic="evd management",
                concept="evd waveform mechanism",
                question="Why can an EVD waveform dampen?",
                answer="Catheter obstruction or compliance/leveling issues can dampen it.",
                correct=2,
                tested_claim="EVD waveform quality reflects catheter patency, leveling, and compliance.",
                corrected_rule="Use waveform changes as a troubleshooting signal.",
                learning_operation="mechanism",
                confidence_observed="hesitant",
                answer_mode="unaided",
                teaching_move="mechanism_first",
                force_new_claim=True,
            )
            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="evd management",
                    limit=8,
                    include_model=True,
                )
            )
            calibration = payload["calibration_profile"]
            self.assertEqual(calibration["buckets"]["high"]["count"], 2)
            self.assertEqual(calibration["buckets"]["high"]["misses"], 2)
            self.assertEqual(len(calibration["high_confidence_misses"]), 2)
            operations = payload["operation_profile"]
            self.assertEqual(operations[0]["operation"], "sequencing")
            self.assertEqual(operations[0]["miss_rate"], 1.0)
            moves = payload["teaching_move_profile"]
            self.assertEqual(moves[0]["teaching_move"], "mechanism_first")
            self.assertIn("due_claims", payload)
        finally:
            conn.close()

    def test_model_summary_surfaces_coverage_frontier_and_shadow_queue(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="session-coverage",
                topic="tbi classification",
                concept="marshall ct classification",
                question="What does the Marshall CT score classify?",
                answer="TBI CT severity patterns.",
                correct=2,
                tested_claim="TBI classification includes CT-based Marshall or Rotterdam scoring.",
                corrected_rule="Use CT classification as part of TBI severity stratification.",
            )
            study_memory.log_answer(
                conn,
                session_id="quick-shadow",
                topic="tbi management",
                concept="hyperosmolar choice",
                question="Mannitol or hypertonic saline for impending herniation?",
                answer="Both are temporizing options; choose based on hemodynamics and sodium/osmolality context.",
                correct=2,
                skill="quick-answer",
                tested_claim="Hyperosmolar choice depends on hemodynamics and sodium/osmolality context.",
                learner_claim="Question-only exchange; no learner performance assessed.",
                teaching_intent="quick_answer_reference",
                answer_mode="after_teaching",
            )
            study_memory.log_answer(
                conn,
                session_id="report-shadow",
                topic="tbi management",
                concept="report coverage anchor",
                question="What is covered in the Severe TBI report?",
                answer="Initial resuscitation, ICP treatment, and operative escalation.",
                correct=2,
                skill="generate-report",
                doc_path="Reports/Severe TBI.md",
            )
            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    limit=8,
                    include_model=True,
                    context="TBI herniation hyperosmolar",
                )
            )
            coverage = payload["coverage_frontier"]
            self.assertGreaterEqual(coverage["catalog_topics"], 1)
            self.assertGreaterEqual(coverage["tested_catalog_topics"], 1)
            self.assertTrue(coverage["frontier_candidates"] or coverage["blind_spots"])
            shadow_types = {item["type"] for item in payload["shadow_queue"]}
            self.assertIn("quick_answer_interest", shadow_types)
            self.assertIn("artifact_review_anchor", shadow_types)
            self.assertTrue(payload["context_focus"])
            self.assertTrue(any(item["surface"] == "shadow_queue" for item in payload["context_focus"]))
        finally:
            conn.close()

    def test_context_focus_rejects_single_generic_token_overlap(self) -> None:
        candidates = study_memory._context_focus_for_summary(
            context="anterior cervical discectomy and fusion ACDF",
            due_claims=[
                {
                    "topic": "anterior-choroidal-artery-territory",
                    "concept": "anterior choroidal artery supply",
                    "claim": "Identify anterior choroidal artery territory.",
                },
                {
                    "topic": "cervical-spine-fractures",
                    "concept": "cervical instability clearance",
                    "claim": "Apply cervical instability clearance rules.",
                },
            ],
            coverage_frontier={"frontier_candidates": [], "blind_spots": []},
            shadow_queue=[],
            limit=8,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["item"]["topic"], "cervical-spine-fractures")
        self.assertEqual(candidates[0]["matched_tokens"], ["cervical"])

    def test_topic_summary_emits_planning_brief_with_bounded_agent_validated_frontier(self) -> None:
        conn = self._memory_conn()
        try:
            seed_path = Path(__file__).resolve().parents[1] / "data" / "reference_graph_seed.json"
            load_reference_graph_payload(conn, json.loads(seed_path.read_text()), apply=True)
            study_memory.log_answer(
                conn,
                session_id="spine-frontier",
                topic="spine emergencies acute spinal cord injury critical care",
                concept="cervical sci respiratory mechanics",
                question="What predicts respiratory collapse after cervical SCI?",
                answer="I am not sure.",
                correct=0,
                correction="Trend FVC and NIF; accessory muscle fatigue can precede collapse.",
                error_type="reasoning_gap",
                tested_claim="Cervical SCI respiratory collapse requires trending FVC, NIF, and accessory muscle fatigue.",
                missing_edge="respiratory mechanics and elective intubation thresholds",
                doc_path="Reports/Spine Emergencies, Acute Spinal Cord Injury, and Critical Care.md",
            )
            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="spine emergencies acute spinal cord injury critical care",
                    include_curated=True,
                    include_model=True,
                )
            )
            brief = payload["planning_brief"]
            self.assertTrue(brief["read_first"])
            self.assertTrue(brief["open_first"])
            self.assertTrue(brief["agent_validation_checkpoint"]["required_before_teaching"])
            frontier = brief["contextual_frontier"]
            self.assertTrue(frontier)
            self.assertLessEqual(len(frontier), 8)
            self.assertTrue(all(item["agent_validation_required"] for item in frontier))
            self.assertTrue(any(item["source_surface"] == "reviewed_reference_graph" for item in frontier))

            brief_only = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="spine emergencies acute spinal cord injury critical care",
                    include_curated=True,
                    include_model=True,
                    brief_only=True,
                )
            )
            self.assertEqual(
                set(brief_only),
                {"planning_brief", "counts", "omitted", "retrieval_guidance"},
            )
        finally:
            conn.close()

    def test_unresolved_topic_summary_routes_to_existing_learner_state_before_teaching(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="evd-icp-routing",
                topic="evd management",
                concept="icp waveform interpretation",
                question="What ICP waveform change suggests reduced compliance?",
                answer="P2 becomes greater than P1.",
                correct=2,
                tested_claim="Reduced intracranial compliance is suggested when ICP waveform P2 exceeds P1.",
            )
            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="icp management",
                    include_curated=True,
                    include_model=True,
                    brief_only=True,
                )
            )
            brief = payload["planning_brief"]
            self.assertTrue(brief["read_first"])
            self.assertIn("No stored learner topic resolved", brief["resolution_warning"])
            self.assertTrue(brief["resolution_candidates"])
            self.assertEqual(brief["resolution_candidates"][0]["topic"], "evd-management-icu")
            self.assertTrue(brief["agent_validation_checkpoint"]["required_before_teaching"])
        finally:
            conn.close()

    def test_identity_audit_and_guarded_topic_merge(self) -> None:
        conn = self._memory_conn()
        try:
            conn.execute(
                """INSERT INTO topics (canonical_slug, display_name, domain, created_at)
                   VALUES ('spine-emergencies-sci-critical-care', 'Spine Emergencies SCI Critical Care', 'spine', '')"""
            )
            conn.execute(
                """INSERT INTO topics (canonical_slug, display_name, domain, created_at)
                   VALUES ('spine-emergencies-sci-and-critical-care', 'Spine Emergencies SCI And Critical Care', 'spine', '')"""
            )
            conn.commit()
            audit = study_memory.identity_audit(conn)
            self.assertTrue(audit["duplicate_topic_candidates"])

            source = conn.execute(
                "SELECT id FROM topics WHERE canonical_slug = 'spine-emergencies-sci-critical-care'"
            ).fetchone()["id"]
            target = conn.execute(
                "SELECT id FROM topics WHERE canonical_slug = 'spine-emergencies-sci-and-critical-care'"
            ).fetchone()["id"]
            conn.execute(
                """INSERT INTO concepts (topic_id, canonical_slug, display_name, created_at)
                   VALUES (?, 'respiratory-thresholds', 'respiratory thresholds', '')""",
                (source,),
            )
            conn.commit()

            dry_run = study_memory.merge_topics(
                conn,
                source_topic="spine-emergencies-sci-critical-care",
                target_topic="spine-emergencies-sci-and-critical-care",
            )
            self.assertFalse(dry_run["blocked"])
            self.assertNotIn("applied", dry_run)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0], 2)

            applied = study_memory.merge_topics(
                conn,
                source_topic="spine-emergencies-sci-critical-care",
                target_topic="spine-emergencies-sci-and-critical-care",
                apply=True,
            )
            self.assertTrue(applied["applied"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0], 1)
            concept_topic = conn.execute(
                "SELECT topic_id FROM concepts WHERE canonical_slug = 'respiratory-thresholds'"
            ).fetchone()["topic_id"]
            self.assertEqual(concept_topic, target)
            resolved = study_memory.resolve_topic(conn, "spine-emergencies-sci-critical-care")
            self.assertEqual(resolved.slug, "spine-emergencies-sci-and-critical-care")
        finally:
            conn.close()

    def test_identity_audit_flags_shared_document_family_even_when_titles_diverge(self) -> None:
        conn = self._memory_conn()
        try:
            conn.execute(
                """INSERT INTO topics (canonical_slug, display_name, domain, primary_doc_path, created_at)
                   VALUES ('spine-emergencies-acute-spinal-cord-injury-critical-care',
                           'Spine Emergencies Acute Spinal Cord Injury Critical Care',
                           'spine',
                           'Reports/Spine Emergencies, Acute Spinal Cord Injury, and Critical Care.md',
                           '')"""
            )
            conn.execute(
                """INSERT INTO topics (canonical_slug, display_name, domain, primary_doc_path, created_at)
                   VALUES ('acute-spinal-cord-injury-classification-asia-medical-and-surgical-management',
                           'Acute Spinal Cord Injury Classification Asia Medical And Surgical Management',
                           'spine',
                           'Reports/Spine Emergencies, Acute Spinal Cord Injury, and Critical Care_v5.md',
                           '')"""
            )
            conn.commit()
            audit = study_memory.identity_audit(conn)
            self.assertEqual(audit["counts"]["duplicate_topic_candidates"], 1)
            self.assertTrue(audit["duplicate_topic_candidates"][0]["shared_doc_family"])
        finally:
            conn.close()

    def test_topic_merge_refuses_same_slug_concept_collision(self) -> None:
        conn = self._memory_conn()
        try:
            conn.execute(
                "INSERT INTO topics (canonical_slug, display_name, created_at) VALUES ('source-topic', 'Source Topic', '')"
            )
            conn.execute(
                "INSERT INTO topics (canonical_slug, display_name, created_at) VALUES ('target-topic', 'Target Topic', '')"
            )
            rows = conn.execute("SELECT id, canonical_slug FROM topics ORDER BY id").fetchall()
            ids = {row["canonical_slug"]: int(row["id"]) for row in rows}
            for topic_id in ids.values():
                conn.execute(
                    """INSERT INTO concepts (topic_id, canonical_slug, display_name, created_at)
                       VALUES (?, 'shared-concept', 'shared concept', '')""",
                    (topic_id,),
                )
            conn.commit()
            result = study_memory.merge_topics(
                conn,
                source_topic="source-topic",
                target_topic="target-topic",
                apply=True,
            )
            self.assertTrue(result["blocked"])
            self.assertEqual(result["concept_collisions"], ["shared-concept"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0], 2)
        finally:
            conn.close()

    def test_strict_telemetry_rejects_incomplete_assessment(self) -> None:
        conn = self._memory_conn()
        try:
            # No tested_claim/corrected_rule/correction -> the stored claim would be
            # boilerplate, so strict mode rejects on the claim gate first.
            with self.assertRaisesRegex(ValueError, "strict telemetry requires tested_claim"):
                study_memory.log_answer(
                    conn,
                    session_id="strict-missing",
                    topic="evd management",
                    concept="evd troubleshooting",
                    question="What next?",
                    answer="Check the system.",
                    correct=1,
                    strict_telemetry=True,
                )
            # With a real claim present, the controlled-field gate still rejects when
            # answer_mode/confidence/teaching_move are missing.
            with self.assertRaisesRegex(ValueError, "strict telemetry requires answer_mode"):
                study_memory.log_answer(
                    conn,
                    session_id="strict-missing",
                    topic="evd management",
                    concept="evd troubleshooting",
                    question="What next?",
                    answer="Check the system.",
                    correct=1,
                    tested_claim="External troubleshooting precedes invasive EVD manipulation.",
                    strict_telemetry=True,
                )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0], 0)
        finally:
            conn.close()

    def test_repair_episode_tracks_immediate_and_delayed_outcomes(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="repair-episode",
                topic="evd management",
                concept="evd troubleshooting order",
                question="EVD stops draining. What do you check first?",
                answer="Flush toward the patient.",
                correct=0,
                error_type="reasoning_gap",
                misconception="Flush toward the patient before checking the external system.",
                corrected_rule="Check leveling, clamps, tubing, and patient position before invasive manipulation.",
                missing_edge="external troubleshooting before invasive manipulation",
                answer_mode="unaided",
                confidence_observed="high",
                teaching_move="initial_probe",
                strict_telemetry=True,
            )
            claim_state_id = int(conn.execute("SELECT id FROM claim_state").fetchone()["id"])
            study_memory.log_answer(
                conn,
                session_id="repair-episode",
                topic="evd management",
                concept="evd troubleshooting order",
                question="Changed bedside sequence?",
                answer="Check leveling, clamps, tubing, and patient position first.",
                correct=2,
                corrected_rule="Check external causes before invasive manipulation.",
                answer_mode="after_teaching",
                confidence_observed="medium",
                teaching_move="order_set",
                strict_telemetry=True,
                match_claim_state_id=claim_state_id,
            )
            study_memory.log_answer(
                conn,
                session_id="repair-retention",
                topic="evd management",
                concept="evd troubleshooting order",
                question="Delayed transfer: a transported patient has stopped draining. First checks?",
                answer="Re-level, inspect clamps and tubing, then assess position before invasive manipulation.",
                correct=2,
                corrected_rule="Check external causes before invasive manipulation.",
                teaching_intent="retention_check",
                answer_mode="unaided",
                confidence_observed="high",
                teaching_move="changed_frame_retest",
                strict_telemetry=True,
                match_claim_state_id=claim_state_id,
            )
            episode = conn.execute("SELECT * FROM repair_episodes").fetchone()
            self.assertEqual(episode["status"], "retained")
            self.assertEqual(episode["teaching_move"], "order_set")
            self.assertIsNotNone(episode["repaired_result_id"])
            self.assertIsNotNone(episode["retention_result_id"])
            payload = json.loads(study_memory.retrieval_summary(conn, include_model=True))
            self.assertEqual(payload["tutor_efficacy_profile"][0]["evidence_level"], "insufficient")
            self.assertEqual(payload["telemetry_profile"]["field_completeness"]["answer_mode"]["rate"], 1.0)
        finally:
            conn.close()

    def test_reference_graph_is_reviewed_dry_run_and_predicate_aware(self) -> None:
        conn = self._memory_conn()
        try:
            seed_path = Path(__file__).resolve().parents[1] / "data" / "reference_graph_seed.json"
            seed = json.loads(seed_path.read_text())
            dry_run = load_reference_graph_payload(conn, seed)
            self.assertNotIn("applied", dry_run)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM reference_nodes").fetchone()[0], 0)
            applied = load_reference_graph_payload(conn, seed, apply=True)
            self.assertTrue(applied["applied"])
            due_claims = [{
                "claim_state_id": 42,
                "topic": "spine-emergencies-acute-spinal-cord-injury-and-critical-care",
                "concept": "cervical spinal cord injury respiratory mechanics and elective intubation thresholds",
                "claim": "Use FVC and NIF respiratory thresholds for elective intubation in cervical SCI.",
            }]
            routine_acdf = context_graph_focus_for_summary(
                conn,
                context="ACDF",
                due_claims=due_claims,
            )
            self.assertFalse(any(item["node_key"] == "sci-elective-intubation-thresholds" for item in routine_acdf))
            trauma = context_graph_focus_for_summary(
                conn,
                context="cervical fracture stabilization SCI",
                due_claims=due_claims,
            )
            self.assertFalse(any(item["node_key"] == "acdf" for item in trauma))
            threshold = next(item for item in trauma if item["node_key"] == "sci-elective-intubation-thresholds")
            self.assertLessEqual(threshold["hops"], 2)
            self.assertEqual(threshold["due_claims"][0]["claim_state_id"], 42)
        finally:
            conn.close()

    def test_regression_after_durable_is_explicit(self) -> None:
        conn = self._memory_conn()
        try:
            claim = "Acute spontaneous ICH should avoid SBP below 130."
            study_memory.log_answer(
                conn,
                session_id="session-durable",
                topic="hypertension management",
                concept="ich bp floor",
                question="ICH floor?",
                answer="Do not go below 130.",
                correct=2,
                tested_claim=claim,
                corrected_rule="Avoid SBP below 130.",
            )
            study_memory.log_answer(
                conn,
                session_id="session-regress",
                topic="hypertension management",
                concept="ich bp floor",
                question="Later ICH floor?",
                answer="Below 120 is okay.",
                correct=1,
                tested_claim=claim,
                missing_edge="regressed on SBP floor below 130",
                corrected_rule="Avoid SBP below 130.",
            )
            state = conn.execute("SELECT state, priority FROM claim_state").fetchone()
            self.assertEqual(state["state"], "regressed")
            self.assertEqual(state["priority"], "urgent")
            events = [r["event_type"] for r in conn.execute("SELECT event_type FROM state_events ORDER BY id")]
            self.assertEqual(events, ["confirmed", "regressed"])
        finally:
            conn.close()

    def test_dci_partial_is_urgent(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="session-dci",
                topic="hypertension management",
                concept="sah dci norepinephrine units",
                question="SAH DCI norepi units?",
                answer="mcg/kg/hr",
                correct=1,
                error_type="numerical_recall",
                tested_claim="Secured SAH DCI uses norepinephrine dosed in mcg/kg/min.",
                missing_edge="norepinephrine unit mcg/kg/min",
                corrected_rule="Use mcg/kg/min.",
            )
            state = conn.execute("SELECT priority FROM claim_state").fetchone()
            self.assertEqual(state["priority"], "urgent")
        finally:
            conn.close()

    def test_session_handoff_updates_single_card(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="session-one",
                topic="hypertension management",
                concept="ich bp target",
                question="ICH target?",
                answer="130-140",
                correct=2,
            )
            study_memory.end_session(conn, session_id="session-one", summary="First handoff.", next_strategy="Retest A.")
            study_memory.end_session(conn, session_id="session-one", summary="Second handoff.", next_strategy="Retest B.")
            rows = conn.execute(
                "SELECT summary, next_action FROM retrieval_cards WHERE card_type = 'session_handoff'"
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["summary"], "Second handoff.")
            self.assertEqual(rows[0]["next_action"], "Retest B.")
        finally:
            conn.close()

    def test_session_handoff_deactivates_legacy_duplicates(self) -> None:
        conn = self._memory_conn()
        try:
            topic_id = study_memory._ensure_topic(
                conn,
                study_memory.resolve_topic(conn, "hypertension management"),
            )
            conn.execute(
                """INSERT INTO retrieval_cards
                   (topic_id, claim_state_id, card_type, status, priority, summary, next_action, updated_ts)
                   VALUES (?, NULL, 'session_handoff', 'active', 'medium', 'Old A.', 'Old A.', '2026-01-01')""",
                (topic_id,),
            )
            conn.execute(
                """INSERT INTO retrieval_cards
                   (topic_id, claim_state_id, card_type, status, priority, summary, next_action, updated_ts)
                   VALUES (?, NULL, 'session_handoff', 'active', 'medium', 'Old B.', 'Old B.', '2026-01-02')""",
                (topic_id,),
            )
            study_memory._upsert_session_card(
                conn,
                topic_id,
                "session-new",
                "Current handoff.",
                "Retest current edge.",
                "2026-01-03",
            )
            active = conn.execute(
                """SELECT summary FROM retrieval_cards
                    WHERE topic_id = ? AND card_type = 'session_handoff' AND status = 'active'""",
                (topic_id,),
            ).fetchall()
            self.assertEqual([row["summary"] for row in active], ["Current handoff."])
        finally:
            conn.close()

    def test_doc_family_resolution_prefers_existing_review_topic_over_versioned_catalog_topic(self) -> None:
        conn = self._memory_conn()
        try:
            established = study_memory.TopicResolution(
                "spine-emergencies-acute-spinal-cord-injury-critical-care",
                "Spine Emergencies Acute Spinal Cord Injury Critical Care",
                "spine",
                ("spine emergencies acute spinal cord injury and critical care",),
                1.0,
            )
            established_id = study_memory._ensure_topic(
                conn,
                established,
                "Reports/Spine Emergencies, Acute Spinal Cord Injury, and Critical Care.md",
            )
            conn.execute(
                """INSERT INTO topics (canonical_slug, display_name, domain, primary_doc_path, created_at)
                   VALUES ('acute-spinal-cord-injury-classification-asia-medical-and-surgical-management',
                           'Acute Spinal Cord Injury Classification Asia Medical And Surgical Management',
                           'spine',
                           'Reports/Spine Emergencies, Acute Spinal Cord Injury, and Critical Care_v5.md',
                           '')"""
            )
            study_memory.log_answer(
                conn,
                session_id="spine-review",
                topic="spine emergencies acute spinal cord injury and critical care",
                concept="map augmentation target",
                question="MAP target?",
                answer="75-80",
                correct=2,
                tested_claim="Modern traumatic SCI MAP target is 75-80 mmHg.",
                doc_path="Reports/Spine Emergencies, Acute Spinal Cord Injury, and Critical Care.md",
            )
            resolved = study_memory.resolve_topic(
                conn,
                "acute spinal cord injury classification asia medical and surgical management",
                "Reports/Spine Emergencies, Acute Spinal Cord Injury, and Critical Care_v5.md",
            )
            self.assertEqual(resolved.slug, established.slug)
            self.assertEqual(
                conn.execute("SELECT topic_id FROM claim_results").fetchone()["topic_id"],
                established_id,
            )
        finally:
            conn.close()

    def test_strict_telemetry_rejects_sentence_length_concept_label(self) -> None:
        conn = self._memory_conn()
        try:
            with self.assertRaisesRegex(ValueError, "succinct concept label"):
                study_memory.log_answer(
                    conn,
                    session_id="strict-long-concept",
                    topic="spine emergencies",
                    concept=(
                        "dexamethasone bolus dose is 10 mg iv then 16 mg per day divided every "
                        "six hours to treat vasogenic edema in metastatic spinal cord compression"
                    ),
                    question="What steroid protocol?",
                    answer="10 mg IV then 16 mg/day.",
                    correct=2,
                    tested_claim="MSCC dexamethasone protocol starts with 10 mg IV then 16 mg/day.",
                    answer_mode="unaided",
                    confidence_observed="high",
                    teaching_move="changed_frame_retest",
                    strict_telemetry=True,
                )
        finally:
            conn.close()

    def test_session_handoff_compacts_without_mid_sentence_truncation(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="session-compact",
                topic="hypertension management",
                concept="ich bp target",
                question="ICH target?",
                answer="130-140",
                correct=2,
            )
            summary = (
                "First sentence is the important compressed handoff. "
                + "Second sentence contains extra details that should not be cut in the middle of a word. " * 20
            )
            next_strategy = (
                "Retest exact ischemic stroke thresholds first. "
                + "Then continue with long explanatory content that should be compacted cleanly. " * 20
            )
            study_memory.end_session(conn, session_id="session-compact", summary=summary, next_strategy=next_strategy)
            row = conn.execute(
                "SELECT summary, next_action FROM retrieval_cards WHERE card_type = 'session_handoff'"
            ).fetchone()
            self.assertLessEqual(len(row["summary"]), 500)
            self.assertLessEqual(len(row["next_action"]), 500)
            self.assertTrue(row["summary"].endswith(".") or row["summary"].endswith("..."))
            self.assertTrue(row["next_action"].endswith(".") or row["next_action"].endswith("..."))
        finally:
            conn.close()

    def test_retrieval_caps_scaffolds_independent_of_total_limit(self) -> None:
        conn = self._memory_conn()
        try:
            self._log_scaffolds(conn, "hypertension management", 6)
            study_memory.log_answer(
                conn,
                session_id="session-gap",
                topic="hypertension management",
                concept="dci norepinephrine units",
                question="Norepinephrine units for DCI?",
                answer="mcg/kg/hr",
                correct=1,
                tested_claim="SAH DCI norepinephrine is dosed in mcg/kg/min.",
                missing_edge="norepinephrine unit mcg/kg/min",
                corrected_rule="Use mcg/kg/min.",
            )
            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="hypertension management",
                    limit=20,
                    scaffold_limit=2,
                )
            )
            card_types = [card["type"] for card in payload["cards"]]
            self.assertEqual(card_types.count("scaffold"), 2)
            self.assertIn("must_retest", card_types)
            self.assertEqual(payload["counts"]["scaffold"], 6)
            self.assertEqual(payload["omitted"]["scaffold"], 4)
            self.assertTrue(payload["retrieval_guidance"]["is_truncated"])
            self.assertEqual(payload["retrieval_guidance"]["omitted_high_signal"], {})
            self.assertTrue(payload["retrieval_guidance"]["suggested_commands"])
        finally:
            conn.close()

    def test_retrieval_expansion_commands_preserve_include_curated(self) -> None:
        conn = self._memory_conn()
        try:
            self._log_scaffolds(conn, "hypertension management", 5)
            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="hypertension management",
                    limit=8,
                    scaffold_limit=2,
                    include_curated=True,
                )
            )
            commands = payload["retrieval_guidance"]["suggested_commands"]
            self.assertTrue(commands)
            self.assertTrue(all("--include-curated" in command for command in commands))

            model_payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="hypertension management",
                    limit=8,
                    scaffold_limit=2,
                    include_curated=True,
                    include_model=True,
                    context="stroke blood pressure",
                )
            )
            model_commands = model_payload["retrieval_guidance"]["suggested_commands"]
            self.assertTrue(model_commands)
            self.assertTrue(all("--include-model" in command for command in model_commands))
            self.assertTrue(all("--context" in command for command in model_commands))
        finally:
            conn.close()

    def test_startup_recall_auto_expands_omitted_high_signal_cards(self) -> None:
        conn = self._memory_conn()
        try:
            for idx in range(5):
                study_memory.log_answer(
                    conn,
                    session_id=f"gap-{idx}",
                    topic="hypertension management",
                    concept=f"bp management gap {idx}",
                    question=f"BP management question {idx}?",
                    answer="I am not sure.",
                    correct=0,
                    correction="Use the condition-specific blood pressure target.",
                    error_type="omission",
                    tested_claim=f"BP management claim {idx}.",
                    missing_edge=f"condition-specific target {idx}",
                    force_new_claim=True,
                )
            payload = json.loads(
                study_memory.startup_recall(
                    conn,
                    topic="hypertension management",
                    limit=2,
                )
            )
            self.assertTrue(payload["startup_recall"]["auto_expanded"])
            self.assertEqual(payload["startup_recall"]["initial_limit"], 2)
            self.assertEqual(payload["startup_recall"]["final_limit"], 5)
            self.assertEqual(payload["retrieval_guidance"]["omitted_high_signal"], {})
            self.assertEqual(len(payload["planning_brief"]["open_first"]), 5)
        finally:
            conn.close()

    def test_startup_recall_uses_doc_family_to_resolve_canonical_topic(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="spine-v4",
                topic="spine emergencies acute spinal cord injury critical care",
                concept="neurogenic shock distinction",
                question="How do you distinguish neurogenic shock?",
                answer="Hypotension and bradycardia from sympathetic uncoupling.",
                correct=2,
                tested_claim="Neurogenic shock is hypotension and bradycardia from sympathetic uncoupling.",
                doc_path="Reports/Spine Emergencies, Acute Spinal Cord Injury, and Critical Care_v4.md",
            )
            payload = json.loads(
                study_memory.startup_recall(
                    conn,
                    topic="acute spinal cord injury classification asia medical and surgical management",
                    doc_path="Reports/Spine Emergencies, Acute Spinal Cord Injury, and Critical Care_v5.md",
                )
            )
            self.assertEqual(
                payload["startup_recall"]["resolved_topic"],
                "spine-emergencies-acute-spinal-cord-injury-critical-care",
            )
            self.assertEqual(payload["startup_recall"]["resolver_confidence"], 1.0)
            self.assertTrue(payload["startup_recall"]["ready_to_teach"])
        finally:
            conn.close()

    def test_startup_recall_blocks_teaching_when_topic_requires_routing(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="evd-icp-startup",
                topic="evd management",
                concept="icp waveform interpretation",
                question="What ICP waveform change suggests reduced compliance?",
                answer="P2 becomes greater than P1.",
                correct=2,
                tested_claim="Reduced intracranial compliance is suggested when ICP waveform P2 exceeds P1.",
            )
            payload = json.loads(study_memory.startup_recall(conn, topic="icp management"))
            self.assertTrue(payload["startup_recall"]["routing_required"])
            self.assertFalse(payload["startup_recall"]["ready_to_teach"])
            self.assertTrue(payload["planning_brief"]["resolution_candidates"])
        finally:
            conn.close()

    def test_global_startup_recall_defers_bulk_expansion_to_topic_drilldown(self) -> None:
        conn = self._memory_conn()
        try:
            for idx in range(5):
                study_memory.log_answer(
                    conn,
                    session_id=f"global-gap-{idx}",
                    topic=f"global topic {idx}",
                    concept=f"global gap {idx}",
                    question=f"Global question {idx}?",
                    answer="I am not sure.",
                    correct=0,
                    correction="Use the topic-specific rule.",
                    error_type="omission",
                    tested_claim=f"Global claim {idx}.",
                    missing_edge=f"topic-specific rule {idx}",
                )
            payload = json.loads(study_memory.startup_recall(conn, global_mode=True, limit=2))
            startup = payload["startup_recall"]
            self.assertFalse(startup["auto_expanded"])
            self.assertEqual(startup["final_limit"], 2)
            self.assertEqual(startup["expansion_policy"], "global_compact_then_topic_drilldown")
            self.assertTrue(startup["deferred_high_signal"])
            self.assertTrue(startup["candidate_selection_required"])
            self.assertFalse(startup["ready_to_teach"])
            self.assertTrue(all(item["topic"] for item in payload["planning_brief"]["open_first"]))
        finally:
            conn.close()

    def test_retrieval_scaffold_only_topic_still_uses_compact_payload(self) -> None:
        conn = self._memory_conn()
        try:
            self._log_scaffolds(conn, "cerebral blood flow physiology", 5)
            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="cerebral blood flow physiology",
                    limit=8,
                    scaffold_limit=2,
                )
            )
            self.assertEqual(len(payload["cards"]), 2)
            self.assertTrue(all(card["type"] == "scaffold" for card in payload["cards"]))
            self.assertEqual(payload["counts"], {"scaffold": 5})
            self.assertEqual(payload["omitted"], {"scaffold": 3})
            self.assertEqual(payload["retrieval_guidance"]["scope"], "topic")
        finally:
            conn.close()

    def test_retrieval_can_suppress_scaffolds_but_report_omissions(self) -> None:
        conn = self._memory_conn()
        try:
            self._log_scaffolds(conn, "hypertension management", 3)
            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="hypertension management",
                    limit=8,
                    include_scaffolds=False,
                )
            )
            self.assertEqual(payload["cards"], [])
            self.assertEqual(payload["counts"], {"scaffold": 3})
            self.assertEqual(payload["omitted"], {"scaffold": 3})
        finally:
            conn.close()

    def test_global_retrieval_suppresses_scaffolds_by_default(self) -> None:
        conn = self._memory_conn()
        try:
            self._log_scaffolds(conn, "hypertension management", 3)
            self._log_scaffolds(conn, "tbi management", 2)
            payload = json.loads(study_memory.retrieval_summary(conn, limit=10))
            self.assertEqual(payload["cards"], [])
            self.assertEqual(payload["counts"], {"scaffold": 5})
            self.assertEqual(payload["omitted"], {"scaffold": 5})
            self.assertEqual(payload["retrieval_guidance"]["scope"], "global")
            self.assertIn("--include-global-scaffolds", payload["retrieval_guidance"]["suggested_commands"][0])

            with_scaffolds = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    limit=10,
                    scaffold_limit=2,
                    include_global_scaffolds=True,
                )
            )
            self.assertEqual(len(with_scaffolds["cards"]), 2)
            self.assertEqual(with_scaffolds["omitted"], {"scaffold": 3})
        finally:
            conn.close()

    def test_topic_hint_overrides_doc_context_and_records_session_topics(self) -> None:
        conn = self._memory_conn()
        try:
            doc = "Reports/Hypertension Management in the Neuro ICU and Emergency Department.md"
            study_memory.log_answer(
                conn,
                session_id="session-doc",
                topic="hypertension management",
                concept="unsecured sah bp target",
                question="What SBP target?",
                answer="<160",
                correct=2,
                doc_path=doc,
            )
            study_memory.log_answer(
                conn,
                session_id="session-doc",
                topic="tbi management",
                concept="cpp calculation map target with elevated icp",
                question="MAP 78 ICP 26: what is CPP?",
                answer="52, raise MAP.",
                correct=2,
                doc_path=doc,
            )
            topics = [
                r["canonical_slug"]
                for r in conn.execute(
                    """SELECT t.canonical_slug
                       FROM session_topics st
                       JOIN topics t ON t.id = st.topic_id
                       WHERE st.session_id = ?
                       ORDER BY t.canonical_slug""",
                    ("session-doc",),
                )
            ]
            self.assertEqual(topics, ["hypertension-management-neuro-emergencies", "tbi-management"])
        finally:
            conn.close()

    def test_topic_resolver_preserves_exact_legacy_topics(self) -> None:
        conn = self._memory_conn()
        try:
            expected = {
                "tbi": "tbi-management",
                "tbi management": "tbi-management",
                "severe tbi": "tbi-management",
                "evd management in icu": "evd-management-icu",
                "hypertension management": "hypertension-management-neuro-emergencies",
                "cerebral vasospasm management": "sah-vasospasm-management",
            }
            for hint, slug in expected.items():
                with self.subTest(hint=hint):
                    self.assertEqual(study_memory.resolve_topic(conn, hint).slug, slug)
        finally:
            conn.close()

    def test_topic_resolver_lets_specific_catalog_queries_override_broad_legacy_seed(self) -> None:
        conn = self._memory_conn()
        try:
            probes = {
                "tbi ct": "emergency-ct-head-interpretation-in-tbi-blood-herniation-midline-shift",
                "emergency ct head tbi": "emergency-ct-head-interpretation-in-tbi-blood-herniation-midline-shift",
                "tbi classification": "tbi-classification-mild-moderate-severe-gcs-and-marshall-or-rotterdam-ct-score",
                "hunt hess grading": "sah-grading-scales-hunt-hess-wfns-and-fisher-or-modified-fisher",
                "subdural hematoma management": "chronic-subdural-hematoma-burr-hole-drainage-and-recurrence-management",
            }
            for hint, slug in probes.items():
                with self.subTest(hint=hint):
                    self.assertEqual(study_memory.resolve_topic(conn, hint).slug, slug)
        finally:
            conn.close()


class CurationLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.memory_path = Path(self.tmp.name) / "study_memory.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _conn(self) -> sqlite3.Connection:
        return study_memory._get_db(self.memory_path)

    _SEED_FIXTURES: list[dict[str, str]] = [
        {
            "concept": "norepinephrine starting dose neuro icu",
            "tested_claim": "Norepinephrine starts at 0.05 mcg/kg/min in SAH DCI.",
            "corrected_rule": "Begin norepinephrine at 0.05 mcg/kg/min titrated to MAP.",
            "missing_edge": "norepinephrine unit mcg/kg/min not mcg/kg/hr",
        },
        {
            "concept": "nicardipine infusion ceiling acute ich",
            "tested_claim": "Nicardipine infusions in acute ICH ceiling at 15 mg/hr.",
            "corrected_rule": "Cap nicardipine at 15 mg/hr; switch agent if higher needed.",
            "missing_edge": "nicardipine maximum infusion rate 15 mg/hr",
        },
        {
            "concept": "labetalol bolus dose hypertensive emergency",
            "tested_claim": "Labetalol bolus is 10-20 mg IV for hypertensive emergency.",
            "corrected_rule": "Push labetalol 10-20 mg IV, may repeat to 80 mg total.",
            "missing_edge": "labetalol bolus 10-20 mg IV",
        },
        {
            "concept": "clevidipine onset duration acute bp",
            "tested_claim": "Clevidipine has 1-2 minute onset and lasts 5-15 minutes after stop.",
            "corrected_rule": "Use clevidipine for fine titration: onset 1-2 min, half-life ~1 min.",
            "missing_edge": "clevidipine pharmacokinetics onset half-life",
        },
        {
            "concept": "hydralazine pitfall raised icp",
            "tested_claim": "Hydralazine raises ICP via cerebral vasodilation in TBI.",
            "corrected_rule": "Avoid hydralazine in elevated ICP; pick titratable alternatives.",
            "missing_edge": "hydralazine cerebral vasodilator ICP risk",
        },
        {
            "concept": "esmolol indication aortic dissection neuro",
            "tested_claim": "Esmolol controls shear stress in aortic dissection with neuro injury.",
            "corrected_rule": "Use esmolol or labetalol first in dissection: target SBP <120 and HR <60.",
            "missing_edge": "esmolol dissection target SBP <120 HR <60",
        },
    ]

    def _seed_session(self, conn: sqlite3.Connection, session_id: str, *, score: int = 0, fixture_idx: int | None = None, topic: str = "hypertension management") -> int:
        idx = fixture_idx if fixture_idx is not None else (abs(hash(session_id)) % len(self._SEED_FIXTURES))
        fx = self._SEED_FIXTURES[idx]
        study_memory.log_answer(
            conn,
            session_id=session_id,
            topic=topic,
            concept=fx["concept"],
            question=f"Probe {session_id}: {fx['concept']}?",
            answer="learner placeholder answer",
            correct=score,
            correction=fx["corrected_rule"],
            error_type="numerical_recall" if score == 0 else "",
            tested_claim=fx["tested_claim"],
            corrected_rule=fx["corrected_rule"],
            missing_edge=fx["missing_edge"],
        )
        return int(
            conn.execute(
                "SELECT id FROM claim_results WHERE created_at = (SELECT MAX(created_at) FROM claim_results)"
            ).fetchone()[0]
        )

    def _end(self, conn: sqlite3.Connection, session_id: str) -> dict:
        return study_memory.end_session(
            conn,
            session_id=session_id,
            summary="Session recap.",
            next_strategy="Retest the missing threshold next session.",
        )

    def test_end_session_returns_curation_status_and_counts_unique_only(self) -> None:
        conn = self._conn()
        try:
            self._seed_session(conn, "session-a")
            result_a = self._end(conn, "session-a")
            self.assertTrue(result_a["newly_counted"])
            self.assertEqual(result_a["curation"]["sessions_since_last_curation"], 1)
            self.assertFalse(result_a["curation"]["recommended"])

            # Re-ending the same session must not increment the counter.
            result_a_again = self._end(conn, "session-a")
            self.assertFalse(result_a_again["newly_counted"])
            self.assertEqual(result_a_again["curation"]["sessions_since_last_curation"], 1)
        finally:
            conn.close()

    def test_threshold_trips_after_five_unique_sessions(self) -> None:
        conn = self._conn()
        try:
            last = None
            for i in range(5):
                sid = f"session-{i}"
                self._seed_session(conn, sid, fixture_idx=i)
                last = self._end(conn, sid)
            assert last is not None
            self.assertTrue(last["curation"]["recommended"])
            self.assertEqual(last["curation"]["sessions_since_last_curation"], 5)
        finally:
            conn.close()

    def test_curate_candidates_includes_built_at_version_and_compact_rows(self) -> None:
        from memory_operations import build_curation_candidates

        conn = self._conn()
        try:
            self._seed_session(conn, "session-cand-1")
            self._end(conn, "session-cand-1")
            packet = build_curation_candidates(conn, mode="compact")
            self.assertIn("built_at_version", packet)
            self.assertEqual(packet["built_at_version"], 0)
            self.assertEqual(packet["mode"], "compact")
            self.assertGreaterEqual(packet["token_budget_estimate"], 1)
            for row in packet["recent_claim_results"]:
                self.assertNotIn("raw_question", row)
                self.assertNotIn("raw_answer", row)
                self.assertNotIn("corrected_rule", row)
            self.assertIn("instructions", packet)
        finally:
            conn.close()

    def test_quick_answer_claim_results_can_inform_curation_without_recent_session_weight(self) -> None:
        from memory_operations import build_curation_candidates

        conn = self._conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="quick-curation-1",
                topic="pupillary pathways",
                concept="edinger westphal pathway",
                question="How does the Edinger-Westphal pathway work?",
                answer="The preganglionic parasympathetic fibers travel with CN III to the ciliary ganglion, then short ciliary nerves constrict the pupil.",
                correct=2,
                skill="quick-answer",
                tested_claim="Edinger-Westphal parasympathetic output reaches the sphincter pupillae through CN III, ciliary ganglion, and short ciliary nerves.",
                learner_claim="Question-only exchange; no learner performance assessed.",
                teaching_intent="quick_answer_reference",
                learning_operation="sequencing",
                coverage_role="synthesis",
                answer_mode="after_teaching",
            )
            study_memory.end_session(
                conn,
                session_id="quick-curation-1",
                summary="Answered a quick reference question about the Edinger-Westphal pathway.",
                next_strategy="If revisited, ask for the afferent and efferent limbs of the pupillary light reflex.",
            )

            packet = build_curation_candidates(conn, mode="compact")
            self.assertEqual(packet["recent_sessions"], [])
            self.assertEqual(packet["curation_state"]["sessions_since_last_curation"], 0)
            self.assertEqual(len(packet["recent_claim_results"]), 1)
            self.assertEqual(packet["recent_claim_results"][0]["skill"], "quick-answer")
            self.assertEqual(packet["recent_claim_results"][0]["topic"], "pupillary-pathways")
            self.assertIn("quick-answer", packet["instructions"]["skill_weighting"])
            self.assertIn("Low-stakes reference capture", packet["instructions"]["skill_weighting"]["quick-answer"])
        finally:
            conn.close()

    def test_curate_candidates_detailed_mode_adds_corrected_rule(self) -> None:
        from memory_operations import build_curation_candidates

        conn = self._conn()
        try:
            self._seed_session(conn, "session-det-1")
            self._end(conn, "session-det-1")
            packet = build_curation_candidates(conn, mode="detailed")
            self.assertTrue(packet["recent_claim_results"])
            self.assertIn("corrected_rule", packet["recent_claim_results"][0])
        finally:
            conn.close()

    def test_apply_curation_rejects_stale_version(self) -> None:
        from memory_operations import CurationError, apply_curation_payload

        conn = self._conn()
        try:
            cr_id_a = self._seed_session(conn, "session-stale-1", fixture_idx=0)
            cr_id_b = self._seed_session(conn, "session-stale-2", fixture_idx=1)
            self._end(conn, "session-stale-1")
            self._end(conn, "session-stale-2")
            payload = {
                "built_at_version": 99,
                "summaries": [
                    {
                        "client_id": "s1",
                        "summary_type": "thematic",
                        "topic_slug": "hypertension-management-neuro-emergencies",
                        "content": "Pressor unit confusion recurs across SAH DCI vignettes.",
                        "importance_score": 0.8,
                        "evidence_claim_result_ids": [cr_id_a, cr_id_b],
                    }
                ],
            }
            with self.assertRaises(CurationError) as ctx:
                apply_curation_payload(conn, payload)
            self.assertIn("stale built_at_version", str(ctx.exception))
        finally:
            conn.close()

    def test_apply_curation_rejects_invalid_evidence_ids(self) -> None:
        from memory_operations import CurationError, apply_curation_payload

        conn = self._conn()
        try:
            cr_id = self._seed_session(conn, "session-bad-evidence")
            self._end(conn, "session-bad-evidence")
            payload = {
                "built_at_version": 0,
                "summaries": [
                    {
                        "client_id": "s1",
                        "summary_type": "thematic",
                        "topic_slug": "hypertension-management-neuro-emergencies",
                        "content": "Synthesis content.",
                        "importance_score": 0.6,
                        "evidence_claim_result_ids": [cr_id, 999_999],
                    }
                ],
            }
            with self.assertRaises(CurationError) as ctx:
                apply_curation_payload(conn, payload)
            self.assertIn("unknown claim_result_ids", str(ctx.exception))
        finally:
            conn.close()

    def test_apply_curation_writes_evidence_joins_and_increments_version(self) -> None:
        from memory_operations import apply_curation_payload

        conn = self._conn()
        try:
            cr_id_a = self._seed_session(conn, "session-apply-1", fixture_idx=0)
            cr_id_b = self._seed_session(conn, "session-apply-2", fixture_idx=1)
            self._end(conn, "session-apply-1")
            self._end(conn, "session-apply-2")
            payload = {
                "built_at_version": 0,
                "summaries": [
                    {
                        "client_id": "s1",
                        "summary_type": "thematic",
                        "topic_slug": "hypertension-management-neuro-emergencies",
                        "content": "Pressor unit confusion recurs.",
                        "importance_score": 0.85,
                        "evidence_claim_result_ids": [cr_id_a, cr_id_b],
                    }
                ],
            }
            result = apply_curation_payload(conn, payload)
            self.assertTrue(result["ok"])
            self.assertEqual(result["new_version"], 1)
            summary_id = result["summaries_created"][0]
            joins = conn.execute(
                "SELECT claim_result_id FROM memory_summary_evidence WHERE summary_id = ? ORDER BY claim_result_id",
                (summary_id,),
            ).fetchall()
            self.assertEqual(
                sorted(int(r["claim_result_id"]) for r in joins),
                sorted([cr_id_a, cr_id_b]),
            )
            state = conn.execute("SELECT * FROM curation_state WHERE id = 1").fetchone()
            self.assertEqual(int(state["sessions_since_last_curation"]), 0)
            self.assertEqual(int(state["last_curation_version"]), 1)
        finally:
            conn.close()

    def test_supersede_marks_old_summary_superseded(self) -> None:
        from memory_operations import apply_curation_payload

        conn = self._conn()
        try:
            cr_id_a = self._seed_session(conn, "session-supersede-1", fixture_idx=0)
            cr_id_b = self._seed_session(conn, "session-supersede-2", fixture_idx=1)
            self._end(conn, "session-supersede-1")
            self._end(conn, "session-supersede-2")
            first = apply_curation_payload(
                conn,
                {
                    "built_at_version": 0,
                    "summaries": [
                        {
                            "client_id": "s1",
                            "summary_type": "thematic",
                            "topic_slug": "hypertension-management-neuro-emergencies",
                            "content": "Old synthesis.",
                            "importance_score": 0.7,
                            "evidence_claim_result_ids": [cr_id_a, cr_id_b],
                        }
                    ],
                },
            )
            old_id = first["summaries_created"][0]
            second = apply_curation_payload(
                conn,
                {
                    "built_at_version": 1,
                    "summaries": [
                        {
                            "client_id": "s2",
                            "summary_type": "thematic",
                            "topic_slug": "hypertension-management-neuro-emergencies",
                            "content": "Updated synthesis.",
                            "importance_score": 0.8,
                            "evidence_claim_result_ids": [cr_id_a, cr_id_b],
                        }
                    ],
                    "supersede_summary_ids": [old_id],
                },
            )
            self.assertIn(old_id, second["superseded"])
            status_old = conn.execute("SELECT status FROM memory_summaries WHERE id = ?", (old_id,)).fetchone()
            self.assertEqual(status_old["status"], "superseded")
        finally:
            conn.close()

    def test_invalid_relation_type_rejected(self) -> None:
        from memory_operations import CurationError, apply_curation_payload

        conn = self._conn()
        try:
            cr_id_a = self._seed_session(conn, "session-rel-bad-1", fixture_idx=0)
            cr_id_b = self._seed_session(conn, "session-rel-bad-2", fixture_idx=1)
            self._end(conn, "session-rel-bad-1")
            self._end(conn, "session-rel-bad-2")
            concept_ids = [int(r["concept_id"]) for r in conn.execute("SELECT DISTINCT concept_id FROM claim_results").fetchall()]
            payload = {
                "built_at_version": 0,
                "relationships": [
                    {
                        "source_concept_id": concept_ids[0],
                        "target_concept_id": concept_ids[1],
                        "relation_type": "related_by_topic",
                        "strength": 0.7,
                        "evidence_claim_result_ids": [cr_id_a],
                    }
                ],
            }
            with self.assertRaises(CurationError) as ctx:
                apply_curation_payload(conn, payload)
            self.assertIn("relation_type", str(ctx.exception))
        finally:
            conn.close()

    def test_self_edge_rejected(self) -> None:
        from memory_operations import CurationError, apply_curation_payload

        conn = self._conn()
        try:
            cr_id = self._seed_session(conn, "session-self-edge")
            self._end(conn, "session-self-edge")
            concept_id = int(conn.execute("SELECT concept_id FROM claim_results LIMIT 1").fetchone()["concept_id"])
            payload = {
                "built_at_version": 0,
                "relationships": [
                    {
                        "source_concept_id": concept_id,
                        "target_concept_id": concept_id,
                        "relation_type": "confused_with",
                        "strength": 0.7,
                        "evidence_claim_result_ids": [cr_id],
                    }
                ],
            }
            with self.assertRaises(CurationError) as ctx:
                apply_curation_payload(conn, payload)
            self.assertIn("self-edge", str(ctx.exception))
        finally:
            conn.close()

    def test_single_evidence_summary_rejected(self) -> None:
        from memory_operations import CurationError, apply_curation_payload

        conn = self._conn()
        try:
            cr_id = self._seed_session(conn, "session-evidence-floor")
            self._end(conn, "session-evidence-floor")
            payload = {
                "built_at_version": 0,
                "summaries": [
                    {
                        "client_id": "s1",
                        "summary_type": "thematic",
                        "topic_slug": "hypertension-management-neuro-emergencies",
                        "content": "Solo claim summary.",
                        "importance_score": 0.5,
                        "evidence_claim_result_ids": [cr_id],
                    }
                ],
            }
            with self.assertRaises(CurationError) as ctx:
                apply_curation_payload(conn, payload)
            self.assertIn("evidence floor", str(ctx.exception))
        finally:
            conn.close()

    def test_summary_include_curated_returns_curated_block(self) -> None:
        from memory_operations import apply_curation_payload

        conn = self._conn()
        try:
            cr_id_a = self._seed_session(conn, "session-incl-1", fixture_idx=0)
            cr_id_b = self._seed_session(conn, "session-incl-2", fixture_idx=1)
            self._end(conn, "session-incl-1")
            self._end(conn, "session-incl-2")
            apply_curation_payload(
                conn,
                {
                    "built_at_version": 0,
                    "summaries": [
                        {
                            "client_id": "s1",
                            "summary_type": "thematic",
                            "topic_slug": "hypertension-management-neuro-emergencies",
                            "content": "Cross-session pressor pattern.",
                            "importance_score": 0.9,
                            "evidence_claim_result_ids": [cr_id_a, cr_id_b],
                        }
                    ],
                },
            )
            raw = study_memory.retrieval_summary(
                conn,
                topic="hypertension management",
                limit=8,
                include_curated=True,
            )
            payload = json.loads(raw)
            self.assertIn("curated_summaries", payload)
            self.assertIn("graph_signals", payload)
            self.assertEqual(len(payload["curated_summaries"]), 1)
            self.assertEqual(payload["curated_summaries"][0]["summary_type"], "thematic")
        finally:
            conn.close()

    def test_concept_scoped_summary_does_not_leak_into_other_topic_retrieval(self) -> None:
        from memory_operations import apply_curation_payload

        conn = self._conn()
        try:
            cr_id_a = self._seed_session(conn, "session-leak-a", fixture_idx=0)
            cr_id_b = self._seed_session(conn, "session-leak-b", fixture_idx=1)
            self._end(conn, "session-leak-a")
            self._end(conn, "session-leak-b")
            concept_id = int(conn.execute("SELECT concept_id FROM claim_results LIMIT 1").fetchone()["concept_id"])
            apply_curation_payload(
                conn,
                {
                    "built_at_version": 0,
                    "summaries": [
                        {
                            "client_id": "concept_only",
                            "summary_type": "proficiency_map",
                            "concept_id": concept_id,
                            "content": "Concept-scoped synthesis attached only to this concept.",
                            "importance_score": 0.7,
                            "evidence_claim_result_ids": [cr_id_a, cr_id_b],
                        }
                    ],
                },
            )
            raw = study_memory.retrieval_summary(
                conn,
                topic="tbi management",
                limit=4,
                include_curated=True,
            )
            payload = json.loads(raw)
            self.assertEqual(
                payload["curated_summaries"],
                [],
                f"concept-scoped summary leaked into unrelated topic retrieval: {payload['curated_summaries']!r}",
            )
        finally:
            conn.close()

    def test_default_summary_output_unchanged_when_curated_flag_absent(self) -> None:
        conn = self._conn()
        try:
            self._seed_session(conn, "session-default-summary")
            self._end(conn, "session-default-summary")
            raw = study_memory.retrieval_summary(
                conn,
                topic="hypertension management",
                limit=8,
            )
            payload = json.loads(raw)
            self.assertNotIn("curated_summaries", payload)
            self.assertNotIn("graph_signals", payload)
        finally:
            conn.close()

    def test_focus_filter_drops_non_relevant_curated_summaries(self) -> None:
        """Curated summaries that cite no concept in returned cards are dropped,
        except for the top `anchor_count` summaries by importance."""
        from memory_operations import apply_curation_payload

        conn = self._conn()
        try:
            # Seed two distinct concepts under the hypertension topic with low
            # scores so they produce must_retest cards when we query that topic.
            cr_id_a = self._seed_session(conn, "session-focus-a", fixture_idx=0)
            self._end(conn, "session-focus-a")
            cr_id_a2 = self._seed_session(conn, "session-focus-a2", fixture_idx=0)
            self._end(conn, "session-focus-a2")

            # Seed claim_results under a DIFFERENT topic so their concept_ids are
            # not in the returned cards for a hypertension query. These will back
            # the anchor and non-relevant summaries that are topic-scoped to
            # hypertension but cite TBI-domain evidence.
            cr_id_c = self._seed_session(conn, "session-focus-c", fixture_idx=2, topic="tbi management")
            self._end(conn, "session-focus-c")
            cr_id_c2 = self._seed_session(conn, "session-focus-c2", fixture_idx=2, topic="tbi management")
            self._end(conn, "session-focus-c2")
            apply_curation_payload(
                conn,
                {
                    "built_at_version": 0,
                    "summaries": [
                        {
                            "client_id": "anchor_high_imp",
                            "summary_type": "thematic",
                            "topic_slug": "hypertension-management-neuro-emergencies",
                            "content": "Dominant fault line on labetalol indications and dose.",
                            "importance_score": 0.95,
                            "evidence_claim_result_ids": [cr_id_c, cr_id_c2],
                        },
                        {
                            "client_id": "relevant_to_returned",
                            "summary_type": "thematic",
                            "topic_slug": "hypertension-management-neuro-emergencies",
                            "content": "Norepinephrine dosing units recur as a fault line.",
                            "importance_score": 0.7,
                            "evidence_claim_result_ids": [cr_id_a, cr_id_a2],
                        },
                        {
                            "client_id": "not_relevant",
                            "summary_type": "thematic",
                            "topic_slug": "hypertension-management-neuro-emergencies",
                            "content": "Labetalol PK details, low-priority context.",
                            "importance_score": 0.4,
                            "evidence_claim_result_ids": [cr_id_c, cr_id_c2],
                        },
                    ],
                },
            )

            # Retrieve with the topic limited so only fixtures 0+1 concepts appear
            # in cards (anchor's cited concept does not appear in must_retest).
            raw = study_memory.retrieval_summary(
                conn,
                topic="hypertension management",
                limit=4,
                include_curated=True,
            )
            payload = json.loads(raw)
            contents = [s["content"] for s in payload["curated_summaries"]]

            # Anchor (highest importance) is always present even though it cites a
            # non-returned concept.
            self.assertTrue(
                any("Dominant fault line on labetalol" in c for c in contents),
                f"high-importance anchor was dropped: {contents}",
            )
            # Relevant summary (cites fixture-0 concept, in must_retest set) is kept.
            self.assertTrue(
                any("Norepinephrine dosing units" in c for c in contents),
                f"relevant summary was dropped: {contents}",
            )
            # Non-relevant low-importance summary is dropped.
            self.assertFalse(
                any("Labetalol PK details" in c for c in contents),
                f"non-relevant low-importance summary leaked through filter: {contents}",
            )
        finally:
            conn.close()

    def test_graph_signals_capped_to_top_three_must_retest(self) -> None:
        """Graph signals only traverse from the top 3 must_retest concepts by priority,
        regardless of how many must_retest cards are returned."""
        from memory_operations import apply_curation_payload

        conn = self._conn()
        try:
            # Seed 5 distinct concepts under the same topic with low scores.
            cr_ids = []
            for i in range(5):
                cr_ids.append(self._seed_session(conn, f"session-cap-{i}", fixture_idx=i))
                self._end(conn, f"session-cap-{i}")

            # Pull concept_ids in card-return order (priority/recency).
            concept_rows = conn.execute(
                """SELECT DISTINCT cs.concept_id FROM claim_state cs
                   WHERE cs.state IN ('missed','partially_repaired','regressed')
                   ORDER BY cs.last_seen_ts DESC""",
            ).fetchall()
            concept_ids = [int(r["concept_id"]) for r in concept_rows]
            self.assertGreaterEqual(len(concept_ids), 5)

            # Pair concept 0 with concept 4 by a confused_with edge of strength 0.8
            # (above the visibility floor). If the cap is enforced, this edge will
            # NOT appear because concept 4 is the 5th must_retest, beyond the cap.
            # First author a multi-evidence summary so the relationship has anchor.
            apply_curation_payload(
                conn,
                {
                    "built_at_version": 0,
                    "summaries": [
                        {
                            "client_id": "anchor",
                            "summary_type": "thematic",
                            "topic_slug": "hypertension-management-neuro-emergencies",
                            "content": "Anchor summary for the cap test.",
                            "importance_score": 0.8,
                            "evidence_claim_result_ids": [cr_ids[0], cr_ids[4]],
                        }
                    ],
                    "relationships": [
                        {
                            "source_concept_id": concept_ids[0],
                            "target_concept_id": concept_ids[4],
                            "relation_type": "confused_with",
                            "strength": 0.8,
                            "evidence_summary_client_id": "anchor",
                            "evidence_claim_result_ids": [cr_ids[0], cr_ids[4]],
                        }
                    ],
                },
            )

            raw = study_memory.retrieval_summary(
                conn,
                topic="hypertension management",
                limit=10,
                include_curated=True,
            )
            payload = json.loads(raw)
            # graph_signals should be empty: concept[0] and concept[4] don't both
            # fit in the top-3 must_retest window in any ordering of 5 cards.
            # (At minimum, concept 4 is outside the cap.)
            from_concepts = {int(g["from_concept_id"]) for g in payload["graph_signals"]}
            to_concepts = {int(g["to_concept_id"]) for g in payload["graph_signals"]}
            # The cap means at most 3 distinct from_concept ids appear.
            self.assertLessEqual(
                len(from_concepts), 3,
                f"graph_signals fired from more than 3 must_retest concepts: {from_concepts}",
            )
        finally:
            conn.close()

    def test_graph_signal_emitted_for_confused_with_above_floor(self) -> None:
        from memory_operations import apply_curation_payload

        conn = self._conn()
        try:
            cr_id_a = self._seed_session(conn, "session-graph-1", fixture_idx=0)
            cr_id_b = self._seed_session(conn, "session-graph-2", fixture_idx=1)
            self._end(conn, "session-graph-1")
            self._end(conn, "session-graph-2")
            rows = conn.execute("SELECT DISTINCT concept_id FROM claim_results ORDER BY concept_id").fetchall()
            concept_ids = [int(r["concept_id"]) for r in rows]
            self.assertGreaterEqual(len(concept_ids), 2)
            apply_curation_payload(
                conn,
                {
                    "built_at_version": 0,
                    "summaries": [
                        {
                            "client_id": "s1",
                            "summary_type": "thematic",
                            "topic_slug": "hypertension-management-neuro-emergencies",
                            "content": "Cross-confusion observed.",
                            "importance_score": 0.9,
                            "evidence_claim_result_ids": [cr_id_a, cr_id_b],
                        }
                    ],
                    "relationships": [
                        {
                            "source_concept_id": concept_ids[0],
                            "target_concept_id": concept_ids[1],
                            "relation_type": "confused_with",
                            "strength": 0.8,
                            "evidence_summary_client_id": "s1",
                            "evidence_claim_result_ids": [cr_id_a, cr_id_b],
                        }
                    ],
                },
            )
            raw = study_memory.retrieval_summary(
                conn,
                topic="hypertension management",
                limit=8,
                include_curated=True,
            )
            payload = json.loads(raw)
            self.assertTrue(
                any(g["relation_type"] == "confused_with" for g in payload["graph_signals"]),
                f"expected at least one confused_with graph signal, got {payload['graph_signals']!r}",
            )
        finally:
            conn.close()

    def test_prerequisite_graph_signal_preserves_direction(self) -> None:
        from memory_operations import apply_curation_payload

        conn = self._conn()
        try:
            cr_foundation = self._seed_session(
                conn,
                "session-prereq-foundation",
                topic="evd management in icu",
                fixture_idx=0,
            )
            cr_dependent = self._seed_session(
                conn,
                "session-prereq-dependent",
                topic="evd management in icu",
                fixture_idx=1,
            )
            concept_ids = [
                int(r["concept_id"])
                for r in conn.execute("SELECT DISTINCT concept_id FROM claim_results ORDER BY concept_id").fetchall()
            ]
            self.assertGreaterEqual(len(concept_ids), 2)
            apply_curation_payload(
                conn,
                {
                    "built_at_version": 0,
                    "summaries": [
                        {
                            "client_id": "prereq-summary",
                            "summary_type": "thematic",
                            "topic_slug": "evd-management-icu",
                            "content": "A dependent EVD management miss appears downstream of a shaky prerequisite.",
                            "importance_score": 0.9,
                            "evidence_claim_result_ids": [cr_foundation, cr_dependent],
                        }
                    ],
                    "relationships": [
                        {
                            "source_concept_id": concept_ids[0],
                            "target_concept_id": concept_ids[1],
                            "relation_type": "prerequisite",
                            "strength": 0.9,
                            "evidence_summary_client_id": "prereq-summary",
                            "evidence_claim_result_ids": [cr_foundation, cr_dependent],
                        }
                    ],
                },
            )

            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="evd management in icu",
                    limit=8,
                    include_curated=True,
                )
            )
            signals = payload["graph_signals"]
            self.assertTrue(any(g["relation_type"] == "prerequisite" for g in signals), signals)
            directions = {g["direction"] for g in signals if g["relation_type"] == "prerequisite"}
            self.assertIn("prerequisite_of_current", directions)
            self.assertIn("depends_on_current", directions)
        finally:
            conn.close()

    def test_shadow_rule_requires_evidence_and_surfaces_bounded_probe(self) -> None:
        from memory_operations import CurationError, apply_curation_payload

        conn = self._conn()
        try:
            cr_a = self._seed_session(conn, "shadow-a", fixture_idx=0)
            cr_b = self._seed_session(conn, "shadow-b", fixture_idx=1)
            concept_id = int(conn.execute("SELECT concept_id FROM claim_results WHERE id = ?", (cr_a,)).fetchone()["concept_id"])
            base_rule = {
                "false_rule": "Any hypertensive neuro emergency should be normalized immediately.",
                "corrected_rule": "Match blood pressure action to pathology and perfusion physiology.",
                "clinical_consequence": "Reflex lowering can worsen cerebral or spinal cord perfusion.",
                "probe_shape": "Present bradycardic hypertension across two pathologies and require the management split.",
                "severity": "urgent",
                "bindings": [{"concept_id": concept_id, "binding_type": "trigger"}],
            }
            with self.assertRaisesRegex(CurationError, "evidence floor"):
                apply_curation_payload(
                    conn,
                    {
                        "built_at_version": 0,
                        "shadow_rules": [{**base_rule, "evidence_claim_result_ids": [cr_a]}],
                    },
                )
            result = apply_curation_payload(
                conn,
                {
                    "built_at_version": 0,
                    "shadow_rules": [{**base_rule, "evidence_claim_result_ids": [cr_a, cr_b]}],
                },
            )
            self.assertEqual(len(result["shadow_rules_upserted"]), 1)
            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="hypertension management",
                    limit=8,
                    include_curated=True,
                )
            )
            signals = payload["shadow_rule_signals"]
            self.assertEqual(len(signals), 1)
            self.assertEqual(signals[0]["severity"], "urgent")
            self.assertIn("changed-frame", signals[0]["next_action"])
        finally:
            conn.close()

    def test_shadow_rule_extinction_requires_changed_frame_and_two_transfer_contexts(self) -> None:
        from memory_operations import apply_curation_payload

        conn = self._conn()
        try:
            miss_a = self._seed_session(conn, "shadow-extinct-miss-a", fixture_idx=0)
            miss_b = self._seed_session(conn, "shadow-extinct-miss-b", fixture_idx=1)
            concept_id = int(conn.execute("SELECT concept_id FROM claim_results WHERE id = ?", (miss_a,)).fetchone()["concept_id"])
            rule_id = apply_curation_payload(
                conn,
                {
                    "built_at_version": 0,
                    "shadow_rules": [{
                        "false_rule": "All severe hypertension requires immediate lowering.",
                        "corrected_rule": "First classify whether hypertension is compensatory or injurious.",
                        "clinical_consequence": "Incorrect lowering can reduce perfusion.",
                        "probe_shape": "Contrast Cushing physiology, autonomic dysreflexia, and ICH.",
                        "severity": "urgent",
                        "evidence_claim_result_ids": [miss_a, miss_b],
                        "bindings": [{"concept_id": concept_id, "binding_type": "trigger"}],
                    }],
                },
            )["shadow_rules_upserted"][0]
            pass_ids = [
                self._seed_session(conn, f"shadow-pass-{idx}", fixture_idx=idx, score=2)
                for idx in range(3)
            ]
            first = study_memory.record_shadow_rule_check(
                conn,
                shadow_rule_id=rule_id,
                claim_result_id=pass_ids[0],
                context_label="tumor herniation",
                check_type="changed_frame",
                outcome="pass",
                apply=True,
            )
            self.assertEqual(first["status"], "repaired")
            second = study_memory.record_shadow_rule_check(
                conn,
                shadow_rule_id=rule_id,
                claim_result_id=pass_ids[1],
                context_label="autonomic dysreflexia",
                check_type="transfer",
                outcome="pass",
                apply=True,
            )
            self.assertEqual(second["status"], "repaired")
            third = study_memory.record_shadow_rule_check(
                conn,
                shadow_rule_id=rule_id,
                claim_result_id=pass_ids[2],
                context_label="intracerebral hemorrhage",
                check_type="transfer",
                outcome="pass",
                apply=True,
            )
            self.assertEqual(third["status"], "extinguished")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
