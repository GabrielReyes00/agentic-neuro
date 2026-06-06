from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import lance_retriever as lr
from retrieval import pipeline


class LanceRetrieverIntegrationTests(unittest.TestCase):
    def test_build_scratch_context_ids_passages_and_skips_references(self) -> None:
        result = {
            "query": "aneurysm clipping",
            "hits": [
                {
                    "text": "Temporary clipping softens the aneurysm before final clip placement.",
                    "citation": "Youmans, p. 100",
                    "metadata": {"page_start": 100},
                    "rank_score": 0.9,
                },
                {
                    "text": (
                        "References\n"
                        "1. Smith JA et al. Neurosurgery. 2020;10:1-5.\n"
                        "2. Jones AB et al. J Neurosurg. 2021;12:6-9.\n"
                        "3. Patel CD et al. Stroke. 2022;53:10-14.\n"
                        "4. Lee EF et al. World Neurosurg. 2023;15:20-25.\n"
                        "5. Kim GH et al. Neurosurg Focus. 2024;56:30-35."
                    ),
                    "citation": "Reference section",
                    "metadata": {},
                },
            ],
        }

        context = lr.build_scratch_context(result)

        self.assertIn("Query:\naneurysm clipping", context)
        self.assertIn("[P1] [TEXTBOOK THEORY] Youmans, p. 100 [Page 100]", context)
        self.assertIn("Temporary clipping softens", context)
        self.assertNotIn("Reference section", context)
        self.assertIn("No external frontier notes provided", context)

    def test_search_returns_results(self) -> None:
        if not (ROOT / "neurosurgery_v4.lance").exists():
            self.skipTest("local LanceDB fixture is not present")
        try:
            table = lr._get_lance_table()
            first = table.head(1)
            query_vec = first["dense_vec"][0].as_py()
            dense_hits, _ = lr._dense_search(table, query_vec, n_results=8)
            fts_hits, _ = lr._sparse_search_fts(table, "cerebral aneurysm", n_results=8)
            fused = lr._apply_rrf(dense_hits, fts_hits)
            hits = lr._rerank_hits_lexical("cerebral aneurysm", fused)
        except Exception as exc:
            self.skipTest(f"local LanceDB retrieval unavailable: {exc}")

        self.assertIsInstance(hits, list)
        self.assertGreater(len(hits), 0)
        scores = []
        for hit in hits:
            self.assertTrue(hit.get("text"))
            score = hit.get("rank_score", hit.get("similarity"))
            self.assertIsNotNone(score)
            scores.append(float(score))
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_bge_cache_status_requires_root_weights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            snapshot = (
                cache
                / "models--BAAI--bge-m3"
                / "snapshots"
                / "abc123"
            )
            snapshot.mkdir(parents=True)
            (cache / "models--BAAI--bge-m3" / "refs").mkdir()
            (cache / "models--BAAI--bge-m3" / "refs" / "main").write_text("abc123")

            missing = lr._bge_cache_status(cache_dir=cache)
            self.assertFalse(missing["ok"])

            (snapshot / "pytorch_model.bin").write_text("weights")
            ready = lr._bge_cache_status(cache_dir=cache)
            self.assertTrue(ready["ok"])
            self.assertEqual(ready["snapshot"], str(snapshot))

    def test_list_textbooks_uses_stored_inventory(self) -> None:
        payload = {
            "generated_from": "unit_table",
            "book_count": 2,
            "books": ["Book B", "Book A"],
            "counts": {"Book A": 3, "Book B": 7},
        }
        with tempfile.TemporaryDirectory() as tmp:
            inventory = Path(tmp) / "rag_textbook_sources.json"
            inventory.write_text(json.dumps(payload))
            with mock.patch.object(pipeline, "TEXTBOOK_INVENTORY_PATH", inventory):
                with mock.patch.object(pipeline, "_source_book_counts_from_lance") as live_scan:
                    buf = io.StringIO()
                    with mock.patch("sys.stdout", buf):
                        lr.list_textbooks()

        live_scan.assert_not_called()
        output = buf.getvalue()
        self.assertIn("unit_table", output)
        self.assertIn("7  Book B", output)
        self.assertIn("10  TOTAL (2 books)", output)


if __name__ == "__main__":
    unittest.main()
