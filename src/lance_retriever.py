"""
LanceDB Retrieval Module — Primary retrieval engine for agentic-neuro.

Pipeline: BGE-M3 encode → Dense search + FTS → RRF fusion → MiniLM-L6 rerank
          → Reference filtering → Parent-child expansion
          → Adaptive Context Distillation (axis decomposition + budgeting) → Output

CLI:
    python3 src/lance_retriever.py compare "query" [--append] [--output path] [--no-distill]
    python3 src/lance_retriever.py compare_multi "sq1" "sq2" "sq3" [--no-distill]
    python3 src/lance_retriever.py list_textbooks
    python3 src/lance_retriever.py search "query" [--json]
    python3 src/lance_retriever.py digest [--input path] [--output path]
"""

import json
import math
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ── Configuration ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent

# LanceDB defaults
DEFAULT_LANCE_DIR = os.environ.get(
    "NEURO_LANCE_DIR",
    "/Users/gabrielreyes/agentic-neuro",
)
DEFAULT_LANCE_TABLE = os.environ.get("NEURO_LANCE_TABLE", "neurosurgery_v4")

# Retrieval parameters
DEFAULT_MIN_SIMILARITY = 0.35
DEFAULT_N_RESULTS = 35
RERANKER_SCORE_FLOOR = float(os.environ.get("NEURO_RERANKER_SCORE_FLOOR", "0.15"))

# Context limits
CONTEXT_MAX_PASSAGES = int(os.environ.get("NEURO_CONTEXT_MAX_PASSAGES", "8"))
CONTEXT_MIN_SOURCES = int(os.environ.get("NEURO_CONTEXT_MIN_SOURCES", "3"))

# Reranker model registry
RERANKER_MODELS = {
    "bge-reranker-base": "BAAI/bge-reranker-base",
    "minilm-l6": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "minilm-l4": "cross-encoder/ms-marco-MiniLM-L-4-v2",
}
DEFAULT_RERANKER = "minilm-l6"

# Medical stopwords for keyword extraction
STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "has", "have", "been", "some", "them",
    "than", "its", "over", "such", "that", "this", "with", "will", "each",
    "from", "they", "were", "which", "their", "what", "there", "when", "make",
    "like", "into", "also", "most", "more", "other", "these", "then", "does",
    "may", "should", "could", "would", "about", "after", "before", "during",
    "between", "through", "being", "those", "where", "very", "well", "much",
    "many", "only", "both", "same", "often", "usually", "typically",
}

# Regex for splitting source blocks in scratch_context.md (for --append merge)
_SOURCE_BLOCK_RE = re.compile(r'^\[([A-Za-z][A-Za-z _]*)\]\s*', re.MULTILINE)


# ── Lazy-loaded singletons ──────────────────────────────────────────────────

_LANCE_DB = None
_LANCE_TABLE = None
_EMBEDDING_MODEL = None
_RERANKER_CACHE: Dict[str, Any] = {}


def _get_lance_table(lance_dir: str = "", table_name: str = ""):
    """Open LanceDB connection and table (lazy, cached)."""
    global _LANCE_DB, _LANCE_TABLE
    lance_dir = lance_dir or DEFAULT_LANCE_DIR
    table_name = table_name or DEFAULT_LANCE_TABLE

    if _LANCE_TABLE is not None:
        return _LANCE_TABLE

    import lancedb
    _LANCE_DB = lancedb.connect(lance_dir)
    _LANCE_TABLE = _LANCE_DB.open_table(table_name)
    return _LANCE_TABLE


def _get_embedding_model():
    """Load BGE-M3 for query encoding (dense + sparse)."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        from FlagEmbedding import BGEM3FlagModel
        _EMBEDDING_MODEL = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    return _EMBEDDING_MODEL


def _get_reranker(model_key: str = DEFAULT_RERANKER):
    """Load a cross-encoder reranker by key. Cached per model_key."""
    if model_key in _RERANKER_CACHE:
        return _RERANKER_CACHE[model_key], model_key

    model_id = RERANKER_MODELS.get(model_key, model_key)
    try:
        from sentence_transformers import CrossEncoder
        import torch
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        ce = CrossEncoder(model_id, device=device)
        ce.predict([["warmup", "warmup"]])
        _RERANKER_CACHE[model_key] = ce
        return ce, model_key
    except Exception as e:
        print(f"[WARN] Failed to load reranker '{model_id}': {e}")
        _RERANKER_CACHE[model_key] = None
        return None, model_key


# ── Utility functions ────────────────────────────────────────────────────────

def _extract_keywords(text: str) -> set:
    tokens = re.findall(r"[a-zA-Z]{3,}", (text or "").lower())
    return {t for t in tokens if t not in STOPWORDS}


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _content_hash(text: str) -> str:
    return (text or "").strip().lower()[:220]


def _is_reference_chunk(text: str) -> bool:
    """Detect bibliography/citation-list chunks."""
    if not text or len(text) < 100:
        return False
    text_lower = text.lower()
    total_chars = len(text)

    et_al_count = text_lower.count("et al")
    et_al_density = et_al_count / (total_chars / 1000.0)
    numbered_refs = len(re.findall(r'(?:^|\n)\s*\d{1,3}\.\s+[A-Z][a-z]', text))
    journal_patterns = len(re.findall(r'\d{4};\s*\d+', text))
    journal_patterns += len(re.findall(r'\d+:\d+-\d+', text))
    semicolons = text.count(';')

    score = 0
    if et_al_density > 3.0:
        score += 3
    elif et_al_density > 1.5:
        score += 2
    elif et_al_density > 0.5:
        score += 1
    if numbered_refs >= 5:
        score += 3
    elif numbered_refs >= 3:
        score += 2
    if journal_patterns >= 6:
        score += 2
    elif journal_patterns >= 3:
        score += 1
    if semicolons > 10 and et_al_count > 2:
        score += 1
    return score >= 4


def _format_citation(row: dict) -> str:
    """Build a human-readable citation from LanceDB row metadata."""
    book = row.get("source_book", "Unknown")
    chapter = row.get("chapter_title", "")
    heading = row.get("heading", "")
    page = row.get("page_start")
    parts = [book]
    if chapter:
        parts.append(f"Ch: {chapter}")
    if heading and heading != chapter:
        parts.append(f"§ {heading}")
    if page:
        parts.append(f"p.{page}")
    return " — ".join(parts)


# ── Core retrieval ───────────────────────────────────────────────────────────

def _encode_query(query: str) -> Tuple[List[float], Dict[int, float]]:
    """Encode query with BGE-M3 → (dense_vec, sparse_weights)."""
    model = _get_embedding_model()
    out = model.encode(
        [query], batch_size=1, max_length=512,
        return_dense=True, return_sparse=True,
    )
    dense = out["dense_vecs"][0].astype(np.float32).tolist()
    sparse = out["lexical_weights"][0]
    return dense, sparse


def _dense_search(table, query_vec: List[float], n_results: int = DEFAULT_N_RESULTS):
    """Vector similarity search on LanceDB dense_vec column."""
    t0 = time.perf_counter()
    results = (
        table.search(query_vec, vector_column_name="dense_vec")
        .metric("cosine")
        .limit(n_results)
        .to_list()
    )
    ms = round((time.perf_counter() - t0) * 1000, 2)

    hits = []
    for row in results:
        dist = row.get("_distance", 1.0)
        similarity = 1.0 - (dist / 2.0)
        hits.append(_row_to_hit(row, similarity))
    return hits, ms


def _sparse_search_fts(table, query_text: str, n_results: int = DEFAULT_N_RESULTS):
    """Full-text search on child_text column as the sparse retrieval channel."""
    t0 = time.perf_counter()
    try:
        results = table.search(query_text, query_type="fts").limit(n_results).to_list()
    except Exception:
        return [], round((time.perf_counter() - t0) * 1000, 2)

    ms = round((time.perf_counter() - t0) * 1000, 2)
    hits = []
    for row in results:
        fts_score = float(row.get("_score", 0.0))
        # Normalize BM25 scores to [0,1] using sigmoid-like mapping
        # fts_score=2 → 0.67, fts_score=5 → 0.83, fts_score=10 → 0.91
        similarity = fts_score / (fts_score + 1.0) if fts_score > 0 else 0.0
        hits.append(_row_to_hit(row, similarity))
    return hits, ms


def _row_to_hit(row: dict, similarity: float) -> dict:
    """Convert a LanceDB row to a standardized hit dict."""
    return {
        "text": row.get("child_text", ""),
        "parent_text": row.get("parent_text", ""),
        "similarity": round(similarity, 4),
        "metadata": {
            "source_book": row.get("source_book", ""),
            "source_path": row.get("source_book", ""),
            "chapter_title": row.get("chapter_title", ""),
            "heading": row.get("heading", ""),
            "section_path": row.get("section_path", ""),
            "page_start": row.get("page_start"),
            "page_end": row.get("page_end"),
            "chunk_index": row.get("child_index_in_parent", 0),
            "has_image": row.get("has_image", False),
            "has_table": row.get("has_table", False),
            "has_caption": row.get("has_caption", False),
            "item_types": row.get("item_types", ""),
            "subspecialty": row.get("subspecialty", ""),
            "noise_type": row.get("noise_type", "content"),
        },
        "citation": _format_citation(row),
        "source_key": row.get("source_book", "unknown"),
        "child_id": row.get("child_id", ""),
        "parent_id": row.get("parent_id", ""),
        "table_markdown": row.get("table_markdown", ""),
        "caption_text": row.get("caption_text", ""),
    }


# ── Fusion & Reranking ───────────────────────────────────────────────────────

def _apply_rrf(vector_hits: list, fts_hits: list, k: int = 60) -> list:
    """Reciprocal Rank Fusion."""
    scores = defaultdict(float)
    hit_map = {}

    for rank, hit in enumerate(vector_hits, start=1):
        key = _content_hash(hit["text"])
        scores[key] += 1.0 / (k + rank)
        hit_map[key] = hit

    for rank, hit in enumerate(fts_hits, start=1):
        key = _content_hash(hit["text"])
        scores[key] += 1.0 / (k + rank)
        if key not in hit_map:
            hit_map[key] = hit

    sorted_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    fused = []
    for key in sorted_keys:
        hit = dict(hit_map[key])
        hit["rrf_score"] = round(scores[key], 6)
        fused.append(hit)
    return fused


def _rerank_hits(query: str, hits: list, reranker_key: str = DEFAULT_RERANKER):
    """Cross-encoder reranking. Returns (reranked_hits, latency_ms)."""
    if not hits:
        return hits, 0.0

    ce, model_key = _get_reranker(reranker_key)
    if ce is None:
        return _rerank_hits_lexical(query, hits), 0.0

    t0 = time.perf_counter()
    try:
        doc_texts = [hit.get("text", "")[:2200] for hit in hits]
        pairs = [[query, doc] for doc in doc_texts]
        raw_scores = ce.predict(pairs, batch_size=32)
        scores = [float(s) for s in raw_scores]
    except Exception:
        return _rerank_hits_lexical(query, hits), 0.0

    ms = round((time.perf_counter() - t0) * 1000, 2)

    max_score = max(scores) if scores else 0
    min_score = min(scores) if scores else 0
    scores_are_sigmoid = (0 <= min_score and max_score <= 1.0)

    reranked = []
    for i, hit in enumerate(hits):
        enriched = dict(hit)
        sim = float(hit.get("similarity") or 0.0)
        ce_score = scores[i]
        sigmoid_ce = ce_score if scores_are_sigmoid else 1.0 / (1.0 + math.exp(-ce_score))
        rank_score = (0.2 * sim) + (0.8 * sigmoid_ce)

        enriched["ce_score"] = round(ce_score, 4)
        enriched["sigmoid_ce"] = round(sigmoid_ce, 4)
        enriched["rank_score"] = round(rank_score, 4)

        if _is_reference_chunk(hit.get("text", "")):
            enriched["rank_score"] = round(rank_score * 0.3, 4)
            enriched["is_reference_chunk"] = True

        reranked.append(enriched)

    reranked.sort(key=lambda x: (x.get("rank_score", 0.0), x.get("similarity", 0.0)), reverse=True)
    reranked = [h for h in reranked if h.get("sigmoid_ce", 1.0) >= RERANKER_SCORE_FLOOR]
    return reranked, ms


def _rerank_hits_lexical(query: str, hits: list) -> list:
    """Fallback lexical-overlap reranking."""
    q_terms = _extract_keywords(query)
    reranked = []
    for hit in hits:
        sim = float(hit.get("similarity") or 0.0)
        h_terms = _extract_keywords(hit.get("text", ""))
        overlap = len(q_terms & h_terms) / max(1, len(q_terms)) if q_terms else 0.0
        enriched = dict(hit)
        enriched["rank_score"] = round((0.7 * sim) + (0.3 * overlap), 4)
        reranked.append(enriched)
    reranked.sort(key=lambda x: x.get("rank_score", 0.0), reverse=True)
    return reranked


# ── Parent-child context expansion ───────────────────────────────────────────

def _expand_with_parent_text(hits: list) -> list:
    """Use stored parent_text instead of re-fetching adjacent chunks."""
    parent_groups: Dict[str, list] = defaultdict(list)
    orphans = []

    for hit in hits:
        pid = hit.get("parent_id", "")
        if pid:
            parent_groups[pid].append(hit)
        else:
            orphans.append(hit)

    expanded = []
    for parent_id, children in parent_groups.items():
        children.sort(key=lambda h: h.get("metadata", {}).get("chunk_index", 0))
        anchor = max(children, key=lambda h: h.get("rank_score", h.get("similarity", 0.0)))
        parent_text = anchor.get("parent_text", "") or anchor.get("text", "")

        enriched = dict(anchor)
        enriched["text_original"] = anchor["text"]
        enriched["text"] = parent_text
        enriched["context_expanded"] = True
        enriched["passage_tokens"] = _approx_tokens(parent_text)
        enriched["passage_chunks"] = len(children)
        enriched["cluster_hits"] = len(children)
        enriched["cluster_score"] = round(
            max(h.get("rank_score", h.get("similarity", 0.0)) for h in children), 4
        )
        expanded.append(enriched)

    expanded.extend(orphans)
    expanded.sort(
        key=lambda x: x.get("cluster_score", x.get("rank_score", x.get("similarity", 0.0))),
        reverse=True,
    )

    # Enforce passage limits and source diversity
    selected = []
    source_set = set()
    for hit in expanded:
        if len(selected) >= CONTEXT_MAX_PASSAGES:
            break
        selected.append(hit)
        source_set.add(hit.get("source_key", ""))

    if len(source_set) < CONTEXT_MIN_SOURCES and len(expanded) > len(selected):
        unselected_new = [
            h for h in expanded
            if h not in selected and h.get("source_key", "") not in source_set
        ]
        if unselected_new:
            src_counts = defaultdict(int)
            for s in selected:
                src_counts[s.get("source_key", "")] += 1
            for i in range(len(selected) - 1, -1, -1):
                if src_counts[selected[i].get("source_key", "")] > 1:
                    evicted = selected.pop(i)
                    src_counts[evicted.get("source_key", "")] -= 1
                    selected.append(unselected_new[0])
                    source_set.add(unselected_new[0].get("source_key", ""))
                    break

    return selected


# ── Adaptive Context Distillation ────────────────────────────────────────────

_QUESTION_PREFIXES = re.compile(
    r"^(?:what\s+(?:is|are|does|do|was|were)\s+(?:the\s+)?|"
    r"how\s+(?:does|do|is|are|can|should)\s+(?:the\s+)?|"
    r"why\s+(?:does|do|is|are)\s+(?:the\s+)?|"
    r"describe\s+(?:the\s+)?|"
    r"explain\s+(?:the\s+)?|"
    r"compare\s+(?:the\s+)?|"
    r"differentiate\s+(?:between\s+)?(?:the\s+)?|"
    r"contrast\s+(?:the\s+)?)",
    re.IGNORECASE,
)

_MAX_AXES = 4


def _decompose_axes(query: str) -> List[str]:
    """Parse query into semantic axes via heuristic splitting.

    Splits on ', and ', ' and ', commas, question marks. Strips common
    question prefixes and stopwords. Falls back to full query as single axis.
    Capped at 4 axes.
    """
    # Strip leading question prefix
    cleaned = _QUESTION_PREFIXES.sub("", query.strip())
    cleaned = cleaned.strip("? ").strip()

    if not cleaned:
        cleaned = query.strip("? ").strip()

    # Split on explicit delimiters: ", and " first, then " and ", then commas,
    # then question marks (multi-question queries)
    # Order matters: try compound delimiter first
    parts = [cleaned]
    new_parts = []
    for p in parts:
        new_parts.extend(re.split(r",\s*and\s+", p))
    parts = new_parts

    new_parts = []
    for p in parts:
        new_parts.extend(re.split(r"\s+and\s+", p))
    parts = new_parts

    new_parts = []
    for p in parts:
        new_parts.extend(re.split(r",\s*", p))
    parts = new_parts

    new_parts = []
    for p in parts:
        new_parts.extend(re.split(r"\?\s*", p))
    parts = new_parts

    # Clean each axis: strip stopwords from edges, drop empty
    axes = []
    for part in parts:
        part = part.strip("? .,").strip()
        # Re-apply prefix stripping on each part
        part = _QUESTION_PREFIXES.sub("", part).strip("? ").strip()
        if not part:
            continue
        # Drop axes that are purely stopwords
        tokens = set(re.findall(r"[a-zA-Z]{3,}", part.lower()))
        if tokens and not tokens.issubset(STOPWORDS):
            axes.append(part)

    if not axes:
        return [query.strip()]

    return axes[:_MAX_AXES]


def _score_passages_by_axis(
    query_axes: List[str],
    hits: list,
    reranker,
) -> list:
    """Score each hit against every axis using the loaded cross-encoder.

    Adds `axis_scores` dict and `primary_axis` to each hit.
    Returns the enriched hits list (same order).
    """
    if not hits or not query_axes:
        return hits

    # Build all (axis, passage) pairs at once for batched inference
    pairs = []
    for hit in hits:
        child_text = (hit.get("text_original") or hit.get("text", ""))[:2200]
        for axis in query_axes:
            pairs.append([axis, child_text])

    try:
        raw_scores = reranker.predict(pairs, batch_size=64)
        scores = [float(s) for s in raw_scores]
    except Exception:
        # Fallback: no axis scoring, assign equal scores
        for hit in hits:
            hit["axis_scores"] = {ax: 0.5 for ax in query_axes}
            hit["primary_axis"] = query_axes[0]
        return hits

    # Map raw CE scores to sigmoid probabilities
    n_axes = len(query_axes)
    for i, hit in enumerate(hits):
        axis_scores = {}
        for j, axis in enumerate(query_axes):
            raw = scores[i * n_axes + j]
            sig = raw if (0 <= raw <= 1.0) else 1.0 / (1.0 + math.exp(-raw))
            axis_scores[axis] = round(sig, 4)
        hit["axis_scores"] = axis_scores
        hit["primary_axis"] = max(axis_scores, key=axis_scores.get)

    return hits


def _budget_passages(
    hits_with_axes: list,
    axes: List[str],
    max_total: int = CONTEXT_MAX_PASSAGES,
    min_sources: int = CONTEXT_MIN_SOURCES,
) -> list:
    """Allocate passages across axes with source diversity enforcement.

    Budget: ceil(max_total / len(axes)) per axis. Within each axis bucket,
    prefer source diversity (different source_book), sorted by axis score.
    Surplus budget from underfilled axes redistributes to others.
    """
    if not hits_with_axes or not axes:
        return hits_with_axes[:max_total]

    per_axis_budget = math.ceil(max_total / len(axes))

    # Group by primary axis
    axis_candidates: Dict[str, list] = {ax: [] for ax in axes}
    for hit in hits_with_axes:
        primary = hit.get("primary_axis", axes[0])
        if primary in axis_candidates:
            axis_candidates[primary].append(hit)
        else:
            # Axis not in our list (shouldn't happen), assign to best match
            axis_candidates[axes[0]].append(hit)

    # Sort each bucket by axis score descending
    for ax in axes:
        axis_candidates[ax].sort(
            key=lambda h: h.get("axis_scores", {}).get(ax, 0.0),
            reverse=True,
        )

    # Select within each axis bucket with source diversity
    selected_per_axis: Dict[str, list] = {ax: [] for ax in axes}
    global_seen = set()  # content hashes to avoid cross-axis duplicates

    def _select_from_bucket(ax: str, budget: int):
        bucket = axis_candidates[ax]
        chosen = selected_per_axis[ax]
        sources_in_bucket = set()

        for hit in bucket:
            if len(chosen) >= budget:
                break
            ch = _content_hash(hit.get("text", ""))
            if ch in global_seen:
                continue
            src = hit.get("source_key", "")
            # Prefer new sources if we have room
            if src in sources_in_bucket and len(chosen) < budget - 1:
                # Check if there's a candidate from a different source later
                remaining = [
                    h for h in bucket
                    if _content_hash(h.get("text", "")) not in global_seen
                    and h.get("source_key", "") not in sources_in_bucket
                    and h not in chosen
                ]
                if remaining:
                    # Take the diverse one first, come back to this one
                    continue
            chosen.append(hit)
            global_seen.add(ch)
            sources_in_bucket.add(src)

        # Backfill if diversity preference left gaps
        for hit in bucket:
            if len(chosen) >= budget:
                break
            ch = _content_hash(hit.get("text", ""))
            if ch in global_seen:
                continue
            chosen.append(hit)
            global_seen.add(ch)

    # First pass: allocate base budget
    for ax in axes:
        _select_from_bucket(ax, per_axis_budget)

    # Redistribute surplus from underfilled axes
    total_selected = sum(len(v) for v in selected_per_axis.values())
    if total_selected < max_total:
        remaining_budget = max_total - total_selected
        # Axes sorted by how many candidates remain
        for ax in sorted(axes, key=lambda a: len(axis_candidates[a]), reverse=True):
            if remaining_budget <= 0:
                break
            extra = min(remaining_budget, len(axis_candidates[ax]) - len(selected_per_axis[ax]))
            if extra > 0:
                _select_from_bucket(ax, len(selected_per_axis[ax]) + extra)
                added = len(selected_per_axis[ax]) - (len(selected_per_axis[ax]) - extra)
                remaining_budget -= extra

    # Flatten, preserving axis grouping order
    result = []
    for ax in axes:
        result.extend(selected_per_axis[ax])

    # Final source diversity check
    source_set = {h.get("source_key", "") for h in result if h.get("source_key")}
    if len(source_set) < min_sources and len(hits_with_axes) > len(result):
        for hit in hits_with_axes:
            if len(result) >= max_total:
                break
            ch = _content_hash(hit.get("text", ""))
            if ch in global_seen:
                continue
            src = hit.get("source_key", "")
            if src not in source_set:
                result.append(hit)
                source_set.add(src)
                global_seen.add(ch)
                if len(source_set) >= min_sources:
                    break

    return result[:max_total]


def _select_text_level(hit: dict) -> str:
    """Choose child_text vs parent_text based on axis score and sibling context.

    - High-scoring primary (axis_score > 0.7) with parent_text → parent_text
    - Supplementary (0.4-0.7) → child_text only
    - Always include table_markdown and caption_text alongside
    Returns the selected text content.
    """
    axis_scores = hit.get("axis_scores", {})
    primary_axis = hit.get("primary_axis")
    primary_score = axis_scores.get(primary_axis, 0.0) if primary_axis else 0.0

    parent_text = hit.get("parent_text", "")
    child_text = hit.get("text_original") or hit.get("text", "")

    # High-scoring primary with meaningful parent context → use parent
    if primary_score > 0.7 and parent_text and len(parent_text) > len(child_text) * 1.3:
        text = parent_text
    else:
        text = child_text

    # Append table and caption data if present
    extras = []
    if hit.get("table_markdown"):
        extras.append(hit["table_markdown"])
    if hit.get("caption_text"):
        extras.append(hit["caption_text"])

    if extras:
        text = text + "\n\n" + "\n\n".join(extras)

    return text


def _distill_by_axes(
    query: str,
    hits: list,
    reranker_key: str = DEFAULT_RERANKER,
) -> dict:
    """Full distillation pipeline: decompose → score → budget → text-level select.

    Returns dict with:
        axes: list of detected axes
        hits: budgeted hits with axis metadata and text_level selected
        distilled: True
    """
    axes = _decompose_axes(query)

    if len(axes) <= 1:
        # Single axis: no distillation needed, just select text levels
        for hit in hits:
            hit["axis_scores"] = {axes[0]: hit.get("rank_score", 0.5)}
            hit["primary_axis"] = axes[0]
            hit["distilled_text"] = _select_text_level(hit)
        return {"axes": axes, "hits": hits, "distilled": False}

    ce, _ = _get_reranker(reranker_key)
    if ce is None:
        for hit in hits:
            hit["axis_scores"] = {ax: 0.5 for ax in axes}
            hit["primary_axis"] = axes[0]
            hit["distilled_text"] = _select_text_level(hit)
        return {"axes": axes, "hits": hits, "distilled": False}

    scored = _score_passages_by_axis(axes, hits, ce)
    budgeted = _budget_passages(scored, axes)

    for hit in budgeted:
        hit["distilled_text"] = _select_text_level(hit)

    return {"axes": axes, "hits": budgeted, "distilled": True}


# ── Main retrieval pipeline ──────────────────────────────────────────────────

def retrieve(
    query: str,
    lance_dir: str = "",
    table_name: str = "",
    n_results: int = DEFAULT_N_RESULTS,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    reranker_key: str = DEFAULT_RERANKER,
    use_parent_expansion: bool = True,
    visual: bool = False,
    use_learner: bool = True,
) -> dict:
    """Full retrieval pipeline: encode → dense+FTS → RRF → rerank → expand."""
    t_total_start = time.perf_counter()

    table = _get_lance_table(lance_dir, table_name)

    t0 = time.perf_counter()
    query_dense, query_sparse = _encode_query(query)
    encode_ms = round((time.perf_counter() - t0) * 1000, 2)

    dense_hits, dense_ms = _dense_search(table, query_dense, n_results)
    fts_hits, fts_ms = _sparse_search_fts(table, query, n_results)

    t0 = time.perf_counter()
    fused = _apply_rrf(dense_hits, fts_hits)
    rrf_ms = round((time.perf_counter() - t0) * 1000, 2)

    candidates = [h for h in fused if h.get("similarity", 0.0) >= min_similarity]
    below_threshold = len(fused) - len(candidates)
    if not candidates and fused:
        candidates = fused[:10]

    pre_ref_count = len(candidates)
    candidates = [h for h in candidates if not _is_reference_chunk(h.get("text", ""))]
    refs_dropped = pre_ref_count - len(candidates)

    reranked, rerank_ms = _rerank_hits(query, candidates, reranker_key)
    reranked = [
        h for h in reranked
        if not h.get("is_reference_chunk") and not _is_reference_chunk(h.get("text", ""))
    ]

    # Learner-aware rerank modifier (tiebreaker only, never filters)
    learner_applied = False
    if use_learner and reranked:
        learner_data = _load_learner_concepts(query)
        if learner_data:
            reranked = _apply_learner_modifier(reranked, learner_data)
            learner_applied = True

    t0 = time.perf_counter()
    if use_parent_expansion and reranked:
        final_hits = _expand_with_parent_text(reranked)
    else:
        final_hits = reranked[:CONTEXT_MAX_PASSAGES]
    expand_ms = round((time.perf_counter() - t0) * 1000, 2)

    # Visual mode: enrich final hits with image_bytes from LanceDB
    if visual:
        image_ids = [h.get("child_id") for h in final_hits
                     if h.get("metadata", {}).get("has_image") and h.get("child_id")]
        if image_ids:
            try:
                import pyarrow.compute as pc
                arrow = table.to_arrow()
                for cid in image_ids:
                    mask = pc.equal(arrow["child_id"], cid)
                    filtered = arrow.filter(mask)
                    if len(filtered) > 0:
                        img = filtered["image_bytes"][0].as_py()
                        for h in final_hits:
                            if h.get("child_id") == cid and img:
                                h["_image_bytes"] = img
            except Exception:
                pass

    total_ms = round((time.perf_counter() - t_total_start) * 1000, 2)
    unique_sources = {h.get("source_key", "") for h in final_hits if h.get("source_key")}

    return {
        "query": query,
        "reranker": reranker_key,
        "hits": final_hits,
        "latency": {
            "encode_ms": encode_ms, "dense_ms": dense_ms, "fts_ms": fts_ms,
            "rrf_ms": rrf_ms, "rerank_ms": rerank_ms, "expand_ms": expand_ms,
            "total_ms": total_ms,
        },
        "metadata": {
            "dense_candidates": len(dense_hits),
            "fts_candidates": len(fts_hits),
            "fused_candidates": len(fused),
            "below_threshold": below_threshold,
            "refs_dropped": refs_dropped,
            "after_rerank": len(reranked),
            "final_passages": len(final_hits),
            "unique_sources": len(unique_sources),
            "source_books": sorted(unique_sources),
            "learner_modifier_applied": learner_applied,
        },
    }


# ── Context building ─────────────────────────────────────────────────────────

def _load_frontier_notes() -> str:
    """Read frontier_cache.md if it exists and is fresh (<5 min)."""
    cache_path = BASE_DIR / "data" / "Sessions" / "frontier_cache.md"
    try:
        if cache_path.exists():
            age_sec = time.time() - cache_path.stat().st_mtime
            if age_sec < 300:
                cached = cache_path.read_text(encoding="utf-8", errors="ignore").strip()
                if cached and "No frontier evidence found" not in cached:
                    return cached
    except Exception:
        pass
    return ""


def _extract_images(hits: list) -> list:
    """Extract image_bytes from hits with has_image=True, save to temp files.
    Returns list of dicts with {path, citation, page, source_book}.
    """
    import base64
    figures_dir = BASE_DIR / "data" / "Sessions" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    for i, hit in enumerate(hits):
        meta = hit.get("metadata", {})
        img_bytes = hit.get("_image_bytes")
        if not img_bytes or not meta.get("has_image"):
            continue
        fname = f"fig_{i:02d}.png"
        fpath = figures_dir / fname
        try:
            fpath.write_bytes(img_bytes)
            extracted.append({
                "path": str(fpath),
                "citation": hit.get("citation", ""),
                "page": meta.get("page_start", "?"),
                "source_book": meta.get("source_book", ""),
            })
        except Exception:
            pass
    return extracted


def _format_hit_block(hit: dict) -> Optional[str]:
    """Format a single hit into a passage block. Returns None for reference chunks."""
    # Use distilled text if available (axis-aware text-level selection),
    # otherwise fall back to raw text
    text = hit.get("distilled_text") or hit.get("text", "")
    if _is_reference_chunk(text):
        return None

    citation = hit.get("citation", "uncited")
    meta_flags = []
    meta = hit.get("metadata", {})
    if meta.get("has_image"):
        meta_flags.append("[HAS_FIGURE]")
    if meta.get("has_table"):
        meta_flags.append("[HAS_TABLE]")
    if meta.get("page_start"):
        meta_flags.append(f"[Page {meta['page_start']}]")
    chunks = hit.get("passage_chunks")
    cluster_hits = hit.get("cluster_hits")
    if chunks and chunks > 1:
        meta_flags.append(f"[{cluster_hits} hits clustered across {chunks} chunks]")

    flag_str = " ".join(meta_flags)
    block = f"[TEXTBOOK THEORY] {citation} {flag_str}\n{text}"

    # Only append table_markdown separately if not already included via distilled_text
    if hit.get("table_markdown") and not hit.get("distilled_text"):
        block += f"\n\n[TEXTBOOK THEORY TABLE DATA]\n{hit['table_markdown']}"

    return block


def build_scratch_context(result: dict, frontier_text: str = "",
                          visual: bool = False) -> str:
    """Format retrieval results into scratch_context.md for the Transform subagent."""
    query = result["query"]
    hits = result["hits"]
    axes = result.get("axes", [])
    distilled = result.get("distilled", False)

    if distilled and len(axes) > 1:
        # Group passages by axis
        axis_groups: Dict[str, list] = {ax: [] for ax in axes}
        for hit in hits:
            primary = hit.get("primary_axis", axes[0])
            if primary in axis_groups:
                axis_groups[primary].append(hit)
            else:
                axis_groups[axes[0]].append(hit)

        sections = []
        for ax in axes:
            group_hits = axis_groups[ax]
            if not group_hits:
                continue
            blocks = []
            for hit in group_hits:
                block = _format_hit_block(hit)
                if block:
                    blocks.append(block)
            if blocks:
                sections.append(f"## Axis: {ax.strip().title()}\n\n" + "\n\n".join(blocks))

        source_knowledge = "\n\n".join(sections).strip() or "No local source knowledge provided."
    else:
        # Flat format (single axis or no distillation)
        blocks = []
        for hit in hits:
            block = _format_hit_block(hit)
            if block:
                blocks.append(block)
        source_knowledge = "\n\n".join(blocks).strip() or "No local source knowledge provided."

    if frontier_text:
        frontier_section = frontier_text
    else:
        frontier_section = (
            "No external frontier notes provided. "
            "IMPORTANT: Do NOT use [Frontier] tags or fabricate external citations."
        )

    context = (
        f"Query:\n{query.strip()}\n\n"
        f"Source Knowledge:\n{source_knowledge}\n\n"
        f"Frontier Evidence:\n{frontier_section}\n"
    )

    # Visual mode: extract and embed figure references
    if visual:
        figures = _extract_images(hits)
        if figures:
            fig_lines = ["\n# 🖼️ Extracted Figures\n"]
            for fig in figures:
                fig_lines.append(
                    f"**Figure** — {fig['citation']} (p.{fig['page']})\n"
                    f"```python\nfrom IPython.display import Image, display\n"
                    f"display(Image(filename='{fig['path']}'))\n```\n"
                )
            context += "\n".join(fig_lines)

    return context


def _merge_source_blocks(existing_content: str, new_prompt: str, max_total_passages: int = 20):
    """Merge new Source Knowledge passages into existing scratch_context.md.
    Deduplicates by 220-char fingerprint. Returns (merged, added, skipped).
    """
    def _fingerprint(text: str) -> str:
        return text[:220].lower().strip()

    def _split_passages(source_block: str) -> list:
        if not source_block.strip():
            return []
        parts = _SOURCE_BLOCK_RE.split(source_block)
        passages = []
        i = 1
        while i < len(parts) - 1:
            label = parts[i]
            body = parts[i + 1]
            passages.append(f"[{label}]{body}")
            i += 2
        if not passages and source_block.strip():
            passages = [source_block.strip()]
        return passages

    # Parse existing
    existing_query = ""
    existing_source = ""
    existing_frontier = ""

    if "Source Knowledge:" in existing_content:
        pre_source, rest = existing_content.split("Source Knowledge:", 1)
        existing_query = pre_source.replace("Query:", "").strip()
        if "Frontier Evidence:" in rest:
            existing_source, existing_frontier = rest.split("Frontier Evidence:", 1)
            existing_source = existing_source.strip()
            existing_frontier = existing_frontier.strip()
        else:
            existing_source = rest.strip()
    else:
        existing_query = existing_content.strip()

    # Parse new
    new_query = ""
    new_source = ""
    if "Source Knowledge:" in new_prompt:
        pre, rest = new_prompt.split("Source Knowledge:", 1)
        new_query = pre.replace("Query:", "").strip()
        if "Frontier Evidence:" in rest:
            new_source = rest.split("Frontier Evidence:", 1)[0].strip()
        else:
            new_source = rest.strip()

    # Deduplicate and merge
    existing_passages = _split_passages(existing_source)
    new_passages = _split_passages(new_source)

    seen_fps = set()
    for p in existing_passages:
        lines = p.split("\n", 1)
        body = lines[1] if len(lines) > 1 else lines[0]
        seen_fps.add(_fingerprint(body))

    added = 0
    skipped = 0
    for p in new_passages:
        if len(existing_passages) >= max_total_passages:
            break
        lines = p.split("\n", 1)
        body = lines[1] if len(lines) > 1 else lines[0]
        fp = _fingerprint(body)
        if fp in seen_fps:
            skipped += 1
            continue
        seen_fps.add(fp)
        existing_passages.append(p)
        added += 1

    merged_query = existing_query
    if new_query and new_query not in merged_query:
        merged_query += f" | Sub-query: {new_query}"

    merged_source = "\n\n".join(existing_passages)
    frontier_section = existing_frontier if existing_frontier else (
        "No external frontier notes provided. "
        "IMPORTANT: Do NOT use [Frontier] tags or fabricate external citations."
    )

    merged = (
        f"Query:\n{merged_query}\n\n"
        f"Source Knowledge:\n{merged_source}\n\n"
        f"Frontier Evidence:\n{frontier_section}\n"
    )
    return merged, added, skipped


# ── Learner-aware rerank modifier (KG ↔ Retriever bridge) ─────────────────────

# Learner modifier constants — intentionally tiny (tiebreaker only)
_LEARNER_GAP_BONUS = 0.05
_LEARNER_CONFIRMED_PENALTY = 0.03
_LEARNER_CONTEXT_MAX_AGE_SEC = 1800  # 30 minutes


def _load_learner_concepts(query: str) -> Optional[dict]:
    """Load gap/confirmed concept keywords from pre-flight learner context JSON.

    Reads data/Sessions/learner_context.json (generated by Step 0 pre-flight).
    Returns None if file is missing, stale (>30 min), or malformed.
    """
    ctx_path = BASE_DIR / "data" / "Sessions" / "learner_context.json"
    try:
        if not ctx_path.exists():
            return None
        age_sec = time.time() - ctx_path.stat().st_mtime
        if age_sec > _LEARNER_CONTEXT_MAX_AGE_SEC:
            return None

        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
        topics = ctx.get("topics", [])
        if not topics:
            return None

        gap_keywords = set()
        confirmed_keywords = set()

        for topic in topics:
            for concept in topic.get("concepts_unknown", []):
                concept_text = concept.get("concept", "")
                if concept_text:
                    gap_keywords |= _extract_keywords(concept_text)
            for concept in topic.get("concepts_known", []):
                concept_text = concept.get("concept", "")
                if concept_text:
                    confirmed_keywords |= _extract_keywords(concept_text)

        if not gap_keywords and not confirmed_keywords:
            return None

        return {"gap_keywords": gap_keywords, "confirmed_keywords": confirmed_keywords}
    except Exception:
        return None


def _apply_learner_modifier(hits: list, learner_data: dict) -> list:
    """Apply gentle score modifier based on learner's known/gap concepts.

    This is a TIEBREAKER only — modifier capped to [-0.03, +0.05].
    Confirmed concepts still appear at full weight if they're the best matches.
    """
    gap_kw = learner_data.get("gap_keywords", set())
    confirmed_kw = learner_data.get("confirmed_keywords", set())

    if not gap_kw and not confirmed_kw:
        return hits

    for hit in hits:
        hit_kw = _extract_keywords(hit.get("text", ""))

        gap_overlap = len(hit_kw & gap_kw) / max(1, len(gap_kw))
        confirmed_overlap = len(hit_kw & confirmed_kw) / max(1, len(confirmed_kw))

        modifier = (gap_overlap * _LEARNER_GAP_BONUS) - (confirmed_overlap * _LEARNER_CONFIRMED_PENALTY)
        modifier = max(-_LEARNER_CONFIRMED_PENALTY, min(_LEARNER_GAP_BONUS, modifier))

        hit["rank_score"] = round(hit.get("rank_score", 0.0) + modifier, 4)
        hit["learner_modifier"] = round(modifier, 4)

    hits.sort(key=lambda x: (x.get("rank_score", 0.0), x.get("similarity", 0.0)), reverse=True)
    return hits


def _log_retrieval_coverage(query: str, hits: list, axes: list = None):
    """Log retrieval coverage metadata. Silent, never-fail."""
    try:
        source_counts = defaultdict(int)
        source_scores = defaultdict(list)
        for hit in hits:
            src = hit.get("source_key", "unknown")
            source_counts[src] += 1
            score = hit.get("rank_score", hit.get("similarity", 0.0))
            source_scores[src].append(score)

        per_source = {}
        for src, count in source_counts.items():
            scores = source_scores[src]
            per_source[src] = {
                "passages": count,
                "avg_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
            }

        coverage = {
            "query": query,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_passages": len(hits),
            "unique_sources": len(source_counts),
            "per_source": per_source,
        }

        if axes:
            axis_coverage = {}
            for axis in axes:
                axis_kw = _extract_keywords(axis)
                count = sum(
                    1 for h in hits
                    if len(_extract_keywords(h.get("text", "")) & axis_kw) >= 2
                )
                axis_coverage[axis] = {
                    "passages_with_overlap": count,
                    "coverage": "strong" if count >= 3 else "thin" if count >= 1 else "none",
                }
            coverage["per_axis"] = axis_coverage

        coverage_path = BASE_DIR / "data" / "Sessions" / "retrieval_coverage.json"
        coverage_path.parent.mkdir(parents=True, exist_ok=True)
        coverage_path.write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Knowledge graph hook (silent, never blocks) ──────────────────────────────

def _log_to_knowledge_graph(query: str, confidence: str = "medium",
                            source_books: list = None):
    """Log retrieval metadata to knowledge graph. Never raises."""
    try:
        import sys
        sys.path.insert(0, str(BASE_DIR / "src"))
        from knowledge_graph import KnowledgeGraph
        KnowledgeGraph().log_rag_query(
            query=query, confidence=confidence,
            hit_counts={}, source_books=source_books or [],
        )
    except Exception:
        pass


# ── High-level CLI commands ──────────────────────────────────────────────────

def compare(query: str, append: bool = False, output_file: str = "",
            force_refresh: bool = False, visual: bool = False,
            no_distill: bool = False, use_learner: bool = True):
    """Retrieve, build context, write to scratch_context.md.
    This is the primary entrypoint called by the agent workflow.
    """
    result = retrieve(query, visual=visual, use_learner=use_learner)

    # Adaptive Context Distillation (between retrieval and context building)
    if not no_distill and result["hits"]:
        distill_result = _distill_by_axes(query, result["hits"])
        result["hits"] = distill_result["hits"]
        result["axes"] = distill_result["axes"]
        result["distilled"] = distill_result["distilled"]

    frontier_text = _load_frontier_notes()
    prompt_content = build_scratch_context(result, frontier_text, visual=visual)

    if output_file:
        context_file = Path(output_file)
    else:
        context_file = BASE_DIR / "data" / "Sessions" / "scratch_context.md"
    context_file.parent.mkdir(parents=True, exist_ok=True)

    if append and context_file.exists():
        existing = context_file.read_text(encoding="utf-8")
        merged, added, skipped = _merge_source_blocks(existing, prompt_content)
        context_file.write_text(merged, encoding="utf-8")
        print(f"OK appended — {added} new, {skipped} dupes | "
              f"{result['metadata']['unique_sources']} src | "
              f"{result['latency']['total_ms']:.0f}ms")
    else:
        context_file.write_text(prompt_content, encoding="utf-8")
        n_passages = result["metadata"]["final_passages"]
        n_sources = result["metadata"]["unique_sources"]
        ms = result["latency"]["total_ms"]
        print(f"OK {n_passages} passages | {n_sources} sources | {ms:.0f}ms")

    _log_to_knowledge_graph(
        query, confidence="medium",
        source_books=result["metadata"]["source_books"],
    )
    _log_retrieval_coverage(
        query, result["hits"],
        axes=result.get("axes"),
    )


def compare_multi(queries: list, max_passages: int = 20, no_distill: bool = False,
                  use_learner: bool = True):
    """Run multiple sub-queries, merge results into scratch_context.md."""
    if not queries:
        print("No queries provided.")
        return

    context_file = BASE_DIR / "data" / "Sessions" / "scratch_context.md"
    context_file.parent.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    results_content = []
    statuses = []

    for i, q in enumerate(queries):
        t0 = time.time()
        result = retrieve(q, use_learner=use_learner)

        # Adaptive Context Distillation per sub-query
        if not no_distill and result["hits"]:
            distill_result = _distill_by_axes(q, result["hits"])
            result["hits"] = distill_result["hits"]
            result["axes"] = distill_result["axes"]
            result["distilled"] = distill_result["distilled"]

        frontier_text = _load_frontier_notes()
        prompt = build_scratch_context(result, frontier_text)
        results_content.append(prompt)
        elapsed = time.time() - t0
        n_src = result["metadata"]["unique_sources"]
        statuses.append(f"  sq{i+1}: {elapsed:.1f}s | {n_src} books")

    # Merge all sub-query results
    if len(results_content) == 1:
        merged_content = results_content[0]
    else:
        merged_content = results_content[0]
        total_added = 0
        total_skipped = 0
        for prompt in results_content[1:]:
            merged_content, added, skipped = _merge_source_blocks(
                merged_content, prompt, max_total_passages=max_passages
            )
            total_added += added
            total_skipped += skipped

    context_file.write_text(merged_content, encoding="utf-8")

    # Knowledge graph signals
    for q in queries:
        _log_to_knowledge_graph(q)

    t_total = time.time() - t_start
    print(f"OK compare_multi — {len(queries)} queries in {t_total:.1f}s")
    for s in statuses:
        print(s)
    if len(results_content) > 1:
        print(f"  merge: {total_added} added, {total_skipped} dupes skipped")


def list_textbooks():
    """List all unique textbooks and chunk counts in the LanceDB table."""
    import pyarrow.compute as pc
    table = _get_lance_table()
    arrow = table.to_arrow()
    vc = pc.value_counts(arrow["source_book"])

    entries = []
    total = 0
    for i in range(len(vc)):
        s = vc[i]
        name = s["values"].as_py()
        count = s["counts"].as_py()
        entries.append((count, name))
        total += count
    entries.sort(key=lambda x: -x[0])

    print(f"Database Inventory ({DEFAULT_LANCE_TABLE})")
    print(f"{'─' * 50}")
    for count, name in entries:
        print(f"  {count:>5d}  {name}")
    print(f"{'─' * 50}")
    print(f"  {total:>5d}  TOTAL ({len(entries)} books)")


def clear_cache():
    """No-op — LanceDB queries are fast enough that caching is unnecessary."""
    print("OK — no cache to clear (LanceDB queries are <6s)")


def generate_digest(transform_path: str = None, output_path: str = None) -> str:
    """Generate a compressed digest of the last synthesis for follow-up context.

    Extracts: key facts, dosages/thresholds, source list, and the Gym question.
    Strips: prose filler, setup language, redundant citations, narrative paragraphs.
    Target: ~500-800 tokens (vs 3,000-5,000 for full synthesis).
    """
    sessions_dir = BASE_DIR / "data" / "Sessions"
    src = Path(transform_path) if transform_path else sessions_dir / "transform_output.md"
    dst = Path(output_path) if output_path else sessions_dir / "synthesis_digest.md"

    if not src.exists():
        msg = f"No synthesis found at {src} — run a RAG query first."
        print(msg)
        return msg

    raw = src.read_text(encoding="utf-8")
    lines = raw.split("\n")

    # ── Section parser ──
    sections: Dict[str, List[str]] = {}
    current_section = "_preamble"
    sections[current_section] = []

    for line in lines:
        if line.startswith("## ") or line.startswith("### "):
            current_section = line.lstrip("#").strip().lower()
            sections[current_section] = []
        else:
            sections.setdefault(current_section, []).append(line)

    digest_parts: List[str] = []
    digest_parts.append("## Synthesis Digest (compressed from prior turn)\n")

    # 1. YAML frontmatter — verbatim (in _preamble, between --- lines)
    preamble = sections.get("_preamble", [])
    in_frontmatter = False
    fm_lines: List[str] = []
    for line in preamble:
        if line.strip() == "---":
            in_frontmatter = not in_frontmatter
            fm_lines.append(line)
            continue
        if in_frontmatter:
            fm_lines.append(line)
    if fm_lines:
        digest_parts.append("\n".join(fm_lines))
        digest_parts.append("")

    # 2. Compress section — verbatim (it's already a mental model summary)
    for key in ("compress", "compress: mental model", "mental model"):
        if key in sections:
            digest_parts.append(f"### Compress")
            digest_parts.append("\n".join(sections[key]))
            digest_parts.append("")
            break

    # 3. Lines with clinical numbers/units (doses, thresholds, timing)
    #    Scan Build section and others for lines with number+unit patterns
    unit_pattern = re.compile(
        r'\d+\s*(?:mg|mcg|µg|mL|L|mmHg|cmH2O|mOsm|%|mm|cm|kg|g/dL|mEq|'
        r'IU|units?|hrs?|hours?|min|days?|weeks?|months?|q\d+h|mg/kg|'
        r'mcg/kg|mL/hr|mmol|cc)\b',
        re.IGNORECASE,
    )
    classification_pattern = re.compile(
        r'\b(?:Grade|Stage|Type|Class|Score|Scale|Fisher|Hunt.?Hess|'
        r'WFNS|Spetzler|GCS|GOS|mRS|Rankin|Nurick|JOA|ASIA)\b',
        re.IGNORECASE,
    )
    # Sections to mine for clinical facts (skip Anchor — redundant, skip Compress — already included)
    fact_sections = [k for k in sections if k not in (
        "_preamble", "compress", "compress: mental model", "mental model",
        "anchor", "anchor: one-liner", "one-liner",
    )]
    clinical_facts: List[str] = []
    seen_facts: set = set()
    for sec_key in fact_sections:
        for line in sections.get(sec_key, []):
            stripped = line.strip()
            if not stripped or stripped in seen_facts:
                continue
            if unit_pattern.search(stripped) or classification_pattern.search(stripped):
                clinical_facts.append(line)
                seen_facts.add(stripped)

    if clinical_facts:
        digest_parts.append("### Key Clinical Facts")
        digest_parts.append("\n".join(clinical_facts))
        digest_parts.append("")

    # 4. Evidence Reconciliation — only if it flags a conflict
    for key in ("evidence reconciliation", "reconciliation"):
        if key in sections:
            conflict_lines = [
                l for l in sections[key]
                if any(w in l.lower() for w in (
                    "conflict", "contradict", "disagree", "discrepan",
                    "however", "but ", "versus", "vs.", "differs",
                ))
            ]
            if conflict_lines:
                digest_parts.append("### Evidence Conflicts")
                digest_parts.append("\n".join(conflict_lines))
                digest_parts.append("")
            break

    # 5. Gym question — verbatim
    for key in ("gym", "gym question", "gym: test yourself", "test yourself"):
        if key in sections:
            digest_parts.append("### Gym")
            digest_parts.append("\n".join(sections[key]))
            digest_parts.append("")
            break

    # 6. Red flag / metacognitive highlight lines
    red_flag_pattern = re.compile(
        r'(?:red flag|⚠|🚨|warning|caution|never|always|critical|danger|'
        r'do not|avoid|contraindicated|black.?box)',
        re.IGNORECASE,
    )
    red_flags: List[str] = []
    for sec_key, sec_lines in sections.items():
        for line in sec_lines:
            stripped = line.strip()
            if stripped and red_flag_pattern.search(stripped) and stripped not in seen_facts:
                red_flags.append(line)
                seen_facts.add(stripped)
    if red_flags:
        digest_parts.append("### Safety / Red Flags")
        digest_parts.append("\n".join(red_flags))
        digest_parts.append("")

    # 7. Source citations — deduplicated
    citation_pattern = re.compile(r'\[([^\]]+(?:Ch\.|Chapter|p\.|pp\.|ed\.)[^\]]*)\]')
    source_refs: set = set()
    for line in lines:
        for match in citation_pattern.finditer(line):
            source_refs.add(match.group(1).strip())
    # Also grab lines that look like source attributions
    source_line_pattern = re.compile(r'^\s*[-*]\s*\*?\*?Source', re.IGNORECASE)
    for line in lines:
        if source_line_pattern.match(line):
            source_refs.add(line.strip().lstrip("-* "))

    if source_refs:
        digest_parts.append("### Sources")
        for ref in sorted(source_refs):
            digest_parts.append(f"- {ref}")
        digest_parts.append("")

    digest_text = "\n".join(digest_parts)

    # Write output
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(digest_text, encoding="utf-8")

    token_est = len(digest_text.split()) * 4 // 3  # rough token estimate
    print(f"OK digest — {token_est} tokens (est) → {dst}")
    return digest_text


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LanceDB retrieval engine")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # compare
    p_compare = subparsers.add_parser("compare", help="Retrieve and write scratch_context.md")
    p_compare.add_argument("query", help="Search query")
    p_compare.add_argument("--append", action="store_true", help="Append to existing context")
    p_compare.add_argument("--output", default="", help="Custom output file path")
    p_compare.add_argument("--force-refresh", action="store_true", help="Bypass cache (no-op)")
    p_compare.add_argument("--visual", action="store_true", help="Extract images from hits")
    p_compare.add_argument("--no-distill", action="store_true",
                           help="Bypass adaptive context distillation")
    p_compare.add_argument("--no-learner", action="store_true",
                           help="Disable KG learner modifier on reranking")

    # compare_multi
    p_multi = subparsers.add_parser("compare_multi", help="Multi-query merge")
    p_multi.add_argument("queries", nargs="+", help="Sub-queries to merge")
    p_multi.add_argument("--no-distill", action="store_true",
                         help="Bypass adaptive context distillation")
    p_multi.add_argument("--no-learner", action="store_true",
                         help="Disable KG learner modifier on reranking")

    # search (raw retrieval for debugging)
    p_search = subparsers.add_parser("search", help="Raw retrieval (debug)")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--json", action="store_true", help="JSON output")
    p_search.add_argument("--reranker", default=DEFAULT_RERANKER,
                          choices=list(RERANKER_MODELS.keys()))
    p_search.add_argument("--n-results", type=int, default=DEFAULT_N_RESULTS)
    p_search.add_argument("--no-learner", action="store_true",
                         help="Disable KG learner modifier on reranking")

    # list_textbooks
    subparsers.add_parser("list_textbooks", help="Show database inventory")

    # clear_cache
    subparsers.add_parser("clear_cache", help="No-op (caching not needed)")

    # digest
    p_digest = subparsers.add_parser("digest", help="Compress last synthesis for follow-up context")
    p_digest.add_argument("--input", default=None, help="Custom transform_output.md path")
    p_digest.add_argument("--output", default=None, help="Custom output path")

    args = parser.parse_args()

    if args.command == "compare":
        compare(args.query, append=args.append, output_file=args.output,
                force_refresh=args.force_refresh, visual=args.visual,
                no_distill=args.no_distill,
                use_learner=not args.no_learner)

    elif args.command == "compare_multi":
        compare_multi(args.queries, no_distill=args.no_distill,
                      use_learner=not args.no_learner)

    elif args.command == "search":
        result = retrieve(args.query, reranker_key=args.reranker,
                          n_results=args.n_results,
                          use_learner=not args.no_learner)
        if args.json:
            output = {
                "query": result["query"], "reranker": result["reranker"],
                "latency": result["latency"], "metadata": result["metadata"],
                "hits": [
                    {"citation": h.get("citation"), "similarity": h.get("similarity"),
                     "rank_score": h.get("rank_score"), "sigmoid_ce": h.get("sigmoid_ce"),
                     "passage_tokens": h.get("passage_tokens"),
                     "source_key": h.get("source_key"),
                     "text_preview": h.get("text", "")[:200]}
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
                print(f"      rank={hit.get('rank_score')}, ce={hit.get('sigmoid_ce')}, "
                      f"tokens={hit.get('passage_tokens', '?')}")

    elif args.command == "list_textbooks":
        list_textbooks()

    elif args.command == "clear_cache":
        clear_cache()

    elif args.command == "digest":
        generate_digest(transform_path=args.input, output_path=args.output)

    else:
        parser.print_help()
