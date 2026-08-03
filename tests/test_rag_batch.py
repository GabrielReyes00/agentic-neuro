from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retrieval import batch, cli, pipeline


def _hit(
    child_id: str,
    *,
    source: str = "Book A",
    parent_id: str = "P1",
    text: str = "Relevant clinical management passage.",
    score: float = 0.8,
) -> dict:
    return {
        "child_id": child_id,
        "parent_id": parent_id,
        "source_key": source,
        "text": text,
        "parent_text": text,
        "citation": f"{source} — p.1",
        "similarity": score,
        "rank_score": score,
        "metadata": {
            "source_book": source,
            "heading": "Management",
            "chapter_title": "Clinical chapter",
            "section_path": "Clinical chapter > Management",
            "page_start": 1,
            "chunk_index": 0,
        },
    }


class RetrievalIdentityTests(unittest.TestCase):
    def test_local_embedding_load_uses_resolved_snapshot_not_hub_id(self) -> None:
        created = {}

        class FakeModel:
            def __init__(self, model_source, **kwargs):
                created["model_source"] = model_source
                created["kwargs"] = kwargs

        fake_module = types.ModuleType("FlagEmbedding")
        fake_module.BGEM3FlagModel = FakeModel
        previous = pipeline._EMBEDDING_MODEL
        pipeline._EMBEDDING_MODEL = None
        try:
            with (
                mock.patch.dict(sys.modules, {"FlagEmbedding": fake_module}),
                mock.patch.object(pipeline, "MODEL_LOAD_LOCAL_ONLY", True),
                mock.patch.object(pipeline, "_require_bge_cache_ready"),
                mock.patch.object(
                    pipeline,
                    "_find_cached_snapshot",
                    return_value=Path("/models/bge-m3/snapshots/local"),
                ),
            ):
                model = pipeline._get_embedding_model()
        finally:
            pipeline._EMBEDDING_MODEL = previous

        self.assertIsInstance(model, FakeModel)
        self.assertEqual(
            created["model_source"],
            "/models/bge-m3/snapshots/local",
        )

    def test_sparse_search_uses_content_and_structural_fts_columns(self) -> None:
        class Query:
            def limit(self, _count):
                return self

            def to_list(self):
                return []

        class Table:
            def __init__(self):
                self.kwargs = {}

            def search(self, query, **kwargs):
                self.kwargs = {"query": query, **kwargs}
                return Query()

        table = Table()
        pipeline._sparse_search_fts(table, "vestibular schwannoma", 5)

        self.assertEqual(table.kwargs["query_type"], "fts")
        self.assertEqual(
            table.kwargs["fts_columns"],
            list(pipeline.FTS_COLUMNS),
        )

    def test_hit_key_scopes_source_local_ids(self) -> None:
        left = _hit("7", source="Book A", parent_id="2")
        right = _hit("7", source="Book B", parent_id="2")

        self.assertNotEqual(pipeline._hit_key(left), pipeline._hit_key(right))

    def test_parent_expansion_does_not_merge_different_books(self) -> None:
        left = _hit("7", source="Book A", parent_id="2", text="Book A passage")
        right = _hit("7", source="Book B", parent_id="2", text="Book B passage")

        expanded = pipeline._expand_with_parent_text([left, right])

        self.assertEqual(len(expanded), 2)
        self.assertEqual(
            {item["source_key"] for item in expanded},
            {"Book A", "Book B"},
        )

    def test_rrf_preserves_source_local_id_collisions(self) -> None:
        left = _hit("7", source="Book A", parent_id="2")
        right = _hit("7", source="Book B", parent_id="2")

        fused = pipeline._apply_rrf([left], [right])

        self.assertEqual(len(fused), 2)


class BatchedOrchestrationTests(unittest.TestCase):
    def test_retrieve_many_deduplicates_exact_queries_and_restores_order(self) -> None:
        def fake_unique(queries, **kwargs):
            return [
                {"query": query, "hits": [{"value": query}]}
                for query in queries
            ]

        with mock.patch.object(batch, "_retrieve_unique", side_effect=fake_unique) as run:
            results = batch.retrieve_many(["alpha", "alpha", "beta"])

        self.assertEqual(run.call_args.args[0], ["alpha", "beta"])
        self.assertEqual([result["query"] for result in results], ["alpha", "alpha", "beta"])
        self.assertIsNot(results[0], results[1])
        results[0]["hits"][0]["value"] = "changed"
        self.assertEqual(results[1]["hits"][0]["value"], "alpha")

    def test_rerank_many_uses_one_cross_encoder_call(self) -> None:
        class FakeReranker:
            def __init__(self):
                self.calls = []

            def predict(self, pairs, batch_size):
                self.calls.append((pairs, batch_size))
                return [0.1, 0.9, 0.8]

        reranker = FakeReranker()
        groups = [
            [_hit("1", score=0.5), _hit("2", score=0.5)],
            [_hit("3", score=0.5)],
        ]
        with mock.patch.object(
            pipeline,
            "_get_reranker",
            return_value=(reranker, "fake"),
        ):
            reranked, _ = batch._rerank_many(
                ["first query", "second query"],
                groups,
                "fake",
            )

        self.assertEqual(len(reranker.calls), 1)
        self.assertEqual(len(reranker.calls[0][0]), 3)
        self.assertEqual(reranked[0][0]["child_id"], "2")
        self.assertEqual(reranked[1][0]["child_id"], "3")

    def test_search_many_preserves_query_order_under_concurrency(self) -> None:
        def dense(_table, vector, _n_results):
            return ([{"channel": "dense", "value": vector[0]}], vector[0])

        def fts(_table, query, _n_results):
            return ([{"channel": "fts", "value": query}], float(len(query)))

        with (
            mock.patch.object(pipeline, "_dense_search", side_effect=dense),
            mock.patch.object(pipeline, "_sparse_search_fts", side_effect=fts),
        ):
            grouped, timings, _ = batch._search_many(
                object(),
                ["alpha", "b"],
                [[1.0], [2.0]],
                5,
            )

        self.assertEqual(grouped[0][0][0]["value"], 1.0)
        self.assertEqual(grouped[0][1][0]["value"], "alpha")
        self.assertEqual(grouped[1][0][0]["value"], 2.0)
        self.assertEqual(timings[1]["fts_ms"], 1.0)

    def test_bounded_distillation_avoids_second_cross_encoder_pass(self) -> None:
        results = [{
            "query": "alpha and beta",
            "hits": [
                _hit("1", text="Alpha diagnosis and management.", score=0.9),
                _hit("2", text="Beta diagnosis and management.", score=0.8),
            ],
        }]
        with (
            mock.patch.object(
                pipeline,
                "_decompose_axes",
                return_value=["alpha", "beta"],
            ),
            mock.patch.object(pipeline, "_get_reranker") as get_reranker,
        ):
            distilled, _ = batch._distill_many(results, "fake")

        get_reranker.assert_not_called()
        self.assertEqual(distilled[0]["distill_mode"], "keyword_bounded_pool")
        self.assertEqual(len(distilled[0]["hits"]), 2)


class BatchSerializationTests(unittest.TestCase):
    def test_batch_source_cards_have_one_topic_manifest_and_stable_ids(self) -> None:
        results = [{
            "query": "aneurysm management",
            "axes": ["aneurysm management"],
            "hits": [
                _hit(
                    "1",
                    text=(
                        "Surgical treatment is indicated when rupture risk exceeds "
                        "procedural risk. Temporary clipping can reduce aneurysm "
                        "tension during dissection."
                    ),
                ),
            ],
            "metadata": {"unique_sources": 1},
        }]

        rows = [
            json.loads(line)
            for line in batch.build_batch_source_cards_jsonl(results).splitlines()
        ]

        self.assertEqual(rows[0]["type"], "batch_source_card_manifest")
        self.assertEqual(rows[0]["source_type"], "textbook_rag_full")
        self.assertEqual(rows[1]["type"], "topic_manifest")
        self.assertEqual(rows[1]["query"], "aneurysm management")
        self.assertEqual(rows[2]["type"], "source_card")
        self.assertEqual(rows[2]["topic_id"], "T01")
        self.assertEqual(rows[2]["card_id"], "T01-C01")
        self.assertNotIn("query", rows[2])

    def test_batch_packet_excludes_internal_candidate_pool(self) -> None:
        result = {
            "query": "topic",
            "hits": [_hit("1")],
            "_reranked_pool": [_hit("2")],
            "latency": {},
            "metadata": {},
            "batch": {"total_ms": 10.0},
        }

        packet = batch.build_batch_packet([result])

        self.assertEqual(packet["schema_version"], 1)
        self.assertEqual(len(packet["topics"][0]["hits"]), 1)
        self.assertNotIn("_reranked_pool", packet["topics"][0])

    def test_query_file_loader_accepts_json_list_and_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "queries.json"
            json_path.write_text(json.dumps(["alpha", {"query": "beta"}]))
            jsonl_path = Path(tmp) / "queries.jsonl"
            jsonl_path.write_text('{"query":"gamma"}\ndelta\n')

            from_json = cli._load_batch_queries([], str(json_path))
            from_jsonl = cli._load_batch_queries([], str(jsonl_path))

        self.assertEqual(from_json, ["alpha", "beta"])
        self.assertEqual(from_jsonl, ["gamma", "delta"])


if __name__ == "__main__":
    unittest.main()
