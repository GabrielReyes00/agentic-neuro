"""Command-line entrypoint for the LanceDB retrieval pipeline."""

from __future__ import annotations

import argparse
import json

from . import pipeline


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"))


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
    except pipeline.RetrievalPreflightError as exc:
        print(f"RAG preflight failed: {exc}", file=__import__("sys").stderr)
        return 2

    parser.print_help()
    return 0
