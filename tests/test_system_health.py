from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import system_health as health_module
from src.system_health import SQLiteSpec, check_sqlite, session_lifecycle_status
from src.store_migrations import MigrationError, stamp_sqlite_version


class SystemHealthTests(unittest.TestCase):
    def test_sqlite_health_is_read_only_and_version_aware(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "store.db"
            with sqlite3.connect(db_path) as connection:
                connection.execute("CREATE TABLE required (id INTEGER PRIMARY KEY)")
                connection.execute("PRAGMA user_version=3")
            before = db_path.read_bytes()
            report = check_sqlite(SQLiteSpec("fixture", db_path, 3, ("required",)))
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["schema_version"], 3)
            self.assertEqual(before, db_path.read_bytes())

    def test_sqlite_health_reports_schema_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "store.db"
            with sqlite3.connect(db_path) as connection:
                connection.execute("CREATE TABLE wrong (id INTEGER PRIMARY KEY)")
                connection.execute("PRAGMA user_version=1")
            report = check_sqlite(SQLiteSpec("fixture", db_path, 2, ("required",)))
            self.assertFalse(report["ok"])
            self.assertEqual(report["status"], "needs_attention")
            self.assertEqual(report["missing_tables"], ["required"])

    def test_missing_store_is_not_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "missing.db"
            report = check_sqlite(SQLiteSpec("fixture", db_path, 1, ("required",)))
            self.assertTrue(report["ok"])
            self.assertEqual(report["status"], "not_provisioned")
            self.assertFalse(db_path.exists())

    def test_session_status_distinguishes_managed_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "run").mkdir()
            (root / "run" / "run_manifest.json").write_text("{}")
            (root / "run" / "artifact.txt").write_text("evidence")
            report = session_lifecycle_status(root)
            self.assertEqual(report["files"], 2)
            self.assertEqual(report["run_manifests"], 1)
            self.assertEqual(report["status"], "managed")

    def test_version_migration_refuses_incompatible_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "store.db"
            with sqlite3.connect(db_path) as connection:
                connection.execute("CREATE TABLE wrong (id INTEGER PRIMARY KEY)")
            with self.assertRaises(MigrationError):
                stamp_sqlite_version(
                    db_path,
                    version=2,
                    required_tables=("required",),
                )
            with sqlite3.connect(db_path) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_legacy_vault_vector_copy_is_a_health_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root / "data" / "vault_index.lance"
            active.mkdir(parents=True)
            legacy = root / "neurosurgery_v4.lance" / "vault_notes.lance"
            legacy.mkdir(parents=True)
            lance_result = {
                "name": "fixture",
                "root": str(root),
                "table": "fixture",
                "exists": True,
                "status": "available",
                "size_bytes": 0,
                "manifest_count": 1,
            }
            with patch.object(health_module, "REPO_ROOT", root), patch.object(
                health_module, "VAULT_LANCE_DIR", active
            ), patch.object(health_module, "RUNTIME_DIR", root / "runtime"), patch.object(
                health_module, "sqlite_specs", return_value=[]
            ), patch.object(health_module, "_lance_status", return_value=lance_result):
                report = health_module.system_health()
                self.assertFalse(report["ok"])
                self.assertIn("forbidden_legacy_vault_copy", report["failures"])
                self.assertEqual(
                    report["storage_boundaries"]["vault_vectors"]["status"],
                    "legacy_copy_detected",
                )

    def test_stale_active_vault_index_is_a_health_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active_lance = root / "data" / "vault_index.lance"
            active_lance.mkdir(parents=True)
            vault_db = root / "data" / "vault_index.db"
            vault_db.parent.mkdir(parents=True, exist_ok=True)
            vault_db.touch()
            lance_result = {
                "name": "fixture", "root": str(root), "table": "fixture",
                "exists": True, "status": "available", "size_bytes": 0,
                "manifest_count": 1,
            }
            with patch.object(health_module, "REPO_ROOT", root), patch.object(
                health_module, "VAULT_LANCE_DIR", active_lance
            ), patch.object(health_module, "VAULT_INDEX_DB", vault_db), patch.object(
                health_module, "VAULT_ROOT", root / "vault"
            ), patch.object(health_module, "RUNTIME_DIR", root / "runtime"), patch.object(
                health_module, "sqlite_specs", return_value=[]
            ), patch.object(health_module, "_lance_status", return_value=lance_result), patch(
                "src.vault_index.vault_freshness_status",
                return_value={"ok": False, "status": "stale", "counts": {"stale": 1}},
            ):
                report = health_module.system_health()
            self.assertFalse(report["ok"])
            self.assertIn("vault_index_freshness", report["failures"])


if __name__ == "__main__":
    unittest.main()
