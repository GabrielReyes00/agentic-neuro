#!/usr/bin/env python3
"""Read-only integrity and lifecycle health for Agentic Neuro data stores."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from runtime_paths import (
        ANKI_CACHE_DB,
        CONCEPT_INVENTORY_DB,
        DATA_DIR,
        MINI_FTS_DB,
        REPO_ROOT,
        RUNTIME_DIR,
        STUDY_MEMORY_DB,
        VAULT_ROOT,
        VAULT_INDEX_DB,
        VAULT_LANCE_DIR,
    )
    from store_contracts import (
        SQLITE_SCHEMA_VERSIONS,
        VAULT_BINARY_COMPONENT,
        VAULT_MARKDOWN_COMPONENT,
    )
except (ImportError, ModuleNotFoundError):  # pragma: no cover - package import
    from .runtime_paths import (
        ANKI_CACHE_DB,
        CONCEPT_INVENTORY_DB,
        DATA_DIR,
        MINI_FTS_DB,
        REPO_ROOT,
        RUNTIME_DIR,
        STUDY_MEMORY_DB,
        VAULT_ROOT,
        VAULT_INDEX_DB,
        VAULT_LANCE_DIR,
    )
    from .store_contracts import (
        SQLITE_SCHEMA_VERSIONS,
        VAULT_BINARY_COMPONENT,
        VAULT_MARKDOWN_COMPONENT,
    )

@dataclass(frozen=True)
class SQLiteSpec:
    name: str
    path: Path
    expected_version: int
    required_tables: tuple[str, ...]
    required_components: tuple[str, ...] = ()


def sqlite_specs() -> tuple[SQLiteSpec, ...]:
    return (
        SQLiteSpec(
            "study_memory",
            STUDY_MEMORY_DB,
            SQLITE_SCHEMA_VERSIONS["study_memory"],
            (
                "sessions", "exchanges", "claim_results", "claim_state",
                "turn_assessments", "claim_assessments",
                "study_runtime_sessions", "learner_profile", "artifact_maps",
            ),
        ),
        SQLiteSpec(
            "concept_inventory",
            CONCEPT_INVENTORY_DB,
            SQLITE_SCHEMA_VERSIONS["concept_inventory"],
            ("domains", "topics", "concepts", "edges", "meta"),
        ),
        SQLiteSpec(
            "vault_index",
            VAULT_INDEX_DB,
            SQLITE_SCHEMA_VERSIONS["vault_index"],
            ("vault_notes", "vault_sections", "vault_files", "store_meta"),
            (VAULT_MARKDOWN_COMPONENT, VAULT_BINARY_COMPONENT),
        ),
        SQLiteSpec(
            "anki_vector_cache",
            ANKI_CACHE_DB,
            SQLITE_SCHEMA_VERSIONS["anki_vector_cache"],
            ("card_vectors", "query_embeddings"),
        ),
        SQLiteSpec(
            "mini_rag_fts",
            MINI_FTS_DB,
            SQLITE_SCHEMA_VERSIONS["mini_rag_fts"],
            ("chunks",),
        ),
    )


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def check_sqlite(spec: SQLiteSpec) -> dict[str, Any]:
    """Inspect one SQLite store without creating, migrating, or journaling it."""
    path = spec.path.expanduser()
    result: dict[str, Any] = {
        "name": spec.name,
        "path": str(path),
        "exists": path.is_file(),
        "expected_schema_version": spec.expected_version,
    }
    if not path.is_file():
        result.update({"ok": True, "status": "not_provisioned"})
        return result

    result["size_bytes"] = path.stat().st_size
    try:
        with _readonly_connection(path) as connection:
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            foreign_key_violations = len(
                connection.execute("PRAGMA foreign_key_check").fetchall()
            )
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            }
            missing_tables = sorted(set(spec.required_tables) - tables)
            component_versions: dict[str, int] = {}
            if spec.required_components and "store_meta" in tables:
                component_versions = {
                    str(row[0]): int(row[1])
                    for row in connection.execute(
                        "SELECT component, schema_version FROM store_meta"
                    )
                }
            missing_components = sorted(
                component
                for component in spec.required_components
                if component_versions.get(component) != spec.expected_version
            )
        ok = (
            quick_check == "ok"
            and foreign_key_violations == 0
            and version == spec.expected_version
            and not missing_tables
            and not missing_components
        )
        result.update(
            {
                "ok": ok,
                "status": "ok" if ok else "needs_attention",
                "quick_check": quick_check,
                "foreign_key_violations": foreign_key_violations,
                "schema_version": version,
                "missing_tables": missing_tables,
                "component_versions": component_versions,
                "missing_components": missing_components,
            }
        )
    except sqlite3.Error as exc:
        result.update({"ok": False, "status": "unreadable", "error": str(exc)})
    return result


def _lance_status(name: str, root: Path, table: str) -> dict[str, Any]:
    table_dir = root / f"{table}.lance"
    manifests = list((table_dir / "_versions").glob("*.manifest")) if table_dir.is_dir() else []
    return {
        "name": name,
        "root": str(root),
        "table": table,
        "exists": table_dir.is_dir(),
        "status": "available" if table_dir.is_dir() else "not_provisioned",
        "manifest_count": len(manifests),
        "size_bytes": sum(
            path.stat().st_size for path in table_dir.rglob("*") if path.is_file()
        ) if table_dir.is_dir() else 0,
    }


def session_lifecycle_status(root: Path = RUNTIME_DIR) -> dict[str, Any]:
    if not root.is_dir():
        return {
            "root": str(root),
            "exists": False,
            "files": 0,
            "bytes": 0,
            "run_manifests": 0,
            "status": "not_provisioned",
        }
    files = [path for path in root.rglob("*") if path.is_file()]
    manifests = [path for path in files if path.name == "run_manifest.json"]
    return {
        "root": str(root),
        "exists": True,
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "run_manifests": len(manifests),
        "unmanaged_files": len(files) - len(manifests),
        "status": "managed" if files and manifests else ("empty" if not files else "legacy_unmanaged"),
    }


def system_health() -> dict[str, Any]:
    sqlite = [check_sqlite(spec) for spec in sqlite_specs()]
    textbook_root = Path(os.environ.get("NEURO_LANCE_DIR", REPO_ROOT)).expanduser()
    textbook_table = os.environ.get("NEURO_LANCE_TABLE", "neurosurgery_v4")
    mini_root = Path(
        os.environ.get("NEURO_MINI_LANCE_DIR", DATA_DIR / "mini_rag.lance")
    ).expanduser()
    vault_root = VAULT_LANCE_DIR
    lance = [
        _lance_status("textbook", textbook_root, textbook_table),
        _lance_status("mini_rag", mini_root, os.environ.get("NEURO_MINI_TABLE", "lookup_chunks")),
        _lance_status("vault", vault_root, os.environ.get("NEURO_VAULT_LANCE_TABLE", "vault_notes")),
    ]
    sessions = session_lifecycle_status()
    try:
        try:
            from vault_index import vault_freshness_status
        except ModuleNotFoundError:  # package import in tests
            from .vault_index import vault_freshness_status

        vault_freshness = vault_freshness_status(
            vault_root=VAULT_ROOT,
            db_path=VAULT_INDEX_DB,
        )
    except Exception as exc:  # a health check must surface, not hide, parser drift
        vault_freshness = {"ok": False, "status": "unreadable", "error": str(exc)}
    legacy_vault_table = REPO_ROOT / "neurosurgery_v4.lance" / "vault_notes.lance"
    legacy_vault_present = legacy_vault_table.is_dir()
    vault_boundary = {
        "active_root": str(vault_root),
        "isolated_from_textbook": vault_root.resolve() != legacy_vault_table.parent.resolve(),
        "forbidden_legacy_path": str(legacy_vault_table),
        "forbidden_legacy_path_present": legacy_vault_present,
        "status": (
            "legacy_copy_detected"
            if legacy_vault_present
            else "isolated"
            if vault_root.resolve() != legacy_vault_table.parent.resolve()
            else "co_located"
        ),
    }
    present_failures = [item["name"] for item in sqlite if item["exists"] and not item["ok"]]
    if VAULT_INDEX_DB.is_file() and not vault_freshness.get("ok"):
        present_failures.append("vault_index_freshness")
    if legacy_vault_present:
        present_failures.append("forbidden_legacy_vault_copy")
    return {
        "ok": not present_failures,
        "sqlite": sqlite,
        "lance": lance,
        "storage_boundaries": {"vault_vectors": vault_boundary},
        "vault_freshness": vault_freshness,
        "sessions": sessions,
        "failures": present_failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = system_health()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"system health: {'PASS' if report['ok'] else 'FAIL'}")
        for item in report["sqlite"]:
            print(f"- sqlite/{item['name']}: {item['status']}")
        for item in report["lance"]:
            print(f"- lance/{item['name']}: {item['status']}")
        print(f"- vault freshness: {report['vault_freshness']['status']}")
        print(f"- sessions: {report['sessions']['status']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
