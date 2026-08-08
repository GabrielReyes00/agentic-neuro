from __future__ import annotations

import json

from src.retrieval import mini, pipeline, provenance


def test_source_roles_keep_grant_books_out_of_clinical_queries():
    source = "How to Write a Successful NIH Grant Application"
    assert provenance.source_role(source) == "research_methodology"
    assert not provenance.source_allowed_for_query(source, "management of acute subdural hematoma")
    assert provenance.source_allowed_for_query(source, "how to write NIH grant specific aims")


def test_retrieval_provenance_is_stable_and_relative():
    first = provenance.retrieval_provenance(
        route="full",
        reranker_key="minilm-l6",
        reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        embedding_model="BAAI/bge-m3",
    )
    second = provenance.retrieval_provenance(
        route="full",
        reranker_key="minilm-l6",
        reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        embedding_model="BAAI/bge-m3",
    )
    assert first == second
    assert first["corpus"]["fingerprint"]
    assert first["corpus"]["ingestion_version"] == "legacy-unrecorded"
    assert "/Users/" not in json.dumps(first)


def test_full_source_cards_carry_manifest_and_source_roles():
    hit = pipeline._row_to_hit(
        {
            "child_text": "Clinical anatomy text.",
            "source_book": "Cranial Anatomy and Surgical Approaches",
            "child_id": "1",
            "parent_id": "p1",
        },
        0.9,
    )
    result = {
        "query": "cranial anatomy",
        "reranker": "minilm-l6",
        "hits": [hit],
        "provenance": provenance.retrieval_provenance(route="full"),
    }
    rows = [json.loads(line) for line in pipeline.build_source_cards_jsonl(result).splitlines()]
    assert rows[0]["provenance"]["corpus"]["fingerprint"]
    assert rows[1]["source_role"] == "anatomic_reference"


def test_mini_packet_filters_nonclinical_source_role():
    packet = mini._finalize_packet(
        "acute subdural hematoma management",
        strategy="lexical",
        routing={"route": "lexical"},
        hits=[{
            "text": "Write the specific aims page.",
            "source_key": "Grant Writing for Dummies",
            "source_role": "research_methodology",
            "citation": "Grant Writing for Dummies",
        }],
        timing={},
        limit=2,
        max_chars=1000,
    )
    assert packet["hits"] == []
    assert packet["metadata"]["source_role_dropped"] == 1
    assert packet["escalate"] is True
