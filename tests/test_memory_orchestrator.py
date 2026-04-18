from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knowledge_graph import KnowledgeGraph
from memory_orchestrator import _build_parser, _dispatch


class MemoryOrchestratorRecordAnswerTests(unittest.TestCase):
    def test_record_answer_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                args = _build_parser().parse_args([
                    "record-answer",
                    "--session-ts", "2026-04-15T12:00:00+00:00",
                    "--turn", "1",
                    "--skill", "test-skill",
                    "--topic", "aneurysm clipping workflow",
                    "--concept", "temporary clip rationale",
                    "--question", "Why use a temporary clip before final clipping?",
                    "--answer", "To soften the aneurysm and reduce rupture risk.",
                    "--correct", "1",
                    "--correction", "Also confirm collateral flow and limit occlusion time.",
                    "--error-type", "omission",
                    "--misconception", "temporary clipping only reduces sac pressure",
                    "--root-cause", "incomplete operative workflow model",
                    "--remediation", "review clip sequence and ischemia timing",
                ])
                result = _dispatch(args, kg)
                self.assertTrue(result["ok"])
                self.assertIn("exchange_id", result)

                row = kg.conn.execute(
                    "SELECT COUNT(*) AS n FROM learning_exchanges WHERE exchange_id = ?",
                    (result["exchange_id"],),
                ).fetchone()
                self.assertEqual(row["n"], 1)

                v2 = kg.conn.execute(
                    """SELECT mastery_prob, familiarity_prob, dominant_misconception,
                              evidence_event_ids, evidence_exchange_ids
                       FROM learner_concept_state
                       WHERE concept_text = 'temporary clip rationale'"""
                ).fetchone()
                self.assertIsNotNone(v2)
                self.assertGreater(v2["mastery_prob"], 0.0)
                self.assertGreater(v2["familiarity_prob"], 0.0)
                self.assertIn(str(result["memory_event_id"]), v2["evidence_event_ids"])
                self.assertIn(str(result["exchange_id"]), v2["evidence_exchange_ids"])
            finally:
                kg.close()

    def test_record_answer_invalid_correct(self) -> None:
        parser = _build_parser()
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args([
                    "record-answer",
                    "--session-ts", "2026-04-15T12:00:00+00:00",
                    "--turn", "1",
                    "--skill", "test-skill",
                    "--topic", "aneurysm clipping workflow",
                    "--concept", "temporary clip rationale",
                    "--question", "Question?",
                    "--answer", "Answer.",
                    "--correct", "5",
                ])

    def test_record_answer_auto_routes_to_active_memory_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                active_ts = "2026-04-15T12:00:00+00:00"
                accidental_ts = "2026-04-15T12:05:00+00:00"
                kg.set_memory_session(
                    session_ts=active_ts,
                    skill="study-material",
                    topic_text="Neuroimaging Lab 2",
                    memory_enabled=True,
                    consent_scope="study_session",
                )
                args = _build_parser().parse_args([
                    "record-answer",
                    "--session-ts", accidental_ts,
                    "--turn", "1",
                    "--skill", "study-material",
                    "--topic", "Neuroimaging Lab 2",
                    "--concept", "hydrocephalus types",
                    "--question", "Communicating vs non-communicating hydrocephalus?",
                    "--answer", "Communicating affects all ventricles.",
                    "--correct", "2",
                ])
                result = _dispatch(args, kg)
                self.assertTrue(result["ok"])
                self.assertTrue(result["session_resolution"]["changed"])
                self.assertEqual(result["session_resolution"]["session_ts"], active_ts)

                row = kg.conn.execute(
                    """SELECT session_ts FROM learning_exchanges
                       WHERE exchange_id = ?""",
                    (result["exchange_id"],),
                ).fetchone()
                self.assertEqual(row["session_ts"], active_ts)
            finally:
                kg.close()

    def test_record_passive_is_exposure_not_mastery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                kg.set_memory_session(
                    session_ts="2026-04-15T12:00:00+00:00",
                    skill="study-session",
                    topic_text="vasospasm surveillance",
                    memory_enabled=True,
                    consent_scope="study_session",
                )
                args = _build_parser().parse_args([
                    "record-passive",
                    "--session-ts", "2026-04-15T12:00:00+00:00",
                    "--turn", "1",
                    "--skill", "study-session",
                    "--topic", "vasospasm surveillance",
                    "--concept", "MCA velocity threshold",
                    "--content", "MCA mean flow velocity above 120 cm/s suggests vasospasm.",
                ])
                result = _dispatch(args, kg)
                self.assertTrue(result["ok"])

                event = kg.conn.execute(
                    "SELECT event_type FROM memory_events WHERE memory_event_id = ?",
                    (result["memory_event_id"],),
                ).fetchone()
                self.assertEqual(event["event_type"], "teaching_exposure")

                state = kg.conn.execute(
                    """SELECT mastery_prob, familiarity_prob, last_active_tested_at,
                              last_passive_exposed_at
                       FROM learner_concept_state
                       WHERE concept_text = 'mca velocity threshold'"""
                ).fetchone()
                self.assertIsNotNone(state)
                self.assertEqual(state["mastery_prob"], 0.0)
                self.assertGreater(state["familiarity_prob"], 0.0)
                self.assertIsNone(state["last_active_tested_at"])
                self.assertIsNotNone(state["last_passive_exposed_at"])
            finally:
                kg.close()

    def test_document_profile_stores_rapid_review_mode_and_context_pack_retrieves_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                sample = "\n".join(
                    f"**[Q{i}]** [recall]\nWhat is item {i}?\n<details><summary>Answer</summary>A{i}</details>"
                    for i in range(1, 8)
                )
                args = _build_parser().parse_args([
                    "document-profile",
                    "--doc", "Study Material/Neuroimaging Lab 2.md",
                    "--doc-type", "study-material",
                    "--content-sample", sample,
                    "--apply",
                ])
                profile = _dispatch(args, kg)
                self.assertTrue(profile["ok"])
                self.assertEqual(profile["preferred_study_mode"], "rapid_review")
                self.assertEqual(profile["pacing_goal"], "throughput")
                self.assertGreaterEqual(profile["mode_confidence"], 0.75)
                self.assertGreater(profile["memory_item_id"], 0)

                row = kg.conn.execute(
                    """SELECT preferred_study_mode, source_kind, pacing_goal
                       FROM document_sessions WHERE doc_path = ?""",
                    ("Study Material/Neuroimaging Lab 2.md",),
                ).fetchone()
                self.assertEqual(row["preferred_study_mode"], "rapid_review")
                self.assertEqual(row["source_kind"], "review_material")
                self.assertEqual(row["pacing_goal"], "throughput")

                pack = kg.context_pack(
                    "Neuroimaging Lab 2 hydrocephalus",
                    topic_name="Neuroimaging Lab 2",
                    skill="study-material",
                    intent="teach",
                    max_tokens=1000,
                    log_retrieval=False,
                )
                self.assertIn("Document Study Mode", pack["text"])
                self.assertIn("mode=rapid_review", pack["text"])
                self.assertIn("high-throughput question deck", pack["text"])
            finally:
                kg.close()

    def test_active_correction_temporally_supersedes_misconception(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                wrong = _build_parser().parse_args([
                    "record-answer",
                    "--session-ts", "2026-04-15T12:00:00+00:00",
                    "--turn", "1",
                    "--skill", "study-session",
                    "--topic", "ICP management",
                    "--concept", "CPP definition",
                    "--question", "What is CPP?",
                    "--answer", "CPP is the same as ICP.",
                    "--correct", "0",
                    "--correction", "CPP equals MAP minus ICP.",
                    "--error-type", "conceptual_confusion",
                    "--misconception", "CPP and ICP are interchangeable",
                    "--root-cause", "pressure metric conflation",
                    "--remediation", "contrast compartment pressure versus perfusion gradient",
                ])
                wrong_result = _dispatch(wrong, kg)
                self.assertTrue(wrong_result["ok"])

                state = kg.conn.execute(
                    """SELECT mastery_prob, dominant_misconception
                       FROM learner_concept_state
                       WHERE concept_text = 'cpp definition'"""
                ).fetchone()
                self.assertEqual(state["dominant_misconception"], "CPP and ICP are interchangeable")
                wrong_mastery = state["mastery_prob"]

                correct = _build_parser().parse_args([
                    "record-answer",
                    "--session-ts", "2026-04-15T12:00:00+00:00",
                    "--turn", "2",
                    "--skill", "study-session",
                    "--topic", "ICP management",
                    "--concept", "CPP definition",
                    "--question", "What is CPP?",
                    "--answer", "CPP is MAP minus ICP.",
                    "--correct", "2",
                ])
                correct_result = _dispatch(correct, kg)
                self.assertTrue(correct_result["ok"])

                updated = kg.conn.execute(
                    """SELECT mastery_prob, dominant_misconception
                       FROM learner_concept_state
                       WHERE concept_text = 'cpp definition'"""
                ).fetchone()
                self.assertGreater(updated["mastery_prob"], wrong_mastery)
                self.assertEqual(updated["dominant_misconception"], "")

                duplicate_wrong = _dispatch(wrong, kg)
                self.assertTrue(duplicate_wrong["ok"])
                after_duplicate = kg.conn.execute(
                    """SELECT mastery_prob, dominant_misconception
                       FROM learner_concept_state
                       WHERE concept_text = 'cpp definition'"""
                ).fetchone()
                self.assertEqual(after_duplicate["dominant_misconception"], "")
                self.assertEqual(after_duplicate["mastery_prob"], updated["mastery_prob"])

                open_items = kg.conn.execute(
                    """SELECT COUNT(*) AS n FROM memory_items
                       WHERE item_type = 'learner_state'
                         AND concept_text = 'cpp definition'
                         AND (valid_to IS NULL OR valid_to = '')"""
                ).fetchone()
                closed_items = kg.conn.execute(
                    """SELECT COUNT(*) AS n FROM memory_items
                       WHERE item_type = 'learner_state'
                         AND concept_text = 'cpp definition'
                         AND valid_to != ''"""
                ).fetchone()
                self.assertEqual(open_items["n"], 1)
                self.assertGreaterEqual(closed_items["n"], 1)
            finally:
                kg.close()

    def test_context_pack_has_fixed_sections_and_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                args = _build_parser().parse_args([
                    "record-answer",
                    "--session-ts", "2026-04-15T12:00:00+00:00",
                    "--turn", "1",
                    "--skill", "study-session",
                    "--topic", "aneurysm clipping workflow",
                    "--concept", "temporary clip rationale",
                    "--question", "Why use a temporary clip before final clipping?",
                    "--answer", "It lowers sac pressure.",
                    "--correct", "1",
                    "--correction", "It also enables safer dissection and limits rupture risk while watching occlusion time.",
                    "--error-type", "omission",
                    "--misconception", "temporary clipping only lowers sac pressure",
                    "--root-cause", "incomplete operative workflow model",
                    "--remediation", "retest the sequence with ischemia timing",
                ])
                _dispatch(args, kg)

                pack = kg.context_pack(
                    "temporary clip rationale",
                    topic_name="aneurysm clipping workflow",
                    skill="study-session",
                    intent="review",
                    max_tokens=650,
                    log_retrieval=False,
                )
                required = {
                    "learner_state",
                    "recent_episode_continuity",
                    "prior_misconceptions_to_retest",
                    "mastered_anchors_to_avoid_reteaching",
                    "teaching_policy",
                    "evidence_ids",
                    "abstention_warnings",
                }
                self.assertTrue(required.issubset(set(pack["sections"])))
                self.assertLessEqual(pack["token_estimate"], 650)
                self.assertIn("Evidence IDs", pack["text"])
            finally:
                kg.close()

    def test_backfill_and_consolidate_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                args = _build_parser().parse_args([
                    "record-answer",
                    "--session-ts", "2026-04-15T12:00:00+00:00",
                    "--turn", "1",
                    "--skill", "study-session",
                    "--topic", "vasospasm surveillance",
                    "--concept", "MCA velocity threshold",
                    "--question", "What MCA velocity suggests vasospasm?",
                    "--answer", "Above 120 cm/s.",
                    "--correct", "2",
                ])
                _dispatch(args, kg)
                backfill = kg.memory_v2_backfill(apply=False)
                self.assertTrue(backfill["ok"])
                self.assertEqual(backfill["planned"]["learning_exchanges"], 1)

                consolidate = kg.consolidate_memory_v2(
                    session_ts="2026-04-15T12:00:00+00:00",
                    mode="dry-run",
                    embed=False,
                )
                self.assertTrue(consolidate["ok"])
                self.assertEqual(consolidate["planned"]["sessions"], 1)
            finally:
                kg.close()

    def test_anki_review_updates_v2_as_external_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                result = kg.record_anki_review_v2(
                    topic_name="vasospasm surveillance",
                    concept_text="MCA velocity threshold",
                    interval_days=30,
                    ease_factor=2.6,
                    lapses=0,
                    confidence_delta=0.03,
                    signal_event_id=123,
                )
                self.assertTrue(result["ok"])
                self.assertGreater(result["memory_event_id"], 0)

                event = kg.conn.execute(
                    "SELECT event_type FROM memory_events WHERE memory_event_id = ?",
                    (result["memory_event_id"],),
                ).fetchone()
                self.assertEqual(event["event_type"], "anki_review_evidence")

                state = kg.conn.execute(
                    """SELECT mastery_prob, transfer_state, evidence_event_ids
                       FROM learner_concept_state
                       WHERE concept_text = 'mca velocity threshold'"""
                ).fetchone()
                self.assertGreater(state["mastery_prob"], 0.0)
                self.assertEqual(state["transfer_state"], "anki_reviewed")
                self.assertIn(str(result["memory_event_id"]), state["evidence_event_ids"])
            finally:
                kg.close()

    def test_transfer_case_core_rotation_and_session_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                transfer_args = _build_parser().parse_args([
                    "record-transfer",
                    "--session-ts", "2026-04-15T12:00:00+00:00",
                    "--turn", "1",
                    "--skill", "intern-bootcamp",
                    "--topic", "ICP management",
                    "--concept", "CPP definition",
                    "--context", "Severe TBI: MAP 75 and ICP 25. Compute CPP and decide next step.",
                    "--answer", "CPP is 50; increase MAP or reduce ICP depending on the full picture.",
                    "--success",
                    "--transfer-level", "applied_under_time_pressure",
                ])
                transfer = _dispatch(transfer_args, kg)
                self.assertTrue(transfer["ok"])
                state = kg.conn.execute(
                    """SELECT transfer_state FROM learner_concept_state
                       WHERE concept_text = 'cpp definition'"""
                ).fetchone()
                self.assertEqual(state["transfer_state"], "applied_under_time_pressure")

                case_args = _build_parser().parse_args([
                    "record-case",
                    "--session-ts", "2026-04-15T12:00:00+00:00",
                    "--turn", "2",
                    "--skill", "intern-bootcamp",
                    "--topic", "ICP management",
                    "--case-context", "Night-float patient with severe TBI and rising ICP after transport.",
                    "--decision-point", "Check EVD leveling before treating the number.",
                    "--learner-action", "Wanted to give hypertonic saline before checking the setup.",
                    "--outcome", "partial",
                    "--teaching-target", "Troubleshoot EVD setup before assuming true ICP crisis.",
                    "--concept", "EVD troubleshooting",
                ])
                case = _dispatch(case_args, kg)
                self.assertTrue(case["ok"])
                case_row = kg.conn.execute(
                    "SELECT item_type FROM memory_items WHERE item_id = ?",
                    (case["memory_item_id"],),
                ).fetchone()
                self.assertEqual(case_row["item_type"], "case_memory")

                profile = kg.promote_core_profile_v2(
                    statement="Gabriel learns neurocritical care best through time-pressured vignettes.",
                    apply=True,
                )
                self.assertTrue(profile["ok"])
                self.assertGreaterEqual(len(profile["written_item_ids"]), 1)

                pack = kg.pre_rotation_pack_v2("ICP", max_items=5)
                self.assertTrue(pack["ok"])
                self.assertIn("Pre-Rotation Memory Pack", pack["text"])
                self.assertIn("Core Learner Profile", pack["text"])

                summary = kg.session_summary_v2(
                    session_ts="2026-04-15T12:00:00+00:00",
                    apply=True,
                )
                self.assertTrue(summary["ok"])
                self.assertIn("What Changed", summary["text"])
            finally:
                kg.close()

    def test_classify_event_and_calibration_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                classified = kg.classify_memory_capture_v2(
                    content="Explained vasospasm thresholds without asking a question.",
                    teaching_only=True,
                )
                self.assertEqual(classified["recommended_command"], "record-passive")

                args = _build_parser().parse_args([
                    "record-answer",
                    "--session-ts", "2026-04-15T12:00:00+00:00",
                    "--turn", "1",
                    "--skill", "study-session",
                    "--topic", "ICP management",
                    "--concept", "CPP definition",
                    "--question", "What is CPP?",
                    "--answer", "Definitely the same as ICP.",
                    "--correct", "0",
                    "--response-confidence", "high",
                    "--error-type", "conceptual_confusion",
                ])
                _dispatch(args, kg)
                pack = kg.calibration_training_pack_v2()
                self.assertTrue(pack["ok"])
                self.assertTrue(any("Overconfident wrong" in alert for alert in pack["alerts"]))

                item = kg.conn.execute(
                    """SELECT details_json FROM memory_items
                       WHERE item_type = 'episode'
                       ORDER BY item_id DESC LIMIT 1"""
                ).fetchone()
                self.assertIn("physiology_equation_confusion", item["details_json"])
            finally:
                kg.close()

    def test_finish_session_rolls_up_fragments_and_closes_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                active_ts = "2026-04-15T12:00:00+00:00"
                fragment_ts = "2026-04-15T12:05:00+00:00"
                kg.set_memory_session(
                    session_ts=active_ts,
                    skill="study-material",
                    topic_text="Neuroimaging Lab 2",
                    memory_enabled=True,
                    consent_scope="study_session",
                )
                direct = kg.log_answer(
                    session_ts=fragment_ts,
                    turn_number=1,
                    skill="study-material",
                    topic_name="Neuroimaging Lab 2",
                    concept_text="traumatic tap vs SAH",
                    question_text="LP findings to distinguish SAH from traumatic tap?",
                    answer_text="Xanthochromia and persistent RBCs.",
                    answer_correct=1,
                    correction_text="Also compare tube clearing and timing; SAH should not clear across tubes.",
                    error_type="omission",
                    misconception="",
                    root_cause="incomplete LP discrimination checklist",
                    remediation="force a tube-by-tube interpretation vignette",
                    teaching_approach="forced_discrimination",
                    response_confidence="high",
                )
                self.assertTrue(direct["ok"])

                finish = kg.finish_learning_session_v2(
                    session_ts=active_ts,
                    skill="study-material",
                    topic_name="Neuroimaging Lab 2",
                    mode="apply",
                    repair_fragments=True,
                    embed=False,
                )
                self.assertTrue(finish["ok"])
                self.assertIn(fragment_ts, finish["fragment_session_ts"])
                self.assertEqual(finish["counts"]["active_answers"], 1)
                self.assertGreater(finish["memory_item_id"], 0)

                session = kg.conn.execute(
                    """SELECT status, ended_ts FROM memory_sessions
                       WHERE session_ts = ? AND skill = ?""",
                    (active_ts, "study-material"),
                ).fetchone()
                self.assertEqual(session["status"], "complete")
                self.assertIsNotNone(session["ended_ts"])

                item = kg.conn.execute(
                    "SELECT details_json FROM memory_items WHERE item_id = ?",
                    (finish["memory_item_id"],),
                ).fetchone()
                self.assertIn("session_finish_rollup", item["details_json"])
            finally:
                kg.close()

    def test_finish_session_repairs_late_created_session_and_writes_teaching_intelligence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                first_ts = "2026-04-17T05:57:48+00:00"
                second_ts = "2026-04-17T06:09:29+00:00"
                finish_ts = "2026-04-17T06:09:54+00:00"

                partial = kg.log_answer(
                    session_ts=first_ts,
                    turn_number=1,
                    skill="neuroradiology-review",
                    topic_name="Traumatic Subarachnoid Hemorrhage",
                    concept_text="xanthochromia mechanism",
                    question_text=(
                        "What finding distinguishes SAH from traumatic tap, and what "
                        "physiological prerequisite must occur first?"
                    ),
                    answer_text="Xanthochromia, but I don't know the prerequisite.",
                    answer_correct=1,
                    correction_text="RBCs must lyse in vivo with heme oxygenase conversion to bilirubin.",
                )
                self.assertTrue(partial["ok"])

                correct = kg.log_answer(
                    session_ts=second_ts,
                    turn_number=2,
                    skill="neuroradiology-review",
                    topic_name="IVH and hydrocephalus risk",
                    concept_text="acute obstructive hydrocephalus",
                    question_text=(
                        "What is the specific mechanical mechanism, and why is "
                        "hemicraniectomy not the answer for this crisis?"
                    ),
                    answer_text="Blood obstructs the aqueduct causing acute hydrocephalus; EVD treats CSF accumulation.",
                    answer_correct=2,
                    depth=2,
                )
                self.assertTrue(correct["ok"])

                finish = kg.finish_learning_session_v2(
                    session_ts=finish_ts,
                    skill="neuroradiology-review",
                    topic_name="traumatic tap vs sah, ivh and hydrocephalus risk",
                    mode="apply",
                    repair_fragments=True,
                    embed=False,
                )
                self.assertTrue(finish["ok"])
                self.assertEqual(finish["counts"]["active_answers"], 2)
                self.assertIn(first_ts, finish["fragment_session_ts"])
                self.assertIn(second_ts, finish["fragment_session_ts"])
                self.assertGreater(finish["narrative_id"], 0)

                narrative = kg.conn.execute(
                    """SELECT teaching_successes, teaching_failures, depth_profile_json,
                              strategy_outcome, next_session_strategy
                       FROM session_narratives
                       WHERE narrative_id = ?""",
                    (finish["narrative_id"],),
                ).fetchone()
                self.assertIsNotNone(narrative)
                self.assertNotEqual(narrative["teaching_successes"], "[]")
                self.assertNotEqual(narrative["depth_profile_json"], "{}")
                self.assertIn(narrative["strategy_outcome"], {"effective", "mixed_but_useful"})
                self.assertIn("progressive reveal", narrative["next_session_strategy"])

                policy_count = kg.conn.execute(
                    "SELECT COUNT(*) AS n FROM teaching_policy_stats"
                ).fetchone()["n"]
                self.assertGreater(policy_count, 0)

                repaired = kg.conn.execute(
                    """SELECT teaching_approach, error_type, root_cause
                       FROM learning_exchanges
                       WHERE exchange_id = ?""",
                    (partial["exchange_id"],),
                ).fetchone()
                self.assertTrue(repaired["teaching_approach"])
                self.assertTrue(repaired["error_type"])
                self.assertTrue(repaired["root_cause"])

                pack = kg.context_pack(
                    "hydrocephalus xanthochromia teaching behavior",
                    topic_name="ivh and hydrocephalus risk",
                    skill="neuroradiology-review",
                    intent="teach",
                    max_tokens=1200,
                    log_retrieval=False,
                )
                self.assertIn("Narrative #", pack["text"])
                self.assertIn("Teaching Policy", pack["text"])
            finally:
                kg.close()


if __name__ == "__main__":
    unittest.main()
