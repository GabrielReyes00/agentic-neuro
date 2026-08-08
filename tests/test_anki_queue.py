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
import study_memory
from anki_sync.schemas import CardDraft, ClaimModel
from anki_sync.anki_client import AnkiClient, AnkiDispatchResult
from anki_sync.novelty import NoveltyDecision


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

    def test_enqueue_allows_shift_debrief_deck_with_provenance_tag(self):
        ok = anki_queue.enqueue(
            session="ts",
            exchange_id=102,
            deck="Neurosurgery::Shift Debriefs",
            card_type="qa",
            front="During local transport practice, what EVD step requires confirmation?",
            back="Confirm the institution-specific clamping and leveling plan with the supervising service.",
            tags="shift-debrief,study-review",
            queue_path=self.queue,
        )
        self.assertTrue(ok)
        entries = anki_queue._read_queue(self.queue)
        self.assertEqual(entries[0]["deck"], "Neurosurgery::Shift Debriefs")
        self.assertIn("shift-debrief", entries[0]["tags"])

    def test_enqueue_rejects_unlabelled_or_misrouted_shift_debrief_card(self):
        unlabelled = anki_queue.enqueue(
            session="ts",
            exchange_id=103,
            deck="Neurosurgery::Shift Debriefs",
            card_type="qa",
            front="During local transport practice, what EVD step requires confirmation?",
            back="Confirm local practice.",
            queue_path=self.queue,
        )
        misrouted = anki_queue.enqueue(
            session="ts",
            exchange_id=104,
            deck="Neurosurgery::Neurocritical care::EVD",
            card_type="qa",
            front="During local transport practice, what EVD step requires confirmation?",
            back="Confirm local practice.",
            tags="shift-debrief",
            queue_path=self.queue,
        )
        self.assertFalse(unlabelled)
        self.assertFalse(misrouted)
        self.assertFalse(self.queue.exists())

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
        ok = anki_queue.enqueue(
            session="ts",
            exchange_id=1,
            deck="Neurosurgery::General::Test",
            card_type="cloze",
            cloze="No cloze markers in this text at all",
            answer="Some answer",
            queue_path=self.queue,
        )
        self.assertFalse(ok)
        self.assertFalse(self.queue.exists())
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

    def test_cloze_answer_is_optional(self):
        draft = CardDraft(
            claim_id="abc123",
            card_type="cloze",
            cloze_text="CPP target is {{c1::60-70}} mmHg in TBI",
        )
        self.assertEqual(draft.answer_text, "")

    def test_enqueue_allows_related_multi_cloze(self):
        ok = anki_queue.enqueue(
            session="ts",
            exchange_id=1,
            deck="Neurosurgery::Trauma::ICP",
            card_type="cloze",
            cloze=(
                "Severe TBI pressure targets: treat ICP above {{c1::22 mmHg}} "
                "and target CPP {{c2::60-70 mmHg}}."
            ),
            queue_path=self.queue,
        )

        self.assertTrue(ok)

    def test_enqueue_allows_feedback_prompt_for_agent_review(self):
        ok = anki_queue.enqueue(
            session="ts",
            exchange_id=1,
            deck="Neurosurgery::Vascular::EVD",
            card_type="cloze",
            cloze=(
                "For flat EVD waveform unreliable ICP, the key discriminator is "
                "{{c1::Correct interpretation}}: the displayed ICP is not trustworthy."
            ),
            queue_path=self.queue,
        )

        self.assertTrue(ok)
        entries = anki_queue._read_queue(self.queue)
        self.assertEqual(len(entries), 1)

    def test_enqueue_allows_long_basic_answer_for_agent_review(self):
        ok = anki_queue.enqueue(
            session="ts",
            exchange_id=1,
            deck="Neurosurgery::General::Hypertension",
            card_type="qa",
            front="How should neurogenic hypertension be triaged?",
            back=" ".join(f"word{i}" for i in range(46)),
            queue_path=self.queue,
        )

        self.assertTrue(ok)
        entries = anki_queue._read_queue(self.queue)
        self.assertEqual(len(entries), 1)

    def test_stable_metadata_tags_are_generated_from_topic_and_concept(self):
        tags = anki_queue._stable_metadata_tags(
            {
                "topic": "EVD Management",
                "concept": "Flat EVD Waveform Interpretation",
            },
            "abc123",
        )

        self.assertEqual(
            tags,
            [
                "topic/evd-management",
                "concept/flat-evd-waveform-interpretation",
                "claim/abc123",
            ],
        )

    def test_stable_metadata_tags_include_inventory_concept_id(self):
        tags = anki_queue._stable_metadata_tags(
            {
                "topic": "Vasospasm",
                "concept": "Vasospasm Threshold",
                "inventory_concept_id": "vas.vasospasm_threshold",
            },
            "def456",
        )
        self.assertIn("inv/vas.vasospasm_threshold", tags)


class AnkiClientFormattingTests(unittest.TestCase):
    def test_cloze_add_note_does_not_write_back_extra(self):
        client = AnkiClient("http://localhost:8765")
        calls = []

        def fake_invoke(action, **params):
            calls.append((action, params))
            if action == "addNote":
                return 12345
            return None

        client._invoke = fake_invoke
        result = client.add_card(
            CardDraft(
                claim_id="abc123",
                card_type="cloze",
                cloze_text="CPP target is {{c1::60-70}} mmHg in TBI",
                answer_text="60-70 mmHg",
            ),
            "Neurosurgery::Trauma::ICP",
        )

        self.assertEqual(result.status, "created")
        note = [params["note"] for action, params in calls if action == "addNote"][0]
        self.assertEqual(note["modelName"], "Cloze")
        self.assertEqual(set(note["fields"]), {"Text"})

    def test_qa_back_is_wrapped_for_grey_styling(self):
        client = AnkiClient("http://localhost:8765")
        calls = []

        def fake_invoke(action, **params):
            calls.append((action, params))
            if action == "addNote":
                return 12346
            return None

        client._invoke = fake_invoke
        result = client.add_card(
            CardDraft(
                claim_id="def456",
                card_type="qa",
                front="What is CPP?",
                back="MAP minus ICP.",
            ),
            "Neurosurgery::Trauma::ICP",
        )

        self.assertEqual(result.status, "created")
        note = [params["note"] for action, params in calls if action == "addNote"][0]
        self.assertEqual(note["modelName"], "Basic")
        self.assertEqual(note["fields"]["Back"], '<div class="neuro-agent-back">MAP minus ICP.</div>')


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

    def _mock_no_existing_duplicates(self, MockStore):
        mock_store = MockStore.return_value
        mock_store.filter_novel_claims.side_effect = lambda claims, threshold: (claims, [
            NoveltyDecision(
                claim_id=c.claim_id,
                claim_text=c.claim_text,
                max_similarity=0,
                is_novel=True,
            )
            for c in claims
        ])
        mock_store._embed.side_effect = lambda texts: [
            [1.0, float(i)] for i, _ in enumerate(texts)
        ]
        return mock_store

    @patch.object(anki_queue, "NoveltyStore")
    @patch.object(anki_queue, "AnkiClient")
    def test_flush_dispatches_after_clear_duplicate_gate(self, MockClient, MockStore):
        self._enqueue_sample(n=1)
        entries = anki_queue._read_queue(self.queue)
        self._mock_no_existing_duplicates(MockStore)

        mock_client = MockClient.return_value
        mock_client.check_connection.return_value = (True, "")
        mock_client.add_card.return_value = AnkiDispatchResult(
            claim_id="x", card_type="cloze", status="created", note_id=12345, error="",
        )

        result = anki_queue.flush(queue_path=self.queue)

        self.assertEqual(result["created"], len(entries))
        self.assertEqual(result["duplicate_candidate_count"], 0)
        self.assertEqual(result["duplicate_gate"], "clear")
        self.assertIn("Neurosurgery::Vascular::EVD Management", result["decks_touched"])
        remaining = anki_queue._read_queue(self.queue)
        self.assertEqual(len(remaining), 0)

    @patch.object(anki_queue, "AnkiClient")
    def test_flush_preserves_queue_on_anki_unavailable(self, MockClient):
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
        self._mock_no_existing_duplicates(MockStore)

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
        self._enqueue_sample(n=1)
        self._mock_no_existing_duplicates(MockStore)

        result = anki_queue.flush(dry_run=True, queue_path=self.queue)

        self.assertTrue(result.get("dry_run"))
        self.assertEqual(result["would_dispatch"], 1)
        remaining = anki_queue._read_queue(self.queue)
        self.assertEqual(len(remaining), 1)

    @patch.object(anki_queue, "NoveltyStore")
    @patch.object(anki_queue, "AnkiClient")
    def test_flush_blocks_duplicate_candidates_by_default(self, MockClient, MockStore):
        self._enqueue_sample(n=2)
        mock_store = self._mock_no_existing_duplicates(MockStore)
        mock_store._embed.return_value = [[1.0, 0.0], [1.0, 0.0]]
        MockClient.return_value.check_connection.return_value = (True, "")

        result = anki_queue.flush(queue_path=self.queue)

        self.assertEqual(result["error"], "duplicate_candidates_require_agent_review")
        self.assertEqual(len(result["duplicate_candidates"]), 1)
        self.assertFalse(MockClient.return_value.add_card.called)
        remaining = anki_queue._read_queue(self.queue)
        self.assertEqual(len(remaining), 2)

    @patch.object(anki_queue, "NoveltyStore")
    @patch.object(anki_queue, "AnkiClient")
    def test_flush_allows_duplicate_candidates_with_explicit_override(self, MockClient, MockStore):
        self._enqueue_sample(n=2)
        mock_store = self._mock_no_existing_duplicates(MockStore)
        mock_store._embed.return_value = [[1.0, 0.0], [1.0, 0.0]]

        mock_client = MockClient.return_value
        mock_client.check_connection.return_value = (True, "")
        mock_client.add_card.return_value = AnkiDispatchResult(
            claim_id="x", card_type="cloze", status="created", note_id=12345, error="",
        )

        result = anki_queue.flush(
            queue_path=self.queue,
            allow_duplicate_candidates=True,
        )

        self.assertEqual(result["created"], 2)
        self.assertEqual(result["duplicate_gate"], "overridden")
        remaining = anki_queue._read_queue(self.queue)
        self.assertEqual(len(remaining), 0)

    def _enqueue_two_distinct(self):
        anki_queue.enqueue(
            session="ts", exchange_id=1,
            deck="Neurosurgery::Vascular::EVD Management",
            card_type="cloze",
            cloze="EVD infection risk increases with {{c1::duration and manipulation}}",
            queue_path=self.queue,
        )
        anki_queue.enqueue(
            session="ts", exchange_id=2,
            deck="Neurosurgery::Trauma::ICP",
            card_type="qa",
            front="What is the ICP treatment threshold in severe TBI?",
            back="Treat sustained ICP above 22 mmHg.",
            queue_path=self.queue,
        )

    @patch.object(anki_queue, "NoveltyStore")
    @patch.object(anki_queue, "AnkiClient")
    def test_flush_tags_each_card_with_its_own_claim_id(self, MockClient, MockStore):
        # claim/<slug> is the join key between Anki review history and the
        # learner model; every card must carry its OWN claim id, not the last one.
        self._enqueue_two_distinct()
        entries = anki_queue._read_queue(self.queue)
        self.assertEqual(len(entries), 2)
        expected_slugs = [
            anki_queue._metadata_slug(e["claim_id"]) for e in entries
        ]
        self.assertNotEqual(expected_slugs[0], expected_slugs[1])

        self._mock_no_existing_duplicates(MockStore)
        mock_client = MockClient.return_value
        mock_client.check_connection.return_value = (True, "")
        mock_client.add_card.return_value = AnkiDispatchResult(
            claim_id="x", card_type="cloze", status="created", note_id=1, error="",
        )

        anki_queue.flush(queue_path=self.queue)

        dispatched_tags = [call.args[2] for call in mock_client.add_card.call_args_list]
        self.assertEqual(len(dispatched_tags), 2)
        for tags, slug in zip(dispatched_tags, expected_slugs):
            self.assertIn(f"claim/{slug}", tags)
        # No cross-contamination: card 0 must not carry card 1's claim tag.
        self.assertNotIn(f"claim/{expected_slugs[1]}", dispatched_tags[0])

    @patch.object(anki_queue, "NoveltyStore")
    @patch.object(anki_queue, "AnkiClient")
    def test_flush_retains_failed_cards_for_retry(self, MockClient, MockStore):
        self._enqueue_two_distinct()
        self._mock_no_existing_duplicates(MockStore)

        mock_client = MockClient.return_value
        mock_client.check_connection.return_value = (True, "")
        mock_client.add_card.side_effect = [
            AnkiDispatchResult(claim_id="a", card_type="cloze", status="created", note_id=1, error=""),
            AnkiDispatchResult(claim_id="b", card_type="cloze", status="failed", note_id=None, error="boom"),
        ]

        result = anki_queue.flush(queue_path=self.queue)

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["retained_failed"], 1)
        remaining = anki_queue._read_queue(self.queue)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["card_type"], "qa")
        self.assertIn("ICP treatment threshold", remaining[0]["front"])

    @patch.object(anki_queue, "NoveltyStore")
    def test_check_reports_intra_batch_duplicate(self, MockStore):
        anki_queue.enqueue(
            session="ts", exchange_id=1,
            deck="Neurosurgery::General::ICP",
            card_type="qa",
            front="What is cerebral perfusion pressure?",
            back="CPP equals MAP minus ICP.",
            queue_path=self.queue,
        )
        anki_queue.enqueue(
            session="ts", exchange_id=2,
            deck="Neurosurgery::Trauma::ICP",
            card_type="qa",
            front="How do you calculate CPP?",
            back="CPP equals MAP minus ICP.",
            queue_path=self.queue,
        )

        mock_store = MockStore.return_value
        mock_store.filter_novel_claims.side_effect = lambda claims, threshold: (claims, [
            NoveltyDecision(
                claim_id=c.claim_id,
                claim_text=c.claim_text,
                max_similarity=0,
                is_novel=True,
            )
            for c in claims
        ])
        mock_store._embed.return_value = [[1.0, 0.0], [1.0, 0.0]]

        result = anki_queue.check(queue_path=self.queue)

        self.assertEqual(len(result["duplicate_candidates"]), 1)
        self.assertEqual(len(result["duplicates"]), 1)

    @patch.object(anki_queue, "NoveltyStore")
    def test_check_reports_quality_warnings_without_blocking(self, MockStore):
        anki_queue.enqueue(
            session="ts",
            exchange_id=1,
            deck="Neurosurgery::Vascular::EVD",
            card_type="cloze",
            cloze=(
                "For flat EVD waveform unreliable ICP, the key discriminator is "
                "{{c1::Correct interpretation}}: the displayed ICP is not trustworthy."
            ),
            queue_path=self.queue,
        )

        mock_store = MockStore.return_value
        mock_store.filter_novel_claims.side_effect = lambda claims, threshold: (claims, [
            NoveltyDecision(
                claim_id=c.claim_id,
                claim_text=c.claim_text,
                max_similarity=0,
                is_novel=True,
            )
            for c in claims
        ])
        mock_store._embed.return_value = [[1.0, 0.0]]

        result = anki_queue.check(queue_path=self.queue)

        self.assertEqual(result["queue_size"], 1)
        self.assertEqual(result["quality_warnings"][0]["warnings"], ["feedback_derived_prompt"])


class CardDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = Path(self.tmp.name) / "queue.jsonl"
        self.memory = Path(self.tmp.name) / "study_memory.db"
        self.conn = study_memory._get_db(self.memory)
        self.exchange_id = study_memory.log_answer(
            self.conn,
            session_id="decision-session",
            topic="intracranial pressure",
            concept="cerebral perfusion pressure",
            question="How is CPP calculated?",
            answer="I am not sure.",
            correct=0,
            tested_claim="CPP equals MAP minus ICP.",
            corrected_rule="CPP equals MAP minus ICP.",
        )

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_missing_decision_blocks_but_explicit_skip_does_not_force_card(self):
        with patch.object(anki_queue, "STUDY_MEMORY_DB", self.memory):
            unresolved = anki_queue.check(
                session="decision-session",
                queue_path=self.queue,
                emit=False,
            )
            self.assertEqual(
                unresolved["card_decision_blockers"][0]["reason"],
                "missing_card_decision",
            )

            study_memory.record_anki_card_decision(
                self.conn,
                session_id="decision-session",
                exchange_id=self.exchange_id,
                decision="skip_low_value",
                rationale="Incidental fact that does not protect a durable clinical trace.",
            )
            resolved = anki_queue.check(
                session="decision-session",
                queue_path=self.queue,
                emit=False,
            )
            self.assertEqual(resolved["card_decision_blockers"], [])
            self.assertEqual(resolved["card_decision_counts"], {"skip_low_value": 1})

    def test_enqueue_decision_without_card_blocks_flush(self):
        study_memory.record_anki_card_decision(
            self.conn,
            session_id="decision-session",
            exchange_id=self.exchange_id,
            decision="enqueue",
        )
        with patch.object(anki_queue, "STUDY_MEMORY_DB", self.memory):
            result = anki_queue.flush(
                session="decision-session",
                queue_path=self.queue,
            )
        self.assertEqual(result["error"], "card_decisions_require_resolution")
        self.assertEqual(
            result["card_decision_blockers"][0]["reason"],
            "enqueue_decision_missing_card",
        )


if __name__ == "__main__":
    unittest.main()
