"""Tests for src/anki_queue.py — enqueue, review, flush."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import anki_queue
from anki_sync.schemas import CardDraft, ClaimModel
from anki_sync.anki_client import AnkiDispatchResult


class EnqueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = Path(self.tmp.name) / "queue.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_enqueue_cloze(self):
        ok = anki_queue.enqueue(
            session="2026-05-07T15:00:00+00:00",
            exchange_id=100,
            deck="Neurosurgery::Vascular::EVD Management",
            card_type="cloze",
            cloze="IDSA recommends {{c1::against}} prolonged prophylactic antibiotics for EVD duration",
            answer="Selects for resistant organisms without reducing ventriculitis",
            tags="study-review,conceptual_confusion",
            queue_path=self.queue,
        )
        self.assertTrue(ok)
        entries = anki_queue._read_queue(self.queue)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["card_type"], "cloze")
        self.assertIn("{{c1::", e["cloze_text"])
        self.assertEqual(e["exchange_id"], 100)
        self.assertEqual(e["deck"], "Neurosurgery::Vascular::EVD Management")
        self.assertIn("study-review", e["tags"])

    def test_enqueue_qa(self):
        ok = anki_queue.enqueue(
            session="2026-05-07T15:00:00+00:00",
            exchange_id=101,
            deck="Neurosurgery::Vascular::EVD Management",
            card_type="qa",
            front="What does a flat EVD waveform with low displayed ICP indicate?",
            back="System is not transducing — ICP number is untrustworthy. Check stopcock, tubing, and catheter.",
            queue_path=self.queue,
        )
        self.assertTrue(ok)
        entries = anki_queue._read_queue(self.queue)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["card_type"], "qa")
        self.assertIn("flat EVD waveform", entries[0]["front"])

    def test_enqueue_rejects_short_text(self):
        ok = anki_queue.enqueue(
            session="ts",
            exchange_id=1,
            deck="Neurosurgery::General::Test",
            card_type="cloze",
            cloze="{{c1::x}}",
            answer="y",
            queue_path=self.queue,
        )
        self.assertFalse(ok)
        self.assertFalse(self.queue.exists())

    def test_enqueue_rejects_bad_cloze(self):
        with self.assertRaises(Exception):
            anki_queue.enqueue(
                session="ts",
                exchange_id=1,
                deck="Neurosurgery::General::Test",
                card_type="cloze",
                cloze="No cloze markers in this text at all",
                answer="Some answer",
                queue_path=self.queue,
            )

    def test_enqueue_multiple_appends(self):
        for i in range(3):
            anki_queue.enqueue(
                session="ts",
                exchange_id=i,
                deck="Neurosurgery::Vascular::Test",
                card_type="cloze",
                cloze="Concept " + str(i) + " has threshold {{c1::value_" + str(i) + "}}",
                answer=f"Answer for concept {i}",
                queue_path=self.queue,
            )
        entries = anki_queue._read_queue(self.queue)
        self.assertEqual(len(entries), 3)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = Path(self.tmp.name) / "queue.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _enqueue_two_sessions(self):
        anki_queue.enqueue(
            session="session-A", exchange_id=1,
            deck="Neurosurgery::Vascular::EVD",
            card_type="cloze",
            cloze="CPP target is {{c1::60-70}} mmHg in TBI",
            answer="Below 60 risks ischemia",
            queue_path=self.queue,
        )
        anki_queue.enqueue(
            session="session-B", exchange_id=2,
            deck="Neurosurgery::Trauma::ICP",
            card_type="qa",
            front="What is the danger of pushing CPP above 70 mmHg in TBI?",
            back="ARDS risk from aggressive fluid and pressor use",
            queue_path=self.queue,
        )

    def test_review_all(self):
        self._enqueue_two_sessions()
        entries = anki_queue.review(queue_path=self.queue)
        self.assertEqual(len(entries), 2)

    def test_review_filters_by_session(self):
        self._enqueue_two_sessions()
        entries = anki_queue.review(session="session-A", queue_path=self.queue)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["session_ts"], "session-A")

    def test_review_empty(self):
        entries = anki_queue.review(queue_path=self.queue)
        self.assertEqual(len(entries), 0)


class FlushTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = Path(self.tmp.name) / "queue.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _enqueue_sample(self, session="ts", n=2):
        for i in range(n):
            anki_queue.enqueue(
                session=session, exchange_id=i,
                deck="Neurosurgery::Vascular::EVD Management",
                card_type="cloze",
                cloze=f"EVD infection risk increases with {{{{c1::duration and manipulation}}}} (fact {i})",
                answer=f"Answer {i}",
                queue_path=self.queue,
            )

    @patch.object(anki_queue, "NoveltyStore")
    @patch.object(anki_queue, "AnkiClient")
    def test_flush_dispatches_and_dedup(self, MockClient, MockStore):
        self._enqueue_sample()
        entries = anki_queue._read_queue(self.queue)
        first_cid = entries[0]["claim_id"]
        first_text = entries[0]["cloze_text"]

        mock_store = MockStore.return_value
        mock_store.filter_novel_claims.return_value = (
            [ClaimModel(claim_id=first_cid, subject="EVD infection", verb="increases with",
                        object="duration and manipulation", claim_text=first_text[:420])],
            [],
        )

        mock_client = MockClient.return_value
        mock_client.check_connection.return_value = (True, "")
        mock_client.add_card.return_value = AnkiDispatchResult(
            claim_id=first_cid, card_type="cloze", status="created", note_id=12345, error="",
        )

        result = anki_queue.flush(queue_path=self.queue)

        self.assertEqual(result["created"], 1)
        self.assertIn("Neurosurgery::Vascular::EVD Management", result["decks_touched"])
        mock_store.persist_claims.assert_called_once()
        remaining = anki_queue._read_queue(self.queue)
        self.assertEqual(len(remaining), 0)

    @patch.object(anki_queue, "NoveltyStore")
    @patch.object(anki_queue, "AnkiClient")
    def test_flush_preserves_queue_on_anki_unavailable(self, MockClient, MockStore):
        self._enqueue_sample()

        mock_client = MockClient.return_value
        mock_client.check_connection.return_value = (False, "Connection refused")

        result = anki_queue.flush(queue_path=self.queue)

        self.assertIn("error", result)
        remaining = anki_queue._read_queue(self.queue)
        self.assertEqual(len(remaining), 2)

    @patch.object(anki_queue, "NoveltyStore")
    @patch.object(anki_queue, "AnkiClient")
    def test_flush_session_filter_preserves_other_sessions(self, MockClient, MockStore):
        self._enqueue_sample(session="keep-me", n=1)
        self._enqueue_sample(session="flush-me", n=1)

        mock_store = MockStore.return_value
        entries_to_flush = [e for e in anki_queue._read_queue(self.queue) if e["session_ts"] == "flush-me"]
        mock_store.filter_novel_claims.return_value = (
            [ClaimModel(claim_id=e["claim_id"], subject="EVD infection", verb="increases with",
                        object="duration and manipulation", claim_text=e["cloze_text"][:420])
             for e in entries_to_flush],
            [],
        )

        mock_client = MockClient.return_value
        mock_client.check_connection.return_value = (True, "")
        mock_client.add_card.return_value = AnkiDispatchResult(
            claim_id="x", card_type="cloze", status="created", note_id=1, error="",
        )

        anki_queue.flush(session="flush-me", queue_path=self.queue)

        remaining = anki_queue._read_queue(self.queue)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["session_ts"], "keep-me")

    def test_flush_empty_queue(self):
        result = anki_queue.flush(queue_path=self.queue)
        self.assertEqual(result["queue_size"], 0)

    @patch.object(anki_queue, "NoveltyStore")
    def test_flush_dry_run(self, MockStore):
        self._enqueue_sample()
        mock_store = MockStore.return_value
        mock_store.filter_novel_claims.return_value = ([], [])

        result = anki_queue.flush(dry_run=True, queue_path=self.queue)

        self.assertTrue(result.get("dry_run"))
        remaining = anki_queue._read_queue(self.queue)
        self.assertEqual(len(remaining), 2)


if __name__ == "__main__":
    unittest.main()
