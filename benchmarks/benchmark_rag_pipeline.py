#!/usr/bin/env python3
"""Reproducible latency, relevance, density, and serialization benchmark for RAG.

The benchmark intentionally uses only local corpus/model state and never calls
frontier search. ``serial`` is the scalar compatibility baseline. ``batch``
uses the dedicated batch orchestrator.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_ROOT = Path(os.environ.get("NEURO_BENCH_PIPELINE_ROOT", ROOT))
sys.path.insert(0, str(PIPELINE_ROOT / "src"))

from retrieval import batch, pipeline  # noqa: E402


DEFAULT_CASES = Path(__file__).with_name("rag_queries.json")
WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9-]{2,}")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
SIGNAL_RE = re.compile(
    r"\b(?:indicat|contraindicat|diagnos|sensitiv|specific|threshold|"
    r"approach|treat|manage|outcome|complication|risk|predict|recommend|"
    r"resect|decompress|monitor|avoid|repair|mortality|morbidity)\w*",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|mm|cm|mg|years?|months?|weeks?|days?|hours?)?\b",
    re.IGNORECASE,
)


def _hit_text(hit: dict[str, Any]) -> str:
    return (
        hit.get("distilled_text")
        or hit.get("text")
        or hit.get("text_original")
        or ""
    )


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").lower()


def _significant_words(text: str) -> set[str]:
    return {
        token.lower()
        for token in WORD_RE.findall(text or "")
        if token.lower() not in pipeline.STOPWORDS
    }


def _mean_pairwise_jaccard(texts: list[str]) -> float:
    scores: list[float] = []
    word_sets = [_significant_words(text) for text in texts]
    for left in range(len(word_sets)):
        for right in range(left + 1, len(word_sets)):
            union = word_sets[left] | word_sets[right]
            if union:
                scores.append(len(word_sets[left] & word_sets[right]) / len(union))
    return statistics.fmean(scores) if scores else 0.0


def _prepare_serial(query: str) -> dict[str, Any]:
    result = pipeline.retrieve(query)
    if result.get("hits"):
        distilled = pipeline._distill_by_axes(query, result["hits"])
        result["hits"] = distilled["hits"]
        result["axes"] = distilled["axes"]
        result["distilled"] = distilled["distilled"]
    candidates = result.get("_reranked_pool") or []
    if candidates and result.get("hits"):
        result["hits"], result["augment_ce"] = pipeline._quality_augment(
            query,
            result["hits"],
            candidates,
        )
    return result


def _prepare_many(cases: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "batch":
        return batch.retrieve_many(
            [case["query"] for case in cases],
            distill=True,
            augment=True,
        )
    return [_prepare_serial(case["query"]) for case in cases]


def _case_metrics(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    hits = result.get("hits", [])
    texts = [_hit_text(hit) for hit in hits if _hit_text(hit)]
    joined = _normalized("\n".join(texts))
    anchor_matches = [
        any(_normalized(alternative) in joined for alternative in group)
        for group in case["anchor_groups"]
    ]
    entity_hit_count = sum(
        1
        for text in texts
        if any(_normalized(term) in _normalized(text) for term in case["entity_terms"])
    )
    sentences = [
        sentence.strip()
        for text in texts
        for sentence in SENTENCE_RE.split(re.sub(r"\s+", " ", text).strip())
        if sentence.strip()
    ]
    high_signal_sentences = sum(
        1 for sentence in sentences if SIGNAL_RE.search(sentence) or NUMBER_RE.search(sentence)
    )
    source_count = len(
        {
            hit.get("source_key")
            for hit in hits
            if hit.get("source_key")
        }
    )
    approx_tokens = sum(pipeline._approx_tokens(text) for text in texts)
    redundancy = _mean_pairwise_jaccard(texts)
    anchor_recall = sum(anchor_matches) / max(1, len(anchor_matches))
    entity_hit_rate = entity_hit_count / max(1, len(texts))
    source_diversity = min(1.0, source_count / 3.0)
    quality_score = (
        0.55 * anchor_recall
        + 0.25 * entity_hit_rate
        + 0.10 * (1.0 - redundancy)
        + 0.10 * source_diversity
    )
    source_cards = pipeline.build_source_cards_jsonl(
        result,
        card_prefix=f"BENCH-{case['id'].upper()}",
    )
    compact_payload = {
        "query": result.get("query"),
        "hits": [
            {
                "child_id": hit.get("child_id"),
                "source_key": hit.get("source_key"),
                "score": hit.get("rank_score"),
                "text": _hit_text(hit),
            }
            for hit in hits
        ],
    }
    t0 = time.perf_counter()
    serialized = json.dumps(
        compact_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    serialize_ms = (time.perf_counter() - t0) * 1000
    return {
        "id": case["id"],
        "query": case["query"],
        "hit_count": len(hits),
        "source_count": source_count,
        "anchor_matches": anchor_matches,
        "anchor_recall": round(anchor_recall, 4),
        "entity_hit_rate": round(entity_hit_rate, 4),
        "mean_pairwise_redundancy": round(redundancy, 4),
        "quality_score": round(quality_score, 4),
        "approx_tokens": approx_tokens,
        "high_signal_sentences": high_signal_sentences,
        "high_signal_per_1k_tokens": round(
            high_signal_sentences * 1000 / max(1, approx_tokens),
            4,
        ),
        "source_card_bytes": len(source_cards.encode("utf-8")),
        "serialized_bytes": len(serialized.encode("utf-8")),
        "serialize_ms": round(serialize_ms, 4),
        "top_child_ids": [hit.get("child_id") for hit in hits[:5]],
        "pipeline_latency": result.get("latency", {}),
    }


def _aggregate(
    mode: str,
    repetitions: list[dict[str, Any]],
    warmup_ms: float,
) -> dict[str, Any]:
    run_ms = [item["wall_ms"] for item in repetitions]
    final_cases = repetitions[-1]["cases"]
    return {
        "mode": mode,
        "case_count": len(final_cases),
        "warmup_ms": round(warmup_ms, 2),
        "wall_ms": {
            "median": round(statistics.median(run_ms), 2),
            "min": round(min(run_ms), 2),
            "max": round(max(run_ms), 2),
            "per_query_median": round(statistics.median(run_ms) / max(1, len(final_cases)), 2),
        },
        "quality": {
            "mean_anchor_recall": round(
                statistics.fmean(case["anchor_recall"] for case in final_cases),
                4,
            ),
            "mean_entity_hit_rate": round(
                statistics.fmean(case["entity_hit_rate"] for case in final_cases),
                4,
            ),
            "mean_redundancy": round(
                statistics.fmean(case["mean_pairwise_redundancy"] for case in final_cases),
                4,
            ),
            "mean_quality_score": round(
                statistics.fmean(case["quality_score"] for case in final_cases),
                4,
            ),
            "total_high_signal_sentences": sum(
                case["high_signal_sentences"] for case in final_cases
            ),
            "high_signal_per_1k_tokens": round(
                sum(case["high_signal_sentences"] for case in final_cases)
                * 1000
                / max(1, sum(case["approx_tokens"] for case in final_cases)),
                4,
            ),
        },
        "serialization": {
            "total_payload_bytes": sum(case["serialized_bytes"] for case in final_cases),
            "total_source_card_bytes": sum(case["source_card_bytes"] for case in final_cases),
            "total_serialize_ms": round(
                sum(case["serialize_ms"] for case in final_cases),
                4,
            ),
            "delivery_bytes": repetitions[-1]["delivery_bytes"],
            "delivery_serialize_ms_median": round(
                statistics.median(
                    repetition["delivery_serialize_ms"]
                    for repetition in repetitions
                ),
                4,
            ),
        },
        "runs": repetitions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--mode", choices=("serial", "batch"), default="serial")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-warmup", action="store_true")
    args = parser.parse_args(argv)

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("benchmark case file must contain a non-empty JSON list")

    warmup_start = time.perf_counter()
    if not args.skip_warmup:
        pipeline._warm_models(verbose=False)
    warmup_ms = (time.perf_counter() - warmup_start) * 1000

    repetitions: list[dict[str, Any]] = []
    for _ in range(max(1, args.repeat)):
        started = time.perf_counter()
        results = _prepare_many(cases, args.mode)
        wall_ms = (time.perf_counter() - started) * 1000
        case_metrics = [
            _case_metrics(case, result)
            for case, result in zip(cases, results, strict=True)
        ]
        delivery_started = time.perf_counter()
        if args.mode == "batch":
            from retrieval import batch as batch_pipeline

            delivery_payload = batch_pipeline.build_batch_source_cards_jsonl(results)
        else:
            delivery_payload = "".join(
                pipeline.build_source_cards_jsonl(result)
                for result in results
            )
        delivery_ms = (time.perf_counter() - delivery_started) * 1000
        repetitions.append({
            "wall_ms": round(wall_ms, 2),
            "delivery_bytes": len(delivery_payload.encode("utf-8")),
            "delivery_serialize_ms": round(delivery_ms, 4),
            "cases": case_metrics,
        })

    payload = _aggregate(args.mode, repetitions, warmup_ms)
    output = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
