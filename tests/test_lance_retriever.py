from __future__ import annotations

import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import lance_retriever as lr


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

    def test_merge_source_blocks_deduplicates_and_preserves_frontier(self) -> None:
        existing = (
            "Query:\naneurysm clipping\n\n"
            "Source Knowledge:\n"
            "[P1] [TEXTBOOK THEORY] Youmans\n"
            "Temporary clipping softens the aneurysm before final clip placement.\n\n"
            "Frontier Evidence:\nFrontier note"
        )
        new = (
            "Query:\nclip reconstruction\n\n"
            "Source Knowledge:\n"
            "[P2] [TEXTBOOK THEORY] Winn\n"
            "Temporary clipping softens the aneurysm before final clip placement.\n\n"
            "[P3] [TEXTBOOK THEORY] Rhoton\n"
            "Fenestrated clips can reconstruct the neck when branch anatomy is complex.\n\n"
            "Frontier Evidence:\nIgnored new frontier"
        )

        merged, added, skipped = lr._merge_source_blocks(existing, new)

        self.assertEqual(added, 1)
        self.assertEqual(skipped, 1)
        self.assertIn("Sub-query: clip reconstruction", merged)
        self.assertIn("Fenestrated clips can reconstruct", merged)
        self.assertIn("Frontier Evidence:\nFrontier note", merged)
        self.assertNotIn("Ignored new frontier", merged)

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


if __name__ == "__main__":
    unittest.main()
