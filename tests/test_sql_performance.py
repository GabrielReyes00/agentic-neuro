"""Phase 1 SQL scalability: schema-version gating, index coverage, pragmas,
maintenance, and that the hot queries resolve via index (no scans / temp sorts)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import study_memory  # noqa: E402

# Indexes that must exist for the hot paths to scale (the Phase 1 additions).
REQUIRED_INDEXES = {
    "idx_memory_claim_results_concept",
    "idx_memory_claim_results_topic_concept",
    "idx_memory_claim_state_concept_state",
    "idx_memory_claim_state_due",
}


class SqlPerformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = study_memory._get_db(Path(self.tmp.name) / "m.db")
        for i, claim in enumerate(("Vasospasm peaks day 4-14.", "Nimodipine runs 21 days.",
                                   "Modified Fisher predicts DCI.")):
            study_memory.log_answer(
                self.conn, session_id="s", topic="sah vasospasm", concept=f"Concept {i}",
                question="Q", answer="A", correct=i % 3, tested_claim=claim,
            )

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_schema_version_is_set(self) -> None:
        v = int(self.conn.execute("PRAGMA user_version").fetchone()[0])
        self.assertEqual(v, study_memory.SCHEMA_VERSION)

    def test_required_indexes_exist(self) -> None:
        names = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        missing = REQUIRED_INDEXES - names
        self.assertFalse(missing, f"missing indexes: {missing}")

    def test_connection_pragmas_applied(self) -> None:
        self.assertEqual(int(self.conn.execute("PRAGMA foreign_keys").fetchone()[0]), 1)
        self.assertEqual(str(self.conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(), "wal")
        self.assertEqual(int(self.conn.execute("PRAGMA synchronous").fetchone()[0]), 1)  # NORMAL

    def test_maintain_runs_analyze(self) -> None:
        result = study_memory.maintain_db(self.conn)
        self.assertTrue(result["ok"])
        stat_rows = self.conn.execute("SELECT COUNT(*) FROM sqlite_stat1").fetchone()[0]
        self.assertGreater(stat_rows, 0)

    def test_health_detects_foreign_key_violations_without_mutating(self) -> None:
        healthy = study_memory.database_health(self.conn)
        self.assertTrue(healthy["ok"])
        self.assertEqual(healthy["foreign_key_violations"], [])

        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys=OFF")
        self.conn.execute(
            "INSERT INTO topic_aliases (topic_id, alias, source, confidence) "
            "VALUES (999999, 'orphan health fixture', 'test', 1.0)"
        )
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys=ON")

        unhealthy = study_memory.database_health(self.conn)
        self.assertFalse(unhealthy["ok"])
        self.assertEqual(len(unhealthy["foreign_key_violations"]), 1)
        self.assertEqual(unhealthy["foreign_key_violations"][0]["table"], "topic_aliases")

    def test_hot_queries_use_indexes_not_scans(self) -> None:
        # With stats present, the per-concept and concept+state hot queries must
        # resolve via index (no full-table SCAN, no temp b-tree sort/group).
        study_memory.maintain_db(self.conn)
        cid = int(self.conn.execute("SELECT id FROM concepts LIMIT 1").fetchone()[0])
        for sql, params in [
            ("SELECT * FROM claim_state WHERE concept_id=? AND state IN ('missed','partially_repaired','regressed')", (cid,)),
            ("SELECT concept_id, COUNT(*) FROM claim_results WHERE topic_id=1 AND origin='assessed' GROUP BY concept_id", ()),
        ]:
            plan = " ".join(r[3] for r in self.conn.execute(f"EXPLAIN QUERY PLAN {sql}", params))
            self.assertNotIn("SCAN claim_state", plan)
            self.assertNotIn("SCAN claim_results", plan)
            self.assertIn("USING INDEX", plan)


class KnowledgeMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = study_memory._get_db(Path(self.tmp.name) / "m.db")
        # bound concept with a miss -> should be a weak spot; unbound stays out.
        t = study_memory.resolve_topic(self.conn, "sah vasospasm", "")
        tid = study_memory._ensure_topic(self.conn, t)
        self.conn.execute("UPDATE topics SET domain='vascular' WHERE id=?", (tid,))
        study_memory.log_answer(
            self.conn, session_id="s", topic="sah vasospasm", concept="Cerebral vasospasm",
            question="Q", answer="wrong", correct=0, tested_claim="Vasospasm peaks day 4-14.",
            error_type="omission", missing_edge="days 4-14",
            inventory_concept_id="vasc.sah.vasospasm",
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_view_exists_and_is_fan_out_safe(self) -> None:
        # one bound concept, one assessed miss -> exactly one row, attempts=1, open_gaps=1
        row = self.conn.execute(
            "SELECT attempts, successes, open_gaps FROM v_concept_mastery WHERE inventory_concept_id='vasc.sah.vasospasm'"
        ).fetchone()
        self.assertEqual(row["attempts"], 1)   # not multiplied by a join fan-out
        self.assertEqual(row["successes"], 0)
        self.assertEqual(row["open_gaps"], 1)

    def test_overview_surfaces_weak_spot_and_domain(self) -> None:
        out = study_memory.knowledge_map_overview(self.conn)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["bound_concepts"], 1)
        domains = {d["domain"] for d in out["domain_rollup"]}
        self.assertIn("vascular", domains)
        # log_answer lowercases the stored display_name via _normalize
        weak = {w["concept"].lower() for w in out["weak_spots"]}
        self.assertIn("cerebral vasospasm", weak)

    def test_overview_aggregates_duplicate_topic_envelopes_by_inventory_identity(self) -> None:
        study_memory.log_answer(
            self.conn,
            session_id="second-envelope",
            topic="delayed cerebral ischemia",
            concept="Cerebral vasospasm",
            question="Q2",
            answer="correct",
            correct=2,
            tested_claim="Vasospasm can produce delayed cerebral ischemia.",
            inventory_concept_id="vasc.sah.vasospasm",
        )
        self.conn.commit()

        local_rows = self.conn.execute(
            "SELECT COUNT(*) FROM concepts WHERE inventory_concept_id='vasc.sah.vasospasm'"
        ).fetchone()[0]
        self.assertEqual(local_rows, 2)

        out = study_memory.knowledge_map_overview(self.conn)
        self.assertEqual(out["bound_concepts"], 1)
        self.assertEqual(out["bound_local_rows"], 2)
        self.assertEqual(out["duplicate_envelope_rows"], 1)
        self.assertEqual(sum(int(row["concepts"]) for row in out["domain_rollup"]), 1)


if __name__ == "__main__":
    unittest.main()
