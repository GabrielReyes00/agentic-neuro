"""Tests for the /debrief vault writer (src/debrief_writer.py)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import debrief_writer as dw


def _make_vault(root: Path) -> Path:
    (root / "Debriefs").mkdir(parents=True, exist_ok=True)
    return root


def _bottom_yaml(text: str) -> dict:
    body, meta = dw._split_bottom_yaml(text)
    return meta or {}


class TitleSlugTests(unittest.TestCase):
    def test_title_case_preserves_uppercase_tokens(self):
        self.assertEqual(
            dw._title_case_slug("L4-L5 spondylolisthesis TLIF"),
            "L4-L5 Spondylolisthesis TLIF",
        )

    def test_strips_forbidden_punctuation(self):
        slug = dw._title_case_slug("Chiari I — decompression (posterior fossa)")
        self.assertNotIn("—", slug)
        self.assertNotIn("(", slug)

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            dw._title_case_slug("   ")


class CreateDebriefTests(unittest.TestCase):
    def test_writes_file_with_bottom_yaml_and_no_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            body = (
                "Key takeaway: this is a debrief.\n\n"
                "## Imaging\n\nMRI lumbar spine with flex/ext XR."
            )
            path = dw.create_debrief(
                vault_root=vault,
                pathology="L4-L5 Spondylolisthesis TLIF",
                body=body,
                domain="Spine",
                key_terms=["spondylolisthesis", "tlif"],
                summary="TLIF workup debrief",
            )
            self.assertTrue(path.exists())
            text = path.read_text(encoding="utf-8")
            # No H1 at top.
            first_non_blank = next((ln for ln in text.splitlines() if ln.strip()), "")
            self.assertFalse(first_non_blank.startswith("# "))
            # YAML at bottom.
            self.assertTrue(text.rstrip().endswith("---"))
            meta = _bottom_yaml(text)
            self.assertEqual(meta["pathology"], "L4-L5 Spondylolisthesis TLIF")
            self.assertEqual(meta["encounters"], 1)
            self.assertIn("spondylolisthesis", meta["key_terms"])
            self.assertIn("skill/debrief", meta["tags"])

    def test_rejects_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            with self.assertRaises(ValueError):
                dw.create_debrief(
                    vault_root=vault,
                    pathology="Test",
                    body="# Big title\n\nbody",
                )

    def test_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            dw.create_debrief(vault, "Chiari I Decompression", "body", domain="Spine")
            with self.assertRaises(FileExistsError):
                dw.create_debrief(vault, "Chiari I Decompression", "body 2", domain="Spine")


class MergeIntoDebriefTests(unittest.TestCase):
    def _seed(self, vault: Path) -> Path:
        return dw.create_debrief(
            vault_root=vault,
            pathology="Chiari I Decompression",
            body="Initial body content.\n\n## Imaging\n\nMRI brain + CV junction.",
            domain="Pediatric",
            key_terms=["chiari", "posterior fossa"],
            summary="First encounter",
        )

    def test_appends_dated_section_and_preserves_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            path = self._seed(vault)
            dw.merge_into_debrief(
                vault_root=vault,
                target_path=path,
                body="Follow-up notes from a new consult.\n\n## Labs\n\nCoags, type-screen.",
                encounter_label="VA consult",
                new_key_terms=["syringomyelia"],
                summary_update="Two encounters logged",
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("Initial body content.", text)
            self.assertIn("## Encounter — ", text)
            self.assertIn("VA consult", text)
            self.assertIn("Follow-up notes from a new consult.", text)
            # Only one bottom YAML block after merge.
            self.assertEqual(text.count("\n---\n"), 2,
                             "expected a single YAML block (2 fences) at bottom")

    def test_encounter_count_increments_and_terms_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            path = self._seed(vault)
            dw.merge_into_debrief(
                vault_root=vault,
                target_path=path,
                body="more body",
                new_key_terms=["syringomyelia", "chiari"],  # duplicate
            )
            meta = _bottom_yaml(path.read_text(encoding="utf-8"))
            self.assertEqual(meta["encounters"], 2)
            self.assertIn("syringomyelia", meta["key_terms"])
            self.assertEqual(
                meta["key_terms"].count("chiari"), 1,
                "duplicate key_term should not be added twice",
            )
            self.assertEqual(meta["last_encounter"][:4], str(meta["created"])[:4])

    def test_merge_rejects_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            path = self._seed(vault)
            with self.assertRaises(ValueError):
                dw.merge_into_debrief(vault, path, "# Illegal\n\nbody")

    def test_merge_missing_target_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            with self.assertRaises(FileNotFoundError):
                dw.merge_into_debrief(vault, Path("Debriefs/Nope.md"), "body")


class UpsertIndexTests(unittest.TestCase):
    def test_creates_index_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            path = dw.upsert_index(
                vault_root=vault,
                title="Chiari I Decompression",
                pathology="Chiari I malformation",
                domain="Pediatric",
                last_encounter="2026-04-19",
                encounters=1,
                summary="First encounter",
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("| Debrief |", text)
            self.assertIn("Chiari I Decompression", text)

    def test_upsert_replaces_existing_row_by_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            dw.upsert_index(vault, "Chiari I Decompression", "Chiari I malformation",
                            "Pediatric", "2026-04-10", 1, "First encounter")
            dw.upsert_index(vault, "Chiari I Decompression", "Chiari I malformation",
                            "Pediatric", "2026-04-19", 2, "Second encounter")
            text = (vault / "Debriefs" / "INDEX.md").read_text(encoding="utf-8")
            # Title appears twice per row (wikilink target + alias), so exactly one row == 2.
            self.assertEqual(text.count("Chiari I Decompression"), 2)
            data_rows = [ln for ln in text.splitlines()
                         if ln.strip().startswith("|") and "Chiari" in ln]
            self.assertEqual(len(data_rows), 1)
            self.assertIn("2026-04-19", text)
            self.assertNotIn("2026-04-10", text)

    def test_multiple_titles_are_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            dw.upsert_index(vault, "Zeta Test", "Z", "Spine", "2026-04-19", 1, "z")
            dw.upsert_index(vault, "Alpha Test", "A", "Spine", "2026-04-19", 1, "a")
            text = (vault / "Debriefs" / "INDEX.md").read_text(encoding="utf-8")
            alpha_pos = text.find("Alpha Test")
            zeta_pos = text.find("Zeta Test")
            self.assertLess(alpha_pos, zeta_pos)


class CLIFlatActionTests(unittest.TestCase):
    """Validate the --action flat CLI interface replaces the old subcommand style."""

    def test_create_via_action_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            ret = dw.main([
                "--action", "create",
                "--pathology", "Chiari I Decompression",
                "--body", "Teaching notes on Chiari.",
                "--domain", "Pediatric",
                "--vault-root", str(vault),
                "--quiet",
            ])
            self.assertEqual(ret, 0)
            self.assertTrue((vault / "Debriefs" / "Chiari I Decompression.md").exists())

    def test_content_alias_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            ret = dw.main([
                "--action", "create",
                "--pathology", "Chiari I Decompression",
                "--content", "Body via content alias.",  # alias for --body
                "--vault-root", str(vault),
                "--quiet",
            ])
            self.assertEqual(ret, 0)

    def test_merge_via_action_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            dw.main([
                "--action", "create",
                "--pathology", "Chiari I Decompression",
                "--body", "Initial body.",
                "--vault-root", str(vault),
                "--quiet",
            ])
            ret = dw.main([
                "--action", "merge",
                "--target", "Debriefs/Chiari I Decompression.md",
                "--body", "Second encounter body.",
                "--vault-root", str(vault),
                "--quiet",
            ])
            self.assertEqual(ret, 0)
            text = (vault / "Debriefs" / "Chiari I Decompression.md").read_text()
            self.assertIn("Second encounter body.", text)
            self.assertIn("## Encounter — ", text)

    def test_upsert_index_via_action_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            ret = dw.main([
                "--action", "upsert-index",
                "--title", "Chiari I Decompression",
                "--pathology", "Chiari I malformation",
                "--domain", "Pediatric",
                "--last-encounter", "2026-04-19",
                "--encounters", "1",
                "--summary", "First debrief",
                "--vault-root", str(vault),
                "--quiet",
            ])
            self.assertEqual(ret, 0)
            self.assertTrue((vault / "Debriefs" / "INDEX.md").exists())

    def test_quiet_suppresses_stdout(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            buf = io.StringIO()
            with redirect_stdout(buf):
                dw.main([
                    "--action", "create",
                    "--pathology", "Chiari I Decompression",
                    "--body", "body",
                    "--vault-root", str(vault),
                    "--quiet",
                ])
            self.assertEqual(buf.getvalue(), "")

    def test_no_quiet_emits_json(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            buf = io.StringIO()
            with redirect_stdout(buf):
                dw.main([
                    "--action", "create",
                    "--pathology", "Chiari I Decompression",
                    "--body", "body",
                    "--vault-root", str(vault),
                ])
            import json as _json
            result = _json.loads(buf.getvalue())
            self.assertTrue(result["ok"])


class CLIAssemblerTests(unittest.TestCase):
    """Validate assembler CLI: --pathology flag, positional fallback, --quiet."""

    def _kg_path(self, tmp: str) -> Path:
        from knowledge_graph import KnowledgeGraph
        p = Path(tmp) / "kg.db"
        kg = KnowledgeGraph(p)
        kg.close()
        return p

    def test_pathology_flag(self):
        import io
        from contextlib import redirect_stdout
        import debrief_context_assembler as dca
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = _make_vault(Path(tmp) / "vault")
            db = self._kg_path(tmp)
            out_path = Path(tmp) / "out.json"
            buf = io.StringIO()
            with redirect_stdout(buf):
                dca.main([
                    "--pathology", "Chiari I decompression",
                    "--output", str(out_path),
                    "--quiet",
                    "--vault-root", str(vault_root),
                    "--db", str(db),
                ])
            # --quiet suppresses stdout
            self.assertEqual(buf.getvalue(), "")
            self.assertTrue(out_path.exists())

    def test_positional_pathology_fallback(self):
        import debrief_context_assembler as dca
        with tempfile.TemporaryDirectory() as tmp:
            vault_root = _make_vault(Path(tmp) / "vault")
            db = self._kg_path(tmp)
            out_path = Path(tmp) / "out.json"
            # Positional arg — no --pathology flag
            dca.main([
                "Chiari I decompression",
                "--output", str(out_path),
                "--quiet",
                "--vault-root", str(vault_root),
                "--db", str(db),
            ])
            import json as _json
            bundle = _json.loads(out_path.read_text())
            self.assertEqual(bundle["pathology"], "Chiari I decompression")


if __name__ == "__main__":
    unittest.main()
