from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retrieval import cli, mini


def _hit(
    text: str,
    *,
    score: float = 0.9,
    child_id: str = "c1",
    parent_id: str = "p1",
    chunk_index: int = 0,
    source: str = "Test Textbook",
) -> dict:
    return {
        "text": text,
        "similarity": score,
        "mini_score": score,
        "citation": f"{source} — p.10",
        "source_key": source,
        "child_id": child_id,
        "parent_id": parent_id,
        "metadata": {
            "heading": "Grading table",
            "chapter_title": "Classification",
            "page_start": 10,
            "chunk_index": chunk_index,
            "has_table": True,
        },
        "retrievers": ["lexical"],
    }


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "AVM operative risk from size, eloquence, and deep venous drainage",
            "Spetzler-Martin",
        ),
        (
            "Meningioma dural attachment and abnormal bone versus subtotal resection",
            "Simpson",
        ),
        (
            "SAH CT blood burden with IVH and thick cisternal clot",
            "modified Fisher",
        ),
    ],
)
def test_signature_expansion_is_transparent(query: str, expected: str):
    expanded, aliases = mini.expand_query(query)

    assert expected in aliases
    assert expected in expanded


def test_route_rejects_complex_synthesis():
    route = mini.route_query(
        "Comprehensive perioperative management and operative walkthrough "
        "for a ruptured aneurysm"
    )

    assert route["route"] == "full"
    assert "synthesis" in route["reason"]


def test_route_uses_exact_fts_for_recognized_signature():
    route = mini.route_query(
        "How do size, eloquent location, and deep venous drainage combine "
        "to estimate AVM operative risk?"
    )

    assert route["route"] == "lexical"
    assert route["query_expansions"] == ["Spetzler-Martin"]


def test_duplicate_extraction_units_are_removed():
    text = (
        "Grade I, Description = Normal facial function. "
        "Grade I, Description = Normal facial function. "
        "Grade II, Description = Mild dysfunction."
    )

    cleaned = mini._clean_serialized_text(text)

    assert cleaned.count("Grade I, Description") == 1
    assert "Grade II" in cleaned


def test_adjacent_chunk_only_stitches_when_it_adds_query_evidence():
    first = _hit(
        "Location, pain, bone lesion, and alignment scoring.",
        child_id="c1",
        chunk_index=1,
    )
    useful_adjacent = _hit(
        "Vertebral collapse and posterior element scoring.",
        child_id="c2",
        chunk_index=2,
    )
    irrelevant_adjacent = _hit(
        "General metastatic spine management discussion.",
        child_id="c3",
        chunk_index=0,
    )

    clustered = mini._cluster_adjacent_hits(
        "location pain bone lesion alignment collapse posterior elements",
        [first, useful_adjacent, irrelevant_adjacent],
    )

    assert clustered[0]["cluster_chunks"] == 2
    assert "posterior element" in clustered[0]["text"]
    assert "General metastatic" not in clustered[0]["text"]


def test_compact_packet_stays_bounded_and_source_traced():
    hits = [
        _hit("Grade I. " + ("useful evidence " * 500), child_id="c1"),
        _hit(
            "Grade II. " + ("second source " * 300),
            child_id="c2",
            parent_id="p2",
            source="Second Textbook",
        ),
    ]

    compact = mini._compact_hits(
        "grading system",
        hits,
        limit=2,
        max_chars=1200,
    )

    assert sum(len(hit["text"]) for hit in compact) <= 1200
    assert compact[0]["citation"]
    assert compact[0]["raw_ref"]["child_id"] == "c1"
    assert any(hit["truncated"] for hit in compact)


def test_hybrid_fusion_prefers_strong_exact_table_over_semantic_overview():
    lexical = _hit(
        "Table. Size criteria = small. Eloquence points = 1. "
        "Deep venous drainage points = 1.",
        score=0.95,
        child_id="table",
    )
    semantic = _hit(
        "This section discusses operative risk for vascular malformations.",
        score=0.82,
        child_id="overview",
        source="Overview",
    )

    fused = mini._fuse_hybrid_hits(
        "Spetzler-Martin AVM grading scale",
        [lexical],
        [semantic],
    )

    assert fused[0]["child_id"] == "table"


def test_auto_batch_deduplicates_and_skips_semantic_for_confident_named_lookup(
    monkeypatch: pytest.MonkeyPatch,
):
    calls = {"lexical": 0, "semantic": 0}

    def fake_lexical(queries, **_kwargs):
        calls["lexical"] += 1
        assert queries == ["Hunt and Hess scale grades"]
        return [
            (
                [
                    _hit(
                        "Hunt and Hess grades. Grade 1 asymptomatic. "
                        "Grade 2 headache. Grade 3 confusion. Grade 4 stupor. "
                        "Grade 5 deep coma.",
                        score=1.0,
                    )
                ],
                {"total_ms": 1.0},
            )
        ]

    def fake_semantic(_queries, **_kwargs):
        calls["semantic"] += 1
        raise AssertionError("semantic fallback should not run")

    monkeypatch.setattr(mini, "lexical_search_many", fake_lexical)
    monkeypatch.setattr(mini, "semantic_search_many", fake_semantic)

    packets = mini.retrieve_many(
        ["Hunt and Hess scale grades", "Hunt and Hess scale grades"],
        strategy="auto",
    )

    assert calls == {"lexical": 1, "semantic": 0}
    assert len(packets) == 2
    assert packets[0]["strategy"] == "lexical"
    assert packets[0]["batch"]["unique_query_count"] == 1


def test_auto_returns_lexical_evidence_with_escalation_when_semantic_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        mini,
        "lexical_search_many",
        lambda queries, **_kwargs: [
            ([_hit("Facial movement after surgery.", score=0.2)], {"total_ms": 1.0})
            for _ in queries
        ],
    )

    def missing_semantic(_queries, **_kwargs):
        raise mini.MiniRAGPreflightError("index missing")

    monkeypatch.setattr(mini, "semantic_search_many", missing_semantic)

    packet = mini.retrieve_mini(
        "How is facial nerve function described after vestibular schwannoma surgery?"
    )

    assert packet["hits"]
    assert packet["escalate"] is True
    assert "index missing" in packet["escalation_reason"]


def test_explicit_semantic_strategy_propagates_missing_index(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        mini,
        "semantic_search_many",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            mini.MiniRAGPreflightError("index missing")
        ),
    )

    with pytest.raises(mini.MiniRAGPreflightError, match="index missing"):
        mini.retrieve_mini("unnamed classification", strategy="semantic")


def test_sqlite_match_query_is_fts_safe():
    match_query = mini._sqlite_match_query(
        'Spetzler-Martin AVM "grading" table'
    )

    assert '"spetzler-martin"' in match_query
    assert " OR " in match_query


def test_fts_sidecar_path_is_workspace_local():
    assert isinstance(mini.MINI_FTS_PATH, Path)
    assert mini.MINI_FTS_PATH.name == "mini_rag_fts.db"


def test_sidecar_freshness_uses_source_manifest_mtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    sidecar = tmp_path / "sidecar.db"
    manifest = tmp_path / "sidecar.json"
    sidecar.write_text("index", encoding="utf-8")
    manifest.write_text("{}", encoding="utf-8")
    os.utime(sidecar, (100.0, 100.0))
    monkeypatch.setattr(mini, "_source_manifest_mtime", lambda: 200.0)

    assert mini._sidecar_is_fresh(sidecar, manifest) is False

    os.utime(sidecar, (300.0, 300.0))
    assert mini._sidecar_is_fresh(sidecar, manifest) is True


def test_mini_batch_cli_emits_versioned_packet(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    packet = {
        "type": "mini_rag",
        "schema_version": 1,
        "query": "Hunt and Hess",
        "strategy": "lexical",
        "confidence": 1.0,
        "hits": [],
        "escalate": False,
        "batch": {
            "query_count": 1,
            "unique_query_count": 1,
            "total_ms": 1.0,
        },
    }
    monkeypatch.setattr(
        cli.mini_pipeline,
        "retrieve_many",
        lambda *_args, **_kwargs: [packet],
    )

    status = cli.main(
        ["mini-batch", "--query", "Hunt and Hess", "--json"]
    )
    output = json.loads(capsys.readouterr().out)

    assert status == 0
    assert output["type"] == "mini_rag_batch"
    assert output["schema_version"] == 1
    assert output["results"][0]["strategy"] == "lexical"


def test_mini_source_cards_have_stable_ids_and_escalation_metadata():
    packets = [{
        "query": "Hunt and Hess",
        "route": {"route": "lexical"},
        "confidence": 1.0,
        "escalate": False,
        "escalation_reason": "",
        "hits": [{
            "citation": "Essential Neurosurgery — p.139",
            "page_start": 139,
            "text": "Grade 1 has minimal headache. Grade 5 is deep coma.",
            "truncated": False,
            "raw_ref": {
                "child_id": "380",
                "source_key": "Essential Neurosurgery",
                "chunk_index": 1,
            },
        }],
    }]

    rows = [
        json.loads(line)
        for line in mini.build_source_cards_jsonl(packets).splitlines()
    ]

    assert rows[0]["type"] == "mini_batch_source_card_manifest"
    assert rows[0]["source_type"] == "textbook_rag_mini"
    assert rows[1]["type"] == "topic_manifest"
    assert rows[1]["topic_id"] == "M01"
    assert rows[1]["escalate"] is False
    assert rows[2]["type"] == "source_card"
    assert rows[2]["card_id"] == "M01-C01"
    assert rows[2]["raw_ref"]["child_id"] == "380"
    assert "query" not in rows[2]


def test_mini_batch_cli_emits_source_cards(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    packet = {
        "query": "Hunt and Hess",
        "route": {"route": "lexical"},
        "confidence": 1.0,
        "hits": [],
        "escalate": False,
        "escalation_reason": "",
    }
    monkeypatch.setattr(
        cli.mini_pipeline,
        "retrieve_many",
        lambda *_args, **_kwargs: [packet],
    )

    status = cli.main(
        ["mini-batch", "--query", "Hunt and Hess", "--card-json"]
    )
    rows = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
    ]

    assert status == 0
    assert rows[0]["type"] == "mini_batch_source_card_manifest"
    assert rows[1]["query"] == "Hunt and Hess"
