"""Tests for the four-layer logging discipline: atomicity guard + binding resolution."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import memory_logging  # noqa: E402


class AtomicityGuardTests(unittest.TestCase):
    def test_clean_canonical_label_has_no_warnings(self) -> None:
        self.assertEqual(memory_logging.atomicity_warnings("Hunt-Hess grading"), [])
        self.assertEqual(memory_logging.atomicity_warnings("Cerebral vasospasm"), [])

    def test_conjunction_label_flagged(self) -> None:
        issues = memory_logging.atomicity_warnings(
            "acute traumatic central cord syndrome management and anatomy"
        )
        self.assertTrue(any("conflated_concept" in i for i in issues))

    def test_comparison_label_flagged(self) -> None:
        issues = memory_logging.atomicity_warnings("neurogenic versus spinal shock")
        self.assertTrue(any("comparison_as_concept" in i for i in issues))

    def test_embedded_trial_flagged(self) -> None:
        issues = memory_logging.atomicity_warnings(
            "metastatic spinal cord compression management and patchell trial details"
        )
        self.assertTrue(any("evidence_in_label" in i for i in issues))

    def test_verbose_label_flagged(self) -> None:
        issues = memory_logging.atomicity_warnings(
            "postoperative spine discharge readiness checklist for elective fusion"
        )
        self.assertTrue(any("verbose_label" in i for i in issues))


class BindingResolutionTests(unittest.TestCase):
    KMAP = [
        {"concept_id": "vasc.sah.hunt-hess", "concept": "Hunt-Hess clinical grading"},
        {"concept_id": "vasc.sah.vasospasm", "concept": "Cerebral vasospasm"},
    ]

    def test_explicit_id_wins(self) -> None:
        res = memory_logging.resolve_inventory_binding(
            explicit_id="vasc.sah.hunt-hess", concept="anything", knowledge_map=self.KMAP,
        )
        self.assertEqual(res.status, "explicit")
        self.assertEqual(res.as_dict()["status"], "explicit")
        self.assertNotIn("score", res.as_dict())  # explicit is certain

    def test_inferred_when_lexically_matched(self) -> None:
        res = memory_logging.resolve_inventory_binding(
            explicit_id="", concept="Hunt-Hess grading", knowledge_map=self.KMAP,
        )
        self.assertEqual(res.status, "inferred")
        self.assertEqual(res.inventory_concept_id, "vasc.sah.hunt-hess")

    def test_unresolved_carries_candidates(self) -> None:
        res = memory_logging.resolve_inventory_binding(
            explicit_id="", concept="nimodipine duration", knowledge_map=self.KMAP,
        )
        self.assertEqual(res.status, "unresolved")
        self.assertEqual(res.inventory_concept_id, "")
        # candidates are best-effort near-misses for the node-proposal queue
        self.assertIsInstance(res.as_dict().get("candidates", []), list)

    def test_unresolved_without_map(self) -> None:
        res = memory_logging.resolve_inventory_binding(
            explicit_id="", concept="x", knowledge_map=None,
        )
        self.assertEqual(res.status, "unresolved")


class LogAnswerBindingEmissionTests(unittest.TestCase):
    """End-to-end: log-answer must emit a loud binding= line and atomicity advisories."""

    def _run_log_answer(self, *, concept: str, topic: str, extra: list[str]):
        import contextlib
        import io
        import tempfile
        import unittest.mock
        import study_memory
        import session_map as sm

        tmp = tempfile.TemporaryDirectory()
        sessions_dir = Path(tmp.name) / "Sessions"
        sessions_dir.mkdir()
        db_path = Path(tmp.name) / "m.db"
        study_memory._get_db(db_path).close()
        argv = [
            "study_memory.py", "log-answer",
            "--session", "smoke", "--topic", topic, "--concept", concept,
            "--question", "Q", "--answer", "A", "--correct", "0",
            "--skill", "study-review", *extra,
        ]
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(study_memory, "DB_PATH", db_path), \
                unittest.mock.patch.object(sm, "SESSIONS_DIR", sessions_dir), \
                unittest.mock.patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            study_memory.main()
        tmp.cleanup()
        return out.getvalue(), err.getvalue()

    def test_explicit_binding_line(self) -> None:
        out, _ = self._run_log_answer(
            concept="Hunt-Hess clinical grading", topic="subarachnoid hemorrhage",
            extra=["--inventory-concept-id", "vasc.sah.hunt-hess"],
        )
        binding = [l for l in out.splitlines() if l.startswith("binding=")]
        self.assertEqual(len(binding), 1)
        self.assertIn('"status":"explicit"', binding[0])
        self.assertIn("vasc.sah.hunt-hess", binding[0])

    def test_inferred_binding_without_explicit_id(self) -> None:
        out, _ = self._run_log_answer(
            concept="Hunt-Hess grading", topic="subarachnoid hemorrhage", extra=[],
        )
        binding = [l for l in out.splitlines() if l.startswith("binding=")]
        self.assertEqual(len(binding), 1)
        # inferred or unresolved, but never silently treated as explicit
        self.assertNotIn('"status":"explicit"', binding[0])

    def test_atomicity_advisory_emitted_for_conflated_label(self) -> None:
        _, err = self._run_log_answer(
            concept="central cord syndrome management and anatomy",
            topic="spinal cord injury", extra=["--inventory-concept-id", "spine.scin.central-cord"],
        )
        self.assertIn("atomicity", err)
        self.assertIn("conflated_concept", err)


class IdentityRowReuseTests(unittest.TestCase):
    """Future-write: an explicit inventory binding reuses the canonical concept row,
    so the consolidated one-concept-per-node model does not re-fragment."""

    def test_same_binding_reuses_one_row(self) -> None:
        import tempfile
        import study_memory

        with tempfile.TemporaryDirectory() as tmp:
            conn = study_memory._get_db(Path(tmp) / "m.db")
            for label in ("dcml decussation level", "dcml sensory modalities", "stt crossing segments"):
                study_memory.log_answer(
                    conn, session_id="s", topic="long tracts", concept=label,
                    question="Q", answer="A", correct=1, tested_claim=label,
                    inventory_concept_id="ana.spine.spinal-cord-tracts",
                )
            rows = conn.execute(
                "SELECT COUNT(*) FROM concepts WHERE inventory_concept_id='ana.spine.spinal-cord-tracts'"
            ).fetchone()[0]
            claims = conn.execute(
                """SELECT COUNT(*) FROM claim_results WHERE origin='assessed'
                   AND concept_id=(SELECT id FROM concepts WHERE inventory_concept_id='ana.spine.spinal-cord-tracts')"""
            ).fetchone()[0]
            self.assertEqual(rows, 1)     # three labels -> one canonical row
            self.assertEqual(claims, 3)   # all three claims on it
            conn.close()


if __name__ == "__main__":
    unittest.main()
