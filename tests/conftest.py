"""Pytest-wide isolation for mutable runtime artifacts.

Most unit tests already inject temporary databases, but source modules used to
retain production defaults for session maps and the rebuildable Anki cache.
Set the environment before test-module collection so subprocesses and imported
constants share one disposable runtime root.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


_TEST_RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="agentic-neuro-tests-"))
os.environ["NEURO_RUNTIME_DIR"] = str(_TEST_RUNTIME_ROOT / "runs")
os.environ["NEURO_EPHEMERAL_DIR"] = str(_TEST_RUNTIME_ROOT / "runtime")
os.environ["NEURO_STUDY_MAP_DIR"] = str(_TEST_RUNTIME_ROOT / "runtime" / "study_maps")
os.environ["NEURO_RETRIEVAL_RUNTIME_DIR"] = str(
    _TEST_RUNTIME_ROOT / "runtime" / "retrieval"
)
os.environ["NEURO_FASTEMBED_CACHE_DIR"] = str(_TEST_RUNTIME_ROOT / "fastembed_cache")
os.environ["NEURO_STUDY_MEMORY_DB"] = str(_TEST_RUNTIME_ROOT / "study_memory.db")
os.environ["NEURO_CONCEPT_INVENTORY_DB"] = str(
    _TEST_RUNTIME_ROOT / "concept_inventory.db"
)
os.environ["NEURO_VAULT_INDEX_DB"] = str(_TEST_RUNTIME_ROOT / "vault_index.db")
os.environ["NEURO_ANKI_CACHE_DB"] = str(_TEST_RUNTIME_ROOT / "anki_vector_cache.db")
os.environ["NEURO_ANKI_QUEUE_PATH"] = str(_TEST_RUNTIME_ROOT / "anki_queue.jsonl")
os.environ["NEURO_MINI_FTS_PATH"] = str(_TEST_RUNTIME_ROOT / "mini_rag_fts.db")
os.environ["NEURO_MINI_LANCE_DIR"] = str(_TEST_RUNTIME_ROOT / "mini_rag.lance")
os.environ["NEURO_VAULT_LANCE_DIR"] = str(_TEST_RUNTIME_ROOT / "vault_index.lance")


def pytest_sessionfinish(session, exitstatus) -> None:  # type: ignore[no-untyped-def]
    del session, exitstatus
    shutil.rmtree(_TEST_RUNTIME_ROOT, ignore_errors=True)
