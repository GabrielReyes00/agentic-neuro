"""Tests for the /grand-rounds vault writer."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import grand_rounds_writer as grw
from vault_schema import parse_frontmatter


def _make_vault(root: Path) -> Path:
    return root


def _frontmatter(text: str) -> dict:
    return parse_frontmatter(text)


def _quality_body() -> str:
    return (
        "**Mode**: Case\n\n"
        "## Presentation Arc\n\nArc.\n\n"
        "## Slide Outline and Speaker Notes\n\n1. Hook.\n\n"
        "## Citation List\n\n- Smith 2024.\n\n"
        "## Image Manifest\n\n- INSERT: sagittal T2 MRI.\n\n"
        "## Anticipated Questions\n\n- Why operate now?\n\n"
        "## Presentation Risks\n\n- No major presentation risks identified.\n\n"
        "## What Not To Say\n\n- Do not overclaim causality."
    )


class TitleSlugTests(unittest.TestCase):
    def test_title_case_preserves_uppercase_and_roman_tokens(self):
        self.assertEqual(
            grw._title_case_slug("chiari I decompression and CSF flow"),
            "Chiari I Decompression And CSF Flow",
        )

    def test_title_case_rejects_empty(self):
        with self.assertRaises(ValueError):
            grw._title_case_slug(" !@# ")


class CreatePresentationTests(unittest.TestCase):
    def test_case_presentation_written_to_cases_with_native_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            path = grw.create_presentation(
                vault_root=vault,
                mode="case",
                title="Chiari I Decompression",
                topic="Chiari I malformation decompression",
                domain="pediatric",
                summary="Case presentation on Chiari decompression.",
                deck_path=Path("/Users/gabrielreyes/Desktop/Chiari I Decompression.pptx"),
                citations=["Smith 2024"],
                image_count=3,
                sessions_dir=vault / "Sessions",
                body=(
                    "**Mode**: Case\n\n"
                    "## Presentation Arc\n\n"
                    "Presentation to decompression to outcome."
                ),
            )
            self.assertEqual(path.parent.name, "Cases")
            self.assertTrue(path.exists())
            text = path.read_text(encoding="utf-8")
            first_non_blank = next((ln for ln in text.splitlines() if ln.strip()), "")
            self.assertFalse(first_non_blank.startswith("# "))
            self.assertTrue(text.startswith("---\n"))
            meta = _frontmatter(text)
            self.assertEqual(meta["mode"], "case")
            self.assertEqual(meta["domain"], "pediatric")
            self.assertEqual(meta["citation_count"], 1)
            self.assertEqual(meta["image_placeholder_count"], 3)
            self.assertIn("skill/grand-rounds", meta["tags"])
            self.assertIn("manifest_path", meta)
            manifest = json.loads(Path(meta["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["title"], "Chiari I Decompression")
            self.assertEqual(manifest["deck_path"], "/Users/gabrielreyes/Desktop/Chiari I Decompression.pptx")

    def test_article_presentation_written_to_articles_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            grw.create_presentation(
                vault_root=vault,
                mode="article",
                title="Flow Diversion For Distal Aneurysms",
                topic="Flow diversion for distal intracranial aneurysms",
                summary="Journal club on distal aneurysm flow diversion.",
                sessions_dir=vault / "Sessions",
                body="**Mode**: Article\n\n## Presentation Arc\n\nMethods and critique.",
            )
            note = vault / "Presentations" / "Articles" / "Flow Diversion For Distal Aneurysms.md"
            index = vault / "Presentations" / "INDEX.md"
            self.assertTrue(note.exists())
            text = index.read_text(encoding="utf-8")
            self.assertIn(
                "[[Presentations/Articles/Flow Diversion For Distal Aneurysms|", text
            )
            self.assertIn("article", text)

    def test_rejects_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                grw.create_presentation(
                    vault_root=Path(tmp),
                    mode="case",
                title="Bad Title",
                topic="Bad topic",
                sessions_dir=Path(tmp) / "Sessions",
                body="# Bad H1\n\nbody",
                )

    def test_refuses_overwrite_without_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            grw.create_presentation(
                vault_root=vault,
                mode="case",
                title="Chiari I Decompression",
                topic="Chiari I malformation",
                sessions_dir=vault / "Sessions",
                body="body",
            )
            with self.assertRaises(FileExistsError):
                grw.create_presentation(
                    vault_root=vault,
                    mode="case",
                    title="Chiari I Decompression",
                    topic="Chiari I malformation",
                    sessions_dir=vault / "Sessions",
                    body="body 2",
                )

    def test_rejects_obvious_phi_in_case_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "PHI"):
                grw.create_presentation(
                    vault_root=Path(tmp),
                    mode="case",
                    title="Case With PHI",
                    topic="PHI case",
                    body="**Mode**: Case\n\nMRN: 12345678\n\n## Presentation Arc\n\nArc.",
                    sessions_dir=Path(tmp) / "Sessions",
                )

    def test_quality_gate_rejects_missing_required_sections_when_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "Quality gate failed"):
                grw.create_presentation(
                    vault_root=Path(tmp),
                    mode="case",
                    title="Thin Deck",
                    topic="Thin deck",
                    body="**Mode**: Case\n\n## Presentation Arc\n\nArc.",
                    sessions_dir=Path(tmp) / "Sessions",
                    require_quality_gate=True,
                )

    def test_quality_gate_accepts_complete_manifest_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            deck = vault / "Complete Chiari Deck.pptx"
            deck.write_bytes(b"test deck")
            path = grw.create_presentation(
                vault_root=vault,
                mode="case",
                title="Complete Chiari Deck",
                topic="Chiari I malformation",
                body=_quality_body(),
                citations=["Smith 2024"],
                slide_titles=["Hook", "Imaging"],
                image_manifest=["INSERT: sagittal T2 MRI"],
                presentation_risks=[],
                anticipated_questions=["Why operate now?"],
                attending_angle="operative anatomy and management controversy",
                deck_path=deck,
                sessions_dir=vault / "Sessions",
                require_quality_gate=True,
            )
            meta = _frontmatter(path.read_text(encoding="utf-8"))
            manifest = json.loads(Path(meta["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["attending_angle"], "operative anatomy and management controversy")
            self.assertEqual(manifest["quality_gate_failures"], [])

    def test_article_metadata_tracks_journal_source_and_deck_qa(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            deck = vault / "Hybrid Epilepsy Surgery.pptx"
            deck.write_bytes(b"test deck")
            body = (
                "**Mode**: Article\n\n"
                "## Presentation Arc\n\nArc.\n\n"
                "## Coverage Ledger\n\nCovered.\n\n"
                "## Slide Outline and Speaker Notes\n\nNotes.\n\n"
                "## Study Design and Methods\n\nCase series.\n\n"
                "## Methods Critique\n\nNo comparator.\n\n"
                "## Clinical Impact\n\nSelection.\n\n"
                "## Citation List\n\n- Reyes 2026.\n\n"
                "## Asset Manifest\n\n- Figure 3.\n\n"
                "## Anticipated Questions\n\n- Why combine?\n\n"
                "## Presentation Risks\n\n- Attribution.\n\n"
                "## What Not To Say\n\n- Do not claim superiority."
            )
            path = grw.create_presentation(
                vault_root=vault,
                mode="article",
                title="Hybrid Epilepsy Surgery",
                topic="Resection and RNS",
                body=body,
                deck_path=deck,
                citations=["Reyes 2026"],
                slide_titles=["Problem", "Results"],
                image_manifest=["Figure 3"],
                presentation_risks=["Attribution"],
                anticipated_questions=["Why combine?"],
                source_journal_club="Journal Club/Hybrid Epilepsy Surgery.md",
                source_pdf="Journal Club/Sources/Hybrid Epilepsy Surgery.pdf",
                duration_minutes=15,
                package_manifest="/tmp/deck_plan.json",
                deck_qa_status="pass",
                sessions_dir=vault / "Sessions",
                require_quality_gate=True,
            )
            meta = _frontmatter(path.read_text(encoding="utf-8"))
            self.assertEqual(meta["source_journal_club"], "Journal Club/Hybrid Epilepsy Surgery.md")
            self.assertEqual(meta["source_pdf"], "Journal Club/Sources/Hybrid Epilepsy Surgery.pdf")
            self.assertEqual(meta["duration_minutes"], 15)
            self.assertEqual(meta["slide_count"], 2)
            self.assertEqual(meta["deck_qa_status"], "pass")


class RehearsalTests(unittest.TestCase):
    def test_append_rehearsal_notes_preserves_single_frontmatter_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            path = grw.create_presentation(
                vault_root=vault,
                mode="case",
                title="Chiari I Decompression",
                topic="Chiari I malformation",
                sessions_dir=vault / "Sessions",
                body="**Mode**: Case\n\n## Anticipated Questions\n\nWhy operate?",
            )
            grw.append_rehearsal_notes(
                vault_root=vault,
                target_path=path,
                notes="Needs tighter defense of observation versus surgery.",
                weak_spots=["natural history", "CINE MRI rationale"],
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn("## Rehearsal Notes - ", text)
            self.assertIn("Needs tighter defense", text)
            self.assertTrue(text.startswith("---\n"))
            self.assertEqual(text.count("\n---\n"), 1)
            meta = _frontmatter(text)
            self.assertIn("last_rehearsal", meta)


class CLITests(unittest.TestCase):
    def test_create_quiet_suppresses_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                ret = grw.main([
                    "--action", "create",
                    "--mode", "case",
                    "--title", "Chiari I Decompression",
                    "--topic", "Chiari I malformation",
                    "--body", "body",
                    "--vault-root", tmp,
                    "--sessions-dir", str(Path(tmp) / "Sessions"),
                    "--quiet",
                ])
            self.assertEqual(ret, 0)
            self.assertEqual(buf.getvalue(), "")

    def test_create_no_quiet_emits_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                ret = grw.main([
                    "--action", "create",
                    "--mode", "article",
                    "--title", "Aneurysm Trial Critique",
                    "--topic", "Aneurysm trial critique",
                    "--body", "body",
                    "--vault-root", tmp,
                    "--sessions-dir", str(Path(tmp) / "Sessions"),
                ])
            self.assertEqual(ret, 0)
            result = json.loads(buf.getvalue())
            self.assertTrue(result["ok"])
            self.assertEqual(result["action"], "create")


if __name__ == "__main__":
    unittest.main()
