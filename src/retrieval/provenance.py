"""Compact, truthful provenance for textbook retrieval outputs."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
CORPUS_MANIFEST_PATH = DATA_DIR / "rag_corpus_manifest.json"
INVENTORY_PATH = DATA_DIR / "rag_textbook_sources.json"
RETRIEVAL_PIPELINE_VERSION = "2"

_RESEARCH_METHODS_RE = re.compile(r"grant writing|nih grant", re.IGNORECASE)
_HISTORY_RE = re.compile(r"history of neurosurgery", re.IGNORECASE)
_ANATOMY_RE = re.compile(r"anatomy|anatomical", re.IGNORECASE)
_OPERATIVE_RE = re.compile(r"operative|surgical techniques", re.IGNORECASE)
_BOARD_REVIEW_RE = re.compile(r"board review|rounds question", re.IGNORECASE)
_RESEARCH_QUERY_RE = re.compile(
    r"\b(?:grant|nih|specific aims|research proposal|study section|funding application)\b",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()


@lru_cache(maxsize=1)
def corpus_manifest() -> dict[str, Any]:
    try:
        payload = json.loads(CORPUS_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def source_role(source_book: object) -> str:
    """Classify a source's permissible evidence role without editing the corpus."""
    name = str(source_book or "")
    if _RESEARCH_METHODS_RE.search(name):
        return "research_methodology"
    if _HISTORY_RE.search(name):
        return "historical_context"
    if _ANATOMY_RE.search(name):
        return "anatomic_reference"
    if _OPERATIVE_RE.search(name):
        return "operative_reference"
    if _BOARD_REVIEW_RE.search(name):
        return "educational_review"
    return "clinical_reference"


def source_allowed_for_query(source_book: object, query: str) -> bool:
    """Keep nonclinical grant-writing books out of clinical retrieval packets."""
    role = source_role(source_book)
    return role != "research_methodology" or bool(_RESEARCH_QUERY_RE.search(query or ""))


def enrich_hit(hit: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(hit)
    source = enriched.get("source_key") or (enriched.get("metadata") or {}).get("source_book")
    enriched["source_role"] = source_role(source)
    return enriched


def retrieval_provenance(
    *,
    route: str,
    reranker_key: str = "",
    reranker_model: str = "",
    embedding_model: str = "",
    table: Any | None = None,
    strategy: str = "",
) -> dict[str, Any]:
    """Return compact corpus/model lineage suitable for JSON and JSONL outputs."""
    manifest = corpus_manifest()
    corpus = manifest.get("corpus") if isinstance(manifest.get("corpus"), dict) else {}
    table_version = int(getattr(table, "version", 0) or corpus.get("table_version", 0) or 0)
    inventory_hash = _sha256(INVENTORY_PATH)
    identity = {
        "table": str(corpus.get("table") or "neurosurgery_v4"),
        "table_version": table_version,
        "inventory_sha256": inventory_hash,
        "manifest_sha256": str(corpus.get("manifest_sha256") or ""),
        "ingestion_version": str(manifest.get("ingestion_pipeline_version") or "unrecorded"),
    }
    identity["fingerprint"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    models: dict[str, Any] = {}
    if embedding_model:
        models["embedding"] = embedding_model
    if reranker_key or reranker_model:
        models["reranker"] = {
            "key": reranker_key,
            "model": reranker_model or reranker_key,
        }
    return {
        "schema_version": 1,
        "retrieval_pipeline_version": RETRIEVAL_PIPELINE_VERSION,
        "route": route,
        "strategy": strategy,
        "corpus": identity,
        "models": models,
        "source_role_policy": "clinical queries exclude research_methodology sources",
    }
