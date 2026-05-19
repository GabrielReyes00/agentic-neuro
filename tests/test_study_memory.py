from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import study_memory


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

    def test_dense_exchange_logs_multiple_claims_without_duplicate_exchanges(self) -> None:
        conn = self._memory_conn()
        try:
            question = "Same SBP 190: unsecured SAH, ICH, TBI with high ICP, and ischemic stroke no tPA?"
            answer = "SAH <160, ICH 130-140, TBI raise MAP for CPP, stroke permissive to 220/120."
            study_memory.log_exchange_claims(
                conn,
                session_id="dense-session",
                topic="hypertension management",
                question=question,
                answer=answer,
                claims=[
                    {
                        "concept": "unsecured sah bp target",
                        "correct": 2,
                        "tested_claim": "Unsecured aneurysmal SAH should be lowered to SBP <160 while preserving CPP.",
                        "corrected_rule": "Target SBP <160 before securing; avoid aggressive normalization.",
                    },
                    {
                        "concept": "acute ich bp target",
                        "correct": 2,
                        "tested_claim": "Acute spontaneous ICH should be lowered to SBP 130-140 and avoid SBP below 130.",
                        "corrected_rule": "Target SBP 130-140; avoid below 130.",
                    },
                    {
                        "concept": "tbi cpp map augmentation",
                        "correct": 2,
                        "tested_claim": "In ICP-monitored TBI, calculate CPP=MAP-ICP and raise MAP to CPP 60-70 when low.",
                        "corrected_rule": "Raise MAP when CPP is low despite acceptable SBP.",
                    },
                    {
                        "concept": "ischemic stroke permissive hypertension",
                        "correct": 2,
                        "tested_claim": "Acute ischemic stroke without tPA allows permissive hypertension up to 220/120.",
                        "corrected_rule": "Do not lower unless above 220/120 or end-organ emergency.",
                    },
                ],
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM exchanges").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_results").fetchone()[0], 4)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_state").fetchone()[0], 4)
            turns = conn.execute("SELECT turn FROM exchanges").fetchall()
            self.assertEqual([row["turn"] for row in turns], [1])
        finally:
            conn.close()

    def test_dense_exchange_mixed_scores_create_separate_states(self) -> None:
        conn = self._memory_conn()
        try:
            study_memory.log_exchange_claims(
                conn,
                session_id="dense-mixed",
                topic="hypertension management",
                question="Compare agents in elevated ICP.",
                answer="Nicardipine ok, labetalol beta-only ok, nitroprusside may help venous drainage.",
                claims=[
                    {
                        "concept": "nicardipine icp neutrality",
                        "correct": 2,
                        "tested_claim": "Nicardipine is acceptable in ICP-risk BP lowering because it is clinically ICP-neutral.",
                        "corrected_rule": "Nicardipine is clinically ICP-neutral.",
                    },
                    {
                        "concept": "labetalol mechanism",
                        "correct": 1,
                        "tested_claim": "Labetalol is combined alpha-1 and beta blockade and is clinically ICP-neutral.",
                        "missing_edge": "labetalol is not beta-only; it has alpha-1 blockade",
                        "corrected_rule": "Labetalol is alpha-1 plus beta blockade.",
                        "error_type": "conceptual_confusion",
                    },
                    {
                        "concept": "nitroprusside icp effect",
                        "correct": 0,
                        "tested_claim": "Nitroprusside is avoided in elevated ICP because cerebral vasodilation raises CBV/ICP.",
                        "missing_edge": "cerebral vasodilation raises CBV and ICP",
                        "corrected_rule": "Avoid nitroprusside in ICP-risk patients.",
                        "error_type": "conceptual_confusion",
                        "misconception": "believed venodilation may help ICP",
                    },
                ],
            )
            states = {
                row["claim_text"]: row["state"]
                for row in conn.execute("SELECT claim_text, state FROM claim_state")
            }
            self.assertIn("durable", states.values())
            self.assertIn("partially_repaired", states.values())
            self.assertIn("missed", states.values())
            summary = study_memory.retrieval_summary(conn, topic="hypertension management", limit=10)
            self.assertIn("must_retest", summary)
            self.assertIn("scaffold", summary)
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


if __name__ == "__main__":
    unittest.main()
