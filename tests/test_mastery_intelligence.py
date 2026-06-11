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

    def test_predominant_exposure_skips_orient(self) -> None:
        # 7 of 9 entries exposed -> a substantial schema, no fog to clear -> DEEPEN.
        entries = [
            {"concept_id": f"e{i}", "role": "entry", "exposure_status": "exposed_superficial"}
            for i in range(7)
        ] + [
            {"concept_id": "u1", "role": "entry", "exposure_status": "unexposed"},
            {"concept_id": "u2", "role": "entry", "exposure_status": "unexposed"},
        ]
        meta = mastery_intelligence.orient_skip_metadata(entries)
        self.assertTrue(meta["skipped"])
        self.assertEqual(meta["reason"], "predominant_prior_exposure")

    def test_substantial_deepenable_core_skips_orient(self) -> None:
        # Broad scope (many unexposed neighbors) but a real body of partially-learned
        # entries -> DEEPEN the gaps, do not re-orient the whole topic.
        entries = [
            {"concept_id": f"s{i}", "role": "entry", "exposure_status": "exposed_superficial",
             "knowledge_state": "partially_repaired"}
            for i in range(5)
        ] + [
            {"concept_id": f"u{i}", "role": "entry", "exposure_status": "unexposed"} for i in range(20)
        ]
        meta = mastery_intelligence.orient_skip_metadata(entries)
        self.assertTrue(meta["skipped"])  # 5 deepenable of 25 entries (20%) still skips
        self.assertEqual(meta["reason"], "substantial_deepenable_core")

    def test_predominantly_new_topic_still_orients(self) -> None:
        # Only 1 of 5 entries exposed -> genuinely new -> ORIENT (not skipped).
        entries = [{"concept_id": "e0", "role": "entry", "exposure_status": "exposed_superficial"}] + [
            {"concept_id": f"u{i}", "role": "entry", "exposure_status": "unexposed"} for i in range(4)
        ]
        self.assertFalse(mastery_intelligence.should_skip_orient(entries))

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


class AcgmeLearnerStatsTests(unittest.TestCase):
    def test_no_fanout_between_claim_results_and_claim_state(self) -> None:
        import tempfile
        from pathlib import Path
        import acgme_readiness

        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "m.db"
            conn = study_memory._get_db(db)
            t = study_memory.resolve_topic(conn, "sah vasospasm", "")
            tid = study_memory._ensure_topic(conn, t)
            cid = conn.execute(
                "INSERT INTO concepts (topic_id, canonical_slug, display_name, inventory_concept_id) VALUES (?,?,?,?)",
                (tid, "vasospasm-threshold", "Vasospasm threshold", "vasc.vasospasm.threshold"),
            ).lastrowid
            # Two distinct claims -> two claim_state rows; claim A logged twice -> 3 assessed results.
            for claim, ans, score in [
                ("Vasospasm peaks day 4-14.", "wrong", 0),
                ("Vasospasm peaks day 4-14.", "right", 2),
                ("Nimodipine is given for 21 days.", "wrong", 0),
            ]:
                study_memory.log_answer(
                    conn, session_id="s", topic="sah vasospasm", concept="Vasospasm threshold",
                    question="Q", answer=ans, correct=score, tested_claim=claim,
                    inventory_concept_id="vasc.vasospasm.threshold",
                )
            # A quick-answer exchange on the same concept must be excluded from attempts.
            study_memory.log_answer(
                conn, session_id="s", topic="sah vasospasm", concept="Vasospasm threshold",
                question="Q", answer="info", correct=2, tested_claim="Quick aside on vasospasm imaging.",
                inventory_concept_id="vasc.vasospasm.threshold", skill="quick-answer", origin="reference",
            )
            stats = acgme_readiness.aggregate_learner_concept_stats(conn)
            rows = [r for r in stats if r["inventory_concept_id"] == "vasc.vasospasm.threshold"]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            # True assessed attempts = 3 (not 3*2=6 from fan-out, not 4 incl quick-answer).
            self.assertEqual(row["attempts"], 3)
            # "peaks" claim missed then corrected -> repaired (not open); "nimodipine" still missed.
            self.assertEqual(row["open_gaps"], 1)
            conn.close()
        finally:
            tmp.cleanup()

    def test_blind_spots_respect_pgy_lens(self) -> None:
        import tempfile
        from pathlib import Path
        import acgme_readiness

        self.assertGreater(len(acgme_readiness._acgme_title_pgy()), 0)
        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "m.db"
            conn = study_memory._get_db(db)  # empty learner history -> all unexposed
            ov = acgme_readiness.build_acgme_readiness_overlay(conn, pgy_target=1)
            self.assertEqual(ov["status"], "ok")
            for spot in ov["top_blind_spots"]:
                pgy = spot.get("pgy_target")
                self.assertTrue(pgy is None or pgy <= 1, f"PGY-{pgy} leaked into PGY-1 lens")
            conn.close()
        finally:
            tmp.cleanup()

    def test_overlay_does_not_double_count_multi_link_concepts(self) -> None:
        import tempfile
        from pathlib import Path
        import acgme_readiness
        from concept_inventory import _open_inventory

        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "m.db"
            conn = study_memory._get_db(db)
            ov = acgme_readiness.build_acgme_readiness_overlay(conn, pgy_target=7, domain_limit=50)
            inv = _open_inventory()
            try:
                true_counts = {
                    r["domain"]: r["n"]
                    for r in inv.execute("SELECT domain, COUNT(*) AS n FROM concepts GROUP BY domain")
                }
            finally:
                inv.close()
            for bucket in ov["domain_gaps"]:
                self.assertEqual(
                    bucket["inventory_total"], true_counts[bucket["domain"]],
                    f"domain {bucket['domain']} count inflated by acgme_links fan-out",
                )
            conn.close()
        finally:
            tmp.cleanup()

    def test_lexical_projection_credits_unbound_history(self) -> None:
        import tempfile
        from pathlib import Path
        import acgme_readiness
        from concept_inventory import _open_inventory

        tmp = tempfile.TemporaryDirectory()
        try:
            db = Path(tmp.name) / "m.db"
            conn = study_memory._get_db(db)
            # No explicit inventory binding; the display name lexically matches a
            # real vascular inventory node so history is still credited.
            study_memory.log_answer(
                conn, session_id="s", topic="sah", concept="Hunt-Hess clinical grading",
                question="Q", answer="wrong", correct=0,
                tested_claim="Hunt-Hess grades SAH clinically I-V.",
            )
            inv = _open_inventory()
            try:
                by_inv, explicit, projected = acgme_readiness.project_learner_history_onto_inventory(conn, inv)
            finally:
                inv.close()
            self.assertEqual(explicit, 0)
            self.assertGreaterEqual(projected, 1)
            self.assertIn("vasc.sah.hunt-hess", by_inv)
            self.assertGreaterEqual(by_inv["vasc.sah.hunt-hess"]["attempts"], 1)
            conn.close()
        finally:
            tmp.cleanup()
