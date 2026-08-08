#!/usr/bin/env python3
"""Benchmark mini-RAG strategies on short neurosurgical learning lookups.

The report preserves top-passage previews and qualitative expectations so a
high anchor score cannot hide an unhelpful or misleading retrieval order.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retrieval import batch, mini, pipeline  # noqa: E402


DEFAULT_CASES = Path(__file__).with_name("mini_rag_queries.json")
DEFAULT_STRATEGIES = ("lexical", "semantic", "hybrid", "auto")
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
SIGNAL_RE = re.compile(
    r"\b(?:grade|class|score|points?|complete|incomplete|deficit|"
    r"location|size|drainage|pain|alignment|collapse|resection|"
    r"attachment|bone|carotid|hemorrhage|ivh|gcs)\b",
    re.IGNORECASE,
)


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").lower()


def _anchor_matches(
    text: str,
    groups: list[list[str]],
) -> list[bool]:
    normalized = _normalized(text)
    return [
        any(_normalized(alternative) in normalized for alternative in group)
        for group in groups
    ]


def _duplicate_unit_ratio(text: str) -> float:
    units = [
        _normalized(unit)
        for unit in re.split(r"(?<=[.!?])\s+", text)
        if len(_normalized(unit)) >= 24
    ]
    if not units:
        return 0.0
    return 1.0 - (len(set(units)) / len(units))


def _case_metrics(
    case: dict[str, Any],
    packet: dict[str, Any],
) -> dict[str, Any]:
    hits = packet.get("hits", [])
    texts = [str(hit.get("text") or "") for hit in hits]
    joined = "\n".join(texts)
    top = texts[0] if texts else ""
    all_anchors = _anchor_matches(joined, case["anchor_groups"])
    top_anchors = _anchor_matches(top, case["anchor_groups"])
    entity_found = any(
        _normalized(term) in _normalized(joined)
        for term in case["entity_terms"]
    )
    entity_in_top = any(
        _normalized(term) in _normalized(top)
        for term in case["entity_terms"]
    )
    serialized = json.dumps(
        packet,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    signal_count = sum(
        1
        for token in re.split(r"(?<=[.!?])\s+|,\s+", joined)
        if SIGNAL_RE.search(token) or NUMBER_RE.search(token)
    )
    approx_tokens = pipeline._approx_tokens(joined)
    return {
        "id": case["id"],
        "kind": case["kind"],
        "query": case["query"],
        "expectation": case["expectation"],
        "strategy_used": packet.get("strategy"),
        "confidence": packet.get("confidence", 0.0),
        "escalate": packet.get("escalate", False),
        "hit_count": len(hits),
        "entity_found": entity_found,
        "entity_in_top": entity_in_top,
        "anchor_recall": round(sum(all_anchors) / len(all_anchors), 4),
        "top_anchor_recall": round(sum(top_anchors) / len(top_anchors), 4),
        "anchor_matches": all_anchors,
        "top_anchor_matches": top_anchors,
        "approx_tokens": approx_tokens,
        "signal_per_1k_tokens": round(
            signal_count * 1000 / max(1, approx_tokens),
            4,
        ),
        "duplicate_unit_ratio": round(_duplicate_unit_ratio(joined), 4),
        "serialized_bytes": len(serialized.encode("utf-8")),
        "truncated_hits": sum(bool(hit.get("truncated")) for hit in hits),
        "top_citation": hits[0].get("citation", "") if hits else "",
        "top_preview": _normalized(top)[:700],
        "latency": packet.get("latency", {}),
    }


def _aggregate(
    strategy: str,
    runs: list[dict[str, Any]],
    cold_ms: float,
) -> dict[str, Any]:
    final_cases = runs[-1]["cases"]
    named = [case for case in final_cases if case["kind"] == "named"]
    paraphrase = [case for case in final_cases if case["kind"] == "paraphrase"]

    def mean(items: list[dict[str, Any]], field: str) -> float:
        return statistics.fmean(float(item[field]) for item in items) if items else 0.0

    return {
        "strategy": strategy,
        "case_count": len(final_cases),
        "cold_batch_ms": round(cold_ms, 2),
        "warm_batch_ms": {
            "median": round(statistics.median(run["wall_ms"] for run in runs), 2),
            "min": round(min(run["wall_ms"] for run in runs), 2),
            "max": round(max(run["wall_ms"] for run in runs), 2),
            "per_query_median": round(
                statistics.median(run["wall_ms"] for run in runs)
                / max(1, len(final_cases)),
                2,
            ),
        },
        "quality": {
            "entity_recall": round(mean(final_cases, "entity_found"), 4),
            "top_entity_recall": round(mean(final_cases, "entity_in_top"), 4),
            "anchor_recall": round(mean(final_cases, "anchor_recall"), 4),
            "top_anchor_recall": round(mean(final_cases, "top_anchor_recall"), 4),
            "named_anchor_recall": round(mean(named, "anchor_recall"), 4),
            "paraphrase_anchor_recall": round(mean(paraphrase, "anchor_recall"), 4),
            "mean_signal_per_1k_tokens": round(
                mean(final_cases, "signal_per_1k_tokens"),
                4,
            ),
            "mean_duplicate_unit_ratio": round(
                mean(final_cases, "duplicate_unit_ratio"),
                4,
            ),
            "escalations": sum(bool(case["escalate"]) for case in final_cases),
        },
        "serialization": {
            "total_bytes": sum(case["serialized_bytes"] for case in final_cases),
            "mean_tokens_per_case": round(mean(final_cases, "approx_tokens"), 2),
            "truncated_hits": sum(case["truncated_hits"] for case in final_cases),
        },
        "runs": runs,
    }


def _run_mini(
    cases: list[dict[str, Any]],
    strategy: str,
    *,
    limit: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    return mini.retrieve_many(
        [case["query"] for case in cases],
        strategy=strategy,
        limit=limit,
        max_chars=max_chars,
    )


def _full_packets(
    cases: list[dict[str, Any]],
    *,
    limit: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    results = batch.retrieve_many(
        [case["query"] for case in cases],
        distill=True,
        augment=True,
    )
    packets = []
    for case, result in zip(cases, results, strict=True):
        ranked = mini._rank_lookup_hits(case["query"], result.get("hits", []))
        packets.append({
            "query": case["query"],
            "strategy": "full",
            "confidence": mini._confidence(case["query"], ranked),
            "escalate": False,
            "hits": mini._compact_hits(
                case["query"],
                ranked,
                limit=limit,
                max_chars=max_chars,
            ),
            "latency": result.get("latency", {}),
        })
    return packets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--strategies",
        default=",".join(DEFAULT_STRATEGIES),
        help="Comma-separated lexical,semantic,hybrid,auto,full",
    )
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument(
        "--kind",
        choices=("all", "named", "paraphrase"),
        default="all",
        help="Optionally benchmark only one case class",
    )
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--max-chars", type=int, default=4200)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.kind != "all":
        cases = [case for case in cases if case["kind"] == args.kind]
    strategies = [
        strategy.strip()
        for strategy in args.strategies.split(",")
        if strategy.strip()
    ]
    allowed = {*DEFAULT_STRATEGIES, "full"}
    if not strategies or any(strategy not in allowed for strategy in strategies):
        raise ValueError(f"strategies must come from {sorted(allowed)}")

    reports = []
    for strategy in strategies:
        run = _full_packets if strategy == "full" else _run_mini
        cold_started = time.perf_counter()
        run(cases, strategy, limit=args.limit, max_chars=args.max_chars) if (
            strategy != "full"
        ) else run(cases, limit=args.limit, max_chars=args.max_chars)
        cold_ms = (time.perf_counter() - cold_started) * 1000

        repetitions = []
        for _ in range(max(1, args.repeat)):
            started = time.perf_counter()
            packets = (
                run(cases, strategy, limit=args.limit, max_chars=args.max_chars)
                if strategy != "full"
                else run(cases, limit=args.limit, max_chars=args.max_chars)
            )
            wall_ms = (time.perf_counter() - started) * 1000
            repetitions.append({
                "wall_ms": round(wall_ms, 2),
                "cases": [
                    _case_metrics(case, packet)
                    for case, packet in zip(cases, packets, strict=True)
                ],
            })
        reports.append(_aggregate(strategy, repetitions, cold_ms))

    payload = {
        "schema_version": 1,
        "case_file": str(args.cases),
        "limit": args.limit,
        "max_chars": args.max_chars,
        "reports": reports,
    }
    output = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
