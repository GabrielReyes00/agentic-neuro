"""Read-only structural health for the learner-memory SQLite store."""

from __future__ import annotations

import sqlite3


def database_health(conn: sqlite3.Connection) -> dict[str, object]:
    quick_check = [str(row[0]) for row in conn.execute("PRAGMA quick_check")]
    foreign_key_violations = [
        {
            "table": str(row[0]),
            "rowid": int(row[1]),
            "parent": str(row[2]),
            "foreign_key_index": int(row[3]),
        }
        for row in conn.execute("PRAGMA foreign_key_check")
    ]
    identity = conn.execute(
        """SELECT COUNT(*) AS bound_rows,
                  COUNT(DISTINCT inventory_concept_id) AS unique_ids
             FROM concepts
            WHERE COALESCE(inventory_concept_id, '') != ''"""
    ).fetchone()
    bound_rows = int(identity["bound_rows"] or 0)
    unique_ids = int(identity["unique_ids"] or 0)
    return {
        "ok": quick_check == ["ok"] and not foreign_key_violations,
        "schema_version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
        "foreign_keys_enabled": bool(conn.execute("PRAGMA foreign_keys").fetchone()[0]),
        "quick_check": quick_check,
        "foreign_key_violations": foreign_key_violations,
        "canonical_identity": {
            "bound_local_rows": bound_rows,
            "unique_inventory_concepts": unique_ids,
            "duplicate_envelope_rows": bound_rows - unique_ids,
        },
    }
