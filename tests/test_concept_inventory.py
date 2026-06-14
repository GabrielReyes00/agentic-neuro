from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import concept_inventory
import study_memory


class _InventoryFixture(unittest.TestCase):
    """A small, self-contained inventory built in a temp dir (no repo data touched)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.inv_dir = Path(self.tmp.name) / "sources"
        self.inv_dir.mkdir()
        self.db_path = Path(self.tmp.name) / "concept_inventory.db"
        self._write_sources()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_sources(self) -> None:
        foundations = {
            "domain": "general", "code": "fnd", "display_name": "Foundations",
            "topics": [{"id": "fnd.icp", "name": "ICP Physiology", "blurb": "ICP basics."}],
            "concepts": [
                {"id": "fnd.icp.monro-kellie", "name": "Monro-Kellie doctrine", "topic": "fnd.icp",
                 "type": "physiology", "tier": "foundation", "blurb": "Fixed cranial volume.",
                 "aliases": ["monro kellie"], "prereqs": [], "discriminators": [], "related": []},
                {"id": "fnd.icp.cpp", "name": "CPP calculation", "topic": "fnd.icp",
                 "type": "physiology", "tier": "foundation", "blurb": "CPP equals MAP minus ICP.",
                 "aliases": ["cpp", "cerebral perfusion pressure"],
                 "prereqs": ["fnd.icp.monro-kellie"], "discriminators": [], "related": []},
            ],
        }
        vascular = {
            "domain": "vascular", "code": "vasc", "display_name": "Vascular",
            "topics": [{"id": "vasc.sah", "name": "Subarachnoid Hemorrhage", "blurb": "SAH."}],
            "concepts": [
                {"id": "vasc.sah.hunt-hess", "name": "Hunt-Hess grading", "topic": "vasc.sah",
                 "type": "classification", "tier": "core", "blurb": "Clinical SAH grade I-V.",
                 "aliases": ["hunt hess", "hh grade"], "prereqs": [],
                 "discriminators": ["vasc.sah.dci"], "related": []},
                {"id": "vasc.sah.dci", "name": "Delayed cerebral ischemia", "topic": "vasc.sah",
                 "type": "pathology", "tier": "core", "blurb": "Clinical deterioration after SAH.",
                 "aliases": ["dci", "delayed cerebral ischemia"], "prereqs": ["fnd.icp.cpp"],
                 "discriminators": ["vasc.sah.vasospasm"], "related": []},
                {"id": "vasc.sah.vasospasm", "name": "Cerebral vasospasm", "topic": "vasc.sah",
                 "type": "pathology", "tier": "core", "blurb": "Arterial narrowing after SAH.",
                 "aliases": ["vasospasm", "angiographic vasospasm"], "prereqs": [],
                 "discriminators": ["vasc.sah.dci"], "related": []},
            ],
        }
        (self.inv_dir / "foundations.json").write_text(json.dumps(foundations))
        (self.inv_dir / "vascular.json").write_text(json.dumps(vascular))

    def _open(self) -> sqlite3.Connection:
        return concept_inventory._open_inventory(self.inv_dir, self.db_path)


class ValidationTests(_InventoryFixture):
    def test_clean_sources_validate(self) -> None:
        report = concept_inventory.validate_sources(self.inv_dir)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["concepts"], 5)

    def test_dangling_edge_is_warning_not_error(self) -> None:
        doc = json.loads((self.inv_dir / "vascular.json").read_text())
        doc["concepts"][0]["related"] = ["vasc.sah.nonexistent"]
        (self.inv_dir / "vascular.json").write_text(json.dumps(doc))
        report = concept_inventory.validate_sources(self.inv_dir)
        self.assertTrue(report["ok"])
        self.assertTrue(any("dangling" in w for w in report["warnings"]))

    def test_invalid_type_is_error(self) -> None:
        doc = json.loads((self.inv_dir / "vascular.json").read_text())
        doc["concepts"][0]["type"] = "not-a-type"
        (self.inv_dir / "vascular.json").write_text(json.dumps(doc))
        report = concept_inventory.validate_sources(self.inv_dir)
        self.assertFalse(report["ok"])

    def test_duplicate_concept_id_is_error(self) -> None:
        doc = json.loads((self.inv_dir / "vascular.json").read_text())
        dup = dict(doc["concepts"][0])
        doc["concepts"].append(dup)
        (self.inv_dir / "vascular.json").write_text(json.dumps(doc))
        report = concept_inventory.validate_sources(self.inv_dir)
        self.assertFalse(report["ok"])
        self.assertTrue(any("duplicate concept id" in e for e in report["errors"]))

    def test_id_prefix_mismatch_is_error(self) -> None:
        doc = json.loads((self.inv_dir / "vascular.json").read_text())
        doc["concepts"][0]["id"] = "wrong.sah.hunt-hess"
        (self.inv_dir / "vascular.json").write_text(json.dumps(doc))
        report = concept_inventory.validate_sources(self.inv_dir)
        self.assertFalse(report["ok"])


class BuildTests(_InventoryFixture):
    def test_build_is_deterministic_and_drops_dangling_edges(self) -> None:
        doc = json.loads((self.inv_dir / "vascular.json").read_text())
        doc["concepts"][0]["related"] = ["vasc.sah.nonexistent"]
        (self.inv_dir / "vascular.json").write_text(json.dumps(doc))
        result = concept_inventory.build_db(self.inv_dir, self.db_path, force=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"]["concepts"], 5)
        self.assertEqual(result["dropped_edge_count"], 1)
        first_hash = result["source_hash"]
        result2 = concept_inventory.build_db(self.inv_dir, self.db_path, force=True)
        self.assertEqual(result2["source_hash"], first_hash)

    def test_open_rebuilds_when_sources_change(self) -> None:
        conn = self._open()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0], 5)
        conn.close()
        doc = json.loads((self.inv_dir / "vascular.json").read_text())
        doc["concepts"].append({
            "id": "vasc.sah.fisher", "name": "Fisher scale", "topic": "vasc.sah",
            "type": "classification", "tier": "core", "blurb": "SAH blood burden grade.",
            "aliases": ["fisher", "modified fisher"], "prereqs": [], "discriminators": [], "related": [],
        })
        (self.inv_dir / "vascular.json").write_text(json.dumps(doc))
        conn = self._open()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0], 6)
        conn.close()


class ScopeTests(_InventoryFixture):
    def test_scope_by_topic_id_returns_entries_plus_neighbors(self) -> None:
        conn = self._open()
        scope = concept_inventory.scope_subgraph(conn, topic_id="vasc.sah", budget=20)
        conn.close()
        self.assertTrue(scope["ok"])
        entry_ids = {n["id"] for n in scope["nodes"] if n["role"] == "entry"}
        self.assertEqual(entry_ids, {"vasc.sah.hunt-hess", "vasc.sah.dci", "vasc.sah.vasospasm"})
        # The prereq fnd.icp.cpp is pulled in as a neighbor across the file boundary.
        self.assertIn("fnd.icp.cpp", {n["id"] for n in scope["nodes"]})

    def test_scope_by_query_anchors_topic(self) -> None:
        conn = self._open()
        scope = concept_inventory.scope_subgraph(conn, query="subarachnoid hemorrhage grading", budget=20)
        conn.close()
        self.assertTrue(scope["ok"])
        self.assertIn("vasc.sah", scope["scope"]["anchored_topics"])

    def test_scope_budget_is_enforced(self) -> None:
        conn = self._open()
        scope = concept_inventory.scope_subgraph(conn, topic_id="vasc.sah", budget=3)
        conn.close()
        self.assertLessEqual(scope["counts"]["nodes"], 3)

    def test_scope_unknown_topic_fails_cleanly(self) -> None:
        conn = self._open()
        scope = concept_inventory.scope_subgraph(conn, topic_id="vasc.nope")
        conn.close()
        self.assertFalse(scope["ok"])
        self.assertEqual(scope["reason"], "unknown_topic_id")

    def test_domain_hint_prunes_cross_domain_collision(self) -> None:
        conn = self._open()
        # "monro vasospasm" is a true 1v1 collision: Monro-Kellie (general) and
        # Cerebral vasospasm (vascular) tie, so the majority fallback leaves both
        # intact; the learner's domain hint disambiguates to vascular only.
        no_hint = concept_inventory.scope_subgraph(conn, query="monro vasospasm", budget=20)
        hinted = concept_inventory.scope_subgraph(conn, query="monro vasospasm", domain_hint="vascular", budget=20)
        conn.close()
        no_hint_domains = {n["domain"] for n in no_hint["nodes"] if n["role"] == "entry"}
        hinted_domains = {n["domain"] for n in hinted["nodes"] if n["role"] == "entry"}
        self.assertIn("vascular", no_hint_domains)
        self.assertIn("general", no_hint_domains)
        self.assertEqual(hinted_domains, {"vascular"})

    def test_anchored_domain_guard_never_empties_scope(self) -> None:
        # A domain_hint that names no matched domain must not prune everything:
        # "hunt hess" only matches a vascular node; a 'general' hint should leave
        # the scope intact rather than collapse it.
        conn = self._open()
        scope = concept_inventory.scope_subgraph(
            conn, query="hunt hess", domain_hint="general", budget=20,
        )
        conn.close()
        self.assertTrue(scope["ok"])
        entry_ids = {n["id"] for n in scope["nodes"] if n["role"] == "entry"}
        self.assertIn("vasc.sah.hunt-hess", entry_ids)

    def test_anchor_tokens_pull_studied_concept_into_scope(self) -> None:
        conn = self._open()
        base = concept_inventory.scope_subgraph(conn, query="hunt hess", budget=20)
        anchored = concept_inventory.scope_subgraph(
            conn, query="hunt hess", anchor_tokens=frozenset({"vasospasm"}), budget=20,
        )
        conn.close()
        base_entries = {n["id"] for n in base["nodes"] if n["role"] == "entry"}
        anchored_entries = {n["id"] for n in anchored["nodes"] if n["role"] == "entry"}
        self.assertNotIn("vasc.sah.vasospasm", base_entries)
        self.assertIn("vasc.sah.vasospasm", anchored_entries)

    def test_concept_based_topic_anchoring(self) -> None:
        # The topic name "Subarachnoid Hemorrhage" shares no tokens with this query,
        # but several of its concepts match -> the topic still anchors and its whole
        # concept set is pulled into scope (the nimodipine-omission fix).
        conn = self._open()
        scope = concept_inventory.scope_subgraph(conn, query="cerebral vasospasm ischemia", budget=20)
        conn.close()
        self.assertTrue(scope["ok"])
        self.assertIn("vasc.sah", scope["scope"]["anchored_topics"])
        ids = {n["id"] for n in scope["nodes"]}
        # Hunt-Hess grading shares no token with the query yet rides in via anchoring
        self.assertIn("vasc.sah.hunt-hess", ids)

    def test_scope_is_deterministic(self) -> None:
        conn = self._open()
        a = concept_inventory.scope_subgraph(conn, query="vasospasm vs dci", budget=10)
        b = concept_inventory.scope_subgraph(conn, query="vasospasm vs dci", budget=10)
        conn.close()
        self.assertEqual([n["id"] for n in a["nodes"]], [n["id"] for n in b["nodes"]])


class MapLearnerTests(_InventoryFixture):
    def _seed_memory(self) -> Path:
        mem_path = Path(self.tmp.name) / "study_memory.db"
        conn = study_memory._get_db(mem_path)
        study_memory.log_answer(
            conn, session_id="s1", topic="subarachnoid hemorrhage",
            concept="delayed cerebral ischemia vs vasospasm", question="Q", answer="confused", correct=0,
            error_type="conceptual_confusion", misconception="thinks vasospasm equals DCI",
            tested_claim="DCI is clinical deterioration; vasospasm may be asymptomatic.",
        )
        study_memory.log_answer(
            conn, session_id="s1", topic="subarachnoid hemorrhage",
            concept="hunt-hess grading", question="Q", answer="correct", correct=2,
            tested_claim="Hunt-Hess grades SAH severity I-V.",
        )
        conn.close()
        return mem_path

    def test_map_learner_projects_memory_and_flags_misconception(self) -> None:
        mem_path = self._seed_memory()
        conn = self._open()
        res = concept_inventory.map_learner(
            inventory_conn=conn, memory_db=mem_path,
            learner_topics=["subarachnoid hemorrhage"],
            topic_id="vasc.sah", budget=20,
        )
        conn.close()
        self.assertTrue(res["ok"])
        self.assertEqual(res["learner_status"], "ok")
        # The hint resolves through study_memory's own resolver to a canonical slug.
        self.assertTrue(res["resolved_learner_topics"])
        by_id = {e["concept_id"]: e for e in res["knowledge_map"]}
        # DCI miss with conceptual_confusion is flagged as an active misconception.
        self.assertTrue(by_id["vasc.sah.dci"]["active_misconception"])
        self.assertNotEqual(by_id["vasc.sah.dci"]["exposure_status"], "unexposed")
        # Hunt-Hess (correct) was matched and is no longer unexposed.
        self.assertNotEqual(by_id["vasc.sah.hunt-hess"]["exposure_status"], "unexposed")
        # A correct (durable) claim must project knowledge_state "passed", not the
        # "untested" default — a mastered concept has to be distinguishable from an
        # untouched one on rebuild (regression guard for the durable->passed mapping).
        self.assertEqual(by_id["vasc.sah.hunt-hess"]["knowledge_state"], "passed")
        # Untouched concepts remain unexposed.
        self.assertEqual(by_id["vasc.sah.vasospasm"]["exposure_status"], "unexposed")
        # Most of the map is unexposed -> ORIENT, but the misconception drives a remediate interrupt.
        plan = res["sequential_teaching_plan"]
        self.assertEqual(plan["current_phase"], "phase_1_clear_fog")
        self.assertIn("Delayed cerebral ischemia", plan["interrupts"]["remediate"])

    def test_explicit_off_scope_binding_stays_unmatched(self) -> None:
        mem_path = Path(self.tmp.name) / "study_memory.db"
        mem = study_memory._get_db(mem_path)
        try:
            study_memory.log_answer(
                mem,
                session_id="s-offscope",
                topic="subarachnoid hemorrhage",
                concept="CPP calculation",
                question="Q",
                answer="A",
                correct=1,
                tested_claim="CPP equals MAP minus ICP.",
                inventory_concept_id="fnd.icp.monro-kellie",
            )
        finally:
            mem.close()

        conn = self._open()
        res = concept_inventory.map_learner(
            inventory_conn=conn, memory_db=mem_path,
            learner_topics=["subarachnoid hemorrhage"],
            topic_id="vasc.sah", budget=20,
        )
        conn.close()

        by_id = {e["concept_id"]: e for e in res["knowledge_map"]}
        self.assertEqual(by_id["fnd.icp.cpp"]["attempts_count"], 0)
        self.assertEqual(by_id["fnd.icp.cpp"]["matched_learner_concepts"], [])
        unmatched = res["unmatched_learner_concepts"]
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(unmatched[0]["inventory_concept_id"], "fnd.icp.monro-kellie")
        self.assertEqual(unmatched[0]["binding_source"], "explicit_out_of_scope")

    def test_map_learner_handles_absent_memory_db(self) -> None:
        conn = self._open()
        res = concept_inventory.map_learner(
            inventory_conn=conn, memory_db=Path(self.tmp.name) / "nonexistent.db",
            learner_topics=["subarachnoid hemorrhage"], topic_id="vasc.sah", budget=20,
        )
        conn.close()
        self.assertTrue(res["ok"])
        self.assertEqual(res["learner_status"], "memory_db_absent")
        # With no learner data, every node is unexposed -> ORIENT.
        self.assertEqual(res["sequential_teaching_plan"]["current_phase"], "phase_1_clear_fog")
        self.assertEqual(res["counts"]["unexposed"], res["counts"]["nodes"])

    def test_map_learner_does_not_write_to_memory_db(self) -> None:
        mem_path = self._seed_memory()
        before = mem_path.read_bytes()
        conn = self._open()
        concept_inventory.map_learner(
            inventory_conn=conn, memory_db=mem_path,
            learner_topics=["subarachnoid hemorrhage"], topic_id="vasc.sah", budget=20,
        )
        conn.close()
        # WAL checkpoint aside, the main db file content must be unchanged by a read-only open.
        self.assertEqual(mem_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
