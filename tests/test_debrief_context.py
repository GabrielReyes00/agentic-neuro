"""Tests for the /debrief context assembler (src/debrief_context_assembler.py).

These tests exercise the deterministic retrieval layer ONLY. No LLM calls.
A temp vault and temp KG database are used so nothing touches real state.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import debrief_context_assembler as dca
from knowledge_graph import KnowledgeGraph


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_vault(root: Path) -> Path:
    for folder in ("Reports", "Study Material", "Operative Guides",
                   "Concepts", "Review Sessions", "Debriefs"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    return root


def _write_note(path: Path, body: str = "", yaml_fields: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = [body.strip() or "Body."]
    if yaml_fields:
        yaml_lines = ["---"]
        for k, v in yaml_fields.items():
            if isinstance(v, list):
                yaml_lines.append(f"{k}:")
                for item in v:
                    yaml_lines.append(f"  - {item}")
            else:
                yaml_lines.append(f"{k}: {v}")
        yaml_lines.append("---")
        parts.append("\n".join(yaml_lines))
    path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    return path


# ── Pure unit tests (no KG) ──────────────────────────────────────────────────


class TokenizeTests(unittest.TestCase):
    def test_lowercase_and_strips_stopwords(self):
        toks = dca.tokenize("Management of New Patient with Spondylolisthesis")
        # "management", "new", "patient" are stopwords; "of", "with" too.
        self.assertIn("spondylolisthesis", toks)
        self.assertNotIn("management", toks)
        self.assertNotIn("new", toks)
        self.assertNotIn("patient", toks)

    def test_empty_input_returns_empty(self):
        self.assertEqual(dca.tokenize(""), set())
        self.assertEqual(dca.tokenize(None if False else ""), set())

    def test_short_tokens_stripped(self):
        toks = dca.tokenize("L4 L5 TLIF")
        # Single or two-char tokens dropped; multi-char alphanumerics retained.
        self.assertIn("tlif", toks)


class JaccardTests(unittest.TestCase):
    def test_identical_sets(self):
        self.assertEqual(dca.jaccard({"a", "b"}, {"a", "b"}), 1.0)

    def test_disjoint_sets(self):
        self.assertEqual(dca.jaccard({"a"}, {"b"}), 0.0)

    def test_partial_overlap(self):
        self.assertAlmostEqual(dca.jaccard({"a", "b"}, {"b", "c"}), 1/3)

    def test_empty_set_returns_zero(self):
        self.assertEqual(dca.jaccard(set(), {"a"}), 0.0)
        self.assertEqual(dca.jaccard({"a"}, set()), 0.0)


class YamlExtractionTests(unittest.TestCase):
    def test_bottom_yaml_key_terms_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "note.md"
            _write_note(p, "Body text about Chiari decompression.",
                        yaml_fields={"key_terms": ["chiari", "posterior fossa"],
                                     "aliases": ["ACM-I"]})
            terms = dca._extract_yaml_list_terms(p)
            self.assertIn("chiari", terms)
            self.assertIn("posterior fossa", terms)
            self.assertIn("ACM-I", terms)

    def test_file_without_yaml_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "plain.md"
            p.write_text("Just a body, no YAML.\n", encoding="utf-8")
            self.assertEqual(dca._extract_yaml_list_terms(p), [])


# ── Vault scanning tests ─────────────────────────────────────────────────────


class ScanVaultTests(unittest.TestCase):
    def test_matching_filename_surfaces_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            _write_note(vault / "Reports" / "Chiari I Malformation Decompression.md")
            hits = dca.scan_vault(vault, dca.tokenize("chiari decompression"))
            self.assertTrue(hits["reports"])
            self.assertEqual(hits["reports"][0]["title"],
                             "Chiari I Malformation Decompression")

    def test_key_terms_yaml_boosts_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            # Filename alone would not match 'acom aneurysm' strongly.
            _write_note(
                vault / "Study Material" / "Anterior Communicating Artery.md",
                yaml_fields={"key_terms": ["acom aneurysm", "subarachnoid hemorrhage"]},
            )
            hits = dca.scan_vault(vault, dca.tokenize("acom aneurysm"))
            self.assertTrue(hits["study_material"],
                            "YAML key_terms should produce a hit")

    def test_index_files_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            _write_note(vault / "Reports" / "INDEX.md")
            _write_note(vault / "Reports" / "Some Chiari Note.md")
            hits = dca.scan_vault(vault, dca.tokenize("chiari"))
            titles = [h["title"] for h in hits["reports"]]
            self.assertNotIn("INDEX", titles)

    def test_missing_folders_do_not_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Only create Reports; the rest are missing.
            (Path(tmp) / "Reports").mkdir()
            _write_note(Path(tmp) / "Reports" / "Spondylolisthesis Fusion.md")
            hits = dca.scan_vault(Path(tmp), dca.tokenize("spondylolisthesis fusion"))
            self.assertTrue(hits["reports"])
            # All other keys present and empty.
            for key in ("study_material", "operative_guides",
                        "concepts", "review_sessions", "debriefs"):
                self.assertEqual(hits[key], [])


class MergeTargetTests(unittest.TestCase):
    def test_merge_suggested_when_similar_debrief_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            _write_note(
                vault / "Debriefs" / "L4 L5 Spondylolisthesis Fusion.md",
                yaml_fields={"key_terms": ["spondylolisthesis", "tlif", "lumbar fusion"]},
            )
            target = dca.find_merge_target(
                vault,
                dca.tokenize("L4 L5 spondylolisthesis TLIF fusion"),
                merge_threshold=0.30,
            )
            self.assertIsNotNone(target)
            self.assertIn("Spondylolisthesis", target["title"])

    def test_no_merge_when_below_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp))
            _write_note(vault / "Debriefs" / "Chiari I Decompression.md")
            target = dca.find_merge_target(
                vault,
                dca.tokenize("anterior cervical discectomy fusion"),
                merge_threshold=0.45,
            )
            self.assertIsNone(target)

    def test_no_merge_when_debriefs_folder_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Vault without Debriefs directory at all.
            (Path(tmp) / "Reports").mkdir()
            target = dca.find_merge_target(
                Path(tmp),
                dca.tokenize("anything"),
                merge_threshold=0.1,
            )
            self.assertIsNone(target)


# ── Scaffold RAG-gating ──────────────────────────────────────────────────────


class ScaffoldFlagsTests(unittest.TestCase):
    def test_rag_needed_when_no_kg_and_no_vault(self):
        scaffold = dca.derive_scaffold_flags({"topics": []}, {k: [] for k, _ in dca._VAULT_FOLDERS})
        self.assertTrue(all(m["rag_needed"] for m in scaffold.values()))

    def test_strong_vault_hit_suppresses_rag(self):
        vault_hits = {k: [] for k, _ in dca._VAULT_FOLDERS}
        vault_hits["reports"] = [{"similarity": 0.55, "title": "Topic"}]
        scaffold = dca.derive_scaffold_flags({"topics": []}, vault_hits)
        self.assertFalse(scaffold["mechanism"]["rag_needed"])
        self.assertFalse(scaffold["imaging"]["rag_needed"])

    def test_kg_depth_two_suppresses_rag(self):
        kg_context = {"topics": [{"status": "known", "depth": 2}]}
        vault_hits = {k: [] for k, _ in dca._VAULT_FOLDERS}
        scaffold = dca.derive_scaffold_flags(kg_context, vault_hits)
        self.assertFalse(scaffold["mechanism"]["rag_needed"])

    def test_operative_guide_covers_intraop_even_without_strong_match(self):
        vault_hits = {k: [] for k, _ in dca._VAULT_FOLDERS}
        vault_hits["operative_guides"] = [{"similarity": 0.20, "title": "Guide"}]
        scaffold = dca.derive_scaffold_flags({"topics": []}, vault_hits)
        self.assertFalse(scaffold["intraop_concepts"]["rag_needed"])
        # But other slots still need RAG (guide was only weakly similar).
        self.assertTrue(scaffold["imaging"]["rag_needed"])


# ── End-to-end assemble_context tests (with real KG on temp db) ──────────────


class AssembleContextTests(unittest.TestCase):
    def _kg_path(self, tmp: str) -> Path:
        # Touch a fresh KG so schema is created, then close it so
        # assemble_context can reopen cleanly.
        p = Path(tmp) / "kg.db"
        kg = KnowledgeGraph(p)
        kg.close()
        return p

    def test_bundle_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp) / "vault")
            db = self._kg_path(tmp)
            bundle = dca.assemble_context(
                pathology="Chiari I malformation decompression",
                user_context="uncertain about imaging and postop",
                vault_root=vault,
                db_path=db,
            )
            for key in ("pathology", "user_context", "query_tokens", "kg_context",
                        "blocking_gaps", "unknown_unknowns", "vault_hits",
                        "merge_target", "scaffold_slots", "rag_needed_slots",
                        "rag_required", "merge_threshold"):
                self.assertIn(key, bundle, f"missing key: {key}")
            self.assertEqual(set(bundle["scaffold_slots"].keys()),
                             set(dca.SCAFFOLD_SLOTS))

    def test_empty_vault_forces_rag(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp) / "vault")
            db = self._kg_path(tmp)
            bundle = dca.assemble_context(
                pathology="anterior choroidal artery aneurysm clipping",
                vault_root=vault,
                db_path=db,
            )
            self.assertTrue(bundle["rag_required"])
            self.assertGreater(len(bundle["rag_needed_slots"]), 0)

    def test_strong_report_hit_suppresses_rag(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp) / "vault")
            _write_note(
                vault / "Reports" / "Anterior Choroidal Artery Aneurysm Clipping.md",
                yaml_fields={"key_terms": [
                    "anterior choroidal artery", "aneurysm", "clipping",
                    "microsurgical", "temporal lobe",
                ]},
            )
            db = self._kg_path(tmp)
            bundle = dca.assemble_context(
                pathology="anterior choroidal artery aneurysm clipping",
                vault_root=vault,
                db_path=db,
            )
            self.assertTrue(bundle["vault_hits"]["reports"],
                            "Report should be surfaced")
            self.assertFalse(bundle["rag_required"],
                             "Strong vault hit should suppress RAG requirement")

    def test_existing_debrief_triggers_merge_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = _make_vault(Path(tmp) / "vault")
            _write_note(
                vault / "Debriefs" / "Lumbar Spondylolisthesis TLIF.md",
                yaml_fields={"key_terms": [
                    "spondylolisthesis", "tlif", "lumbar fusion", "pars defect",
                ]},
            )
            db = self._kg_path(tmp)
            bundle = dca.assemble_context(
                pathology="L4-L5 spondylolisthesis TLIF evaluation",
                vault_root=vault,
                db_path=db,
                merge_threshold=0.25,
            )
            self.assertIsNotNone(bundle["merge_target"])
            self.assertIn("Spondylolisthesis", bundle["merge_target"]["title"])

    def test_requires_pathology(self):
        with self.assertRaises(ValueError):
            dca.assemble_context(pathology="")


if __name__ == "__main__":
    unittest.main()
