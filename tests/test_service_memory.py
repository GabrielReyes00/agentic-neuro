from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import study_memory


class ServiceRotationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.memory_path = Path(self.tmp.name) / "study_memory.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _conn(self) -> sqlite3.Connection:
        return study_memory._get_db(self.memory_path)

    def _log_service_gap(self, conn, *, topic, concept, claim, rotation_id, convention=False, correct=0):
        return study_memory.log_answer(
            conn,
            session_id="svc-session",
            topic=topic,
            concept=concept,
            question=f"Probe: {concept}?",
            answer="learner answer",
            correct=correct,
            skill="service-log",
            origin="service",
            rotation_id=rotation_id,
            convention=convention,
            tested_claim=claim,
            corrected_rule=claim,
        )

    def test_default_origin_is_assessed(self) -> None:
        conn = self._conn()
        try:
            study_memory.log_answer(
                conn, session_id="s", topic="hydrocephalus", concept="evd setpoint",
                question="EVD setpoint?", answer="x", correct=0,
                tested_claim="EVD is leveled at the tragus.", corrected_rule="Level at tragus.",
            )
            origins = [r["origin"] for r in conn.execute("SELECT origin FROM claim_state")]
            self.assertEqual(origins, ["assessed"])
        finally:
            conn.close()

    def test_migration_is_idempotent_and_backfills(self) -> None:
        conn = self._conn()
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(claim_state)")}
            self.assertIn("origin", cols)
            self.assertIn("rotation_id", cols)
            study_memory._migrate_schema(conn)
            study_memory._migrate_schema(conn)
        finally:
            conn.close()

    def test_rotation_start_seeds_acgme_targets_by_domain_and_pgy(self) -> None:
        conn = self._conn()
        try:
            view = study_memory.start_rotation(conn, service="tumor", site="MD Anderson", pgy=1)
            self.assertEqual(view["service"], "tumor")
            self.assertEqual(view["domain"], "tumor")
            self.assertEqual(view["site"], "md-anderson")
            self.assertGreater(view["rubric_seeded"], 0)
            rows = conn.execute(
                "SELECT domain, origin, pgy_target FROM competency_targets WHERE service_id = (SELECT id FROM services WHERE slug='tumor')"
            ).fetchall()
            self.assertTrue(rows)
            for r in rows:
                self.assertEqual(r["domain"], "tumor")
                self.assertEqual(r["origin"], "acgme")
                if r["pgy_target"] is not None:
                    self.assertLessEqual(r["pgy_target"], 1)
        finally:
            conn.close()

    def test_only_one_active_rotation(self) -> None:
        conn = self._conn()
        try:
            study_memory.start_rotation(conn, service="tumor", site="MD Anderson", pgy=1)
            study_memory.start_rotation(conn, service="spine", site="Ben Taub", pgy=1)
            active = conn.execute("SELECT COUNT(*) FROM rotations WHERE active = 1").fetchone()[0]
            self.assertEqual(active, 1)
            self.assertEqual(study_memory.current_rotation(conn)["service"], "spine")
        finally:
            conn.close()

    def test_service_gap_sealed_from_formal_lens(self) -> None:
        conn = self._conn()
        try:
            rid = study_memory.start_rotation(conn, service="tumor", site="MD Anderson", pgy=1)["rotation_id"]
            self._log_service_gap(
                conn, topic="peritumoral edema", concept="dexamethasone dosing",
                claim="Dexamethasone 10 mg IV load then 4 mg q6h for symptomatic vasogenic edema.",
                rotation_id=rid,
            )
            formal = json.loads(study_memory.startup_recall(conn, topic="peritumoral edema", lens="formal"))
            blob = json.dumps(formal).lower()
            self.assertNotIn("dexamethasone 10 mg", blob)
            summ = json.loads(study_memory.retrieval_summary(conn, topic="peritumoral edema"))
            self.assertEqual(summ.get("counts", {}).get("must_retest", 0), 0)
        finally:
            conn.close()

    def test_service_origin_misconceptions_do_not_leak_into_formal_recall(self) -> None:
        conn = self._conn()
        try:
            study_memory.log_answer(
                conn,
                session_id="formal-miss",
                topic="peritumoral edema",
                concept="dexamethasone dosing",
                question="What is the initial dexamethasone approach for symptomatic edema?",
                answer="FORMAL WRONG ANSWER",
                correct=0,
                tested_claim="Dexamethasone dosing for symptomatic vasogenic edema should be individualized to acuity and service plan.",
                missing_edge="formal missing edge",
                force_new_claim=True,
            )
            rid = study_memory.start_rotation(conn, service="tumor", site="MD Anderson", pgy=1)["rotation_id"]
            study_memory.log_answer(
                conn,
                session_id="service-miss",
                topic="peritumoral edema",
                concept="dexamethasone dosing",
                question="What site-local edema convention was discussed?",
                answer="SERVICE LOCAL WRONG ANSWER SHOULD NOT APPEAR",
                correct=0,
                skill="service-log",
                origin="service",
                rotation_id=rid,
                convention=True,
                tested_claim="Dexamethasone dosing for symptomatic vasogenic edema should be individualized to acuity and service plan.",
                missing_edge="service missing edge",
                force_new_claim=True,
            )

            formal = json.loads(study_memory.startup_recall(conn, topic="peritumoral edema", lens="formal"))
            blob = json.dumps(formal)
            self.assertIn("FORMAL WRONG ANSWER", blob)
            self.assertNotIn("SERVICE LOCAL WRONG ANSWER SHOULD NOT APPEAR", blob)
            self.assertNotIn("service missing edge", blob)
        finally:
            conn.close()

    def test_service_lens_primary_plus_capped_tagged_formal(self) -> None:
        conn = self._conn()
        try:
            rid = study_memory.start_rotation(conn, service="tumor", site="MD Anderson", pgy=1)["rotation_id"]
            self._log_service_gap(
                conn, topic="peritumoral edema", concept="dexamethasone dosing",
                claim="Dexamethasone 10 mg IV load then 4 mg q6h for symptomatic vasogenic edema.",
                rotation_id=rid,
            )
            study_memory.log_answer(
                conn, session_id="f", topic="glioblastoma", concept="mgmt methylation",
                question="MGMT significance?", answer="wrong", correct=0, skill="study-review",
                tested_claim="MGMT promoter methylation predicts temozolomide benefit.",
                corrected_rule="MGMT methylation predicts TMZ benefit.",
            )
            conn.execute("UPDATE topics SET domain='tumor'")
            conn.commit()
            svc = json.loads(study_memory.startup_recall(conn, lens="service", service="tumor", site="md-anderson"))
            self.assertTrue(any("dexamethasone" in g["concept"].lower() for g in svc["service_gaps"]))
            self.assertEqual(svc["weighting_policy"], "service_primary_formal_capped")
            self.assertTrue(svc["formal_secondary"])
            self.assertTrue(all(g["origin"] == "assessed" for g in svc["formal_secondary"]))
            self.assertTrue(any("mgmt" in g["concept"].lower() for g in svc["formal_secondary"]))
            self.assertEqual(svc["rotation"]["rotation_id"], rid)
            self.assertGreater(svc["rubric_progress"]["total"], 0)
        finally:
            conn.close()

    def test_service_lens_surfaces_scoped_candidates_and_counts_unmapped(self) -> None:
        conn = self._conn()
        try:
            rid = study_memory.start_rotation(
                conn, service="tumor", site="MD Anderson", pgy=1
            )["rotation_id"]
            assessed_id = study_memory.add_shift_debrief_candidate(
                conn,
                session_id="portable",
                topic="tumor candidate",
                concept="portable tumor teaching",
                doc_path="Shift Debriefs/Portable Tumor Teaching.md",
                prompt="What is the portable tumor teaching?",
                claim_text="Portable tumor claim.",
                provenance_tier="clinical_knowledge",
            )
            conn.execute(
                """UPDATE topics SET domain = 'tumor'
                    WHERE id = (SELECT topic_id FROM shift_debrief_review_candidates WHERE id = ?)""",
                (assessed_id,),
            )
            local_id = study_memory.add_shift_debrief_candidate(
                conn,
                session_id="local",
                topic="local tumor workflow",
                concept="local tumor convention",
                doc_path="Shift Debriefs/Local Tumor Workflow.md",
                prompt="What local convention must be confirmed?",
                claim_text="Local tumor convention.",
                provenance_tier="service_teaching",
                origin="service",
                rotation_id=rid,
                convention=True,
            )
            study_memory.add_shift_debrief_candidate(
                conn,
                session_id="unmapped",
                topic="uncategorized pearl",
                concept="uncategorized pearl",
                doc_path="Shift Debriefs/Uncategorized Pearl.md",
                prompt="What is this uncategorized pearl?",
                claim_text="Do not guess this candidate's service.",
                provenance_tier="clinical_knowledge",
            )
            conn.commit()

            svc = json.loads(
                study_memory.startup_recall(
                    conn, lens="service", service="tumor", site="md-anderson"
                )
            )
            ids = {item["candidate_id"] for item in svc["pending_review_candidates"]}
            self.assertEqual(ids, {assessed_id, local_id})
            self.assertEqual(svc["counts"]["unmapped_review_candidates"], 1)
            self.assertTrue(any("excluded" in warning for warning in svc["data_quality_warnings"]))
        finally:
            conn.close()

    def test_clinical_gap_carries_but_convention_is_site_local(self) -> None:
        conn = self._conn()
        try:
            r1 = study_memory.start_rotation(conn, service="tumor", site="MD Anderson", pgy=1)["rotation_id"]
            self._log_service_gap(
                conn, topic="peritumoral edema", concept="dexamethasone dosing",
                claim="Dexamethasone 10 mg IV load then 4 mg q6h.", rotation_id=r1,
            )
            self._log_service_gap(
                conn, topic="tumor board logistics", concept="mda taper order set",
                claim="MDA uses a specific post-op dexamethasone taper order set.",
                rotation_id=r1, convention=True, correct=2,
            )
            mda = json.loads(study_memory.startup_recall(conn, lens="service", service="tumor", site="md-anderson"))
            self.assertEqual(len(mda["conventions"]), 1)

            study_memory.start_rotation(conn, service="tumor", site="Ben Taub", pgy=1)
            bt = json.loads(study_memory.startup_recall(conn, lens="service", service="tumor", site="ben-taub"))
            self.assertTrue(any("dexamethasone" in g["concept"].lower() for g in bt["service_gaps"]),
                            "clinical gap must carry across sites")
            self.assertEqual(len(bt["conventions"]), 0, "convention must not surface at another site")
        finally:
            conn.close()

    def test_same_convention_text_stays_separate_across_sites(self) -> None:
        conn = self._conn()
        try:
            r1 = study_memory.start_rotation(conn, service="tumor", site="MD Anderson", pgy=1)["rotation_id"]
            self._log_service_gap(
                conn, topic="tumor board logistics", concept="steroid taper order set",
                claim="Use the local steroid taper order set after tumor surgery.",
                rotation_id=r1, convention=True, correct=2,
            )
            r2 = study_memory.start_rotation(conn, service="tumor", site="Ben Taub", pgy=1)["rotation_id"]
            self._log_service_gap(
                conn, topic="tumor board logistics", concept="steroid taper order set",
                claim="Use the local steroid taper order set after tumor surgery.",
                rotation_id=r2, convention=True, correct=2,
            )

            rows = conn.execute(
                "SELECT claim_slug, rotation_id FROM claim_state WHERE gap_type='convention' ORDER BY id"
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertNotEqual(rows[0]["claim_slug"], rows[1]["claim_slug"])

            mda = json.loads(study_memory.startup_recall(conn, lens="service", service="tumor", site="md-anderson"))
            bt = json.loads(study_memory.startup_recall(conn, lens="service", service="tumor", site="ben-taub"))
            self.assertEqual(len(mda["conventions"]), 1)
            self.assertEqual(len(bt["conventions"]), 1)
            self.assertNotEqual(mda["conventions"][0]["claim_state_id"], bt["conventions"][0]["claim_state_id"])
        finally:
            conn.close()

    def test_service_origin_requires_rotation(self) -> None:
        conn = self._conn()
        try:
            with self.assertRaisesRegex(ValueError, "requires an active or explicit valid rotation"):
                study_memory.log_answer(
                    conn,
                    session_id="svc-orphan",
                    topic="peritumoral edema",
                    concept="dexamethasone dosing",
                    question="Dose?",
                    answer="learner answer",
                    correct=0,
                    skill="service-log",
                    origin="service",
                    tested_claim="Dexamethasone 10 mg IV load then 4 mg q6h.",
                    corrected_rule="Dexamethasone 10 mg IV load then 4 mg q6h.",
                )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM claim_state").fetchone()[0], 0)
        finally:
            conn.close()

    def test_service_gap_does_not_bind_to_assessed_claim(self) -> None:
        conn = self._conn()
        try:
            rid = study_memory.start_rotation(conn, service="tumor", site="MD Anderson", pgy=1)["rotation_id"]
            claim = "Dexamethasone 10 mg IV load then 4 mg q6h for symptomatic vasogenic edema."
            study_memory.log_answer(
                conn, session_id="f", topic="peritumoral edema", concept="dexamethasone dosing",
                question="Dose?", answer="x", correct=0, skill="study-review",
                tested_claim=claim, corrected_rule=claim,
            )
            self._log_service_gap(
                conn, topic="peritumoral edema", concept="dexamethasone dosing", claim=claim, rotation_id=rid,
            )
            origins = sorted(r["origin"] for r in conn.execute("SELECT origin FROM claim_state"))
            self.assertEqual(origins, ["assessed", "service"], "service and assessed gaps must stay distinct rows")
        finally:
            conn.close()

    def test_shift_debrief_service_candidate_reviews_as_site_local_convention(self) -> None:
        conn = self._conn()
        try:
            rid = study_memory.start_rotation(conn, service="tumor", site="MD Anderson", pgy=1)["rotation_id"]
            candidate_id = study_memory.add_shift_debrief_candidate(
                conn,
                session_id="shift-debrief-service",
                topic="tumor edema service practice",
                concept="local steroid taper order set",
                doc_path="Shift Debriefs/Tumor Edema Service Teaching.md",
                prompt="Which steroid taper order-set detail needs local confirmation?",
                claim_text="MDA uses a local postoperative dexamethasone taper order set for tumor edema.",
                provenance_tier="Service teaching - locally confirm",
                origin="service",
                rotation_id=rid,
                convention=True,
            )
            study_memory.log_answer(
                conn,
                session_id="shift-debrief-service-review",
                topic="tumor edema service practice",
                concept="local steroid taper order set",
                question="What is the status of the MDA tumor edema taper?",
                answer="It is a local order set to confirm, not a universal rule.",
                correct=2,
                skill="study-review",
                doc_path="Shift Debriefs/Tumor Edema Service Teaching.md",
                tested_claim="MDA uses a local postoperative dexamethasone taper order set for tumor edema.",
                corrected_rule="Treat the taper as a site-local convention to confirm with the service.",
                origin="service",
                rotation_id=rid,
                convention=True,
                shift_debrief_candidate_id=candidate_id,
            )

            state = conn.execute("SELECT origin, gap_type, rotation_id FROM claim_state").fetchone()
            self.assertEqual(state["origin"], "service")
            self.assertEqual(state["gap_type"], "convention")
            self.assertEqual(int(state["rotation_id"]), int(rid))
            formal = json.loads(study_memory.startup_recall(conn, topic="tumor edema service practice", lens="formal"))
            self.assertNotIn("dexamethasone taper", json.dumps(formal).lower())
            svc = json.loads(study_memory.startup_recall(conn, lens="service", service="tumor", site="md-anderson"))
            self.assertTrue(any("taper" in item["concept"] for item in svc["conventions"]))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
