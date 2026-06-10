"""Tests for phase-3 mastery intelligence wiring."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cognitive_ops  # noqa: E402
import mastery_intelligence  # noqa: E402
import study_memory  # noqa: E402


class MasteryIntelligenceTests(unittest.TestCase):
    def test_classify_cognitive_op_prefers_explicit(self) -> None:
        self.assertEqual(
            cognitive_ops.classify_cognitive_op(explicit="quantification"),
            "quantification",
        )

    def test_probe_feedback_on_miss(self) -> None:
        feedback = cognitive_ops.probe_feedback(
            cognitive_op="sequencing",
            score=0,
            inventory_concept_id="vas.vasospasm",
        )
        self.assertEqual(feedback["cognitive_op"], "sequencing")
        self.assertIn("retest_hint", feedback)

    def test_should_skip_orient_when_entry_nodes_deep(self) -> None:
        knowledge_map = [
            {"concept_id": "a", "role": "entry", "exposure_status": "exposed_deep"},
            {"concept_id": "b", "role": "entry", "exposure_status": "exposed_superficial"},
            {"concept_id": "c", "role": "neighbor_1", "exposure_status": "unexposed"},
        ]
        self.assertTrue(mastery_intelligence.should_skip_orient(knowledge_map))

    def test_stuck_escalation_after_repeated_misses(self) -> None:
        knowledge_map = [{
            "concept_id": "vas.stuck",
            "concept": "Stuck",
            "session_probed": True,
            "stuck_probe_count": 2,
            "exposure_status": "exposed_superficial",
            "knowledge_state": "missed",
            "last_session_delta": "reviewed",
            "last_miss_cognitive_op": "quantification",
        }]
        targets = mastery_intelligence.stuck_escalation_targets(knowledge_map)
        self.assertEqual(targets[0]["inventory_concept_id"], "vas.stuck")

    def test_orient_skip_changes_policy_phase(self) -> None:
        knowledge_map = [
            {"concept_id": "a", "concept": "A", "role": "entry", "exposure_status": "exposed_deep", "knowledge_state": "passed"},
            {"concept_id": "b", "concept": "B", "role": "entry", "exposure_status": "exposed_superficial", "knowledge_state": "partially_repaired"},
        ]
        plan = study_memory._compute_teaching_policy(
            knowledge_map,
            orient_skip=mastery_intelligence.orient_skip_metadata(knowledge_map),
        )
        self.assertEqual(plan["current_phase"], "phase_2_recalibrate_gaps")
        self.assertTrue(plan.get("orient_skip", {}).get("skipped"))

    def test_escalate_interrupt_emitted(self) -> None:
        stuck = [{
            "inventory_concept_id": "vas.stuck",
            "concept": "Stuck",
            "stuck_probe_count": "2",
        }]
        plan = study_memory._compute_teaching_policy(
            [{"concept_id": "vas.stuck", "concept": "Stuck", "exposure_status": "exposed_superficial", "knowledge_state": "missed"}],
            stuck_escalations=stuck,
        )
        self.assertEqual(len(plan["interrupts"]["escalate"]), 1)

    def test_escalation_directive_parsing(self) -> None:
        content = "Gabriel has mastered X. Escalation: test transfer to post-op fever workup."
        self.assertIn("post-op fever", mastery_intelligence.parse_escalation_clause(content))

    def test_log_answer_emits_probe_feedback_on_miss(self) -> None:
        import unittest.mock
        import session_map as sm  # noqa: E402

        tmp = tempfile.TemporaryDirectory()
        sessions_dir = Path(tmp.name) / "Sessions"
        sessions_dir.mkdir()
        try:
            with unittest.mock.patch.object(sm, "SESSIONS_DIR", sessions_dir):
                path = Path(tmp.name) / "m.db"
                conn = study_memory._get_db(path)
                sm.write("sess-op", {
                    "knowledge_map": [{
                        "concept_id": "vas.test",
                        "concept": "Test",
                        "exposure_status": "unexposed",
                        "knowledge_state": "untested",
                        "role": "entry",
                    }],
                    "session_stats": {},
                })
                study_memory.log_answer(
                    conn,
                    session_id="sess-op",
                    topic="vasospasm",
                    concept="Test",
                    question="What is the Nimodipine dose?",
                    answer="wrong",
                    correct=0,
                    tested_claim="Nimodipine is 60 mg q4h PO/NG.",
                    inventory_concept_id="vas.test",
                    skill="study-review",
                )
                row = conn.execute(
                    """SELECT plan_json FROM policy_events
                       WHERE session_id = 'sess-op' ORDER BY id DESC LIMIT 1"""
                ).fetchone()
                plan = json.loads(row["plan_json"])
                self.assertIn("probe_feedback", plan)
                self.assertEqual(plan["probe_feedback"]["cognitive_op"], "quantification")
                conn.close()
        finally:
            tmp.cleanup()

    def test_binding_match_count_promoted(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "m.db"
            conn = study_memory._get_db(path)
            t = study_memory.resolve_topic(conn, "acdf", "")
            tid = study_memory._ensure_topic(conn, t)
            cid = conn.execute(
                "INSERT INTO concepts (topic_id, canonical_slug, display_name) VALUES (?,?,?)",
                (tid, "dysphagia", "Dysphagia"),
            ).lastrowid
            for _ in range(2):
                study_memory.log_answer(
                    conn,
                    session_id="bind-sess",
                    topic="acdf",
                    concept="Dysphagia",
                    question="Q",
                    answer="a",
                    correct=2,
                    tested_claim="claim",
                    inventory_concept_id="spine.dysphagia",
                )
            row = conn.execute(
                "SELECT inventory_concept_id, binding_match_count FROM concepts WHERE id = ?",
                (cid,),
            ).fetchone()
            self.assertEqual(row["inventory_concept_id"], "spine.dysphagia")
            self.assertGreaterEqual(int(row["binding_match_count"]), 2)
            conn.close()
        finally:
            tmp.cleanup()

    def test_end_session_probe_telemetry_audit(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "m.db"
            conn = study_memory._get_db(path)
            conn.execute(
                """INSERT INTO policy_events
                   (session_id, ts, event_type, topic_id, mode, phase, interrupts_json, inputs_json, plan_json)
                   VALUES ('s1', 'now', 'turn', NULL, 'deepen', 'phase_2', '{}', ?, '{}')""",
                (json.dumps({"probe_meta": {"cognitive_op": "mechanism", "score": 0, "binding_tier": "bound"}}),),
            )
            audit = study_memory._audit_probe_telemetry(conn, session_id="s1")
            self.assertEqual(audit["by_cognitive_op"]["mechanism"]["misses"], 1)
            lean = study_memory._lean_probe_telemetry(conn, session_id="s1")
            self.assertEqual(lean["probed"], 1)
            conn.close()
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
