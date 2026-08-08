#!/usr/bin/env python3
"""Audit repository-local backups, disposable outputs, and artifact lifecycle drift."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]

ACTIVE_DATABASE_FILES = frozenset(
    {
        "data/study_memory.db",
        "data/concept_inventory.db",
        "data/vault_index.db",
        "data/anki_vector_cache.db",
        "data/mini_rag_fts.db",
    }
)
ACTIVE_LANCE_DIRS = frozenset(
    {
        "neurosurgery_v4.lance",
        "data/mini_rag.lance",
        "data/mini_rag.lance/lookup_chunks.lance",
        "data/vault_index.lance",
        "data/vault_index.lance/vault_notes.lance",
    }
)
ACTIVE_LANCE_STORES = frozenset(
    {
        "neurosurgery_v4.lance",
        "data/mini_rag.lance",
        "data/vault_index.lance",
    }
)
SKIP_DIR_NAMES = frozenset({".git", ".venv", "node_modules", ".cache", "models"})
STANDARD_DISPOSABLE_DIRS = (
    ".pytest_cache",
    "build",
    "agentic_neuro_harness.egg-info",
    "tmp",
)
LEGACY_CANDIDATES = (
    "data/Sessions/vault_redesign_2026-07-29",
    "data/Sessions/rag_audit",
    "data/Sessions/figures",
    "data/artifacts/session-audits",
    "data/runtime/reports/hooks",
)


def _relative(path: Path, root: Path) -> str:
    return path.absolute().relative_to(root.absolute()).as_posix()


def _tree_size(path: Path) -> tuple[int, int]:
    if path.is_file():
        return 1, path.stat().st_size
    files = 0
    size = 0
    for child in path.rglob("*"):
        if child.is_file():
            files += 1
            try:
                size += child.stat().st_size
            except OSError:
                continue
    return files, size


def _record(path: Path, root: Path) -> dict[str, Any]:
    files, size = _tree_size(path)
    return {"path": _relative(path, root), "files": files, "bytes": size}


def _walk(root: Path) -> Iterable[tuple[Path, list[str], list[str]]]:
    for current, directories, files in os.walk(root):
        current_path = Path(current)
        directories[:] = [
            name
            for name in directories
            if name not in SKIP_DIR_NAMES
            and not (current_path == root / "data" and name == "models")
        ]
        yield current_path, directories, files


def audit(root: Path = REPO_ROOT) -> dict[str, Any]:
    root = root.expanduser().resolve()
    database_copies: list[dict[str, Any]] = []
    unexpected_lance: list[dict[str, Any]] = []
    ds_store: list[dict[str, Any]] = []
    pycache: list[dict[str, Any]] = []

    for current, directories, files in _walk(root):
        for filename in files:
            path = current / filename
            relative = _relative(path, root)
            if filename in {".DS_Store"}:
                ds_store.append(_record(path, root))
            if path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
                if relative not in ACTIVE_DATABASE_FILES:
                    database_copies.append(_record(path, root))
        for dirname in directories:
            path = current / dirname
            relative = _relative(path, root)
            if dirname == "__pycache__":
                pycache.append(_record(path, root))
            if dirname.endswith(".lance") and relative not in ACTIVE_LANCE_DIRS:
                unexpected_lance.append(_record(path, root))

    standard: list[dict[str, Any]] = []
    for relative in STANDARD_DISPOSABLE_DIRS:
        path = root / relative
        if path.exists():
            standard.append(_record(path, root))
    standard.extend(ds_store)
    standard.extend(pycache)

    sessions = root / "data" / "Sessions"
    loose_session: list[dict[str, Any]] = []
    if sessions.is_dir():
        for path in sessions.iterdir():
            if (
                path.name.startswith("knowledge_map_")
                or path.name.startswith("tmp_")
                or path.name in {"scratch_context.md", "frontier_cache.md", "fastembed_cache"}
            ):
                loose_session.append(_record(path, root))

    legacy = [
        _record(root / relative, root)
        for relative in LEGACY_CANDIDATES
        if (root / relative).exists()
    ]

    active = {
        "sqlite": [
            {"path": path, "exists": (root / path).is_file()}
            for path in sorted(ACTIVE_DATABASE_FILES)
        ],
        "lance": [
            {"path": path, "exists": (root / path).is_dir()}
            for path in sorted(ACTIVE_LANCE_STORES)
        ],
    }
    missing_active = [
        item["path"]
        for group in active.values()
        for item in group
        if not item["exists"]
    ]
    missing_active.extend(
        path for path in sorted(ACTIVE_LANCE_DIRS) if not (root / path).is_dir()
    )
    missing_active = sorted(set(missing_active))
    violations = {
        "database_copies": database_copies,
        "unexpected_lance": unexpected_lance,
        "loose_session_transients": loose_session,
    }
    violation_count = sum(len(items) for items in violations.values())
    return {
        "root": str(root),
        "ok": violation_count == 0,
        "active_stores": active,
        "missing_active_paths": missing_active,
        "violations": violations,
        "violation_count": violation_count,
        "standard_disposable": standard,
        "legacy_candidates": legacy,
        "summary": {
            "database_copy_count": len(database_copies),
            "unexpected_lance_count": len(unexpected_lance),
            "loose_session_transient_count": len(loose_session),
            "standard_disposable_count": len(standard),
            "legacy_candidate_count": len(legacy),
            "standard_disposable_bytes": sum(item["bytes"] for item in standard),
            "legacy_candidate_bytes": sum(item["bytes"] for item in legacy),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = audit(args.root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if (not args.check or report["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
