"""Batched multi-topic orchestration for the textbook RAG pipeline.

The scalar functions in :mod:`retrieval.pipeline` remain the compatibility
surface.  This module amortizes model work across independent topics:

1. one BGE-M3 query-encoding pass;
2. bounded concurrent LanceDB dense/FTS searches;
3. one cross-encoder reranking pass;
4. one BGE-M3 heading/entity disambiguation pass;
5. one cross-encoder axis-distillation pass when needed.
"""

from __future__ import annotations

import copy
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Iterable

from . import pipeline


BATCH_MAX_QUERIES = max(
    1,
    int(os.environ.get("NEURO_RAG_BATCH_MAX_QUERIES", "32")),
)
BATCH_SEARCH_WORKERS = max(
    1,
    int(os.environ.get("NEURO_RAG_SEARCH_WORKERS", "4")),
)


def _clean_queries(queries: Iterable[str]) -> list[str]:
    cleaned = [str(query).strip() for query in queries]
    if not cleaned or any(not query for query in cleaned):
        raise ValueError("retrieve_many requires one or more non-empty queries")
    if len(cleaned) > BATCH_MAX_QUERIES:
        raise ValueError(
            f"retrieve_many accepts at most {BATCH_MAX_QUERIES} queries per batch"
        )
    return cleaned


def _candidate_pool(
    dense_hits: list,
    fts_hits: list,
    *,
    min_similarity: float,
) -> tuple[list, dict[str, int]]:
    fused = pipeline._apply_rrf(dense_hits, fts_hits)
    candidates = [
        hit
        for hit in fused
        if hit.get("similarity", 0.0) >= min_similarity
    ]
    below_threshold = len(fused) - len(candidates)
    if not candidates and fused:
        candidates = fused[:10]

    pre_hygiene_count = len(candidates)
    candidates = [
        hit
        for hit in candidates
        if not pipeline._is_low_value_retrieval_hit(hit)
    ]
    refs_dropped = pre_hygiene_count - len(candidates)
    before_cap = len(candidates)
    if pipeline.PRE_RERANK_MAX_CANDIDATES > 0:
        candidates = candidates[:pipeline.PRE_RERANK_MAX_CANDIDATES]
    return candidates, {
        "fused_candidates": len(fused),
        "below_threshold": below_threshold,
        "refs_dropped": refs_dropped,
        "pre_rerank_candidates": before_cap,
        "pre_rerank_capped": max(0, before_cap - len(candidates)),
    }


def _search_many(
    table,
    queries: list[str],
    query_vectors: list[list[float]],
    n_results: int,
) -> tuple[list[tuple[list, list]], list[dict[str, float]], float]:
    """Run independent Lance searches concurrently with deterministic ordering."""
    started = time.perf_counter()
    dense_results: list[tuple[list, float] | None] = [None] * len(queries)
    fts_results: list[tuple[list, float] | None] = [None] * len(queries)
    workers = min(BATCH_SEARCH_WORKERS, max(1, len(queries) * 2))

    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="rag-search",
    ) as executor:
        futures = {}
        for index, (query, vector) in enumerate(zip(queries, query_vectors, strict=True)):
            futures[
                executor.submit(
                    pipeline._dense_search,
                    table,
                    vector,
                    n_results,
                )
            ] = ("dense", index)
            futures[
                executor.submit(
                    pipeline._sparse_search_fts,
                    table,
                    query,
                    n_results,
                )
            ] = ("fts", index)

        for future in as_completed(futures):
            channel, index = futures[future]
            value = future.result()
            if channel == "dense":
                dense_results[index] = value
            else:
                fts_results[index] = value

    grouped: list[tuple[list, list]] = []
    timings: list[dict[str, float]] = []
    for dense, fts in zip(dense_results, fts_results, strict=True):
        if dense is None or fts is None:
            raise RuntimeError("incomplete concurrent LanceDB search result")
        grouped.append((dense[0], fts[0]))
        timings.append({"dense_ms": dense[1], "fts_ms": fts[1]})
    wall_ms = round((time.perf_counter() - started) * 1000, 2)
    return grouped, timings, wall_ms


def _rerank_many(
    queries: list[str],
    candidate_groups: list[list],
    reranker_key: str,
) -> tuple[list[list], float]:
    started = time.perf_counter()
    reranker, _ = pipeline._get_reranker(reranker_key)
    if reranker is None:
        return (
            [
                pipeline._rerank_hits_lexical(query, candidates)
                for query, candidates in zip(queries, candidate_groups, strict=True)
            ],
            0.0,
        )

    pairs: list[list[str]] = []
    ranges: list[tuple[int, int]] = []
    for query, candidates in zip(queries, candidate_groups, strict=True):
        start = len(pairs)
        pairs.extend(
            [query, hit.get("text", "")[:2200]]
            for hit in candidates
        )
        ranges.append((start, len(pairs)))

    if not pairs:
        return ([[] for _ in queries], 0.0)
    try:
        raw_scores = reranker.predict(
            pairs,
            batch_size=pipeline.RERANK_BATCH_SIZE,
        )
        scores = [float(score) for score in raw_scores]
    except Exception:
        return (
            [
                pipeline._rerank_hits_lexical(query, candidates)
                for query, candidates in zip(queries, candidate_groups, strict=True)
            ],
            round((time.perf_counter() - started) * 1000, 2),
        )

    grouped: list[list] = []
    for candidates, (start, end) in zip(candidate_groups, ranges, strict=True):
        reranked = pipeline._apply_rerank_scores(
            candidates,
            scores[start:end],
        )
        grouped.append(
            [
                hit
                for hit in reranked
                if not hit.get("is_reference_chunk")
                and not pipeline._is_low_value_retrieval_hit(hit)
            ]
        )
    return grouped, round((time.perf_counter() - started) * 1000, 2)


def _entity_filter_many(
    queries: list[str],
    reranked_groups: list[list],
) -> tuple[list[list], list[tuple[int, int]], float]:
    started = time.perf_counter()
    output: list[list | None] = [None] * len(queries)
    prepared_groups: list[list | None] = [None] * len(queries)
    semantic_specs: list[tuple[list, str]] = []
    semantic_assignments: list[tuple[int, list[int]]] = []
    entity_counts: list[tuple[int, int]] = [(0, 0)] * len(queries)

    for index, (query, reranked) in enumerate(
        zip(queries, reranked_groups, strict=True)
    ):
        before = len(reranked)
        entities = pipeline._extract_primary_entities(query)
        if not entities or not reranked:
            output[index] = reranked
            entity_counts[index] = (before, before)
            continue
        prepared, entity_phrase = pipeline._prepare_entity_aware_filtering(
            reranked,
            query,
            entities,
        )
        prepared_groups[index] = prepared
        semantic_positions: list[int] = []
        for hit_index, hit in enumerate(prepared):
            obvious_match = (
                hit.get("_kw_heading_match", False)
                and hit.get("_entity_ratio", 0.0) >= 1.0
            )
            if obvious_match:
                hit["heading_entity_sim"] = 1.0
                continue
            if (
                pipeline.ENTITY_SEMANTIC_MAX_CANDIDATES == 0
                or len(semantic_positions)
                < pipeline.ENTITY_SEMANTIC_MAX_CANDIDATES
            ):
                semantic_positions.append(hit_index)
                continue
            # Lower-ranked overflow receives a conservative lexical proxy.
            # This bounds BGE work without treating ambiguous hits as clean.
            if hit.get("_kw_text_match"):
                hit["heading_entity_sim"] = 0.72
            elif hit.get("_kw_heading_match"):
                hit["heading_entity_sim"] = 0.62
            else:
                hit["heading_entity_sim"] = 0.45
        if semantic_positions:
            semantic_specs.append((
                [prepared[position] for position in semantic_positions],
                entity_phrase,
            ))
            semantic_assignments.append((index, semantic_positions))
        else:
            output[index] = pipeline._finalize_entity_aware_filtering(prepared)
            entity_counts[index] = (before, len(output[index]))

    if semantic_specs:
        scored_groups, _ = pipeline._compute_heading_entity_similarity_many(
            semantic_specs
        )
        for (index, positions), scored in zip(
            semantic_assignments,
            scored_groups,
            strict=True,
        ):
            prepared = prepared_groups[index] or []
            for position, scored_hit in zip(positions, scored, strict=True):
                prepared[position] = scored_hit
            filtered = pipeline._finalize_entity_aware_filtering(prepared)
            output[index] = filtered
            before = len(reranked_groups[index])
            entity_counts[index] = (before, len(filtered))

    finalized = [
        group if group is not None else []
        for group in output
    ]
    return (
        finalized,
        entity_counts,
        round((time.perf_counter() - started) * 1000, 2),
    )


def _distill_many(
    results: list[dict[str, Any]],
    reranker_key: str,
) -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    pending_specs: list[tuple[list[str], list]] = []
    pending_indices: list[int] = []

    for index, result in enumerate(results):
        query = result["query"]
        hits = result.get("hits", [])
        axes = pipeline._decompose_axes(query)
        result["axes"] = axes
        if not hits:
            result["distilled"] = False
            continue
        if len(axes) <= 1:
            for hit in hits:
                hit["axis_scores"] = {
                    axes[0]: hit.get("rank_score", 0.5)
                }
                hit["primary_axis"] = axes[0]
                hit["distilled_text"] = pipeline._select_text_level(hit)
            result["distilled"] = False
            continue

        if len(hits) <= pipeline.CONTEXT_MAX_PASSAGES:
            coverage = pipeline._keyword_axis_coverage(hits, axes)
            scored = pipeline._assign_axes_by_keyword(hits, axes)
            budgeted = pipeline._budget_passages(scored, axes)
            for hit in budgeted:
                hit["distilled_text"] = pipeline._select_text_level(hit)
            result["hits"] = budgeted
            result["distilled"] = True
            result["distill_mode"] = "keyword_bounded_pool"
            result["axis_coverage"] = coverage
            result["axis_coverage_gaps"] = [
                axis
                for axis, count in coverage.items()
                if count == 0
            ]
            # With an already bounded pool, CE axis scoring cannot introduce
            # new evidence.  Preserve the hit set and avoid a second expensive
            # inference pass; callers can use the explicit gap list for a
            # targeted follow-up batch.
            continue

        pending_specs.append((axes, hits))
        pending_indices.append(index)

    if pending_specs:
        reranker, _ = pipeline._get_reranker(reranker_key)
        if reranker is None:
            for index in pending_indices:
                result = results[index]
                axes = result["axes"]
                for hit in result["hits"]:
                    hit["axis_scores"] = {axis: 0.5 for axis in axes}
                    hit["primary_axis"] = axes[0]
                    hit["distilled_text"] = pipeline._select_text_level(hit)
                result["distilled"] = False
        else:
            scored_groups, _ = pipeline._score_passage_groups_by_axis(
                pending_specs,
                reranker,
            )
            for index, scored in zip(
                pending_indices,
                scored_groups,
                strict=True,
            ):
                result = results[index]
                axes = result["axes"]
                scored = pipeline._apply_distill_entity_penalties(
                    scored,
                    result["query"],
                )
                budgeted = pipeline._budget_passages(scored, axes)
                for hit in budgeted:
                    hit["distilled_text"] = pipeline._select_text_level(hit)
                result["hits"] = budgeted
                result["distilled"] = True
                result["distill_mode"] = "cross_encoder_batch"

    return results, round((time.perf_counter() - started) * 1000, 2)


def _retrieve_unique(
    queries: list[str],
    *,
    lance_dir: str,
    table_name: str,
    n_results: int,
    min_similarity: float,
    reranker_key: str,
    use_parent_expansion: bool,
    distill: bool,
    augment: bool,
    max_passages: int,
) -> list[dict[str, Any]]:
    total_started = time.perf_counter()
    table = pipeline._get_lance_table(lance_dir, table_name)
    vectors, encode_ms = pipeline._encode_queries(queries)
    searched, search_timings, search_wall_ms = _search_many(
        table,
        queries,
        vectors,
        n_results,
    )

    candidate_groups: list[list] = []
    retrieval_meta: list[dict[str, int]] = []
    rrf_started = time.perf_counter()
    for query, dense_fts in zip(queries, searched, strict=True):
        candidates, meta = _candidate_pool(
            dense_fts[0],
            dense_fts[1],
            min_similarity=min_similarity,
        )
        before_roles = len(candidates)
        candidates = [
            hit for hit in candidates
            if pipeline.provenance.source_allowed_for_query(hit.get("source_key"), query)
        ]
        meta["source_role_dropped"] = before_roles - len(candidates)
        candidate_groups.append(candidates)
        retrieval_meta.append(meta)
    rrf_ms = round((time.perf_counter() - rrf_started) * 1000, 2)

    reranked_groups, rerank_ms = _rerank_many(
        queries,
        candidate_groups,
        reranker_key,
    )
    filtered_groups, entity_counts, entity_ms = _entity_filter_many(
        queries,
        reranked_groups,
    )

    expand_started = time.perf_counter()
    expanded_groups: list[list] = []
    per_query_expand_ms: list[float] = []
    for query, hits in zip(queries, filtered_groups, strict=True):
        started = time.perf_counter()
        if use_parent_expansion and hits:
            expanded = pipeline._expand_with_parent_text(hits, query)
        else:
            expanded = hits[:pipeline.CONTEXT_MAX_PASSAGES]
        expanded_groups.append(expanded)
        per_query_expand_ms.append(
            round((time.perf_counter() - started) * 1000, 2)
        )
    expand_ms = round((time.perf_counter() - expand_started) * 1000, 2)

    results: list[dict[str, Any]] = []
    for index, query in enumerate(queries):
        dense_hits, fts_hits = searched[index]
        final_hits = expanded_groups[index]
        before_entity, after_entity = entity_counts[index]
        source_keys = {
            hit.get("source_key", "")
            for hit in final_hits
            if hit.get("source_key")
        }
        meta = retrieval_meta[index]
        results.append({
            "query": query,
            "reranker": reranker_key,
            "provenance": pipeline.provenance.retrieval_provenance(
                route="batch",
                reranker_key=reranker_key,
                reranker_model=pipeline.RERANKER_MODELS.get(reranker_key, reranker_key),
                embedding_model=pipeline.BGE_M3_MODEL_ID,
                table=table,
            ),
            "hits": final_hits,
            "_reranked_pool": list(filtered_groups[index]),
            "latency": {
                "encode_ms": round(encode_ms / len(queries), 2),
                "dense_ms": search_timings[index]["dense_ms"],
                "fts_ms": search_timings[index]["fts_ms"],
                "rrf_ms": round(rrf_ms / len(queries), 2),
                "rerank_ms": round(rerank_ms / len(queries), 2),
                "entity_ms": round(entity_ms / len(queries), 2),
                "expand_ms": per_query_expand_ms[index],
            },
            "metadata": {
                "dense_candidates": len(dense_hits),
                "fts_candidates": len(fts_hits),
                **meta,
                "pre_rerank_cap": pipeline.PRE_RERANK_MAX_CANDIDATES,
                "after_rerank": before_entity,
                "after_entity_filter": after_entity,
                "final_passages": len(final_hits),
                "unique_sources": len(source_keys),
                "source_books": sorted(source_keys),
            },
        })

    distill_ms = 0.0
    if distill:
        results, distill_ms = _distill_many(results, reranker_key)

    augment_started = time.perf_counter()
    if augment:
        for result in results:
            candidates = result.get("_reranked_pool") or []
            if candidates and result.get("hits"):
                result["hits"], result["augment_ce"] = pipeline._quality_augment(
                    result["query"],
                    result["hits"],
                    candidates,
                )
    if max_passages > 0:
        for result in results:
            result["hits"] = result["hits"][:max_passages]
    augment_ms = round((time.perf_counter() - augment_started) * 1000, 2)
    total_ms = round((time.perf_counter() - total_started) * 1000, 2)
    shared = {
        "query_count": len(queries),
        "total_ms": total_ms,
        "encode_ms": encode_ms,
        "search_wall_ms": search_wall_ms,
        "rrf_ms": rrf_ms,
        "rerank_ms": rerank_ms,
        "entity_ms": entity_ms,
        "expand_ms": expand_ms,
        "distill_ms": distill_ms,
        "augment_ms": augment_ms,
        "search_workers": min(BATCH_SEARCH_WORKERS, max(1, len(queries) * 2)),
    }
    for result in results:
        result["batch"] = dict(shared)
        result["latency"]["distill_ms"] = round(distill_ms / len(queries), 2)
        result["latency"]["augment_ms"] = round(augment_ms / len(queries), 2)
        result["latency"]["total_ms"] = round(total_ms / len(queries), 2)
        result["latency"]["batch_total_ms"] = total_ms
        result["metadata"]["final_passages"] = len(result["hits"])
        source_keys = {
            hit.get("source_key", "")
            for hit in result["hits"]
            if hit.get("source_key")
        }
        result["metadata"]["unique_sources"] = len(source_keys)
        result["metadata"]["source_books"] = sorted(source_keys)
    return results


def retrieve_many(
    queries: Iterable[str],
    *,
    lance_dir: str = "",
    table_name: str = "",
    n_results: int = pipeline.DEFAULT_N_RESULTS,
    min_similarity: float = pipeline.DEFAULT_MIN_SIMILARITY,
    reranker_key: str = pipeline.DEFAULT_RERANKER,
    use_parent_expansion: bool = True,
    distill: bool = True,
    augment: bool = True,
    max_passages: int = 0,
) -> list[dict[str, Any]]:
    """Retrieve several independent topics with shared model inference.

    Exact duplicate queries are evaluated once and copied back to their
    original positions.  Topic order is stable.
    """
    cleaned = _clean_queries(queries)
    unique_queries = list(dict.fromkeys(cleaned))
    unique_results = _retrieve_unique(
        unique_queries,
        lance_dir=lance_dir,
        table_name=table_name,
        n_results=n_results,
        min_similarity=min_similarity,
        reranker_key=reranker_key,
        use_parent_expansion=use_parent_expansion,
        distill=distill,
        augment=augment,
        max_passages=max(0, max_passages),
    )
    by_query = {
        result["query"]: result
        for result in unique_results
    }
    return [copy.deepcopy(by_query[query]) for query in cleaned]


def build_batch_packet(
    results: list[dict[str, Any]],
    *,
    include_text: bool = True,
) -> dict[str, Any]:
    """Build a versioned, deterministic JSON packet for agent consumption."""
    topics = []
    for topic_index, result in enumerate(results, 1):
        hits = []
        for hit in result.get("hits", []):
            meta = hit.get("metadata", {}) or {}
            row = {
                "child_id": hit.get("child_id"),
                "citation": hit.get("citation"),
                "source_key": hit.get("source_key"),
                "page_start": meta.get("page_start"),
                "rank_score": hit.get("rank_score"),
                "primary_axis": hit.get("primary_axis"),
            }
            if include_text:
                row["text"] = (
                    hit.get("distilled_text")
                    or hit.get("text")
                    or ""
                )
            hits.append(row)
        topics.append({
            "topic_id": f"T{topic_index:02d}",
            "query": result["query"],
            "axes": result.get("axes", []),
            "latency": result.get("latency", {}),
            "metadata": result.get("metadata", {}),
            "hits": hits,
        })
    batch_meta = results[0].get("batch", {}) if results else {}
    return {
        "type": "rag_batch",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_count": len(results),
        "batch": batch_meta,
        "topics": topics,
    }


def build_batch_source_cards_jsonl(
    results: list[dict[str, Any]],
    *,
    max_takeaways: int = 8,
) -> str:
    """Serialize many topics without repeating query metadata on every card."""
    topic_rows: list[dict[str, Any]] = []
    card_rows: list[dict[str, Any]] = []
    for topic_index, result in enumerate(results, 1):
        topic_id = f"T{topic_index:02d}"
        source_cards = pipeline.build_source_cards_jsonl(
            result,
            card_prefix=topic_id,
            max_takeaways=max_takeaways,
            compact_schema=True,
        )
        parsed = [
            json.loads(line)
            for line in source_cards.splitlines()
            if line.strip()
        ]
        cards = parsed[1:]
        topic_rows.append({
            "type": "topic_manifest",
            "topic_id": topic_id,
            "query": result["query"],
            "axes": result.get("axes", []),
            "card_count": len(cards),
            "source_count": result.get("metadata", {}).get("unique_sources", 0),
        })
        for card_index, card in enumerate(cards, 1):
            card["type"] = "source_card"
            card["topic_id"] = topic_id
            card["card_id"] = f"{topic_id}-C{card_index:02d}"
            card_rows.append(card)

    header = {
        "type": "batch_source_card_manifest",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic_count": len(results),
        "card_count": len(card_rows),
        "format": "jsonl",
        "schema": "compact",
        "source_type": "textbook_rag_full",
        "provenance": (
            results[0].get("provenance")
            if results
            else pipeline.provenance.retrieval_provenance(
                route="batch",
                embedding_model=pipeline.BGE_M3_MODEL_ID,
            )
        ),
    }
    rows = [header, *topic_rows, *card_rows]
    return "\n".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        for row in rows
    ) + "\n"
