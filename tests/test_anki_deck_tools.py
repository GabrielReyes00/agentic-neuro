from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import anki_deck_tools


class FakeClient:
    def find_cards(self, query):
        self.query = query
        return [101, 102]

    def cards_info(self, card_ids, batch_size=50):
        return [
            {"cardId": 101, "note": 201, "deckName": "Neurosurgery::General::ICP"},
            {"cardId": 102, "note": 202, "deckName": "Neurosurgery::Vascular::SAH"},
        ]

    def notes_info(self, note_ids, batch_size=50):
        return [
            {
                "noteId": 201,
                "modelName": "Basic",
                "tags": ["Neuro-Agent"],
                "fields": {
                    "Front": {"value": "What is CPP?"},
                    "Back": {"value": "MAP minus ICP."},
                },
            },
            {
                "noteId": 202,
                "modelName": "Cloze",
                "tags": ["Neuro-Agent"],
                "fields": {
                    "Text": {"value": "Nimodipine lasts {{c1::21 days}} after aSAH."},
                },
            },
        ]


class AnkiDeckToolsTests(unittest.TestCase):
    def test_export_notes_uses_live_anki_fields(self):
        data = anki_deck_tools._export_notes(FakeClient(), "deck:Neurosurgery*")

        self.assertEqual(data["card_count"], 2)
        self.assertEqual(data["note_count"], 2)
        self.assertEqual(data["notes"][0]["claim_text"], "What is CPP? -> MAP minus ICP.")
        self.assertEqual(data["notes"][1]["claim_text"], "Nimodipine lasts {{c1::21 days}} after aSAH.")

    @patch.object(anki_deck_tools, "NoveltyStore")
    @patch.object(anki_deck_tools, "AnkiClient")
    def test_rebuild_chroma_replaces_from_live_anki(self, MockClient, MockStore):
        MockClient.return_value = FakeClient()
        store = MockStore.return_value

        result = anki_deck_tools.rebuild_chroma("deck:Neurosurgery*", dry_run=False)

        self.assertEqual(result["source_of_truth"], "anki")
        self.assertEqual(result["claims"], 2)
        store.replace_claims.assert_called_once()


if __name__ == "__main__":
    unittest.main()
