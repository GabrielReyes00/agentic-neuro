"""Lightning-weight retrieval for short neurosurgical learning lookups.

Mini-RAG is intentionally a separate tier from the BGE-M3/cross-encoder
pipeline.  It supports three strategies:

``lexical``
    Full-corpus multi-field FTS. No neural model. Best for named scales,
    classifications, scores, thresholds, tables, and source lookups.

``semantic``
    A 384-dimensional ONNX model over a pruned high-yield lookup corpus. Best
    for paraphrases that omit the formal name of a score/classification.

``hybrid``
    Reciprocal-rank fusion of lexical and mini-semantic results. This is the
    fallback for short factual questions whose lexical confidence is weak.

``auto`` routes obvious complex synthesis questions back to full RAG rather
than returning a deceptively small evidence packet.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from . import pipeline


MINI_MODEL_ID = os.environ.get(
    "NEURO_MINI_MODEL_ID",
    "BAAI/bge-small-en-v1.5",
)
MINI_MODEL_CACHE = Path(
    os.environ.get(
        "NEURO_MINI_MODEL_CACHE",
        pipeline.DATA_DIR / "fastembed_cache",
    )
)
MINI_LANCE_DIR = Path(
    os.environ.get(
        "NEURO_MINI_LANCE_DIR",
        pipeline.DATA_DIR / "mini_rag.lance",
    )
)
MINI_TABLE_NAME = os.environ.get(
    "NEURO_MINI_TABLE",
    "lookup_chunks",
)
MINI_MANIFEST_PATH = pipeline.RUNTIME_DIR / "mini_rag_manifest.json"
MINI_FTS_PATH = Path(
    os.environ.get(
        "NEURO_MINI_FTS_PATH",
        pipeline.DATA_DIR / "mini_rag_fts.db",
    )
)
MINI_FTS_MANIFEST_PATH = pipeline.RUNTIME_DIR / "mini_rag_fts_manifest.json"
MINI_MODEL_THREADS = max(
    1,
    int(os.environ.get("NEURO_MINI_MODEL_THREADS", "8")),
)
MINI_DEFAULT_LIMIT = max(
    1,
    int(os.environ.get("NEURO_MINI_LIMIT", "2")),
)
MINI_DEFAULT_MAX_CHARS = max(
    500,
    int(os.environ.get("NEURO_MINI_MAX_CHARS", "4200")),
)

LOOKUP_SIGNAL_RE = re.compile(
    r"\b(?:"
    r"scale|score|scoring|classification|grading|"
    r"grade\s+(?:[0-9]|I\b|II\b|III\b|IV\b|V\b)|"
    r"class\s+(?:[0-9]|I\b|II\b|III\b|IV\b|V\b)|"
    r"criteria|stages?|"
    r"types?\s+(?:[0-9]|I\b|II\b|III\b|IV\b|V\b)"
    r")",
    re.IGNORECASE,
)
LOOKUP_INTENT_RE = re.compile(
    r"\b(?:"
    r"scale|score|classification|grading|grade|class|criteria|criterion|"
    r"cutoff|threshold|stages?|types?|table|reference|citation|source|"
    r"introduced|components?|levels?"
    r")\b",
    re.IGNORECASE,
)
COMPLEX_SYNTHESIS_RE = re.compile(
    r"\b(?:"
    r"comprehensive|deep[- ]?dive|pathophysiology|full management|"
    r"operative walkthrough|surgical technique|perioperative management|"
    r"compare all|evidence review|controvers(?:y|ies)|outcomes literature"
    r")\b",
    re.IGNORECASE,
)
EVIDENCE_SIGNAL_RE = re.compile(
    r"(?:"
    r"\b(?:grade|class|type|stage|score|points?|table)\b|"
    r"\b\d+(?:\.\d+)?\s*(?:%|mm|cm|points?)?\b|"
    r"\b[IVX]{1,5}\b"
    r")",
    re.IGNORECASE,
)
MINI_QUERY_STOPWORDS = pipeline.STOPWORDS | {
    "scale",
    "score",
    "scoring",
    "classification",
    "grading",
    "grade",
    "class",
    "criteria",
    "criterion",
    "table",
    "reference",
    "citation",
    "source",
    "components",
    "component",
    "what",
    "which",
}

SIGNATURE_EXPANSIONS = (
    (
        "Spetzler-Martin",
        (
            ("avm", "arteriovenous malformation"),
            ("eloquent", "eloquence"),
            ("deep venous", "deep vein", "venous drainage"),
        ),
    ),
    (
        "Spinal Instability Neoplastic Score",
        (
            ("spine", "spinal", "metastatic"),
            ("mechanical pain",),
            ("collapse", "bone lesion", "posterior elements"),
        ),
    ),
    (
        "modified Fisher",
        (
            ("sah", "subarachnoid"),
            ("ivh", "intraventricular"),
            ("thick", "cisternal", "blood burden"),
        ),
    ),
    (
        "Simpson",
        (
            ("meningioma",),
            ("dural attachment",),
            ("abnormal bone", "subtotal resection"),
        ),
    ),
    (
        "Knosp",
        (
            ("pituitary", "sellar"),
            ("carotid", "ica"),
            ("lateral extension", "cavernous sinus", "intracavernous"),
        ),
    ),
    (
        "WFNS",
        (
            ("sah", "subarachnoid"),
            ("gcs", "glasgow coma"),
            ("motor deficit", "focal deficit"),
        ),
    ),
)

SOURCE_COLUMNS = (
    "child_text",
    "parent_id",
    "child_id",
    "child_index_in_parent",
    "source_book",
    "chapter_title",
    "heading",
    "section_path",
    "page_start",
    "page_end",
    "has_table",
    "table_markdown",
    "caption_text",
    "subspecialty",
    "noise_type",
)

_MINI_EMBEDDER = None
_MINI_DB = None
_MINI_TABLE = None
_MINI_MODEL_LOCK = threading.RLock()
_MINI_TABLE_LOCK = threading.RLock()
_MINI_FTS_LOCAL = threading.local()


class MiniRAGPreflightError(RuntimeError):
    """Raised when the optional semantic lookup index is unavailable."""


def _source_manifest_mtime() -> float:
    table_dir = (
        Path(pipeline.DEFAULT_LANCE_DIR)
        / f"{pipeline.DEFAULT_LANCE_TABLE}.lance"
        / "_versions"
    )
    try:
        return max(
            (
                path.stat().st_mtime
                for path in table_dir.glob("*.manifest")
            ),
            default=0.0,
        )
    except OSError:
        return 0.0


def _sidecar_is_fresh(path: Path, manifest_path: Path) -> bool:
    if not path.exists() or not manifest_path.exists():
        return False
    source_mtime = _source_manifest_mtime()
    try:
        return not source_mtime or path.stat().st_mtime >= source_mtime
    except OSError:
        return False


def _model_snapshot() -> Path | None:
    repo_dir = MINI_MODEL_CACHE / "models--qdrant--bge-small-en-v1.5-onnx-q"
    refs_main = repo_dir / "refs" / "main"
    snapshots = repo_dir / "snapshots"
    candidates: list[Path] = []
    if refs_main.exists():
        ref = refs_main.read_text(encoding="utf-8").strip()
        if ref:
            candidates.append(snapshots / ref)
    if snapshots.exists():
        candidates.extend(
            sorted(
                (path for path in snapshots.iterdir() if path.is_dir()),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        )
    for candidate in candidates:
        if (
            (candidate / "model_optimized.onnx").exists()
            and (candidate / "tokenizer.json").exists()
        ):
            return candidate
    return None


def _get_embedder():
    global _MINI_EMBEDDER
    if _MINI_EMBEDDER is not None:
        return _MINI_EMBEDDER
    with _MINI_MODEL_LOCK:
        if _MINI_EMBEDDER is not None:
            return _MINI_EMBEDDER
        snapshot = _model_snapshot()
        if snapshot is None:
            raise MiniRAGPreflightError(
                "The cached bge-small ONNX model is missing. "
                f"Expected it under {MINI_MODEL_CACHE}."
            )
        from fastembed import TextEmbedding

        _MINI_EMBEDDER = TextEmbedding(
            model_name=MINI_MODEL_ID,
            cache_dir=str(MINI_MODEL_CACHE),
            specific_model_path=str(snapshot),
            threads=MINI_MODEL_THREADS,
        )
    return _MINI_EMBEDDER


def _list_tables(db) -> list[str]:
    raw = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
    if hasattr(raw, "tables"):
        return list(raw.tables)
    return list(raw)


def _get_mini_table(*, required: bool = True):
    global _MINI_DB, _MINI_TABLE
    if _MINI_TABLE is not None:
        return _MINI_TABLE
    with _MINI_TABLE_LOCK:
        if _MINI_TABLE is not None:
            return _MINI_TABLE
        if not _sidecar_is_fresh(MINI_LANCE_DIR, MINI_MANIFEST_PATH):
            if required:
                raise MiniRAGPreflightError(
                    "Mini semantic index is missing or older than the source corpus. Run "
                    "`python3 src/lance_retriever.py mini-build`."
                )
            return None
        import lancedb

        _MINI_DB = lancedb.connect(str(MINI_LANCE_DIR))
        if MINI_TABLE_NAME not in _list_tables(_MINI_DB):
            if required:
                raise MiniRAGPreflightError(
                    f"Mini semantic table '{MINI_TABLE_NAME}' is missing."
                )
            return None
        _MINI_TABLE = _MINI_DB.open_table(MINI_TABLE_NAME)
    return _MINI_TABLE


def _source_signature() -> dict[str, Any]:
    table = pipeline._get_lance_table()
    return {
        "table": pipeline.DEFAULT_LANCE_TABLE,
        "version": int(getattr(table, "version", 0)),
        "rows": int(table.count_rows()),
    }


def preflight() -> dict[str, Any]:
    snapshot = _model_snapshot()
    table = _get_mini_table(required=False)
    manifest = None
    if MINI_MANIFEST_PATH.exists():
        try:
            manifest = json.loads(
                MINI_MANIFEST_PATH.read_text(encoding="utf-8")
            )
        except Exception:
            manifest = None
    current_source = _source_signature()
    indexed_source = (manifest or {}).get("source", {})
    stale = bool(
        table is not None
        and (
            indexed_source.get("version") != current_source["version"]
            or indexed_source.get("rows") != current_source["rows"]
        )
    )
    fts_manifest = None
    if MINI_FTS_MANIFEST_PATH.exists():
        try:
            fts_manifest = json.loads(
                MINI_FTS_MANIFEST_PATH.read_text(encoding="utf-8")
            )
        except Exception:
            fts_manifest = None
    fts_source = (fts_manifest or {}).get("source", {})
    fts_stale = bool(
        MINI_FTS_PATH.exists()
        and (
            fts_source.get("version") != current_source["version"]
            or fts_source.get("rows") != current_source["rows"]
        )
    )
    return {
        "ok": bool(
            MINI_FTS_PATH.exists()
            and not fts_stale
            and snapshot
            and table is not None
            and not stale
        ),
        "model": {
            "ok": snapshot is not None,
            "id": MINI_MODEL_ID,
            "snapshot": str(snapshot) if snapshot else "",
        },
        "index": {
            "ok": table is not None,
            "path": str(MINI_LANCE_DIR),
            "table": MINI_TABLE_NAME,
            "rows": int(table.count_rows()) if table is not None else 0,
            "stale": stale,
        },
        "source": current_source,
        "manifest": manifest or {},
        "fts": {
            "ok": MINI_FTS_PATH.exists(),
            "path": str(MINI_FTS_PATH),
            "stale": fts_stale,
            "manifest": fts_manifest or {},
        },
    }


def _source_text(row: dict[str, Any]) -> str:
    text = str(row.get("child_text") or "").strip()
    table_text = str(row.get("table_markdown") or "").strip()
    caption = str(row.get("caption_text") or "").strip()
    extras = []
    if table_text and table_text not in text:
        extras.append(table_text)
    if caption and caption not in text:
        extras.append(caption)
    if extras:
        text = text + "\n\n" + "\n\n".join(extras)
    return pipeline._collapse_repeated_prefixes(text)[:14000]


def _is_lookup_candidate(row: dict[str, Any], text: str) -> bool:
    if len(text) < 45:
        return False
    if pipeline._is_reference_chunk(text):
        return False
    heading = str(row.get("heading") or "")
    chapter = str(row.get("chapter_title") or "")
    structural = f"{heading}\n{chapter}"
    has_table = bool(row.get("has_table") or row.get("table_markdown"))
    return bool(
        LOOKUP_SIGNAL_RE.search(structural)
        or (has_table and LOOKUP_SIGNAL_RE.search(text[:1600]))
    )


def _embedding_text(row: dict[str, Any], text: str) -> str:
    heading = str(row.get("heading") or "").strip()
    chapter = str(row.get("chapter_title") or "").strip()
    section = str(row.get("section_path") or "").strip()
    prefix = " | ".join(
        value
        for value in (heading, chapter, section)
        if value
    )
    return f"{prefix}\n{text[:600]}".strip()


def build_index() -> dict[str, Any]:
    """Rebuild the pruned semantic lookup index from the primary corpus."""
    started = time.perf_counter()
    source_table = pipeline._get_lance_table()
    arrow = (
        source_table.search()
        .select(list(SOURCE_COLUMNS))
        .limit(int(source_table.count_rows()))
        .to_arrow()
    )
    selected_rows: list[dict[str, Any]] = []
    embedding_texts: list[str] = []
    seen_keys: set[str] = set()
    for row in arrow.to_pylist():
        text = _source_text(row)
        if not _is_lookup_candidate(row, text):
            continue
        source_key = str(row.get("source_book") or "")
        parent_id = str(row.get("parent_id") or "")
        child_id = str(row.get("child_id") or "")
        key = f"{source_key}:{parent_id}:{child_id}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        selected_rows.append({
            "lookup_id": key,
            "text": text,
            "source_book": source_key,
            "chapter_title": str(row.get("chapter_title") or ""),
            "heading": str(row.get("heading") or ""),
            "section_path": str(row.get("section_path") or ""),
            "page_start": row.get("page_start"),
            "page_end": row.get("page_end"),
            "parent_id": parent_id,
            "child_id": child_id,
            "chunk_index": int(row.get("child_index_in_parent") or 0),
            "has_table": bool(row.get("has_table") or row.get("table_markdown")),
            "subspecialty": str(row.get("subspecialty") or ""),
        })
        embedding_texts.append(_embedding_text(row, text))

    embedder = _get_embedder()
    embed_started = time.perf_counter()
    vectors = list(
        embedder.embed(
            embedding_texts,
            batch_size=64,
            parallel=None,
        )
    )
    embed_ms = round((time.perf_counter() - embed_started) * 1000, 2)
    if len(vectors) != len(selected_rows):
        raise RuntimeError("Mini index embedding count mismatch")
    for row, vector in zip(selected_rows, vectors, strict=True):
        row["vector"] = np.asarray(vector, dtype=np.float32).tolist()

    import lancedb
    import pyarrow as pa

    schema = pa.schema([
        ("lookup_id", pa.string()),
        ("text", pa.string()),
        ("source_book", pa.string()),
        ("chapter_title", pa.string()),
        ("heading", pa.string()),
        ("section_path", pa.string()),
        ("page_start", pa.int32()),
        ("page_end", pa.int32()),
        ("parent_id", pa.string()),
        ("child_id", pa.string()),
        ("chunk_index", pa.int32()),
        ("has_table", pa.bool_()),
        ("subspecialty", pa.string()),
        ("vector", pa.list_(pa.float32(), 384)),
    ])
    data = pa.Table.from_pylist(selected_rows, schema=schema)
    MINI_LANCE_DIR.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(MINI_LANCE_DIR))
    table = db.create_table(
        MINI_TABLE_NAME,
        data=data,
        mode="overwrite",
    )

    source = _source_signature()
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "selection": {
            "rows_scanned": len(arrow),
            "rows_indexed": len(selected_rows),
            "rule": "lookup_signal_or_table",
        },
        "model": {
            "id": MINI_MODEL_ID,
            "dimensions": 384,
            "cache": str(MINI_MODEL_CACHE),
        },
        "index": {
            "path": str(MINI_LANCE_DIR),
            "table": MINI_TABLE_NAME,
        },
        "timing": {
            "embed_ms": embed_ms,
            "total_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }
    pipeline.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    MINI_MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    global _MINI_DB, _MINI_TABLE
    _MINI_DB = db
    _MINI_TABLE = table
    return manifest


def build_fts_index() -> dict[str, Any]:
    """Build a full-corpus, process-light FTS5 sidecar for exact mini lookups."""
    started = time.perf_counter()
    source_table = pipeline._get_lance_table()
    arrow = (
        source_table.search()
        .select(list(SOURCE_COLUMNS))
        .limit(int(source_table.count_rows()))
        .to_arrow()
    )
    MINI_FTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = MINI_FTS_PATH.with_suffix(".building.db")
    if temporary_path.exists():
        temporary_path.unlink()
    connection = sqlite3.connect(str(temporary_path))
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute(
            """
            CREATE VIRTUAL TABLE chunks USING fts5(
                child_id UNINDEXED,
                parent_id UNINDEXED,
                chunk_index UNINDEXED,
                source_book,
                chapter_title,
                heading,
                section_path,
                child_text,
                table_markdown,
                caption_text,
                page_start UNINDEXED,
                page_end UNINDEXED,
                has_table UNINDEXED,
                subspecialty UNINDEXED,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )
        rows = []
        for row in arrow.to_pylist():
            rows.append((
                str(row.get("child_id") or ""),
                str(row.get("parent_id") or ""),
                int(row.get("child_index_in_parent") or 0),
                str(row.get("source_book") or ""),
                str(row.get("chapter_title") or ""),
                str(row.get("heading") or ""),
                str(row.get("section_path") or ""),
                _source_text(row),
                str(row.get("table_markdown") or ""),
                str(row.get("caption_text") or ""),
                row.get("page_start"),
                row.get("page_end"),
                int(bool(row.get("has_table") or row.get("table_markdown"))),
                str(row.get("subspecialty") or ""),
            ))
        connection.executemany(
            "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        connection.commit()
        connection.execute("INSERT INTO chunks(chunks) VALUES('optimize')")
        connection.commit()
    finally:
        connection.close()
    temporary_path.replace(MINI_FTS_PATH)
    source = _source_signature()
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "rows_indexed": len(arrow),
        "index": {
            "path": str(MINI_FTS_PATH),
            "engine": "sqlite_fts5",
        },
        "timing": {
            "total_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }
    pipeline.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    MINI_FTS_MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    _MINI_FTS_LOCAL.connection = None
    return manifest


def _distinctive_terms(query: str) -> list[str]:
    return sorted(
        {
            token.lower()
            for token in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", query)
            if token.lower() not in MINI_QUERY_STOPWORDS
        }
    )


def expand_query(query: str) -> tuple[str, list[str]]:
    """Add transparent named-system aliases when a component signature is clear."""
    lowered = query.lower()
    aliases = [
        alias
        for alias, required_groups in SIGNATURE_EXPANSIONS
        if alias.lower() not in lowered
        and all(
            any(term in lowered for term in alternatives)
            for alternatives in required_groups
        )
    ]
    if not aliases:
        return query, []
    return f"{query} {' '.join(aliases)}", aliases


def _term_coverage(text: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    lowered = (text or "").lower()
    return sum(term in lowered for term in terms) / len(terms)


def _lookup_score(query: str, hit: dict[str, Any]) -> float:
    terms = _distinctive_terms(query)
    heading = " ".join([
        str(hit.get("metadata", {}).get("heading") or ""),
        str(hit.get("metadata", {}).get("chapter_title") or ""),
    ])
    text = str(hit.get("text") or "")
    heading_coverage = _term_coverage(heading, terms)
    text_coverage = _term_coverage(text, terms)
    retrieval_score = float(hit.get("similarity") or 0.0)
    phrase = re.sub(r"\s+", " ", query.strip().lower())
    combined = re.sub(r"\s+", " ", f"{heading} {text}".lower())
    exact_bonus = 0.12 if phrase and phrase in combined else 0.0
    label_phrase = re.split(
        r"\b(?:scale|score|scoring|grading|classification|components?|"
        r"interpretation|grades?|criteria|reference|citation)\b",
        phrase,
        maxsplit=1,
    )[0].strip(" ,:;-")
    label_bonus = (
        0.16
        if len(label_phrase.split()) >= 3 and label_phrase in combined
        else 0.0
    )
    table_bonus = 0.08 if hit.get("metadata", {}).get("has_table") else 0.0
    evidence_bonus = 0.06 if EVIDENCE_SIGNAL_RE.search(text) else 0.0
    explicit_table_bonus = (
        0.10
        if re.search(r"\btable\b", text, re.IGNORECASE)
        and text_coverage >= 0.5
        else 0.0
    )
    enumeration_count = len(
        re.findall(
            r"\b(?:grade|class|type|stage|points?)\s*(?:[0-9]|[IVX]{1,5})\b",
            text,
            re.IGNORECASE,
        )
    )
    enumeration_bonus = min(0.08, enumeration_count * 0.012)
    structured_row_count = len(
        re.findall(
            r"\b(?:description|definition|criteria|finding|points?|score|"
            r"extent of resection)\s*=",
            text,
            re.IGNORECASE,
        )
    )
    structured_row_bonus = min(0.32, structured_row_count * 0.018)
    primary_positions = [
        combined.find(term)
        for term in terms
        if combined.find(term) >= 0
    ]
    first_entity_position = min(primary_positions, default=-1)
    entity_position_adjustment = (
        0.08
        if 0 <= first_entity_position < 600
        else (-0.06 if first_entity_position > 1200 else 0.0)
    )
    return round(
        (0.30 * retrieval_score)
        + (0.16 * heading_coverage)
        + (0.30 * text_coverage)
        + exact_bonus
        + label_bonus
        + table_bonus
        + evidence_bonus
        + explicit_table_bonus
        + enumeration_bonus
        + structured_row_bonus
        + entity_position_adjustment,
        4,
    )


def _rank_lookup_hits(
    query: str,
    hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ranked = []
    for hit in hits:
        enriched = dict(hit)
        enriched["mini_score"] = _lookup_score(query, enriched)
        ranked.append(enriched)
    ranked.sort(
        key=lambda hit: (
            hit.get("mini_score", 0.0),
            hit.get("similarity", 0.0),
        ),
        reverse=True,
    )
    return ranked


def _is_structured_lookup_evidence(
    query: str,
    hit: dict[str, Any],
) -> bool:
    """Keep real grading tables that the general nav-marker filter can mislabel."""
    text = str(hit.get("text") or "")
    terms = _distinctive_terms(query)
    structured_fields = len(
        re.findall(
            r"\b(?:description|definition|criteria|finding|points?|score|"
            r"function|extent)\s*=",
            text,
            re.IGNORECASE,
        )
    )
    return bool(
        (structured_fields >= 3 or text.count("=") >= 5)
        and _term_coverage(text, terms) >= 0.3
        and EVIDENCE_SIGNAL_RE.search(text)
    )


def lexical_search(
    query: str,
    *,
    n_results: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    started = time.perf_counter()
    search_query, expansions = expand_query(query)
    if _sidecar_is_fresh(MINI_FTS_PATH, MINI_FTS_MANIFEST_PATH):
        hits, search_ms = _sqlite_fts_search(
            search_query,
            n_results=n_results,
        )
        engine = "sqlite_fts5"
    else:
        table = pipeline._get_lance_table()
        hits, search_ms = pipeline._sparse_search_fts(
            table,
            search_query,
            n_results=n_results,
        )
        engine = "lancedb_fts"
    hits = [
        hit
        for hit in hits
        if (
            not pipeline._is_low_value_retrieval_hit(hit)
            or _is_structured_lookup_evidence(query, hit)
        )
    ]
    ranked = _rank_lookup_hits(query, hits)
    if expansions:
        for hit in ranked:
            combined = " ".join([
                str(hit.get("metadata", {}).get("heading") or ""),
                str(hit.get("metadata", {}).get("chapter_title") or ""),
                str(hit.get("text") or ""),
            ]).lower()
            matched = [
                alias
                for alias in expansions
                if alias.lower() in combined
            ]
            if matched:
                hit["mini_score"] = round(
                    float(hit.get("mini_score") or 0.0) + 0.22,
                    4,
                )
                hit["query_expansions"] = matched
        ranked.sort(
            key=lambda hit: (
                hit.get("mini_score", 0.0),
                hit.get("similarity", 0.0),
            ),
            reverse=True,
        )
    return ranked, {
        "search_ms": search_ms,
        "total_ms": round((time.perf_counter() - started) * 1000, 2),
        "query_expansions": expansions,
        "engine": engine,
    }


def _sqlite_connection() -> sqlite3.Connection:
    connection = getattr(_MINI_FTS_LOCAL, "connection", None)
    if connection is None:
        connection = sqlite3.connect(
            f"file:{MINI_FTS_PATH}?mode=ro&immutable=1",
            uri=True,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        _MINI_FTS_LOCAL.connection = connection
    return connection


def _sqlite_match_query(query: str) -> str:
    terms = _distinctive_terms(query)
    if not terms:
        terms = [
            token.lower()
            for token in re.findall(r"[a-zA-Z][a-zA-Z0-9-]{1,}", query)
        ]
    escaped = [f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms]
    return " OR ".join(escaped)


def _sqlite_fts_search(
    query: str,
    *,
    n_results: int,
) -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    connection = _sqlite_connection()
    rows = connection.execute(
        """
        SELECT *,
               bm25(
                   chunks,
                   0.0, 0.0, 0.0,
                   2.0, 1.5, 3.0, 1.5,
                   1.0, 2.0, 1.5,
                   0.0, 0.0, 0.0, 0.0
               ) AS rank
        FROM chunks
        WHERE chunks MATCH ?
        ORDER BY rank
        LIMIT ?
        """,
        (_sqlite_match_query(query), n_results),
    ).fetchall()
    hits = []
    for row in rows:
        raw_score = max(0.0, -float(row["rank"] or 0.0))
        similarity = raw_score / (raw_score + 1.0) if raw_score else 0.0
        page_start = int(row["page_start"]) if row["page_start"] else None
        page_end = int(row["page_end"]) if row["page_end"] else None
        citation_parts = [str(row["source_book"] or "Unknown")]
        if row["chapter_title"]:
            citation_parts.append(f"Ch: {row['chapter_title']}")
        if row["heading"] and row["heading"] != row["chapter_title"]:
            citation_parts.append(f"§ {row['heading']}")
        if page_start:
            citation_parts.append(f"p.{page_start}")
        hits.append({
            "text": str(row["child_text"] or ""),
            "similarity": round(similarity, 4),
            "fts_score": round(raw_score, 4),
            "citation": " — ".join(citation_parts),
            "source_key": str(row["source_book"] or ""),
            "parent_id": str(row["parent_id"] or ""),
            "child_id": str(row["child_id"] or ""),
            "metadata": {
                "source_book": str(row["source_book"] or ""),
                "chapter_title": str(row["chapter_title"] or ""),
                "heading": str(row["heading"] or ""),
                "section_path": str(row["section_path"] or ""),
                "page_start": page_start,
                "page_end": page_end,
                "chunk_index": int(row["chunk_index"] or 0),
                "has_table": bool(row["has_table"]),
                "subspecialty": str(row["subspecialty"] or ""),
            },
            "retrievers": ["sqlite_fts5"],
        })
    return hits, round((time.perf_counter() - started) * 1000, 2)


def _row_to_semantic_hit(row: dict[str, Any]) -> dict[str, Any]:
    distance = float(row.get("_distance", 2.0))
    similarity = 1.0 - (distance / 2.0)
    citation_parts = [str(row.get("source_book") or "Unknown")]
    chapter = str(row.get("chapter_title") or "")
    heading = str(row.get("heading") or "")
    if chapter:
        citation_parts.append(f"Ch: {chapter}")
    if heading and heading != chapter:
        citation_parts.append(f"§ {heading}")
    if row.get("page_start"):
        citation_parts.append(f"p.{row['page_start']}")
    return {
        "text": str(row.get("text") or ""),
        "similarity": round(similarity, 4),
        "citation": " — ".join(citation_parts),
        "source_key": str(row.get("source_book") or ""),
        "parent_id": str(row.get("parent_id") or ""),
        "child_id": str(row.get("child_id") or ""),
        "metadata": {
            "source_book": str(row.get("source_book") or ""),
            "chapter_title": chapter,
            "heading": heading,
            "section_path": str(row.get("section_path") or ""),
            "page_start": row.get("page_start"),
            "page_end": row.get("page_end"),
            "chunk_index": int(row.get("chunk_index") or 0),
            "has_table": bool(row.get("has_table")),
            "subspecialty": str(row.get("subspecialty") or ""),
        },
        "retrievers": ["mini_semantic"],
    }


def semantic_search(
    query: str,
    *,
    n_results: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    return semantic_search_many([query], n_results=n_results)[0]


def lexical_search_many(
    queries: list[str],
    *,
    n_results: int = 30,
    max_workers: int = 4,
) -> list[tuple[list[dict[str, Any]], dict[str, float]]]:
    """Search several short queries while sharing the open full-corpus table."""
    if not queries:
        return []
    if not MINI_FTS_PATH.exists():
        pipeline._get_lance_table()
    with ThreadPoolExecutor(
        max_workers=min(max_workers, len(queries)),
        thread_name_prefix="mini-fts",
    ) as executor:
        futures = [
            executor.submit(lexical_search, query, n_results=n_results)
            for query in queries
        ]
        return [future.result() for future in futures]


def semantic_search_many(
    queries: list[str],
    *,
    n_results: int = 30,
    max_workers: int = 4,
) -> list[tuple[list[dict[str, Any]], dict[str, float]]]:
    """Embed several lookup queries in one ONNX batch, then search the mini index."""
    if not queries:
        return []
    started = time.perf_counter()
    model_started = time.perf_counter()
    embedder = _get_embedder()
    model_ms = round((time.perf_counter() - model_started) * 1000, 2)
    embed_started = time.perf_counter()
    vectors = [
        np.asarray(vector, dtype=np.float32).tolist()
        for vector in embedder.query_embed(queries)
    ]
    embed_ms = round((time.perf_counter() - embed_started) * 1000, 2)
    table = _get_mini_table(required=True)

    def search_one(item: tuple[str, list[float]]):
        query, vector = item
        search_started = time.perf_counter()
        rows = (
            table.search(vector, vector_column_name="vector")
            .metric("cosine")
            .limit(n_results)
            .to_list()
        )
        search_ms = round((time.perf_counter() - search_started) * 1000, 2)
        rows = [
            row
            for row in rows
            if not re.search(
                r"annotated list of neurosurgical classification systems|"
                r"future directions in classifying classification systems",
                " ".join([
                    str(row.get("chapter_title") or ""),
                    str(row.get("heading") or ""),
                ]),
                re.IGNORECASE,
            )
        ]
        hits = _rank_lookup_hits(
            query,
            [_row_to_semantic_hit(row) for row in rows],
        )
        return hits, search_ms

    with ThreadPoolExecutor(
        max_workers=min(max_workers, len(queries)),
        thread_name_prefix="mini-vector",
    ) as executor:
        searched = list(executor.map(search_one, zip(queries, vectors, strict=True)))
    batch_ms = round((time.perf_counter() - started) * 1000, 2)
    return [
        (
            hits,
            {
                "model_ms": model_ms,
                "embed_batch_ms": embed_ms,
                "search_ms": search_ms,
                "batch_total_ms": batch_ms,
            },
        )
        for hits, search_ms in searched
    ]


def _fuse_hybrid_hits(
    query: str,
    lexical_hits: list[dict[str, Any]],
    semantic_hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fuse mini channels without letting a semantic-only rank swamp exact FTS."""
    scores: dict[str, float] = {}
    hit_map: dict[str, dict[str, Any]] = {}
    channel_scores: dict[str, dict[str, float]] = {}
    channels = (
        ("lexical", lexical_hits, 0.75),
        ("mini_semantic", semantic_hits, 0.25),
    )
    for channel, hits, weight in channels:
        for rank, hit in enumerate(hits, 1):
            key = pipeline._hit_key(hit)
            scores[key] = scores.get(key, 0.0) + weight / (30 + rank)
            channel_scores.setdefault(key, {})[channel] = float(
                hit.get("mini_score") or 0.0
            )
            if key not in hit_map:
                hit_map[key] = dict(hit)
                hit_map[key]["retrievers"] = []
            if channel not in hit_map[key]["retrievers"]:
                hit_map[key]["retrievers"].append(channel)

    max_rrf = max(scores.values(), default=1.0)
    fused = []
    for key, score in scores.items():
        hit = dict(hit_map[key])
        normalized_rrf = score / max_rrf if max_rrf else 0.0
        present = channel_scores[key]
        lexical_bonus = 0.08 if "lexical" in present else 0.0
        agreement_bonus = 0.04 if len(present) > 1 else 0.0
        best_channel_score = max(present.values(), default=0.0)
        hit["rrf_score"] = round(score, 6)
        hit["mini_score"] = round(
            (0.65 * best_channel_score)
            + (0.25 * normalized_rrf)
            + lexical_bonus
            + agreement_bonus,
            4,
        )
        fused.append(hit)
    fused.sort(
        key=lambda hit: (
            hit.get("mini_score", 0.0),
            hit.get("rrf_score", 0.0),
        ),
        reverse=True,
    )
    return fused


def hybrid_search(
    query: str,
    *,
    n_results: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    started = time.perf_counter()
    with ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="mini-rag",
    ) as executor:
        lexical_future = executor.submit(
            lexical_search,
            query,
            n_results=n_results,
        )
        semantic_future = executor.submit(
            semantic_search,
            query,
            n_results=n_results,
        )
        lexical_hits, lexical_timing = lexical_future.result()
        semantic_hits, semantic_timing = semantic_future.result()

    ranked = _fuse_hybrid_hits(query, lexical_hits, semantic_hits)
    return ranked, {
        "lexical_ms": lexical_timing["total_ms"],
        "semantic_ms": semantic_timing["batch_total_ms"],
        "total_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def route_query(query: str) -> dict[str, Any]:
    words = re.findall(r"[a-zA-Z0-9-]+", query)
    lookup_intent = bool(LOOKUP_INTENT_RE.search(query))
    conjunctions = len(re.findall(r"\b(?:and|versus|vs\.?)\b|[,;]", query, re.I))
    complex_query = bool(
        COMPLEX_SYNTHESIS_RE.search(query)
        or len(words) > 28
        or (len(words) > 20 and conjunctions >= 4 and not lookup_intent)
    )
    _, expansions = expand_query(query)
    if complex_query:
        route = "full"
        reason = "query requests multi-axis synthesis beyond a compact evidence packet"
    elif expansions:
        route = "lexical"
        reason = "recognized component signature expands to an exact named lookup"
    elif lookup_intent and len(words) <= 20:
        route = "lexical"
        reason = "short named lookup is suitable for exact multi-field FTS"
    else:
        route = "hybrid"
        reason = "short factual query may benefit from semantic paraphrase recovery"
    return {
        "route": route,
        "reason": reason,
        "word_count": len(words),
        "lookup_intent": lookup_intent,
        "conjunction_count": conjunctions,
        "query_expansions": expansions,
    }


def _confidence(query: str, hits: list[dict[str, Any]]) -> float:
    if not hits:
        return 0.0
    terms = _distinctive_terms(query)
    top_text = "\n".join(
        " ".join([
            str(hit.get("metadata", {}).get("heading") or ""),
            str(hit.get("text") or ""),
        ])
        for hit in hits[:2]
    )
    coverage = _term_coverage(top_text, terms)
    score = min(1.0, float(hits[0].get("mini_score") or 0.0))
    evidence = 1.0 if EVIDENCE_SIGNAL_RE.search(top_text) else 0.0
    return round((0.50 * coverage) + (0.32 * score) + (0.18 * evidence), 4)


def _compact_hits(
    query: str,
    hits: list[dict[str, Any]],
    *,
    limit: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    hits = _cluster_adjacent_hits(query, hits)
    candidates: list[tuple[dict[str, Any], str]] = []
    seen_text: set[str] = set()
    for hit in hits:
        if len(candidates) >= limit:
            break
        text = _clean_serialized_text(str(hit.get("text") or "").strip())
        key = pipeline._content_hash(text)
        if not text or key in seen_text:
            continue
        seen_text.add(key)
        candidates.append((hit, text))

    selected: list[dict[str, Any]] = []
    remaining = max_chars
    for index, (hit, text) in enumerate(candidates):
        later = candidates[index + 1:]
        if not later:
            allowance = remaining
        else:
            reserve = sum(min(len(later_text), 800) for _, later_text in later)
            allowance = max(200, remaining - reserve)
        allowance = min(len(text), allowance)
        truncated = len(text) > allowance
        compact_text = text[:allowance].rstrip()
        enriched = {
            "citation": hit.get("citation", "uncited"),
            "source_key": hit.get("source_key", ""),
            "page_start": hit.get("metadata", {}).get("page_start"),
            "heading": hit.get("metadata", {}).get("heading", ""),
            "score": hit.get("mini_score", hit.get("similarity")),
            "retrievers": hit.get("retrievers", []),
            "text": compact_text,
            "truncated": truncated,
            "cluster_chunks": hit.get("cluster_chunks", 1),
            "raw_ref": {
                "child_id": hit.get("child_id"),
                "parent_id": hit.get("parent_id"),
                "source_key": hit.get("source_key", ""),
                "chunk_index": hit.get("metadata", {}).get("chunk_index"),
            },
        }
        selected.append(enriched)
        remaining -= len(compact_text)
    return selected


def _clean_serialized_text(text: str) -> str:
    """Remove exact adjacent extraction duplicates without rewriting evidence."""
    collapsed = pipeline._collapse_repeated_prefixes(text)
    units = re.split(r"(?<=[.!?])\s+", collapsed)
    cleaned: list[str] = []
    previous = ""
    for unit in units:
        normalized = re.sub(r"\s+", " ", unit).strip().lower()
        if normalized and normalized == previous and len(normalized) >= 24:
            continue
        cleaned.append(unit)
        previous = normalized
    return " ".join(cleaned).strip()


def _join_adjacent_texts(texts: list[str]) -> str:
    joined = ""
    for text in texts:
        text = text.strip()
        if not text:
            continue
        if not joined:
            joined = text
            continue
        overlap = 0
        ceiling = min(240, len(joined), len(text))
        for size in range(ceiling, 39, -1):
            if joined[-size:].lower() == text[:size].lower():
                overlap = size
                break
        joined = f"{joined}\n\n{text[overlap:].lstrip()}".strip()
    return joined


def _cluster_adjacent_hits(
    query: str,
    hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Stitch retrieved pieces of the same table/parent before budgeting text."""
    clustered: list[dict[str, Any]] = []
    consumed: set[int] = set()
    for index, anchor in enumerate(hits):
        if index in consumed:
            continue
        parent_id = str(anchor.get("parent_id") or "")
        source_key = str(anchor.get("source_key") or "")
        anchor_chunk = int(anchor.get("metadata", {}).get("chunk_index") or 0)
        group = [(index, anchor)]
        query_terms = _distinctive_terms(query)
        covered_terms = {
            term
            for term in query_terms
            if term in str(anchor.get("text") or "").lower()
        }
        if parent_id:
            for candidate_index, candidate in enumerate(hits):
                if candidate_index == index or candidate_index in consumed:
                    continue
                if (
                    str(candidate.get("parent_id") or "") == parent_id
                    and str(candidate.get("source_key") or "") == source_key
                ):
                    candidate_chunk = int(
                        candidate.get("metadata", {}).get("chunk_index") or 0
                    )
                    candidate_text = str(candidate.get("text") or "").lower()
                    adds_query_evidence = any(
                        term not in covered_terms and term in candidate_text
                        for term in query_terms
                    )
                    if (
                        abs(candidate_chunk - anchor_chunk) <= 1
                        and adds_query_evidence
                    ):
                        group.append((candidate_index, candidate))
        group.sort(
            key=lambda item: int(
                item[1].get("metadata", {}).get("chunk_index") or 0
            )
        )
        consumed.update(item[0] for item in group)
        if len(group) == 1:
            clustered.append(dict(anchor))
            continue
        merged = dict(anchor)
        merged["text"] = _join_adjacent_texts(
            [str(item[1].get("text") or "") for item in group]
        )
        merged["mini_score"] = max(
            float(item[1].get("mini_score") or 0.0)
            for item in group
        )
        merged["retrievers"] = sorted({
            retriever
            for item in group
            for retriever in item[1].get("retrievers", [])
        })
        merged["cluster_chunks"] = len(group)
        clustered.append(merged)
    return clustered


def _finalize_packet(
    query: str,
    *,
    strategy: str,
    routing: dict[str, Any],
    hits: list[dict[str, Any]],
    timing: dict[str, float],
    limit: int,
    max_chars: int,
    forced_escalation: str = "",
) -> dict[str, Any]:
    confidence = _confidence(query, hits)
    compact = _compact_hits(
        query,
        hits,
        limit=max(1, limit),
        max_chars=max(500, max_chars),
    )
    escalation_threshold = 0.48
    escalate = bool(
        forced_escalation
        or confidence < escalation_threshold
        or not compact
    )
    reason = forced_escalation
    if not reason and confidence < escalation_threshold:
        reason = "mini evidence confidence is below the safe compact-use threshold"
    if not reason and not compact:
        reason = "mini retrieval returned no usable source passage"
    return {
        "type": "mini_rag",
        "schema_version": 1,
        "query": query,
        "strategy": strategy,
        "route": routing,
        "confidence": confidence,
        "hits": compact,
        "escalate": escalate,
        "escalation_reason": reason,
        "latency": timing,
    }


def retrieve_mini(
    query: str,
    *,
    strategy: str = "auto",
    limit: int = MINI_DEFAULT_LIMIT,
    max_chars: int = MINI_DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """Return a compact, source-traced mini-RAG packet."""
    return retrieve_many(
        [query],
        strategy=strategy,
        limit=limit,
        max_chars=max_chars,
    )[0]


def retrieve_many(
    queries: list[str],
    *,
    strategy: str = "auto",
    limit: int = MINI_DEFAULT_LIMIT,
    max_chars: int = MINI_DEFAULT_MAX_CHARS,
) -> list[dict[str, Any]]:
    """Retrieve several mini topics with deduplication and batched embeddings."""
    if strategy not in {"auto", "lexical", "semantic", "hybrid"}:
        raise ValueError(f"unknown mini-RAG strategy: {strategy}")
    normalized = [query.strip() for query in queries]
    if not normalized or any(not query for query in normalized):
        raise ValueError("mini-RAG queries must not be empty")

    started = time.perf_counter()
    unique_queries = list(dict.fromkeys(normalized))
    routes = {query: route_query(query) for query in unique_queries}
    results: dict[str, dict[str, Any]] = {}
    active = [
        query
        for query in unique_queries
        if not (strategy == "auto" and routes[query]["route"] == "full")
    ]
    for query in unique_queries:
        if strategy == "auto" and routes[query]["route"] == "full":
            results[query] = _finalize_packet(
                query,
                strategy="full",
                routing=routes[query],
                hits=[],
                timing={"total_ms": 0.0},
                limit=limit,
                max_chars=max_chars,
                forced_escalation=routes[query]["reason"],
            )

    lexical_map: dict[str, tuple[list[dict[str, Any]], dict[str, float]]] = {}
    semantic_map: dict[str, tuple[list[dict[str, Any]], dict[str, float]]] = {}
    if strategy in {"auto", "lexical", "hybrid"} and active:
        lexical_results = lexical_search_many(active)
        lexical_map = dict(zip(active, lexical_results, strict=True))

    if strategy == "semantic":
        semantic_targets = active
    elif strategy == "hybrid":
        semantic_targets = active
    elif strategy == "auto":
        semantic_targets = [
            query
            for query in active
            if (
                routes[query]["route"] == "hybrid"
                or _confidence(query, lexical_map[query][0]) < 0.70
            )
        ]
    else:
        semantic_targets = []

    semantic_error = ""
    if semantic_targets:
        try:
            semantic_results = semantic_search_many(semantic_targets)
            semantic_map = dict(
                zip(semantic_targets, semantic_results, strict=True)
            )
        except MiniRAGPreflightError as exc:
            if strategy != "auto":
                raise
            semantic_error = str(exc)

    for query in active:
        forced_escalation = ""
        if strategy == "lexical":
            hits, timing = lexical_map[query]
            selected_strategy = "lexical"
        elif strategy == "semantic":
            hits, timing = semantic_map[query]
            selected_strategy = "semantic"
        elif strategy == "hybrid":
            lexical_hits, lexical_timing = lexical_map[query]
            semantic_hits, semantic_timing = semantic_map[query]
            hits = _fuse_hybrid_hits(query, lexical_hits, semantic_hits)
            timing = {
                "lexical_ms": lexical_timing["total_ms"],
                "semantic_batch_ms": semantic_timing["batch_total_ms"],
            }
            selected_strategy = "hybrid"
        elif query in semantic_map:
            lexical_hits, lexical_timing = lexical_map[query]
            semantic_hits, semantic_timing = semantic_map[query]
            hits = _fuse_hybrid_hits(query, lexical_hits, semantic_hits)
            timing = {
                "lexical_ms": lexical_timing["total_ms"],
                "semantic_batch_ms": semantic_timing["batch_total_ms"],
            }
            selected_strategy = "hybrid"
        else:
            hits, timing = lexical_map[query]
            selected_strategy = "lexical"
            if semantic_error and (
                routes[query]["route"] == "hybrid"
                or _confidence(query, hits) < 0.70
            ):
                forced_escalation = (
                    "semantic mini-index unavailable after weak lexical retrieval: "
                    + semantic_error
                )
        results[query] = _finalize_packet(
            query,
            strategy=selected_strategy,
            routing=routes[query],
            hits=hits,
            timing=timing,
            limit=limit,
            max_chars=max_chars,
            forced_escalation=forced_escalation,
        )

    total_ms = round((time.perf_counter() - started) * 1000, 2)
    batch_meta = {
        "query_count": len(normalized),
        "unique_query_count": len(unique_queries),
        "strategy": strategy,
        "total_ms": total_ms,
        "per_query_ms": round(total_ms / max(1, len(normalized)), 2),
    }
    ordered = []
    for query in normalized:
        packet = dict(results[query])
        packet["latency"] = {
            **packet.get("latency", {}),
            "batch_total_ms": total_ms,
        }
        packet["batch"] = batch_meta
        ordered.append(packet)
    return ordered


def build_source_cards_jsonl(
    packets: list[dict[str, Any]],
    *,
    max_takeaways: int = 8,
) -> str:
    """Serialize Mini-RAG packets into the shared compact source-card shape."""
    topic_rows: list[dict[str, Any]] = []
    card_rows: list[dict[str, Any]] = []
    for topic_index, packet in enumerate(packets, 1):
        topic_id = f"M{topic_index:02d}"
        hits = packet.get("hits", [])
        topic_rows.append({
            "type": "topic_manifest",
            "topic_id": topic_id,
            "query": packet.get("query", ""),
            "route": packet.get("route", {}),
            "confidence": packet.get("confidence", 0.0),
            "escalate": bool(packet.get("escalate")),
            "escalation_reason": packet.get("escalation_reason", ""),
            "card_count": len(hits),
        })
        for card_index, hit in enumerate(hits, 1):
            text = str(hit.get("text") or "")
            card_rows.append({
                "type": "source_card",
                "topic_id": topic_id,
                "card_id": f"{topic_id}-C{card_index:02d}",
                "citation": hit.get("citation", "uncited"),
                "page_start": hit.get("page_start"),
                "takeaways": [
                    sentence[:260]
                    for sentence in pipeline._compact_sentences(
                        text,
                        max_items=max_takeaways,
                    )
                ],
                "numbers_thresholds_effects": pipeline._numbers_from_text(
                    text,
                    max_items=5,
                ),
                "truncated": bool(hit.get("truncated")),
                "raw_ref": hit.get("raw_ref", {}),
            })

    header = {
        "type": "mini_batch_source_card_manifest",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic_count": len(packets),
        "card_count": len(card_rows),
        "format": "jsonl",
        "schema": "compact",
        "source_type": "textbook_rag_mini",
    }
    rows = [header, *topic_rows, *card_rows]
    return "\n".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        for row in rows
    ) + "\n"


def format_context(packet: dict[str, Any]) -> str:
    """Render a compact source packet suitable for an agent prompt."""
    if packet.get("escalate") and not packet.get("hits"):
        return (
            f"Mini-RAG escalation: {packet.get('escalation_reason') or 'full retrieval required'}\n"
        )
    lines = [
        f"Mini-RAG query: {packet['query']}",
        (
            f"Strategy: {packet['strategy']} | "
            f"confidence={packet.get('confidence', 0):.2f}"
        ),
        "",
    ]
    for index, hit in enumerate(packet.get("hits", []), 1):
        lines.append(f"[M{index}] {hit['citation']}")
        lines.append(hit["text"])
        lines.append("")
    if packet.get("escalate"):
        lines.append(
            "Escalate to full RAG before relying on this evidence: "
            + packet.get("escalation_reason", "low confidence")
        )
    return "\n".join(lines).rstrip() + "\n"
