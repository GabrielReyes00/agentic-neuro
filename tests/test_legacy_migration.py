"""Pillar B: legacy-binding migration — confident auto-binds, safe demotions,
idempotency, and reviewed-binding application."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import legacy_migration  # noqa: E402
import study_memory  # noqa: E402
from concept_inventory import _open_inventory  # noqa: E402


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "m.db"
        self.conn = study_memory._get_db(self.db)
        self.inv = _open_inventory()

    def tearDown(self) -> None:
        self.inv.close()
        self.conn.close()
        self.tmp.cleanup()

    def _add_concept(self, topic_slug: str, domain: str, name: str) -> int:
        # log_answer creates the topic, concept, exchange, and assessed claim_result.
        study_memory.log_answer(
            self.conn, session_id="m", topic=topic_slug, concept=name,
            question="Q", answer="A", correct=0, tested_claim=name,
        )
        row = self.conn.execute(
            "SELECT id FROM concepts WHERE lower(display_name) = lower(?) ORDER BY id DESC LIMIT 1",
            (name,),
        ).fetchone()
        cid = int(row["id"])
        self.conn.execute(
            "UPDATE topics SET domain = ? WHERE id = (SELECT topic_id FROM concepts WHERE id = ?)",
            (domain, cid),
        )
        self.conn.commit()
        return cid

    def test_clean_in_domain_label_auto_binds(self) -> None:
        cid = self._add_concept("subarachnoid hemorrhage", "vascular", "Hunt-Hess clinical grading")
        report = legacy_migration.migrate(self.conn, self.inv, apply=True)
        auto_ids = {r["learner_concept_id"] for r in report["auto"]}
        self.assertIn(cid, auto_ids)
        row = self.conn.execute("SELECT inventory_concept_id FROM concepts WHERE id = ?", (cid,)).fetchone()
        self.assertEqual(row["inventory_concept_id"], "vasc.sah.hunt-hess")
        # claim_results backfilled too
        cr = self.conn.execute(
            "SELECT COUNT(*) FROM claim_results WHERE concept_id = ? AND inventory_concept_id = 'vasc.sah.hunt-hess'",
            (cid,),
        ).fetchone()[0]
        self.assertEqual(cr, 1)

    def test_conflated_label_is_demoted_not_auto_bound(self) -> None:
        cid = self._add_concept("spinal cord injury", "spine", "neurogenic versus spinal shock distinction and management")
        report = legacy_migration.migrate(self.conn, self.inv, apply=True)
        auto_ids = {r["learner_concept_id"] for r in report["auto"]}
        self.assertNotIn(cid, auto_ids)  # conflated -> review, never auto-bound
        row = self.conn.execute("SELECT inventory_concept_id FROM concepts WHERE id = ?", (cid,)).fetchone()
        self.assertIn(row["inventory_concept_id"], (None, ""))

    def test_cross_domain_match_is_demoted(self) -> None:
        # A vascular concept whose top lexical hit is a trauma node must not auto-bind.
        cid = self._add_concept("aneurysm imaging", "vascular", "non-contrast ct utility")
        report = legacy_migration.migrate(self.conn, self.inv, apply=False)
        rec = next((r for r in report["provisional"] + report["unbindable"] if r["learner_concept_id"] == cid), None)
        self.assertIsNotNone(rec)
        if rec["cross_domain"]:
            self.assertNotIn(cid, {r["learner_concept_id"] for r in report["auto"]})

    def test_idempotent_apply(self) -> None:
        self._add_concept("subarachnoid hemorrhage", "vascular", "Hunt-Hess clinical grading")
        first = legacy_migration.migrate(self.conn, self.inv, apply=True)
        second = legacy_migration.migrate(self.conn, self.inv, apply=True)
        self.assertGreaterEqual(first["counts"]["concepts_bound_this_run"], 1)
        self.assertEqual(second["counts"]["concepts_bound_this_run"], 0)  # nothing left to bind

    def test_reviewed_binding_applies_and_validates(self) -> None:
        cid = self._add_concept("spinal cord injury", "spine", "neurogenic versus spinal shock distinction and management")
        # unknown inventory id is rejected
        bad = legacy_migration.bind_reviewed(self.conn, self.inv, [(cid, "spine.nope.nonexistent")])
        self.assertFalse(bad["ok"])
        # a real reviewed binding applies
        good = legacy_migration.bind_reviewed(self.conn, self.inv, [(cid, "spi.sci.neurogenic-vs-spinal-shock")])
        self.assertTrue(good["ok"])
        row = self.conn.execute("SELECT inventory_concept_id FROM concepts WHERE id = ?", (cid,)).fetchone()
        self.assertEqual(row["inventory_concept_id"], "spi.sci.neurogenic-vs-spinal-shock")


if __name__ == "__main__":
    unittest.main()
