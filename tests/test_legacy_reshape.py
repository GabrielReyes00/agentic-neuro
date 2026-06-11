"""Pillar B (complete): legacy reshape — triage, cluster mapping, decisions, apply."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import legacy_reshape  # noqa: E402
import study_memory  # noqa: E402
from concept_inventory import _open_inventory  # noqa: E402


class ClusterMappingTests(unittest.TestCase):
    def test_cluster_targets(self) -> None:
        cases = {
            "dcml decussation and clinical transfer": "ana.spine.spinal-cord-tracts",
            "cst somatotopy and extramedullary compression": "ana.cortex.corticospinal-tract",
            "rapid vs gradual evd weaning evidence": "ncc.monitoring.evd-weaning",
            "prophylactic antibiotics for evd duration": "ncc.monitoring.evd-infection-prevention",
            "evd low-output obstruction versus high-output overdrainage": "ncc.monitoring.evd-management",
            "osmotherapy agent selection in refractory icp": "fnd.pharm.osmotherapy",
            "upward herniation mechanism": "fnd.icp.herniation-syndromes",
            "metastatic spinal cord compression steroid protocol": "spi.oncology.metastatic-cord-compression",
        }
        for label, expected in cases.items():
            self.assertEqual(legacy_reshape._cluster_target(label, "general"), expected, label)

    def test_claim_text_cleaner(self) -> None:
        cases = {
            "Correct: vasospasm peaks day 4-14.": "Vasospasm peaks day 4-14.",
            "Partial — DCML somatotopy is right at the medulla.": "DCML somatotopy is right at the medulla.",
            "Incorrect, the answer is cushing reflex.": "The answer is cushing reflex.",
            "Vasospasm peaks day 4-14.": "Vasospasm peaks day 4-14.",  # clean -> unchanged
        }
        for raw, expected in cases.items():
            self.assertEqual(legacy_reshape.clean_claim_text_value(raw), expected, raw)
        # idempotent
        once = legacy_reshape.clean_claim_text_value("Correct: x.")
        self.assertEqual(legacy_reshape.clean_claim_text_value(once), once)

    def test_non_clinical_detection(self) -> None:
        for label in ("session length checkpoint", "report coverage anchor", "youve got the cst exactly",
                      "the snowball vs", "if a patient has a syrinx", "c"):
            self.assertTrue(legacy_reshape._is_non_clinical(label), label)
        self.assertFalse(legacy_reshape._is_non_clinical("Hunt-Hess clinical grading"))


class ReshapeApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = study_memory._get_db(Path(self.tmp.name) / "m.db")
        self.inv = _open_inventory()

    def tearDown(self) -> None:
        self.inv.close()
        self.conn.close()
        self.tmp.cleanup()

    def _add(self, topic: str, domain: str, name: str) -> int:
        study_memory.log_answer(self.conn, session_id="s", topic=topic, concept=name,
                                question="Q", answer="A", correct=0, tested_claim=name)
        row = self.conn.execute(
            "SELECT id FROM concepts WHERE lower(display_name)=lower(?) ORDER BY id DESC LIMIT 1", (name,)
        ).fetchone()
        cid = int(row["id"])
        self.conn.execute("UPDATE topics SET domain=? WHERE id=(SELECT topic_id FROM concepts WHERE id=?)", (domain, cid))
        self.conn.commit()
        return cid

    def test_relabel_bind_and_drop(self) -> None:
        bind_id = self._add("evd care", "neurocritical-care", "rapid vs gradual evd weaning outcomes")
        drop_id = self._add("session", "general", "session length checkpoint")
        report = legacy_reshape.analyze(self.conn, self.inv)
        decisions, gaps = legacy_reshape.gen_decisions(report, self.inv)
        result = legacy_reshape.apply_decisions(self.conn, self.inv, decisions)
        self.assertEqual(result["errors"], [])
        # the EVD concept is bound to the canonical weaning node and relabeled
        bound = self.conn.execute("SELECT inventory_concept_id, display_name FROM concepts WHERE id=?", (bind_id,)).fetchone()
        self.assertEqual(bound["inventory_concept_id"], "ncc.monitoring.evd-weaning")
        # the meta row is dropped to reference (no longer a tracked assessed claim)
        states = self.conn.execute(
            "SELECT COUNT(*) FROM claim_results WHERE concept_id=? AND origin='assessed'", (drop_id,)
        ).fetchone()[0]
        self.assertEqual(states, 0)

    def test_consolidation_merges_fragmented_rows(self) -> None:
        # Three verbose label variants of the same canonical concept -> three rows.
        for name in ("dcml decussation level", "dcml sensory modalities", "stt crossing segments"):
            self._add("long tracts", "anatomy", name)
        # Bind all three to the same canonical inventory node.
        self.conn.execute(
            "UPDATE concepts SET inventory_concept_id='ana.spine.spinal-cord-tracts' WHERE topic_id=(SELECT id FROM topics WHERE canonical_slug=(SELECT canonical_slug FROM topics WHERE id=(SELECT topic_id FROM concepts ORDER BY id LIMIT 1)))")
        self.conn.commit()
        before_rows = self.conn.execute(
            "SELECT COUNT(*) FROM concepts WHERE inventory_concept_id='ana.spine.spinal-cord-tracts'").fetchone()[0]
        before_claims = self.conn.execute(
            "SELECT COUNT(*) FROM claim_results WHERE origin='assessed'").fetchone()[0]
        result = legacy_reshape.consolidate_bound_concepts(self.conn)
        self.assertTrue(result["ok"])
        after_rows = self.conn.execute(
            "SELECT COUNT(*) FROM concepts WHERE inventory_concept_id='ana.spine.spinal-cord-tracts'").fetchone()[0]
        after_claims = self.conn.execute(
            "SELECT COUNT(*) FROM claim_results WHERE origin='assessed' AND concept_id=(SELECT id FROM concepts WHERE inventory_concept_id='ana.spine.spinal-cord-tracts')").fetchone()[0]
        self.assertEqual(before_rows, 3)
        self.assertEqual(after_rows, 1)           # collapsed to one canonical row
        self.assertEqual(after_claims, before_claims)  # all claims preserved on the canonical row
        # idempotent: a second pass merges nothing
        self.assertEqual(legacy_reshape.consolidate_bound_concepts(self.conn)["rows_merged"], 0)

    def test_apply_is_idempotent(self) -> None:
        self._add("evd care", "neurocritical-care", "rapid vs gradual evd weaning outcomes")
        report = legacy_reshape.analyze(self.conn, self.inv)
        decisions, _ = legacy_reshape.gen_decisions(report, self.inv)
        legacy_reshape.apply_decisions(self.conn, self.inv, decisions)
        # re-running analyze should now see it already bound (no new bind decisions)
        report2 = legacy_reshape.analyze(self.conn, self.inv)
        self.assertGreaterEqual(report2["counts"]["already_bound"], 1)


if __name__ == "__main__":
    unittest.main()
