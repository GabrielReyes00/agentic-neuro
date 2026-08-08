#!/usr/bin/env python3
"""Idempotent schema-version migrations for rebuildable local stores."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    import concept_inventory
    from runtime_paths import (
        ANKI_CACHE_DB,
        CONCEPT_INVENTORY_DB,
        MINI_FTS_DB,
        STUDY_MEMORY_DB,
        VAULT_INDEX_DB,
    )
    from store_contracts import (
        ANKI_CACHE_SCHEMA_VERSION,
        MINI_FTS_SCHEMA_VERSION,
        VAULT_BINARY_COMPONENT,
        VAULT_INDEX_SCHEMA_VERSION,
        VAULT_MARKDOWN_COMPONENT,
    )
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from . import concept_inventory
    from .runtime_paths import (
        ANKI_CACHE_DB,
        CONCEPT_INVENTORY_DB,
        MINI_FTS_DB,
        STUDY_MEMORY_DB,
        VAULT_INDEX_DB,
    )
    from .store_contracts import (
        ANKI_CACHE_SCHEMA_VERSION,
        MINI_FTS_SCHEMA_VERSION,
        VAULT_BINARY_COMPONENT,
        VAULT_INDEX_SCHEMA_VERSION,
        VAULT_MARKDOWN_COMPONENT,
    )


class MigrationError(RuntimeError):
    """Raised when a store cannot be safely version-stamped in place."""


def stamp_sqlite_version(
    path: Path,
    *,
    version: int,
    required_tables: tuple[str, ...],
    components: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Stamp a compatible existing schema; never invent missing domain tables."""
    if not path.is_file():
        return {"ok": True, "path": str(path), "status": "not_provisioned"}
    with sqlite3.connect(path) as connection:
        quick = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if quick != "ok":
            raise MigrationError(f"{path}: quick_check failed: {quick}")
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        missing = sorted(set(required_tables) - tables)
        if missing:
            raise MigrationError(f"{path}: required tables missing: {', '.join(missing)}")
        if components:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS store_meta (
                       component TEXT PRIMARY KEY,
                       schema_version INTEGER NOT NULL,
                       updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                   )"""
            )
            for component in components:
                connection.execute(
                    """INSERT INTO store_meta (component, schema_version, updated_at)
                       VALUES (?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(component) DO UPDATE SET
                         schema_version=excluded.schema_version,
                         updated_at=CURRENT_TIMESTAMP""",
                    (component, version),
                )
        connection.execute(f"PRAGMA user_version={int(version)}")
        connection.commit()
    return {"ok": True, "path": str(path), "status": "versioned", "schema_version": version}


def upgrade_all() -> dict[str, Any]:
    stores: list[dict[str, Any]] = []
    if CONCEPT_INVENTORY_DB.is_file():
        stores.append(concept_inventory.build_db(db_path=CONCEPT_INVENTORY_DB))
    else:
        stores.append({"ok": True, "path": str(CONCEPT_INVENTORY_DB), "status": "not_provisioned"})
    stores.append(
        stamp_sqlite_version(
            VAULT_INDEX_DB,
            version=VAULT_INDEX_SCHEMA_VERSION,
            required_tables=("vault_notes", "vault_sections", "vault_files"),
            components=(VAULT_MARKDOWN_COMPONENT, VAULT_BINARY_COMPONENT),
        )
    )
    stores.append(
        stamp_sqlite_version(
            ANKI_CACHE_DB,
            version=ANKI_CACHE_SCHEMA_VERSION,
            required_tables=("card_vectors", "query_embeddings"),
        )
    )
    stores.append(
        stamp_sqlite_version(
            MINI_FTS_DB,
            version=MINI_FTS_SCHEMA_VERSION,
            required_tables=("chunks",),
        )
    )
    # Study memory owns real migrations and is intentionally not stamped here.
    stores.append(
        {
            "ok": True,
            "path": str(STUDY_MEMORY_DB),
            "status": "owned_by_study_memory",
        }
    )
    return {"ok": all(item.get("ok", False) for item in stores), "stores": stores}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply compatible version migrations")
    args = parser.parse_args()
    if not args.apply:
        parser.error("no mutation requested; pass --apply after taking appropriate backups")
    try:
        result = upgrade_all()
    except (MigrationError, sqlite3.Error) as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

