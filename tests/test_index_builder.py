"""Tests for the shared domain-grouped INDEX.md renderer."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import index_builder as ib


def _note(folder: Path, name: str, *, body: str = "Body.", **yaml_fields) -> Path:
    lines = ["---"]
    for key, value in yaml_fields.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}: [{', '.join(str(v) for v in value)}]")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    path = folder / f"{name}.md"
    path.write_text(body + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return path


class IndexBuilderTests(unittest.TestCase):
    def test_groups_by_domain_in_canonical_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            folder = vault / "Reports"
            folder.mkdir()
            _note(folder, "Tumor Note", domain="tumor", summary="A tumor topic.")
            _note(folder, "Vascular Note", domain="vascular", summary="A vascular topic.")
            index = ib.write_index(folder, vault_root=vault).read_text(encoding="utf-8")

            self.assertIn("## Vascular", index)
            self.assertIn("## Tumor", index)
            # Vascular precedes Tumor in canonical order.
            self.assertLess(index.index("## Vascular"), index.index("## Tumor"))
            # No auto-generated/count header line.
            self.assertNotIn("Auto-generated", index)
            self.assertNotIn("notes.", index)

    def test_bold_link_with_indented_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            folder = vault / "Reports"
            folder.mkdir()
            _note(folder, "Vascular Note", domain="vascular", summary="A vascular topic.")
            index = ib.write_index(folder, vault_root=vault).read_text(encoding="utf-8")

            self.assertIn("- **[[Reports/Vascular Note|Vascular Note]]**", index)
            self.assertIn("\n  A vascular topic.", index)

    def test_primary_domain_and_also_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            folder = vault / "Reports"
            folder.mkdir()
            # Trauma listed first in YAML, but Vascular is earlier canonically.
            _note(folder, "Cross Note", domain="trauma/vascular", summary="HTN guide.")
            index = ib.write_index(folder, vault_root=vault).read_text(encoding="utf-8")

            self.assertIn("## Vascular", index)
            self.assertNotIn("## Trauma", index)
            self.assertIn("· also: Trauma", index)

    def test_domain_from_tags_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            folder = vault / "Reports"
            folder.mkdir()
            _note(folder, "Tagged Note", tags=["skill/report", "domain/spine"], summary="Spine.")
            index = ib.write_index(folder, vault_root=vault).read_text(encoding="utf-8")
            self.assertIn("## Spine", index)

    def test_uncategorized_fallback_and_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            folder = vault / "Reports"
            folder.mkdir()
            _note(folder, "Vascular Note", domain="vascular", summary="V.")
            _note(folder, "Orphan Note", summary="No domain here.")
            index = ib.write_index(folder, vault_root=vault).read_text(encoding="utf-8")

            self.assertIn(f"## {ib.UNCATEGORIZED}", index)
            self.assertLess(index.index("## Vascular"), index.index(f"## {ib.UNCATEGORIZED}"))

    def test_display_alias_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            folder = vault / "Reports"
            folder.mkdir()
            _note(folder, "Long File Name", domain="vascular", display="AChA Aneurysms", summary="X.")
            index = ib.write_index(folder, vault_root=vault).read_text(encoding="utf-8")
            self.assertIn("[[Reports/Long File Name|AChA Aneurysms]]", index)

    def test_inline_extras_mode_and_deck(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            folder = vault / "Presentations"
            (folder / "Articles").mkdir(parents=True)
            _note(
                folder / "Articles",
                "Flow Diversion",
                domain="vascular",
                mode="article",
                deck_path="/Users/x/Desktop/Flow Diversion.pptx",
                summary="A deck.",
            )
            index = ib.write_index(folder, vault_root=vault, recursive=True).read_text(encoding="utf-8")

            self.assertIn("[[Presentations/Articles/Flow Diversion|Flow Diversion]]", index)
            self.assertIn("article", index)
            self.assertIn("[Flow Diversion.pptx](</Users/x/Desktop/Flow Diversion.pptx>)", index)

    def test_empty_folder_renders_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            folder = vault / "Operative Guides"
            folder.mkdir()
            index = ib.write_index(folder, vault_root=vault).read_text(encoding="utf-8")
            self.assertEqual(index.strip(), "")


if __name__ == "__main__":
    unittest.main()
