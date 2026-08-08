from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.run_artifacts import (
    audit_runtime,
    prune_run_transients,
    register_artifact,
    retention_plan,
    start_run,
    transition_run,
)


class RunArtifactTests(unittest.TestCase):
    def test_manifest_lifecycle_and_relative_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            started = start_run("generate-report", "Case 01", title="Case", root=root)
            run_dir = Path(started["run_dir"])
            artifact = run_dir / "source_cards.jsonl"
            artifact.write_text("{}\n")
            record = register_artifact(
                run_dir,
                artifact,
                role="retrieval_evidence",
                retention="audit",
                root=root,
            )
            self.assertEqual(record["path"], "source_cards.jsonl")
            self.assertNotIn(str(root), json.dumps(started["manifest"]))
            transition_run(run_dir, "running", root=root)
            completed = transition_run(run_dir, "completed", root=root)
            self.assertEqual(completed["status"], "completed")
            with self.assertRaises(ValueError):
                transition_run(run_dir, "running", root=root)

    def test_paths_cannot_escape_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtime"
            run_dir = Path(start_run("workflow", "safe", root=root)["run_dir"])
            outside = Path(tmp) / "outside.txt"
            outside.write_text("outside")
            with self.assertRaises(ValueError):
                register_artifact(
                    run_dir,
                    outside,
                    role="escape",
                    retention="transient",
                    root=root,
                )

    def test_retention_plan_is_non_destructive_and_manifest_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = Path(start_run("journal-club", "old", root=root)["run_dir"])
            transient = run_dir / "raw.txt"
            transient.write_text("raw")
            durable = run_dir / "verdict.json"
            durable.write_text("{}")
            register_artifact(run_dir, transient, role="raw", retention="transient", root=root)
            register_artifact(run_dir, durable, role="verdict", retention="audit", root=root)
            transition_run(run_dir, "running", root=root)
            transition_run(run_dir, "completed", root=root)
            manifest_path = run_dir / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["updated_at"] = (
                datetime.now(timezone.utc) - timedelta(days=60)
            ).isoformat()
            manifest_path.write_text(json.dumps(manifest))
            plan = retention_plan(root=root, older_than_days=30)
            self.assertEqual(plan["candidate_count"], 1)
            self.assertTrue(transient.exists())
            self.assertTrue(durable.exists())

    def test_audit_keeps_legacy_files_visible_but_unmanaged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "legacy.txt").write_text("legacy")
            start_run("study-review", "new", root=root)
            report = audit_runtime(root)
            self.assertEqual(report["managed_runs"], 1)
            self.assertEqual(report["legacy_files"], 1)

    def test_terminal_prune_removes_only_registered_transients(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = Path(start_run("report", "clean", root=root)["run_dir"])
            transient = run_dir / "extract.txt"
            transient.write_text("temporary", encoding="utf-8")
            durable = run_dir / "report.md"
            durable.write_text("durable", encoding="utf-8")
            register_artifact(run_dir, transient, role="extract", retention="transient", root=root)
            register_artifact(run_dir, durable, role="report", retention="deliverable", root=root)
            transition_run(run_dir, "running", root=root)
            with self.assertRaises(ValueError):
                prune_run_transients(run_dir, apply=True, root=root)
            transition_run(run_dir, "completed", root=root)

            plan = prune_run_transients(run_dir, root=root)
            self.assertEqual(plan["candidate_count"], 1)
            self.assertTrue(transient.exists())
            result = prune_run_transients(run_dir, apply=True, root=root)
            self.assertTrue(result["applied"])
            self.assertFalse(transient.exists())
            self.assertTrue(durable.exists())
            manifest = json.loads((run_dir / "run_manifest.json").read_text())
            record = next(item for item in manifest["artifacts"] if item["path"] == "extract.txt")
            self.assertFalse(record["exists"])
            self.assertIn("pruned_at", record)


if __name__ == "__main__":
    unittest.main()
