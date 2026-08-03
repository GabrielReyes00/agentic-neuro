"""Pillar D: fallbacks must be observable. These are HEALTHY-PATH (inverse)
assertions — they fail if the system silently drops to a degraded fallback when
the rich path was available, which is exactly the regression class we want CI to
catch instead of letting a worse experience pass unnoticed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import session_map  # noqa: E402
import study_memory  # noqa: E402


class KnowledgeMapProvenanceTests(unittest.TestCase):
    def _seed_topic(self, conn):
        # One assessed exchange on a real inventory-covered topic so the topic
        # resolves and the inventory projection has something to bind.
        study_memory.log_answer(
            conn, session_id="seed", topic="subarachnoid hemorrhage",
            concept="Hunt-Hess clinical grading", question="Q", answer="A", correct=0,
            tested_claim="Hunt-Hess grades SAH severity I-V.",
            inventory_concept_id="vasc.sah.hunt-hess",
        )

    def _provenance(self, conn) -> str:
        out = study_memory.startup_recall(
            conn, topic="subarachnoid hemorrhage", lens="general", profile="memory",
        )
        brief = json.loads(out).get("planning_brief", {})
        return brief.get("knowledge_map_provenance", "<missing>")

    def test_healthy_inventory_is_used_not_fallback(self) -> None:
        """With a healthy inventory, the session MUST run on the inventory map."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "m.db"
            sessions = Path(tmp) / "Sessions"
            sessions.mkdir()
            with unittest.mock.patch.object(session_map, "SESSIONS_DIR", sessions):
                conn = study_memory._get_db(db)
                self._seed_topic(conn)
                self.assertEqual(self._provenance(conn), "inventory")
                conn.close()

    def test_unstudied_topic_still_gets_inventory_orient_map(self) -> None:
        """A topic with no learner history must still scope an inventory ORIENT map."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "m.db"
            sessions = Path(tmp) / "Sessions"
            sessions.mkdir()
            with unittest.mock.patch.object(session_map, "SESSIONS_DIR", sessions):
                conn = study_memory._get_db(db)  # no seeded topics at all
                out = study_memory.startup_recall(
                    conn, topic="subarachnoid hemorrhage", lens="general", profile="memory",
                )
                payload = json.loads(out)
                brief = payload.get("planning_brief", {})
                # A coherent inventory map with no strong historical collision is
                # a teachable new-topic ORIENT state, not an unresolved dead end.
                self.assertEqual(
                    brief.get("new_topic_orientation", {}).get("status"),
                    "new_topic_no_learner_history",
                )
                self.assertFalse(payload["startup_recall"]["routing_required"])
                self.assertTrue(payload["startup_recall"]["ready_to_teach"])
                self.assertGreater(len(brief.get("knowledge_map", [])), 0)
                self.assertEqual(brief.get("knowledge_map_provenance"), "inventory")
                conn.close()

    def test_inventory_unavailable_is_labeled_degraded_not_silent(self) -> None:
        """If the inventory projection is unavailable, the degradation is LABELED."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "m.db"
            sessions = Path(tmp) / "Sessions"
            sessions.mkdir()
            with unittest.mock.patch.object(session_map, "SESSIONS_DIR", sessions):
                conn = study_memory._get_db(db)
                self._seed_topic(conn)
                # Simulate the inventory asset being unavailable.
                with unittest.mock.patch.object(
                    session_map, "build_inventory_projection", return_value=None
                ):
                    prov = self._provenance(conn)
                # Degraded, but never silent: it is explicitly labeled, not "inventory".
                self.assertIn(prov, {"sqlite_fallback", "none"})
                self.assertNotEqual(prov, "inventory")
                conn.close()


if __name__ == "__main__":
    unittest.main()
