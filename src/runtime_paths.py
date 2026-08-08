"""Central runtime-path configuration for mutable local state.

Repository code is imported both as top-level modules (the CLI compatibility
surface) and through the ``src`` package (tests and library callers).  Keeping
mutable defaults here gives both shapes the same environment overrides and
lets tests redirect every cache/run artifact before source modules import.
"""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("NEURO_DATA_DIR", REPO_ROOT / "data")).expanduser()
RUNTIME_DIR = Path(
    os.environ.get("NEURO_RUNTIME_DIR", DATA_DIR / "Sessions")
).expanduser()
EPHEMERAL_DIR = Path(
    os.environ.get("NEURO_EPHEMERAL_DIR", DATA_DIR / "runtime")
).expanduser()
STUDY_MAP_DIR = Path(
    os.environ.get("NEURO_STUDY_MAP_DIR", EPHEMERAL_DIR / "study_maps")
).expanduser()
RETRIEVAL_RUNTIME_DIR = Path(
    os.environ.get("NEURO_RETRIEVAL_RUNTIME_DIR", EPHEMERAL_DIR / "retrieval")
).expanduser()
FASTEMBED_CACHE_DIR = Path(
    os.environ.get("NEURO_FASTEMBED_CACHE_DIR", DATA_DIR / "fastembed_cache")
).expanduser()
ANKI_CACHE_DB = Path(
    os.environ.get("NEURO_ANKI_CACHE_DB", DATA_DIR / "anki_vector_cache.db")
).expanduser()
ANKI_QUEUE_PATH = Path(
    os.environ.get("NEURO_ANKI_QUEUE_PATH", RUNTIME_DIR / "anki_queue.jsonl")
).expanduser()
STUDY_MEMORY_DB = Path(
    os.environ.get("NEURO_STUDY_MEMORY_DB", DATA_DIR / "study_memory.db")
).expanduser()
CONCEPT_INVENTORY_DB = Path(
    os.environ.get("NEURO_CONCEPT_INVENTORY_DB", DATA_DIR / "concept_inventory.db")
).expanduser()
VAULT_INDEX_DB = Path(
    os.environ.get("NEURO_VAULT_INDEX_DB", DATA_DIR / "vault_index.db")
).expanduser()
VAULT_LANCE_DIR = Path(
    os.environ.get("NEURO_VAULT_LANCE_DIR", DATA_DIR / "vault_index.lance")
).expanduser()
VAULT_ROOT = Path(
    os.environ.get(
        "NEURO_VAULT_ROOT",
        "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro",
    )
).expanduser()
MINI_FTS_DB = Path(
    os.environ.get("NEURO_MINI_FTS_PATH", DATA_DIR / "mini_rag_fts.db")
).expanduser()
