from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knowledge_graph import KnowledgeGraph


class KnowledgeGraphTests(unittest.TestCase):
    def _kg(self, tmp: str) -> KnowledgeGraph:
        return KnowledgeGraph(Path(tmp) / "kg.db")

    def test_apply_decay_reduces_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = self._kg(tmp)
            try:
                topic_id = kg._upsert_topic(
                    kg._normalize_topic("aneurysm natural history"),
                    "aneurysm natural history",
                    "vascular",
                )
                old_seen = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
                with kg.conn:
                    kg.conn.execute(
                        """UPDATE topics
                           SET confidence = 0.9, depth = 1, last_seen = ?,
                               last_decay_ts = NULL, stability_factor = 1.0
                           WHERE topic_id = ?""",
                        (old_seen, topic_id),
                    )

                kg.apply_decay(topic_id=topic_id)

                topic = kg.conn.execute(
                    "SELECT confidence FROM topics WHERE topic_id = ?",
                    (topic_id,),
                ).fetchone()
                self.assertLess(topic["confidence"], 0.9)

                decay_event = kg.conn.execute(
                    """SELECT COUNT(*) AS n FROM signal_events
                       WHERE topic_id = ? AND signal_type = 'decay'""",
                    (topic_id,),
                ).fetchone()
                self.assertGreaterEqual(decay_event["n"], 1)
            finally:
                kg.close()

    def test_log_study_gap_details_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = self._kg(tmp)
            try:
                with self.assertRaises(ValueError):
                    kg.log_study_session(
                        topics=["vasospasm surveillance"],
                        gap_details=[{
                            "concept": "TCD velocity threshold",
                            "error_type": "numerical_recall",
                            "error_process": "numerical_anchor",
                            "misconception": "threshold is 80 cm/s",
                            "remediation": "drill MCA velocity and Lindegaard ratio",
                        }],
                    )

                kg.log_study_session(
                    topics=["vasospasm surveillance"],
                    gap_details=[self._valid_gap()],
                )
                row = kg.conn.execute(
                    """SELECT COUNT(*) AS n
                       FROM concept_mastery
                       WHERE concept_text = 'mca velocity threshold'""",
                ).fetchone()
                self.assertEqual(row["n"], 1)
            finally:
                kg.close()

    def test_log_study_gap_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = self._kg(tmp)
            try:
                kg.log_study_session(
                    topics=["vasospasm surveillance"],
                    gap_details=[self._valid_gap()],
                    depth=2,
                    source="test",
                )
                event = kg.conn.execute(
                    """SELECT metadata FROM signal_events
                       WHERE signal_type = 'study_session'
                       ORDER BY event_id DESC LIMIT 1"""
                ).fetchone()
                self.assertIsNotNone(event)
                metadata = json.loads(event["metadata"])
                gap = metadata["gap_details"][0]
                for key in (
                    "concept", "error_type", "error_process",
                    "misconception", "root_cause", "remediation",
                ):
                    self.assertIn(key, gap)
            finally:
                kg.close()

    def test_last_session_narrative_matches_topic_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg = self._kg(tmp)
            try:
                kg.log_session_narrative(
                    skill="rag-workflow",
                    topics=["ICP management in traumatic brain injury"],
                    summary="Reviewed ICP thresholds and escalation.",
                    next_session_strategy="Start with CPP target before hyperosmolar details.",
                    key_confusions=[{
                        "concept_a": "cerebral perfusion pressure",
                        "concept_b": "intracranial pressure",
                        "disambiguation_axis": "pressure gradient versus compartment pressure",
                    }],
                )

                match = kg.get_last_session_narrative(
                    skill="rag-workflow",
                    topic="ICP management in TBI",
                )
                self.assertIsNotNone(match)
                self.assertEqual(match["summary"], "Reviewed ICP thresholds and escalation.")
                self.assertEqual(
                    match["key_confusions_json"][0]["concept_b"],
                    "intracranial pressure",
                )

                miss = kg.get_last_session_narrative(
                    skill="rag-workflow",
                    topic="vestibular schwannoma radiosurgery",
                )
                self.assertIsNone(miss)
            finally:
                kg.close()

    @staticmethod
    def _valid_gap() -> dict[str, str]:
        return {
            "concept": "MCA velocity threshold",
            "error_type": "numerical_recall",
            "error_process": "numerical_anchor",
            "misconception": "threshold is 80 cm/s",
            "root_cause": "anchored on normal flow velocity instead of vasospasm criteria",
            "remediation": "drill MCA velocity and Lindegaard ratio",
        }


if __name__ == "__main__":
    unittest.main()
