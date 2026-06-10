"""Tests for inventory node drilldown and map enrichment."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import node_recall  # noqa: E402
import study_memory  # noqa: E402


class NodeRecallTests(unittest.TestCase):
    def test_build_orient_menu_prioritizes_entry_unexposed(self) -> None:
        knowledge_map = [
            {"concept_id": "a.x", "concept": "A", "exposure_status": "unexposed", "role": "entry", "tier": "core"},
            {"concept_id": "b.x", "concept": "B", "exposure_status": "unexposed", "role": "neighbor_1", "tier": "core"},
            {"concept_id": "c.x", "concept": "C", "exposure_status": "exposed_deep", "role": "entry", "tier": "core"},
        ]
        menu = node_recall.build_orient_menu(knowledge_map, cap=5)
        self.assertEqual(len(menu), 1)
        self.assertEqual(menu[0]["concept_id"], "a.x")

    def test_orient_menu_emitted_in_policy(self) -> None:
        schema_map = [
            {"concept_id": "vas.a", "concept": "Alpha", "exposure_status": "unexposed", "knowledge_state": "untested", "role": "entry", "tier": "foundation"},
            {"concept_id": "vas.b", "concept": "Beta", "exposure_status": "unexposed", "knowledge_state": "untested", "role": "entry", "tier": "core"},
        ]
        plan = study_memory._compute_teaching_policy(schema_map)
        self.assertIn("orient_menu", plan)
        self.assertEqual(len(plan["orient_menu"]), 2)

    def test_session_handoff_from_map_stuck_nodes(self) -> None:
        smap = {
            "knowledge_map": [
                {
                    "concept_id": "vas.stuck",
                    "exposure_status": "exposed_superficial",
                    "knowledge_state": "partially_repaired",
                    "session_probed": True,
                    "last_session_delta": "reviewed",
                },
                {
                    "concept_id": "vas.improved",
                    "exposure_status": "exposed_deep",
                    "knowledge_state": "passed",
                    "session_probed": True,
                    "last_session_delta": "improved",
                },
            ],
            "session_stats": {"probed": 2, "reviewed": 1, "improved": 1},
        }
        handoff = node_recall.session_handoff_from_map(smap)
        self.assertIn("vas.stuck", handoff["priority_inventory_ids"])
        self.assertIn("vas.improved", handoff["improved_inventory_ids"])

    def test_enrich_knowledge_map_attaches_learner_surface(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "m.db"
            conn = study_memory._get_db(path)
            t = study_memory.resolve_topic(conn, "acdf", "")
            tid = study_memory._ensure_topic(conn, t)
            cid = conn.execute(
                "INSERT INTO concepts (topic_id, canonical_slug, display_name, inventory_concept_id) VALUES (?,?,?,?)",
                (tid, "dysphagia", "Dysphagia", "spine.dysphagia"),
            ).lastrowid
            study_memory.log_answer(
                conn,
                session_id="s",
                topic="acdf",
                concept="Dysphagia",
                question="Q",
                answer="wrong",
                correct=0,
                tested_claim="Dysphagia is common after ACDF.",
                inventory_concept_id="spine.dysphagia",
            )
            knowledge_map = [
                {
                    "concept_id": "spine.dysphagia",
                    "concept": "Dysphagia",
                    "exposure_status": "exposed_superficial",
                    "matched_learner_concepts": [{"learner_concept_id": int(cid), "name": "Dysphagia"}],
                }
            ]
            node_recall.enrich_knowledge_map_learner_surfaces(conn, knowledge_map)
            self.assertIn("learner_surface", knowledge_map[0])
            self.assertGreaterEqual(knowledge_map[0].get("open_claims", 0), 1)
            conn.close()
        finally:
            tmp.cleanup()

    def test_anki_refine_matches_inventory_id(self) -> None:
        brief = {
            "knowledge_map": [{
                "concept_id": "vas.vasospasm",
                "concept": "Vasospasm",
                "exposure_status": "unexposed",
                "knowledge_state": "untested",
            }],
            "sequential_teaching_plan": study_memory._compute_teaching_policy([{
                "concept_id": "vas.vasospasm",
                "concept": "Vasospasm",
                "exposure_status": "unexposed",
                "knowledge_state": "untested",
            }]),
        }
        study_memory._refine_brief_with_anki(brief, {
            "concept_rollup": [{
                "concept": "Different Display Name",
                "inventory_concept_id": "vas.vasospasm",
                "reviews_count": 6,
                "success_rate": 0.9,
            }],
        })
        entry = brief["knowledge_map"][0]
        self.assertEqual(entry["anki_reviews_count"], 6)
        self.assertEqual(entry["exposure_status"], "exposed_deep")

    def test_end_session_returns_handoff_skeleton(self) -> None:
        import unittest.mock
        import session_map as sm  # noqa: E402

        tmp = tempfile.TemporaryDirectory()
        sessions_dir = Path(tmp.name) / "Sessions"
        sessions_dir.mkdir()
        try:
            with unittest.mock.patch.object(sm, "SESSIONS_DIR", sessions_dir):
                path = Path(tmp.name) / "m.db"
                conn = study_memory._get_db(path)
                sm.write("sess-1", {
                    "knowledge_map": [{
                        "concept_id": "vas.stuck",
                        "exposure_status": "exposed_superficial",
                        "knowledge_state": "missed",
                        "session_probed": True,
                        "last_session_delta": "reviewed",
                    }],
                    "session_stats": {"probed": 1},
                    "last_plan": {"current_phase": "phase_2_recalibrate_gaps"},
                })
                result = study_memory.end_session(
                    conn,
                    session_id="sess-1",
                    summary="summary",
                    next_strategy="Re-drill vas.stuck",
                )
                self.assertIn("handoff_skeleton", result)
                self.assertIn("vas.stuck", result["handoff_skeleton"]["priority_inventory_ids"])
                conn.close()
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
