from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import MethodType

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from anki_sync.novelty import NoveltyStore
from anki_sync.schemas import ClaimModel


class AnkiNoveltyTests(unittest.TestCase):
    def test_novel_claim_passes(self) -> None:
        store = self._store()
        claim = self._claim("C001", "Temporary clipping reduces aneurysm turgor before final clip placement.")

        novel, decisions = store.filter_novel_claims([claim], threshold=0.8)

        self.assertEqual(novel, [claim])
        self.assertTrue(decisions[0].is_novel)

    def test_duplicate_claim_filtered(self) -> None:
        store = self._store()
        claim = self._claim("C001", "Temporary clipping reduces aneurysm turgor before final clip placement.")

        novel, _ = store.filter_novel_claims([claim], threshold=0.8)
        store.persist_claims(novel)

        duplicate = self._claim("C002", "Temporary clipping reduces aneurysm turgor before final clip placement.")
        second_pass, decisions = store.filter_novel_claims([duplicate], threshold=0.8)

        self.assertEqual(second_pass, [])
        self.assertFalse(decisions[0].is_novel)

    def test_replace_claims_rebuilds_collection(self) -> None:
        store = self._store()
        first = self._claim("C001", "Temporary clipping reduces aneurysm turgor before final clip placement.")
        second = self._claim("C002", "A new unrelated Anki claim should replace old cache contents.")

        store.persist_claims([first])
        store.replace_claims([second], {"source": "live_anki_rebuild"})

        self.assertEqual(store._collection.count(), 1)
        duplicate_first, decisions_first = store.filter_novel_claims([first], threshold=0.8)
        duplicate_second, decisions_second = store.filter_novel_claims([second], threshold=0.8)
        self.assertEqual(duplicate_first, [first])
        self.assertTrue(decisions_first[0].is_novel)
        self.assertEqual(duplicate_second, [])
        self.assertFalse(decisions_second[0].is_novel)

    def _store(self) -> NoveltyStore:
        try:
            import chromadb  # type: ignore
        except Exception as exc:
            self.skipTest(f"chromadb unavailable: {exc}")

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = NoveltyStore.__new__(NoveltyStore)
        store._client = chromadb.PersistentClient(path=tmp.name)
        store._collection = store._client.get_or_create_collection(
            name="test_claims",
            metadata={"hnsw:space": "cosine", "schema": "anki_claim_memory"},
        )
        store._collection_name = "test_claims"

        def fake_embed(_self: NoveltyStore, texts: list[str]) -> list[list[float]]:
            vectors: list[list[float]] = []
            for text in texts:
                if "temporary clipping" in text.lower():
                    vectors.append([1.0, 0.0, 0.0])
                else:
                    vectors.append([0.0, 1.0, 0.0])
            return vectors

        store._embed = MethodType(fake_embed, store)
        return store

    @staticmethod
    def _claim(claim_id: str, text: str) -> ClaimModel:
        return ClaimModel(
            claim_id=claim_id,
            subject="temporary clipping",
            verb="reduces",
            object="aneurysm turgor",
            claim_text=text,
        )


if __name__ == "__main__":
    unittest.main()
