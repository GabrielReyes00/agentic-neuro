"""Tests for session-scoped inventory knowledge map."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import session_map  # noqa: E402
import study_memory  # noqa: E402


class SessionMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.sessions_dir = Path(self._tmpdir.name) / "Sessions"
        self.sessions_dir.mkdir(parents=True)
        self._patch = patch.object(session_map, "SESSIONS_DIR", self.sessions_dir)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    def test_create_patch_and_progress(self) -> None:
        projection = {
            "knowledge_map": [
                {
                    "concept_id": "vas.test_node",
                    "concept": "Test Vasospasm Threshold",
                    "exposure_status": "unexposed",
                    "knowledge_state": "untested",
                    "attempts_count": 0,
                    "sqlite_success_rate": 0.0,
                    "role": "entry",
                }
            ],
            "edges": [],
            "scope": {"query": "vasospasm"},
            "unmatched_learner_concepts": [],
        }
        data = session_map.create_from_projection(
            projection,
            session_id="s1",
            profile="doc",
            doc_path="Study Material/Vasospasm.md",
        )
        session_map.write("s1", data)
        loaded = session_map.load("s1")
        assert loaded is not None
        patched, delta = session_map.patch_after_log(
            loaded,
            inventory_concept_id="vas.test_node",
            concept_text="Test Vasospasm Threshold",
            correct=2,
            exchange_id=1,
            coverage_role="primary_doc",
            learner_concept_id=10,
        )
        self.assertEqual(delta, "newly_exposed")
        self.assertEqual(patched["knowledge_map"][0]["exposure_status"], "exposed_superficial")
        progress = session_map.session_progress(patched)
        self.assertEqual(progress["newly_exposed"], 1)
        self.assertEqual(progress["probed"], 1)

    def test_lexical_backfill_binding(self) -> None:
        projection = {
            "knowledge_map": [
                {
                    "concept_id": "spine.acdf_pseudarthrosis",
                    "concept": "ACDF Pseudarthrosis Risk",
                    "exposure_status": "unexposed",
                    "knowledge_state": "untested",
                    "attempts_count": 0,
                    "sqlite_success_rate": 0.0,
                    "role": "entry",
                }
            ],
            "edges": [],
            "scope": {},
            "unmatched_learner_concepts": [],
        }
        data = session_map.create_from_projection(projection, session_id="s2", profile="memory")
        patched, delta = session_map.patch_after_log(
            data,
            inventory_concept_id="",
            concept_text="ACDF Pseudarthrosis Risk",
            correct=1,
            exchange_id=2,
        )
        self.assertEqual(delta, "newly_exposed")
        self.assertEqual(patched["knowledge_map"][0]["binding_tier"], "provisional")

    def test_fresh_misconception_flags_node_for_remediate(self) -> None:
        node = {
            "concept_id": "vas.threshold",
            "concept": "Vasospasm threshold",
            "exposure_status": "exposed_superficial",
            "knowledge_state": "untested",
            "attempts_count": 1,
            "sqlite_success_rate": 1.0,
            "active_misconception": False,
            "role": "entry",
        }
        # A misconception-class miss flags the node even with no prior flag.
        data = {"knowledge_map": [dict(node)], "session_stats": {}}
        patched, _ = session_map.patch_after_log(
            data, inventory_concept_id="vas.threshold", concept_text="Vasospasm threshold",
            correct=0, exchange_id=1, gap_type="conceptual_confusion",
        )
        self.assertTrue(patched["knowledge_map"][0]["active_misconception"])

        # A plain omission miss does not manufacture a misconception.
        data2 = {"knowledge_map": [dict(node)], "session_stats": {}}
        patched2, _ = session_map.patch_after_log(
            data2, inventory_concept_id="vas.threshold", concept_text="Vasospasm threshold",
            correct=0, exchange_id=1, gap_type="omission",
        )
        self.assertFalse(patched2["knowledge_map"][0]["active_misconception"])

        # A correct answer clears an existing misconception.
        flagged = dict(node, active_misconception=True)
        data3 = {"knowledge_map": [flagged], "session_stats": {}}
        patched3, _ = session_map.patch_after_log(
            data3, inventory_concept_id="vas.threshold", concept_text="Vasospasm threshold",
            correct=2, exchange_id=1,
        )
        self.assertFalse(patched3["knowledge_map"][0]["active_misconception"])

    def test_success_count_does_not_drift(self) -> None:
        node = {
            "concept_id": "vas.threshold",
            "concept": "Vasospasm threshold",
            "exposure_status": "unexposed",
            "knowledge_state": "untested",
            "attempts_count": 0,
            "successes_count": 0,
            "sqlite_success_rate": 0.0,
            "role": "entry",
        }
        data = {"knowledge_map": [dict(node)], "session_stats": {}}
        # 1 correct then 2 wrong -> true rate 1/3; the old rounded reconstruction
        # truncated int(0.333*3)=0, losing the success.
        for correct in (2, 0, 0):
            data, _ = session_map.patch_after_log(
                data, inventory_concept_id="vas.threshold", concept_text="Vasospasm threshold",
                correct=correct, exchange_id=1,
            )
        entry = data["knowledge_map"][0]
        self.assertEqual(entry["attempts_count"], 3)
        self.assertEqual(entry["successes_count"], 1)
        self.assertEqual(entry["sqlite_success_rate"], round(1 / 3, 3))

    def test_prune_stale_session_maps(self) -> None:
        import os
        import time

        fresh = session_map.create_from_projection(
            {"knowledge_map": [], "edges": [], "scope": {}, "unmatched_learner_concepts": []},
            session_id="fresh", profile="memory",
        )
        session_map.write("fresh", fresh)
        stale = session_map.create_from_projection(
            {"knowledge_map": [], "edges": [], "scope": {}, "unmatched_learner_concepts": []},
            session_id="stale", profile="memory",
        )
        session_map.write("stale", stale)
        # Backdate the stale map well past the TTL.
        stale_path = session_map.session_map_path("stale")
        old = time.time() - session_map.SESSION_MAP_TTL_SECONDS - 3600
        os.utime(stale_path, (old, old))

        removed = session_map.prune_stale_session_maps()
        self.assertEqual(removed, 1)
        self.assertFalse(session_map.session_map_path("stale").exists())
        self.assertTrue(session_map.session_map_path("fresh").exists())

    def test_delete_on_end_session_hook(self) -> None:
        data = session_map.create_from_projection(
            {"knowledge_map": [], "edges": [], "scope": {}, "unmatched_learner_concepts": []},
            session_id="s3",
            profile="memory",
        )
        session_map.write("s3", data)
        self.assertTrue(session_map.session_map_path("s3").exists())
        self.assertTrue(session_map.delete("s3"))
        self.assertFalse(session_map.session_map_path("s3").exists())

    def test_artifact_priority_annotates_doc_plan(self) -> None:
        knowledge_map = [
            {"concept": "Doc Native Concept", "artifact_native": True, "role": "entry", "exposure_status": "unexposed"},
            {"concept": "Map Neighbor Only", "artifact_native": False, "role": "neighbor_1", "exposure_status": "unexposed"},
        ]
        plan = {
            "target_concepts": ["Map Neighbor Only", "Doc Native Concept"],
            "pedagogical_directives": ["Drill gaps."],
        }
        adjusted = session_map.apply_artifact_priority(
            plan,
            knowledge_map,
            profile="doc",
            doc_path="Study Material/Test.md",
        )
        self.assertEqual(adjusted["teaching_priority"], "artifact_primary")
        self.assertEqual(adjusted["target_concepts"][0], "Doc Native Concept")
        self.assertTrue(any("Artifact Priority" in d for d in adjusted["pedagogical_directives"]))

    def test_inventory_concept_id_migration(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "m.db"
            conn = study_memory._get_db(path)
            cols_cr = {r["name"] for r in conn.execute("PRAGMA table_info(claim_results)")}
            cols_c = {r["name"] for r in conn.execute("PRAGMA table_info(concepts)")}
            self.assertIn("inventory_concept_id", cols_cr)
            self.assertIn("inventory_concept_id", cols_c)
            conn.close()
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
