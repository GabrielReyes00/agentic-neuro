"""Command-line entrypoint for the LanceDB retrieval pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import pipeline
from . import batch as batch_pipeline
from . import mini as mini_pipeline


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"))


def _load_batch_queries(values: list[str], query_file: str) -> list[str]:
    queries = [value.strip() for value in values if value.strip()]
    if not query_file:
        return queries
    path = Path(query_file)
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return queries
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, list):
        queries.extend(
            str(item.get("query") if isinstance(item, dict) else item).strip()
            for item in payload
        )
    elif isinstance(payload, dict) and isinstance(payload.get("queries"), list):
        queries.extend(str(item).strip() for item in payload["queries"])
    else:
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                queries.append(stripped)
                continue
            queries.append(
                str(row.get("query") if isinstance(row, dict) else row).strip()
            )
    return [query for query in queries if query]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LanceDB retrieval engine")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    p_compare = subparsers.add_parser(
        "compare",
        help="Retrieve, rerank, distill, and deliver textbook context",
    )
    p_compare.add_argument("query", help="Search query")
    p_compare.add_argument(
        "--stdout",
        action="store_true",
        help="Print context to stdout (agent gets it inline, no file)",
    )
    p_compare.add_argument("--output", default="", help="Custom output file path")
    p_compare.add_argument("--visual", action="store_true", help="Extract images from hits")
    p_compare.add_argument(
        "--no-distill",
        action="store_true",
        help="Bypass adaptive context distillation",
    )
    p_compare.add_argument(
        "--no-frontier",
        action="store_true",
        help="Skip automatic frontier (PMC) search",
    )
    p_compare.add_argument(
        "--card-json",
        action="store_true",
        help="Print/write compact JSONL source cards instead of full formatted context",
    )
    p_compare.add_argument("--card-output", default="", help="Optional path for JSONL source-card output")
    p_compare.add_argument(
        "--coverage-block",
        action="append",
        default=[],
        help="Coverage block label to attach to emitted source cards; repeatable",
    )
    p_compare.add_argument(
        "--max-passages",
        type=int,
        default=0,
        help="Limit final passage/card count after retrieval and distillation",
    )
    p_compare.add_argument(
        "--frontier-max-chars",
        type=int,
        default=0,
        help="Truncate frontier evidence in output/cards to this many characters",
    )
    p_compare.add_argument("--card-prefix", default="QCARD", help="Prefix for emitted source card IDs")
    p_compare.add_argument("--max-takeaways", type=int, default=4, help="Maximum takeaways per source card")
    p_compare.add_argument(
        "--verbose-cards",
        action="store_true",
        help="Include repeated query/coverage metadata on every card row",
    )

    p_search = subparsers.add_parser("search", help="Raw retrieval (debug)")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--json", action="store_true", help="JSON output")
    p_search.add_argument(
        "--reranker",
        default=pipeline.DEFAULT_RERANKER,
        choices=list(pipeline.RERANKER_MODELS.keys()),
    )
    p_search.add_argument("--n-results", type=int, default=pipeline.DEFAULT_N_RESULTS)

    p_batch = subparsers.add_parser(
        "batch",
        help="Retrieve several topics with shared batched model inference",
    )
    p_batch.add_argument(
        "--query",
        action="append",
        default=[],
        help="Topic query; repeat for multiple topics",
    )
    p_batch.add_argument(
        "--query-file",
        default="",
        help="JSON list/object, JSONL, or one-query-per-line input",
    )
    p_batch.add_argument("--json", action="store_true", help="Emit one JSON batch packet")
    p_batch.add_argument(
        "--card-json",
        action="store_true",
        help="Emit compact multi-topic JSONL source cards",
    )
    p_batch.add_argument("--output", default="", help="Optional output path")
    p_batch.add_argument(
        "--no-distill",
        action="store_true",
        help="Skip adaptive context distillation",
    )
    p_batch.add_argument(
        "--no-augment",
        action="store_true",
        help="Skip quality-aware context augmentation",
    )
    p_batch.add_argument(
        "--reranker",
        default=pipeline.DEFAULT_RERANKER,
        choices=list(pipeline.RERANKER_MODELS.keys()),
    )
    p_batch.add_argument("--n-results", type=int, default=pipeline.DEFAULT_N_RESULTS)
    p_batch.add_argument(
        "--max-passages",
        type=int,
        default=0,
        help="Limit final passages/cards per topic after retrieval",
    )
    p_batch.add_argument("--max-takeaways", type=int, default=8)

    p_mini = subparsers.add_parser(
        "mini",
        help="Lightning compact retrieval for short factual lookups",
    )
    p_mini.add_argument("query", help="Short factual or named lookup query")
    p_mini.add_argument(
        "--strategy",
        choices=("auto", "lexical", "semantic", "hybrid"),
        default="auto",
    )
    p_mini.add_argument("--limit", type=int, default=mini_pipeline.MINI_DEFAULT_LIMIT)
    p_mini.add_argument(
        "--max-chars",
        type=int,
        default=mini_pipeline.MINI_DEFAULT_MAX_CHARS,
    )
    p_mini.add_argument("--json", action="store_true", help="Emit the compact JSON packet")
    p_mini.add_argument(
        "--card-json",
        action="store_true",
        help="Emit compact JSONL source cards",
    )
    p_mini.add_argument("--max-takeaways", type=int, default=8)
    p_mini.add_argument("--output", default="", help="Optional output path")

    p_mini_batch = subparsers.add_parser(
        "mini-batch",
        help="Retrieve several short lookups with batched mini-RAG inference",
    )
    p_mini_batch.add_argument(
        "--query",
        action="append",
        default=[],
        help="Short lookup query; repeat for multiple topics",
    )
    p_mini_batch.add_argument(
        "--query-file",
        default="",
        help="JSON list/object, JSONL, or one-query-per-line input",
    )
    p_mini_batch.add_argument(
        "--strategy",
        choices=("auto", "lexical", "semantic", "hybrid"),
        default="auto",
    )
    p_mini_batch.add_argument(
        "--limit",
        type=int,
        default=mini_pipeline.MINI_DEFAULT_LIMIT,
    )
    p_mini_batch.add_argument(
        "--max-chars",
        type=int,
        default=mini_pipeline.MINI_DEFAULT_MAX_CHARS,
    )
    p_mini_batch.add_argument(
        "--json",
        action="store_true",
        help="Emit one compact JSON batch",
    )
    p_mini_batch.add_argument(
        "--card-json",
        action="store_true",
        help="Emit compact multi-topic JSONL source cards",
    )
    p_mini_batch.add_argument("--max-takeaways", type=int, default=8)
    p_mini_batch.add_argument("--output", default="", help="Optional output path")

    subparsers.add_parser(
        "mini-build",
        help="Build/rebuild the pruned ONNX semantic lookup index",
    )
    subparsers.add_parser(
        "mini-fts-build",
        help="Build/rebuild the full-corpus SQLite FTS5 lookup sidecar",
    )
    subparsers.add_parser(
        "mini-preflight",
        help="Check mini-RAG model and semantic index readiness",
    )

    subparsers.add_parser("list_textbooks", help="Show database inventory")
    p_list = subparsers.choices["list_textbooks"]
    p_list.add_argument(
        "--refresh",
        action="store_true",
        help="Rebuild the stored inventory from the Lance table after corpus changes",
    )

    p_warmup = subparsers.add_parser(
        "warmup",
        help="Preload models so HuggingFace cache is verified and ready (one-shot, no daemon)",
    )
    p_warmup.add_argument("--quiet", action="store_true", help="Suppress per-stage logging")
    p_warmup.add_argument(
        "--download",
        action="store_true",
        help="Repair/download required Hugging Face model snapshots into the local cache",
    )

    p_preflight = subparsers.add_parser(
        "preflight",
        help="Check LanceDB, model-cache, and inventory readiness without running retrieval",
    )
    p_preflight.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    args = parser.parse_args(argv)

    try:
        if args.command == "compare":
            pipeline.compare(
                args.query,
                output_file=args.output,
                visual=args.visual,
                no_distill=args.no_distill,
                no_frontier=args.no_frontier,
                stdout=args.stdout,
                card_json=args.card_json,
                card_output=args.card_output,
                coverage_blocks=args.coverage_block,
                max_passages=args.max_passages,
                frontier_max_chars=args.frontier_max_chars,
                card_prefix=args.card_prefix,
                max_takeaways=args.max_takeaways,
                verbose_cards=args.verbose_cards,
            )
            return 0

        if args.command == "warmup":
            timings = pipeline._warm_models(verbose=not args.quiet, download=args.download)
            if args.quiet:
                print(_json_dumps({"ok": True, "timings": timings}))
            return 0

        if args.command == "preflight":
            payload = pipeline.preflight(json_mode=args.json)
            if args.json:
                print(_json_dumps(payload))
            else:
                print(f"OK={payload.get('ok')}")
                lance = payload.get("lance", {})
                bge = payload.get("bge_m3", {})
                reranker = payload.get("reranker", {})
                inventory = payload.get("inventory", {})
                print(f"LanceDB: {lance.get('ok')} rows={lance.get('rows', '?')}")
                print(f"BGE-M3 cache: {bge.get('ok')} snapshot={bge.get('snapshot') or 'missing'}")
                print(f"Reranker cache: {reranker.get('ok')} snapshot={reranker.get('snapshot') or 'missing'}")
                print(f"Inventory: {inventory.get('ok')} path={inventory.get('path')}")
                if payload.get("next_action"):
                    print(payload["next_action"])
            return 0 if payload.get("ok") else 2

        if args.command == "list_textbooks":
            pipeline.list_textbooks(refresh=args.refresh)
            return 0

        if args.command == "search":
            result = pipeline.retrieve(
                args.query,
                reranker_key=args.reranker,
                n_results=args.n_results,
            )
            if args.json:
                output = {
                    "query": result["query"],
                    "reranker": result["reranker"],
                    "latency": result["latency"],
                    "metadata": result["metadata"],
                    "hits": [
                        {
                            "citation": h.get("citation"),
                            "similarity": h.get("similarity"),
                            "rank_score": h.get("rank_score"),
                            "sigmoid_ce": h.get("sigmoid_ce"),
                            "passage_tokens": h.get("passage_tokens"),
                            "source_key": h.get("source_key"),
                            "text_preview": h.get("text", "")[:200],
                        }
                        for h in result["hits"]
                    ],
                }
                print(_json_dumps(output))
            else:
                lat = result["latency"]
                meta = result["metadata"]
                print(f"OK {meta['final_passages']} passages | {meta['unique_sources']} sources | {lat['total_ms']:.0f}ms")
                for i, hit in enumerate(result["hits"], 1):
                    print(f"  [{i}] {hit.get('citation', 'uncited')}")
                    print(
                        f"      rank={hit.get('rank_score')}, ce={hit.get('sigmoid_ce')}, "
                        f"tokens={hit.get('passage_tokens', '?')}"
                    )
            return 0

        if args.command == "batch":
            queries = _load_batch_queries(args.query, args.query_file)
            if not queries:
                parser.error("batch requires --query and/or --query-file")
            results = batch_pipeline.retrieve_many(
                queries,
                n_results=args.n_results,
                reranker_key=args.reranker,
                distill=not args.no_distill,
                augment=not args.no_augment,
                max_passages=args.max_passages,
            )
            if args.card_json:
                output = batch_pipeline.build_batch_source_cards_jsonl(
                    results,
                    max_takeaways=args.max_takeaways,
                )
            elif args.json:
                output = _json_dumps(batch_pipeline.build_batch_packet(results))
            else:
                batch_meta = results[0].get("batch", {}) if results else {}
                lines = [
                    (
                        f"OK {len(results)} topics | "
                        f"{batch_meta.get('total_ms', 0):.0f}ms total | "
                        f"{batch_meta.get('total_ms', 0) / max(1, len(results)):.0f}ms/topic"
                    )
                ]
                for index, result in enumerate(results, 1):
                    meta = result.get("metadata", {})
                    lines.append(
                        f"  [{index}] {meta.get('final_passages', 0)} passages | "
                        f"{meta.get('unique_sources', 0)} sources | {result['query']}"
                    )
                output = "\n".join(lines) + "\n"
            if args.output:
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(output, encoding="utf-8")
            else:
                print(output, end="" if output.endswith("\n") else "\n")
            return 0
        if args.command == "mini-build":
            print(json.dumps(mini_pipeline.build_index(), indent=2))
            return 0

        if args.command == "mini-fts-build":
            print(json.dumps(mini_pipeline.build_fts_index(), indent=2))
            return 0

        if args.command == "mini-preflight":
            payload = mini_pipeline.preflight()
            print(json.dumps(payload, indent=2))
            return 0 if payload.get("ok") else 2

        if args.command == "mini":
            packet = mini_pipeline.retrieve_mini(
                args.query,
                strategy=args.strategy,
                limit=args.limit,
                max_chars=args.max_chars,
            )
            if args.card_json:
                output = mini_pipeline.build_source_cards_jsonl(
                    [packet],
                    max_takeaways=args.max_takeaways,
                )
            elif args.json:
                output = json.dumps(
                    packet,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            else:
                output = mini_pipeline.format_context(packet)
            if args.output:
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(output, encoding="utf-8")
            else:
                print(output, end="" if output.endswith("\n") else "\n")
            return 0

        if args.command == "mini-batch":
            queries = _load_batch_queries(args.query, args.query_file)
            if not queries:
                parser.error("mini-batch requires --query and/or --query-file")
            packets = mini_pipeline.retrieve_many(
                queries,
                strategy=args.strategy,
                limit=args.limit,
                max_chars=args.max_chars,
            )
            if args.card_json:
                output = mini_pipeline.build_source_cards_jsonl(
                    packets,
                    max_takeaways=args.max_takeaways,
                )
            elif args.json:
                output = json.dumps(
                    {
                        "type": "mini_rag_batch",
                        "schema_version": 1,
                        "batch": packets[0].get("batch", {}) if packets else {},
                        "results": packets,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            else:
                output = "\n".join(
                    mini_pipeline.format_context(packet).rstrip()
                    for packet in packets
                ) + "\n"
            if args.output:
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(output, encoding="utf-8")
            else:
                print(output, end="" if output.endswith("\n") else "\n")
            return 0
    except pipeline.RetrievalPreflightError as exc:
        print(f"RAG preflight failed: {exc}", file=__import__("sys").stderr)
        return 2
    except mini_pipeline.MiniRAGPreflightError as exc:
        print(f"Mini-RAG preflight failed: {exc}", file=__import__("sys").stderr)
        return 2

    parser.print_help()
    return 0
