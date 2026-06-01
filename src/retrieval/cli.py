"""Command-line entrypoint for the LanceDB retrieval pipeline."""

from __future__ import annotations

import argparse
import json

from . import pipeline


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

    p_warmup = subparsers.add_parser(
        "warmup",
        help="Preload models so HuggingFace cache is verified and ready (one-shot, no daemon)",
    )
    p_warmup.add_argument("--quiet", action="store_true", help="Suppress per-stage logging")

    args = parser.parse_args(argv)

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
        pipeline._warm_models(verbose=not args.quiet)
        return 0

    if args.command == "list_textbooks":
        pipeline.list_textbooks()
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
            print(json.dumps(output, indent=2))
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

    parser.print_help()
    return 0
