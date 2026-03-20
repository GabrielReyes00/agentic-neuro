#!/usr/bin/env python3
"""
RAG Benchmark Harness — ChromaDB vs LanceDB + Reranker Shootout

Runs a fixed query set through both retrieval backends and multiple reranker
models, collecting latency, hit overlap, source diversity, and reranker
agreement metrics.

Usage:
    cd /Users/gabrielreyes/neuro_rag && source .venv/bin/activate

    # Full benchmark (all tests):
    python3 scripts/benchmark_rag.py --lance-dir /path/to/agentic-neurodb_v4

    # ChromaDB baseline only (no LanceDB needed):
    python3 scripts/benchmark_rag.py --chromadb-only

    # LanceDB reranker shootout only:
    python3 scripts/benchmark_rag.py --lance-dir /path/to/agentic-neurodb_v4 --lance-only

    # Custom query set:
    python3 scripts/benchmark_rag.py --lance-dir /path/to/lancedb --queries queries.json

Output:
    data/Sessions/benchmark_results_YYYYMMDD_HHMMSS.json  — raw JSON
    Terminal — formatted comparison tables

Does NOT modify any existing databases, caches, or code.
"""

import argparse
import contextlib
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from typing import Any, Dict, List, Optional

# Ensure src/ is importable
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))


@contextlib.contextmanager
def suppress_stdout():
    """Suppress all stdout from internal modules (model loading, status lines).
    Keeps stderr for genuine errors only."""
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = old_stdout

# ── Benchmark Query Set ──────────────────────────────────────────────────────
# 8 queries spanning subspecialties, complexity levels, and retrieval patterns.
# Designed to stress-test: multi-source fusion, reference chunk filtering,
# clinical specificity, and cross-subspecialty breadth.

DEFAULT_QUERIES = [
    {
        "id": "Q1_vascular_mechanism",
        "query": "Pathophysiology of cerebral vasospasm after aneurysmal subarachnoid hemorrhage",
        "subspecialty": "vascular",
        "complexity": "moderate",
        "notes": "Core mechanism question — tests dense retrieval depth in a single subspecialty",
    },
    {
        "id": "Q2_tumor_comparison",
        "query": "WHO grading and molecular classification differences between astrocytoma and oligodendroglioma",
        "subspecialty": "tumor",
        "complexity": "complex",
        "notes": "Comparison query — tests multi-axis retrieval and RRF fusion across chapters",
    },
    {
        "id": "Q3_spine_surgical",
        "query": "Indications and surgical technique for anterior cervical discectomy and fusion",
        "subspecialty": "spine",
        "complexity": "moderate",
        "notes": "Procedural query — tests chunk clustering and context expansion around surgical steps",
    },
    {
        "id": "Q4_trauma_management",
        "query": "Initial management and ICP monitoring thresholds for severe traumatic brain injury",
        "subspecialty": "trauma",
        "complexity": "moderate",
        "notes": "Protocol query — tests numerical recall retrieval and guideline-heavy content",
    },
    {
        "id": "Q5_functional_mechanism",
        "query": "Mechanism of action and target selection for deep brain stimulation in Parkinson disease",
        "subspecialty": "functional",
        "complexity": "complex",
        "notes": "Multi-concept query — tests retrieval across anatomy + physiology + technique",
    },
    {
        "id": "Q6_pediatric_congenital",
        "query": "Classification and surgical management of Chiari malformation type I with syringomyelia",
        "subspecialty": "pediatric",
        "complexity": "moderate",
        "notes": "Specific condition — tests precision of retrieval for a well-defined topic",
    },
    {
        "id": "Q7_critical_care_protocol",
        "query": "Cerebral perfusion pressure targets and osmotic therapy in neurosurgical critical care",
        "subspecialty": "critical_care",
        "complexity": "moderate",
        "notes": "ICU protocol — tests retrieval of numerical thresholds and treatment algorithms",
    },
    {
        "id": "Q8_cross_subspecialty",
        "query": "Differences between epidural and subdural hematoma in presentation, imaging, and surgical management",
        "subspecialty": "trauma",
        "complexity": "complex",
        "notes": "Classic comparison — tests disambiguation, source diversity, and reference filtering",
    },
    {
        "id": "Q9_peripheral_nerve",
        "query": "Evaluation and surgical repair options for brachial plexus injury including nerve transfer techniques",
        "subspecialty": "peripheral",
        "complexity": "complex",
        "notes": "Peripheral nerve — tests retrieval across dedicated peripheral nerve texts",
    },
    {
        "id": "Q10_neuroanatomy_imaging",
        "query": "Anatomical boundaries and vascular supply of the internal capsule and clinical significance of lacunar infarcts",
        "subspecialty": "vascular",
        "complexity": "complex",
        "notes": "Cross-domain anatomy+vascular — tests imaging atlas + clinical text integration",
    },
]


# ── ChromaDB Baseline Runner ─────────────────────────────────────────────────

def run_chromadb_baseline(query: str) -> dict:
    """Run the current production ChromaDB pipeline via db_tools internals.

    This imports from the existing codebase but does NOT modify any state.
    Uses the same _retrieve_and_rank path that `compare` uses.
    """
    import db_tools

    t0 = time.perf_counter()
    try:
        with suppress_stdout():
            r = db_tools._retrieve_and_rank(
                query=query,
                n_textbook=35,
                textbook_collection=db_tools.DEFAULT_TEXTBOOK_COLLECTION,
                min_similarity=db_tools.DEFAULT_MIN_SIMILARITY,
                max_per_source=10,
                rerank=True,
            )
        total_ms = round((time.perf_counter() - t0) * 1000, 2)

        grouped = r["grouped"]
        funnel = grouped.pop("_pipeline_funnel", {})
        textbook_hits = grouped.get("textbook", [])

        # Extract comparable metadata
        hit_texts = [h.get("text", "")[:220].lower() for h in textbook_hits]
        source_books = {
            h.get("metadata", {}).get("source_book", "")
            for h in textbook_hits
            if h.get("metadata", {}).get("source_book")
        }

        return {
            "status": "ok",
            "total_ms": total_ms,
            "per_stage_ms": r["result_bundle"].get("per_collection_ms", {}),
            "n_hits": len(textbook_hits),
            "unique_sources": len(source_books),
            "source_books": sorted(source_books),
            "hit_fingerprints": hit_texts,
            "top_5_scores": [
                {
                    "citation": h.get("citation", ""),
                    "similarity": h.get("similarity"),
                    "rank_score": h.get("rank_score"),
                    "sigmoid_ce": h.get("sigmoid_ce"),
                    "text_preview": h.get("text", "")[:200],
                }
                for h in textbook_hits[:5]
            ],
            "funnel": funnel,
            "confidence": db_tools._estimate_confidence(grouped),
            "fallback_used": r["fallback_used"],
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "total_ms": round((time.perf_counter() - t0) * 1000, 2),
        }


# ── LanceDB Runner ───────────────────────────────────────────────────────────

def run_lancedb_retrieval(
    query: str,
    lance_dir: str,
    table_name: str = "neurosurgery_v4",
    reranker_key: str = "bge-reranker-base",
) -> dict:
    """Run the LanceDB pipeline via lance_retriever."""
    import lance_retriever

    try:
        with suppress_stdout():
            result = lance_retriever.retrieve(
                query=query,
                lance_dir=lance_dir,
                table_name=table_name,
                reranker_key=reranker_key,
            )

        hit_texts = [h.get("text", "")[:220].lower() for h in result["hits"]]

        return {
            "status": "ok",
            "reranker": reranker_key,
            "total_ms": result["latency"]["total_ms"],
            "per_stage_ms": result["latency"],
            "n_hits": len(result["hits"]),
            "unique_sources": result["metadata"]["unique_sources"],
            "source_books": result["metadata"]["source_books"],
            "hit_fingerprints": hit_texts,
            "top_5_scores": [
                {
                    "citation": h.get("citation", ""),
                    "similarity": h.get("similarity"),
                    "rank_score": h.get("rank_score"),
                    "sigmoid_ce": h.get("sigmoid_ce"),
                    "text_preview": h.get("text", "")[:200],
                }
                for h in result["hits"][:5]
            ],
            "pipeline_metadata": result["metadata"],
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
            "reranker": reranker_key,
            "total_ms": 0.0,
        }


# ── Comparison Metrics ────────────────────────────────────────────────────────

def compute_hit_overlap(fingerprints_a: list, fingerprints_b: list) -> dict:
    """Compute overlap between two hit sets using 220-char fingerprints."""
    set_a = set(fingerprints_a)
    set_b = set(fingerprints_b)
    intersection = set_a & set_b
    union = set_a | set_b
    jaccard = len(intersection) / max(1, len(union))
    recall_a_in_b = len(intersection) / max(1, len(set_a))
    recall_b_in_a = len(intersection) / max(1, len(set_b))
    return {
        "jaccard": round(jaccard, 4),
        "overlap_count": len(intersection),
        "only_in_a": len(set_a - set_b),
        "only_in_b": len(set_b - set_a),
        "recall_a_in_b": round(recall_a_in_b, 4),
        "recall_b_in_a": round(recall_b_in_a, 4),
    }


def compute_rank_correlation(scores_a: list, scores_b: list) -> float:
    """Kendall's tau rank correlation between two score lists.

    Compares the relative ordering of passages that appear in both result sets.
    """
    if len(scores_a) < 2 or len(scores_b) < 2:
        return 0.0

    n = min(len(scores_a), len(scores_b))
    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            a_diff = scores_a[i] - scores_a[j]
            b_diff = scores_b[i] - scores_b[j]
            if a_diff * b_diff > 0:
                concordant += 1
            elif a_diff * b_diff < 0:
                discordant += 1
    total = concordant + discordant
    if total == 0:
        return 0.0
    return round((concordant - discordant) / total, 4)


# ── Formatted Output ─────────────────────────────────────────────────────────

def print_separator(char="═", width=80):
    print(char * width)


def print_query_header(q: dict, idx: int, total: int):
    print(f"  [{idx}/{total}] {q['id']}: {q['query'][:70]}")


def print_result_row(label: str, result: dict, quiet: bool = False):
    if quiet:
        return
    if result.get("status") == "error":
        print(f"    {label:28s} | ERROR: {result.get('error', 'unknown')[:50]}")
        return
    ms = result.get("total_ms", 0)
    hits = result.get("n_hits", 0)
    sources = result.get("unique_sources", 0)
    print(f"    {label:28s} | {ms:>6.0f}ms | {hits:>2d} hits | {sources:>2d} src")



def print_summary_table(all_results: list):
    """Print compact aggregate summary — designed to be the ONLY output we need to read."""
    # Collect per-backend stats
    backends = defaultdict(lambda: {"latencies": [], "hits": [], "sources": []})
    for entry in all_results:
        for backend_key, result in entry.get("results", {}).items():
            if result.get("status") != "ok":
                continue
            backends[backend_key]["latencies"].append(result["total_ms"])
            backends[backend_key]["hits"].append(result["n_hits"])
            backends[backend_key]["sources"].append(result["unique_sources"])

    print(f"\n{'Backend':30s} | {'p50':>6s} | {'p95':>6s} | {'Mean':>6s} | {'Hits':>4s} | {'Src':>3s}")
    print("─" * 65)
    for bk in sorted(backends.keys()):
        s = backends[bk]
        lats = sorted(s["latencies"])
        if not lats:
            continue
        p50 = lats[len(lats) // 2]
        p95 = lats[int(len(lats) * 0.95)]
        mean = sum(lats) / len(lats)
        avg_h = sum(s["hits"]) / len(s["hits"])
        avg_s = sum(s["sources"]) / len(s["sources"])
        print(f"{bk:30s} | {p50:>5.0f}ms | {p95:>5.0f}ms | {mean:>5.0f}ms | {avg_h:>4.1f} | {avg_s:>3.1f}")

    # Overlap summary
    overlap_stats = defaultdict(list)
    for entry in all_results:
        for key, val in entry.get("overlaps", {}).items():
            if isinstance(val, dict) and "jaccard" in val:
                overlap_stats[key].append(val["jaccard"])
    if overlap_stats:
        print(f"\n{'Overlap':35s} | {'Mean J':>6s} | {'Min':>5s} | {'Max':>5s}")
        print("─" * 58)
        for key in sorted(overlap_stats.keys()):
            vals = overlap_stats[key]
            mean_j = sum(vals) / len(vals)
            print(f"{key:35s} | {mean_j:>6.3f} | {min(vals):>5.3f} | {max(vals):>5.3f}")


# ── Main Benchmark Runner ────────────────────────────────────────────────────

def run_benchmark(
    lance_dir: str = "",
    table_name: str = "neurosurgery_v4",
    queries: Optional[List[dict]] = None,
    chromadb_only: bool = False,
    lance_only: bool = False,
    rerankers: Optional[List[str]] = None,
) -> List[dict]:
    """Run the full benchmark suite.

    Returns a list of per-query result dicts.
    """
    queries = queries or DEFAULT_QUERIES
    if rerankers is None:
        rerankers = ["bge-reranker-base", "minilm-l6", "jina-tiny"]

    all_results = []
    total = len(queries)

    for idx, q in enumerate(queries, 1):
        print_query_header(q, idx, total)
        entry = {"query": q, "results": {}, "overlaps": {}}

        # A: ChromaDB baseline
        if not lance_only:
            chromadb_result = run_chromadb_baseline(q["query"])
            entry["results"]["chromadb_baseline"] = chromadb_result
            print_result_row("ChromaDB+bge-reranker", chromadb_result)

        # B-D: LanceDB with each reranker
        if not chromadb_only and lance_dir:
            for reranker_key in rerankers:
                lance_result = run_lancedb_retrieval(
                    query=q["query"],
                    lance_dir=lance_dir,
                    table_name=table_name,
                    reranker_key=reranker_key,
                )
                result_key = f"lancedb_{reranker_key}"
                entry["results"][result_key] = lance_result
                print_result_row(f"Lance+{reranker_key}", lance_result)

        # Compute overlaps (silent — only shown in aggregate summary)
        chromadb_fps = entry["results"].get("chromadb_baseline", {}).get("hit_fingerprints", [])
        if chromadb_fps:
            for key, result in entry["results"].items():
                if key.startswith("lancedb_") and result.get("status") == "ok":
                    lance_fps = result.get("hit_fingerprints", [])
                    overlap = compute_hit_overlap(chromadb_fps, lance_fps)
                    entry["overlaps"][f"chromadb_vs_{key}"] = overlap

        # Cross-reranker overlap on LanceDB
        lance_keys = [k for k in entry["results"] if k.startswith("lancedb_")]
        for i, k1 in enumerate(lance_keys):
            for k2 in lance_keys[i + 1:]:
                r1 = entry["results"][k1]
                r2 = entry["results"][k2]
                if r1.get("status") == "ok" and r2.get("status") == "ok":
                    overlap = compute_hit_overlap(
                        r1.get("hit_fingerprints", []),
                        r2.get("hit_fingerprints", []),
                    )
                    overlap_key = f"{k1}_vs_{k2}"
                    entry["overlaps"][overlap_key] = overlap

        all_results.append(entry)

    return all_results


def _load_existing_results(output_path: str) -> dict:
    """Load previously saved phase results for merging."""
    p = Path(output_path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _merge_phase_results(existing: dict, new_results: list, phase_label: str) -> list:
    """Merge new phase results into existing per-query entries.

    Each query entry accumulates results from all phases under its 'results' dict.
    """
    if not existing or "results" not in existing:
        return new_results

    # Index existing results by query id
    existing_by_id = {}
    for entry in existing["results"]:
        qid = entry.get("query", {}).get("id", "")
        if qid:
            existing_by_id[qid] = entry

    merged = []
    for new_entry in new_results:
        qid = new_entry.get("query", {}).get("id", "")
        if qid in existing_by_id:
            # Merge: add new backends into existing entry
            old = existing_by_id.pop(qid)
            old["results"].update(new_entry.get("results", {}))
            old["overlaps"].update(new_entry.get("overlaps", {}))
            merged.append(old)
        else:
            merged.append(new_entry)

    # Append any remaining old entries not in new set
    for entry in existing_by_id.values():
        merged.append(entry)

    return merged


# ── Phase definitions ──────────────────────────────────────────────────────
PHASE_CONFIG = {
    1: {"label": "ChromaDB baseline",        "chromadb_only": True,  "lance_only": False, "rerankers": []},
    2: {"label": "LanceDB+bge-reranker-base", "chromadb_only": False, "lance_only": True,  "rerankers": ["bge-reranker-base"]},
    3: {"label": "LanceDB+minilm-l6",         "chromadb_only": False, "lance_only": True,  "rerankers": ["minilm-l6"]},
    4: {"label": "LanceDB+jina-tiny",          "chromadb_only": False, "lance_only": True,  "rerankers": ["jina-tiny"]},
    5: {"label": "LanceDB+minilm-l4",          "chromadb_only": False, "lance_only": True,  "rerankers": ["minilm-l4"]},
}


def main():
    parser = argparse.ArgumentParser(
        description="RAG Benchmark: ChromaDB vs LanceDB + Reranker Shootout",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--lance-dir", default="",
                        help="Path to LanceDB directory (required for LanceDB tests)")
    parser.add_argument("--table", default="neurosurgery_v4",
                        help="LanceDB table name")
    parser.add_argument("--queries", default="",
                        help="Path to custom queries JSON file")
    parser.add_argument("--chromadb-only", action="store_true",
                        help="Run ChromaDB baseline only (no LanceDB needed)")
    parser.add_argument("--lance-only", action="store_true",
                        help="Run LanceDB tests only (skip ChromaDB)")
    parser.add_argument("--rerankers", nargs="+",
                        default=["bge-reranker-base", "minilm-l6"],
                        choices=["bge-reranker-base", "minilm-l6", "minilm-l4", "jina-tiny"],
                        help="Reranker models to test")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4, 5],
                        help="Run a single phase (1=ChromaDB, 2=Lance+BGE, 3=Lance+MiniLM, 4=Lance+Jina). "
                             "Each phase runs in isolation and merges into the same output file.")
    parser.add_argument("--output", default="",
                        help="Output path for JSON results (default: auto-generated)")
    args = parser.parse_args()

    # Phase mode: override flags from PHASE_CONFIG
    if args.phase:
        pcfg = PHASE_CONFIG[args.phase]
        args.chromadb_only = pcfg["chromadb_only"]
        args.lance_only = pcfg["lance_only"]
        if pcfg["rerankers"]:
            args.rerankers = pcfg["rerankers"]
        # Use a fixed output path so phases merge into one file
        if not args.output:
            args.output = str(BASE_DIR / "data" / "Sessions" / "benchmark_phased_results.json")
        print(f"Phase {args.phase}: {pcfg['label']}")

    # Validate arguments
    if not args.chromadb_only and not args.lance_dir:
        print("ERROR: --lance-dir is required for LanceDB tests. "
              "Use --chromadb-only to run baseline only.")
        sys.exit(1)

    # Load custom queries if provided
    queries = None
    if args.queries:
        queries_path = Path(args.queries)
        if not queries_path.exists():
            print(f"ERROR: Queries file not found: {args.queries}")
            sys.exit(1)
        queries = json.loads(queries_path.read_text())

    n_queries = len(queries or DEFAULT_QUERIES)
    backends = []
    if not args.lance_only:
        backends.append("ChromaDB")
    if not args.chromadb_only and args.lance_dir:
        backends.extend([f"Lance+{r}" for r in args.rerankers])
    print(f"Benchmark: {n_queries} queries x {len(backends)} backends ({', '.join(backends)})")

    results = run_benchmark(
        lance_dir=args.lance_dir,
        table_name=args.table,
        queries=queries,
        chromadb_only=args.chromadb_only,
        lance_only=args.lance_only,
        rerankers=args.rerankers,
    )

    # Save results (merge with existing phases if applicable)
    output_path = args.output or str(
        BASE_DIR / "data" / "Sessions"
        / f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Load existing phase data for merging
    existing = _load_existing_results(output_path) if args.phase else {}
    if existing:
        merged_results = _merge_phase_results(existing, results, PHASE_CONFIG[args.phase]["label"])
    else:
        merged_results = results

    # Print summary (shows all phases accumulated so far)
    print_summary_table(merged_results)

    # Build output
    output_data = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "lance_dir": args.lance_dir,
            "table": args.table,
            "rerankers": args.rerankers,
            "chromadb_only": args.chromadb_only,
            "lance_only": args.lance_only,
            "n_queries": len(queries or DEFAULT_QUERIES),
            "phase": args.phase,
            "phases_completed": (existing.get("config", {}).get("phases_completed", [])
                                 + ([args.phase] if args.phase else [])),
        },
        "results": merged_results,
    }

    # Strip large fields but preserve top_5_scores and text previews for quality comparison
    for entry in output_data["results"]:
        for key, result in entry.get("results", {}).items():
            result.pop("hit_fingerprints", None)
            result.pop("traceback", None)
            # top_5_scores are kept for quality/accuracy analysis

    Path(output_path).write_text(json.dumps(output_data, indent=2, default=str))
    print(f"\nSaved: {output_path}")
    if args.phase and args.phase < 4:
        next_p = args.phase + 1
        print(f"Next: python3 scripts/benchmark_rag.py --phase {next_p} --lance-dir {args.lance_dir}")


if __name__ == "__main__":
    main()
