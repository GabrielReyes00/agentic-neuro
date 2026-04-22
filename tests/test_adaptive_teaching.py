from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knowledge_graph import KnowledgeGraph
from learner_model import estimate_mastery, next_item, recompute_learner_model
from memory_orchestrator import _build_parser, _dispatch
from teaching_recommender import recommend_approach, refresh_teaching_policy
from tutor_strategy import build_tutor_strategy
from unknown_unknowns_scout import pop_probe, surface_unknown_unknowns


class AdaptiveTeachingTests(unittest.TestCase):
    def _record(
        self,
        kg: KnowledgeGraph,
        *,
        correct: str = "1",
        concept: str = "CPP definition",
        teaching_approach: str = "mechanism_to_management",
    ) -> dict:
        args = _build_parser().parse_args([
            "record-answer",
            "--session-ts", "2026-04-15T12:00:00+00:00",
            "--turn", "1",
            "--skill", "study-session",
            "--topic", "ICP management",
            "--concept", concept,
            "--question", "What is CPP?",
            "--answer", "MAP minus ICP" if correct == "2" else "It is related to ICP.",
            "--correct", correct,
            "--correction", "CPP equals MAP minus ICP.",
            "--error-type", "conceptual_confusion",
            "--teaching-approach", teaching_approach,
        ])
        return _dispatch(args, kg)

    def test_record_answer_updates_adaptive_snapshots_and_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                result = self._record(kg, correct="2")
                self.assertTrue(result["ok"])
                self.assertTrue(result["learner_model"]["ok"])

                exchange = kg.conn.execute(
                    """SELECT mastery_prob_before, mastery_prob_after, difficulty_band
                       FROM learning_exchanges WHERE exchange_id = ?""",
                    (result["exchange_id"],),
                ).fetchone()
                self.assertIsNotNone(exchange["mastery_prob_before"])
                self.assertGreater(exchange["mastery_prob_after"], exchange["mastery_prob_before"])
                self.assertIn(exchange["difficulty_band"], {"remediate", "zpd", "consolidate", "stretch"})

                state = kg.conn.execute(
                    """SELECT irt_theta, irt_standard_error, irt_observation_count,
                              difficulty_band, last_mastery_delta
                       FROM learner_concept_state
                       WHERE concept_text = 'cpp definition'"""
                ).fetchone()
                self.assertGreaterEqual(state["irt_observation_count"], 1)
                self.assertLessEqual(state["irt_standard_error"], 1.0)
                self.assertNotEqual(state["difficulty_band"], "")
                self.assertGreater(state["last_mastery_delta"], 0.0)

                policy = kg.conn.execute(
                    """SELECT teaching_approach, difficulty_band, mastery_delta_count
                       FROM teaching_policy_stats"""
                ).fetchone()
                self.assertEqual(policy["teaching_approach"], "pathophys_derivation")
                self.assertGreaterEqual(policy["mastery_delta_count"], 1)
            finally:
                kg.close()

    def test_learner_model_cli_helpers_return_zpd_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                self._record(kg, correct="1")
                recompute = recompute_learner_model(kg.conn)
                self.assertTrue(recompute["ok"])
                self.assertGreaterEqual(recompute["states_updated"], 1)

                mastery = estimate_mastery(kg.conn, topic="ICP", concept="CPP definition")
                self.assertTrue(mastery["ok"])
                self.assertFalse(mastery["cold_start"])

                items = next_item(kg.conn, mode="zpd", topic="ICP", limit=3)
                self.assertTrue(items["ok"])
                self.assertGreaterEqual(items["count"], 1)
                self.assertEqual(items["items"][0]["concept"], "cpp definition")
            finally:
                kg.close()

    def test_teaching_recommender_backoff_and_alias_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                self._record(kg, correct="2", teaching_approach="mechanism_to_management")
                refreshed = refresh_teaching_policy(kg.conn)
                self.assertTrue(refreshed["ok"])

                rec = recommend_approach(
                    kg.conn,
                    concept_text="CPP definition",
                    error_type="conceptual_confusion",
                    difficulty_band="remediate",
                )
                self.assertTrue(rec["ok"])
                self.assertEqual(rec["approach"], "pathophys_derivation")
                self.assertIn(rec["backoff_level"], {"concept_error_band", "concept_error"})
            finally:
                kg.close()

    def test_unknown_unknown_scout_queues_and_pops_prerequisite_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                result = self._record(kg, correct="0", concept="CPP calculation")
                topic_id = kg.conn.execute(
                    "SELECT topic_id FROM learning_exchanges WHERE exchange_id = ?",
                    (result["exchange_id"],),
                ).fetchone()["topic_id"]
                with kg.conn:
                    kg.conn.execute(
                        """INSERT INTO concept_relationships
                           (concept_a, topic_a, concept_b, topic_b, relationship,
                            strength, notes, source, created_ts)
                           VALUES (?, ?, ?, ?, 'prerequisite_of', 0.9, ?, 'test', ?)""",
                        (
                            "MAP definition",
                            "ICP management",
                            "CPP calculation",
                            "ICP management",
                            "MAP is prerequisite to CPP calculation",
                            "2026-04-15T12:00:00+00:00",
                        ),
                    )
                surfaced = surface_unknown_unknowns(kg.conn, limit=3)
                self.assertTrue(surfaced["ok"])
                self.assertGreaterEqual(surfaced["queued"], 1)

                popped = pop_probe(kg.conn, output_path=None)
                self.assertEqual(popped["status"], "popped")
                self.assertEqual(popped["prerequisite"], "MAP definition")
                self.assertEqual(popped["concept"], "cpp calculation")
                self.assertGreaterEqual(popped["priority"], 0.5)
                self.assertIsNotNone(topic_id)
            finally:
                kg.close()

    def test_tutor_strategy_outputs_control_loop_and_mastery_ladder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                self._record(kg, correct="2", concept="CPP definition")
                strategy = build_tutor_strategy(
                    kg.conn,
                    query="ICP management CPP",
                    topic="ICP management",
                    concept="CPP definition",
                    skill="study-session",
                )
                self.assertTrue(strategy["ok"])
                self.assertIn(strategy["control_state"], {
                    "calibrate",
                    "repair_prerequisite",
                    "force_discrimination",
                    "raise_fidelity",
                    "transfer",
                    "consolidate",
                    "close_loop",
                })
                self.assertIn("question_job", strategy)
                self.assertIn("current_rung", strategy["mastery_ladder"])
                self.assertIn("minimum_effective_explanation", strategy)
                self.assertIn("mastery_claim_audit", strategy)
                self.assertEqual(strategy["domain_playbook"]["domain"], "icu")
                self.assertIn("learning_yield_optimizer", strategy)
                self.assertIn("concept_bottlenecks", strategy)
                self.assertIn("cross_context_transfer_matrix", strategy)
                self.assertIn("error_recurrence_fingerprints", strategy)
                self.assertIn("compression_card", strategy)
                self.assertIn("anti_illusion_checks", strategy)
                self.assertIn("intern_reality", strategy)
                self.assertIn("chief_challenges", strategy)
                self.assertIn("living_mastery_map", strategy)

                args = _build_parser().parse_args([
                    "tutor-strategy",
                    "ICP management CPP",
                    "--topic", "ICP management",
                    "--concept", "CPP definition",
                    "--skill", "study-session",
                ])
                cli_strategy = _dispatch(args, kg)
                self.assertTrue(cli_strategy["ok"])
                self.assertEqual(cli_strategy["question_job"], strategy["question_job"])
            finally:
                kg.close()

    def test_tutor_strategy_prioritizes_bottleneck_and_recurrence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = KnowledgeGraph(Path(tmp) / "kg.db")
            try:
                self._record(kg, correct="0", concept="CPP calculation")
                self._record(kg, correct="0", concept="CPP calculation")
                with kg.conn:
                    kg.conn.execute(
                        """INSERT INTO concept_relationships
                           (concept_a, topic_a, concept_b, topic_b, relationship,
                            strength, notes, source, created_ts)
                           VALUES
                           ('MAP definition', 'ICP management', 'CPP calculation', 'ICP management',
                            'prerequisite_of', 0.9, 'MAP unlocks CPP', 'test', '2026-04-15T12:00:00+00:00'),
                           ('MAP definition', 'ICP management', 'vasospasm perfusion target', 'Vascular',
                            'prerequisite_of', 0.8, 'MAP unlocks perfusion reasoning', 'test', '2026-04-15T12:00:00+00:00')"""
                    )
                strategy = build_tutor_strategy(
                    kg.conn,
                    query="ICP management CPP",
                    topic="ICP management",
                    concept="CPP calculation",
                    skill="study-session",
                )
                bottlenecks = strategy["concept_bottlenecks"]["targets"]
                self.assertTrue(any(b["concept"] == "MAP definition" for b in bottlenecks))
                yield_targets = strategy["learning_yield_optimizer"]["targets"]
                self.assertTrue(any(t["concept"].lower() in {"map definition", "cpp calculation"} for t in yield_targets))
                fingerprints = strategy["error_recurrence_fingerprints"]
                self.assertTrue(any(f["count"] >= 1 for f in fingerprints))
                self.assertTrue(strategy["chief_challenges"])
                self.assertTrue(strategy["compression_card"]["one_breath"])
            finally:
                kg.close()


if __name__ == "__main__":
    unittest.main()
