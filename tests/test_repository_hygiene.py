from __future__ import annotations

import tempfile
from pathlib import Path

from src.repository_hygiene import ACTIVE_DATABASE_FILES, ACTIVE_LANCE_DIRS, audit


def _provision_active(root: Path) -> None:
    for relative in ACTIVE_DATABASE_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    for relative in ACTIVE_LANCE_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)


def test_hygiene_accepts_only_canonical_active_stores() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _provision_active(root)
        report = audit(root)
        assert report["ok"], report


def test_hygiene_rejects_backup_store_and_loose_session_temp() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _provision_active(root)
        backup = root / "data" / "backups" / "study_memory.before.db"
        backup.parent.mkdir(parents=True)
        backup.touch()
        legacy_lance = root / "neurosurgery_v4.lance" / "vault_notes.lance"
        legacy_lance.mkdir()
        loose = root / "data" / "Sessions" / "tmp_once.json"
        loose.parent.mkdir(parents=True)
        loose.write_text("{}", encoding="utf-8")

        report = audit(root)
        assert not report["ok"]
        assert report["summary"]["database_copy_count"] == 1
        assert report["summary"]["unexpected_lance_count"] == 1
        assert report["summary"]["loose_session_transient_count"] == 1


def test_hygiene_reports_rebuildable_debris_without_failing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _provision_active(root)
        cache = root / ".pytest_cache"
        cache.mkdir()
        (cache / "README.md").write_text("cache", encoding="utf-8")
        report = audit(root)
        assert report["ok"], report
        assert report["summary"]["standard_disposable_count"] == 1
