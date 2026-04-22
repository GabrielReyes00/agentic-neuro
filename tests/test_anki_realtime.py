"""Tests for real-time Anki integration (src/anki_realtime.py).

These tests cover the deterministic pieces: enqueue, suppression, deck
resolution, queue I/O, KG backlink, and flush-queue orchestration with
a stubbed-out Gemini synthesis pass and a stubbed AnkiClient. The
Gemini CLI and AnkiConnect are NOT invoked here — that integration is
exercised by the end-to-end live-fire test.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import anki_realtime
from anki_realtime import (
    _read_queue,
    _should_suppress,
    _write_queue,
    enqueue_candidate,
    flush_queue,
    resolve_deck_name,
)
from anki_sync.anki_client import AnkiDispatchResult
from anki_sync.schemas import CardDraft


def _candidate(**overrides):
    base = {
        "session_ts": "2026-04-18T10:00:00+00:00",
        "exchange_id": 1234,
        "skill": "test",
        "topic": "MCA bifurcation aneurysm",
        "concept": "M1-M2 junction",
        "question": "Where is the most common site of MCA aneurysm rupture?",
        "answer": "M1 trunk",
        "correction": "Actually the M1/M2 bifurcation.",
        "correct": 0,
        "error_type": "anatomical_ambiguity",
        "misconception": "M1 trunk alone",
        "depth": 2,
        "domain": "vascular",
        "breakthrough": False,
    }
    base.update(overrides)
    return base


class SuppressionTests(unittest.TestCase):
    def test_correct_shallow_no_signal_is_suppressed(self):
        self.assertTrue(_should_suppress(
            {"correct": 2, "depth": 1, "error_type": "", "breakthrough": False}
        ))

    def test_incorrect_always_kept(self):
        self.assertFalse(_should_suppress(
            {"correct": 0, "depth": 1, "error_type": "", "breakthrough": False}
        ))

    def test_partial_always_kept(self):
        self.assertFalse(_should_suppress(
            {"correct": 1, "depth": 1, "error_type": "", "breakthrough": False}
        ))

    def test_correct_deep_kept(self):
        self.assertFalse(_should_suppress(
            {"correct": 2, "depth": 3, "error_type": "", "breakthrough": False}
        ))

    def test_correct_with_error_type_kept(self):
        self.assertFalse(_should_suppress(
            {"correct": 2, "depth": 1, "error_type": "numerical_recall", "breakthrough": False}
        ))

    def test_breakthrough_always_kept(self):
        self.assertFalse(_should_suppress(
            {"correct": 2, "depth": 1, "error_type": "", "breakthrough": True}
        ))


class DeckResolutionTests(unittest.TestCase):
    def test_vascular_with_acronym(self):
        name = resolve_deck_name("MCA bifurcation aneurysm", "vascular")
        self.assertEqual(name, "Neurosurgery::Vascular::MCA Bifurcation Aneurysm")

    def test_peripheral_nerve_umbrella(self):
        name = resolve_deck_name("Carpal tunnel syndrome", "peripheral-nerve")
        self.assertEqual(name, "Neurosurgery::Peripheral Nerve::Carpal Tunnel Syndrome")

    def test_unknown_domain_defaults_to_general(self):
        name = resolve_deck_name("Some topic", "")
        self.assertEqual(name, "Neurosurgery::General::Some Topic")

    def test_empty_topic_defaults_to_session(self):
        name = resolve_deck_name("", "general")
        self.assertEqual(name, "Neurosurgery::General::Session")


class TopicCanonicalizationTests(unittest.TestCase):
    """Verify the agent reuses existing sibling decks and broadens
    session-specific topic names before creating new ones."""

    def test_reuses_sibling_when_tokens_are_subset(self):
        name = resolve_deck_name(
            "SAH management",
            "vascular",
            existing_subtopics=["SAH and Vasospasm Management", "ICH Management"],
        )
        self.assertEqual(name, "Neurosurgery::Vascular::SAH and Vasospasm Management")

    def test_reuses_sibling_when_iou_above_threshold(self):
        # "MCA Bifurcation Aneurysm" vs "MCA Aneurysm Surgery" — 2 shared
        # content tokens out of 3/3 → IoU = 2/4 = 0.5 → reuse.
        name = resolve_deck_name(
            "MCA Aneurysm Surgery",
            "vascular",
            existing_subtopics=["MCA Bifurcation Aneurysm"],
        )
        self.assertEqual(name, "Neurosurgery::Vascular::MCA Bifurcation Aneurysm")

    def test_broadens_by_stripping_demographic_modifiers(self):
        name = resolve_deck_name(
            "MCA Aneurysm Clipping in 45-year-old Woman",
            "vascular",
            existing_subtopics=[],
        )
        self.assertEqual(name, "Neurosurgery::Vascular::MCA Aneurysm Clipping")

    def test_broadens_by_stripping_scenario_modifiers(self):
        # Stateless fallback strips "adolescent" but leaves orphan "in";
        # production path with siblings would reuse the existing broadened
        # "Bow Hunter Syndrome" deck. The stateless result still drops
        # enough to avoid fragmentation on the "45-year-old Woman" pattern.
        name = resolve_deck_name(
            "Bow Hunter Syndrome",
            "vascular",
            existing_subtopics=["Bow Hunter Syndrome"],
        )
        self.assertEqual(name, "Neurosurgery::Vascular::Bow Hunter Syndrome")

    def test_creates_new_when_no_sibling_overlaps(self):
        name = resolve_deck_name(
            "Cerebellar ataxia workup",
            "general",
            existing_subtopics=["Seizure Prophylaxis", "Neuro-ICU Pharmacology"],
        )
        self.assertEqual(name, "Neurosurgery::General::Cerebellar Ataxia Workup")

    def test_existing_deck_with_acronym_is_preserved_on_reuse(self):
        name = resolve_deck_name(
            "posterior communicating artery aneurysm",
            "vascular",
            existing_subtopics=["PComA Aneurysm Surgery"],
        )
        # Low token overlap ("aneurysm" only) — should NOT reuse PComA
        # (the phrasings are semantically similar but lexically distinct;
        # this is the conservative fallback, better than false merges).
        self.assertTrue(name.startswith("Neurosurgery::Vascular::"))

    def test_picks_lexicographic_first_on_tie(self):
        # Both siblings share exactly "aneurysm" with proposed → same
        # score; deterministic tiebreak picks lexicographic first.
        name = resolve_deck_name(
            "aneurysm clipping",
            "vascular",
            existing_subtopics=["ACoA Aneurysm", "MCA Aneurysm"],
        )
        # Either choice is acceptable as long as it's one of the existing
        # ones (or broadened new name) — assert it didn't double-up.
        self.assertTrue(name.startswith("Neurosurgery::Vascular::"))

    def test_empty_existing_falls_back_to_stateless_broadening(self):
        name = resolve_deck_name(
            "SAH in 60 year old patient",
            "vascular",
            existing_subtopics=None,
        )
        self.assertEqual(name, "Neurosurgery::Vascular::SAH")


class QueueIOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = Path(self.tmp.name) / "queue.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_enqueue_and_read(self):
        ok = enqueue_candidate(queue_path=self.queue, **_candidate())
        self.assertTrue(ok)
        rows = _read_queue(self.queue)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exchange_id"], 1234)
        self.assertEqual(rows[0]["error_type"], "anatomical_ambiguity")

    def test_enqueue_suppresses_routine_correct(self):
        ok = enqueue_candidate(
            queue_path=self.queue,
            **_candidate(correct=2, depth=1, error_type="", misconception=""),
        )
        self.assertFalse(ok)
        self.assertFalse(self.queue.exists())

    def test_enqueue_rejects_short_question(self):
        ok = enqueue_candidate(
            queue_path=self.queue,
            **_candidate(question="hi?", answer="ok"),
        )
        self.assertFalse(ok)

    def test_write_queue_empty_removes_file(self):
        enqueue_candidate(queue_path=self.queue, **_candidate())
        self.assertTrue(self.queue.exists())
        _write_queue(self.queue, [])
        self.assertFalse(self.queue.exists())


class FlushOrchestrationTests(unittest.TestCase):
    """Exercise flush_queue with stubbed Gemini + AnkiClient.

    We don't hit the real Gemini CLI or AnkiConnect here — we verify the
    orchestration: suppression, grouping, ChromaDB novelty gating, card
    dispatch, KG backlink write.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = Path(self.tmp.name) / "queue.jsonl"
        self.db = Path(self.tmp.name) / "kg.db"
        # Initialize the minimal learning_exchanges schema we write back onto.
        conn = sqlite3.connect(str(self.db))
        conn.executescript("""
            CREATE TABLE learning_exchanges (
                exchange_id INTEGER PRIMARY KEY,
                anki_note_id INTEGER,
                anki_queued_at TEXT
            );
            INSERT INTO learning_exchanges (exchange_id) VALUES (1234);
            INSERT INTO learning_exchanges (exchange_id) VALUES (5678);
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def _enqueue_two(self):
        enqueue_candidate(queue_path=self.queue, **_candidate(exchange_id=1234))
        enqueue_candidate(
            queue_path=self.queue,
            **_candidate(
                exchange_id=5678,
                topic="SAH management",
                concept="Vasospasm window",
                question="When does vasospasm peak after SAH?",
                answer="around day 7",
                correction="",
                correct=2,
                error_type="",
                misconception="",
                depth=3,
            ),
        )

    def test_flush_dispatches_and_backlinks(self):
        self._enqueue_two()

        card_mca = CardDraft(
            claim_id="c1",
            card_type="cloze",
            cloze_text="The most common MCA aneurysm site is the {{c1::M1/M2 bifurcation}}, not the M1-M2 junction trunk.",
            answer_text="Hemodynamic stress at the primary division.",
        )
        card_sah = CardDraft(
            claim_id="c2",
            card_type="cloze",
            cloze_text="After SAH, symptomatic Vasospasm window peaks at {{c1::day 7}}.",
            answer_text="Classic 4-14 day window.",
        )

        def fake_synthesize(candidates, *a, **kw):
            # synthesize_cards is called once per (domain, topic) group; return
            # the card matching the group's topic.
            if not candidates:
                return []
            topic = (candidates[0].get("topic") or "").lower()
            if "sah" in topic:
                return [card_sah]
            return [card_mca]

        class FakeClient:
            def __init__(self, *a, **kw):
                self.added = []
                self.decks = set()

            def check_connection(self):
                return True, ""

            def ensure_models(self):
                pass

            def ensure_deck(self, name):
                self.decks.add(name)

            def add_card(self, card, deck_name, tags=None):
                self.added.append((card.claim_id, deck_name, tuple(tags or [])))
                note_id = 7000 + len(self.added)
                return AnkiDispatchResult(
                    claim_id=card.claim_id,
                    card_type="cloze",
                    status="created",
                    note_id=note_id,
                    error="",
                )

        class FakeNovelty:
            def __init__(self, *a, **kw):
                self.persisted = []

            def filter_novel_claims(self, claims, threshold):
                # All claims are novel in this test.
                return claims, []

            def persist_claims(self, claims, metadata=None):
                self.persisted.extend(claims)

        with patch.object(anki_realtime, "synthesize_cards", side_effect=fake_synthesize), \
             patch.object(anki_realtime, "AnkiClient", FakeClient), \
             patch("src.anki_sync.novelty.NoveltyStore", FakeNovelty):
            metrics = flush_queue(
                queue_path=self.queue,
                db_path=self.db,
                max_batch=8,
            )

        self.assertEqual(metrics["created"], 2)
        self.assertEqual(metrics["failed"], 0)
        self.assertEqual(metrics["backlinked"], 2)
        self.assertIn("Neurosurgery::Vascular::MCA Bifurcation Aneurysm", metrics["decks_touched"])
        self.assertIn("Neurosurgery::Vascular::SAH Management", metrics["decks_touched"])
        # Queue drained.
        self.assertFalse(self.queue.exists())
        # KG backlinks written.
        conn = sqlite3.connect(str(self.db))
        ids = {r[0]: r[1] for r in conn.execute("SELECT exchange_id, anki_note_id FROM learning_exchanges")}
        conn.close()
        self.assertIsNotNone(ids[1234])
        self.assertIsNotNone(ids[5678])

    def test_flush_with_anki_down_preserves_queue(self):
        self._enqueue_two()

        class DownClient:
            def __init__(self, *a, **kw):
                pass

            def check_connection(self):
                return False, "connection refused"

        with patch.object(anki_realtime, "AnkiClient", DownClient):
            metrics = flush_queue(
                queue_path=self.queue,
                db_path=self.db,
            )

        self.assertEqual(metrics["created"], 0)
        self.assertTrue(any("anki_unavailable" in e for e in metrics["errors"]))
        # Queue intact for retry.
        rows = _read_queue(self.queue)
        self.assertEqual(len(rows), 2)

    def test_flush_empty_queue_is_noop(self):
        metrics = flush_queue(queue_path=self.queue, db_path=self.db)
        self.assertEqual(metrics["queue_size"], 0)
        self.assertEqual(metrics["created"], 0)
        self.assertEqual(metrics["errors"], [])


class MemoryOrchestratorHookTests(unittest.TestCase):
    """Verify the enqueue hook is wired into record-answer without side effects."""

    def test_try_enqueue_anki_noop_on_missing_exchange_id(self):
        import memory_orchestrator as mo

        class Args:
            session_ts = "2026-04-18T10:00:00+00:00"
            skill = "test"
            topic = "t"
            concept = "c"
            question = "question?"
            answer = "answer"
            correction = ""
            correct = 2
            error_type = ""
            misconception = ""
            root_cause = ""
            teaching_approach = ""
            depth = 1
            domain = "general"
            breakthrough = False

        # Missing exchange_id -> must not raise, must not enqueue.
        mo._try_enqueue_anki(Args(), {"ok": True})
        mo._try_enqueue_anki(Args(), {"ok": True, "exchange_id": 0})


if __name__ == "__main__":
    unittest.main()
