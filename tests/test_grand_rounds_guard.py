from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from src import grand_rounds_guard as guard


def _write_pptx(path: Path, slide_count: int) -> None:
    presentation = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:sldSz cx="12192000" cy="6858000"/></p:presentation>'
    )
    note = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:t>Substantive speaker notes with transition and faculty defense.</a:t></p:notes>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("ppt/presentation.xml", presentation)
        for idx in range(1, slide_count + 1):
            archive.writestr(f"ppt/slides/slide{idx}.xml", "<slide/>")
            archive.writestr(f"ppt/notesSlides/notesSlide{idx}.xml", note)
        archive.writestr("ppt/media/image1.png", b"png")


def _slide(idx: int, *, backup: bool = False) -> dict:
    layout_families = {
        1: "full_bleed",
        2: "editorial_split",
        3: "figure_first",
        4: "chart_first",
        5: "open_comparison",
        6: "process_flow",
        7: "figure_first",
        8: "chart_first",
        9: "synthesis_field",
        10: "table_stage",
    }
    role = "backup" if backup else ("title" if idx == 1 else ("close" if idx == 9 else "evidence"))
    return {
        "id": f"S{idx:02d}",
        "title": f"Unique Slide Claim {idx}",
        "job": f"Communicate job {idx}",
        "role": role,
        "layout_family": layout_families[idx],
        "visual_anchor": "Typographic opening" if role == "title" else "Native evidence display",
        "visual_coverage": 0 if role == "title" else 60,
        "background_tone": "dark" if idx == 1 else "light",
        "visible_content": ["Evidence point one", "Evidence point two", "Clinical implication"] if idx == 9 else ["Evidence"],
        "speaker_notes": "Explain the evidence, its boundary, transition, and likely faculty challenge.",
        "citations": ["Reyes et al. 2026"],
        "assets": ["figure-3"] if idx == 2 else [],
        "source_sections": ["Results That Matter"],
        "timed_seconds": 30,
        "backup": backup,
        "separation_rationale": "This slide presents distinct evidence that cannot be merged without losing interpretation.",
    }


class GrandRoundsGuardTests(unittest.TestCase):
    def _package(self, root: Path) -> dict[str, Path]:
        deck = root / "deck.pptx"
        journal = root / "Journal Club" / "Hybrid.md"
        source = root / "Journal Club" / "Sources" / "Hybrid.pdf"
        journal.parent.mkdir(parents=True)
        source.parent.mkdir(parents=True)
        source.write_bytes(b"%PDF-test")
        journal.write_text(
            "Body\n\n---\nskill: journal-club\nsource_package_status: complete\n"
            "source_pdf: Journal Club/Sources/Hybrid.pdf\n---\n",
            encoding="utf-8",
        )
        slides = [_slide(idx) for idx in range(1, 10)] + [_slide(10, backup=True)]
        slides[0]["title"] = "Hybrid Epilepsy Surgery"
        slides[1]["title"] = "Background"
        slides[1]["role"] = "background"
        slides[1]["source_sections"] = ["Clinical Foundation"]
        slides[1]["visible_content"] = [
            "Disease mechanism",
            "Natural history",
            "Usual treatment pathway",
            "Clinical evidence gap",
        ]
        slides[8]["title"] = "Main Takeaways"
        slides[8]["role"] = "summary"
        _write_pptx(deck, len(slides))
        plan = {
            "schema": "grand_rounds_deck_plan_v2",
            "mode": "article",
            "title": "Hybrid Epilepsy Surgery",
            "duration_minutes": 15,
            "style_profile": "editorial_academic",
            "design_brief": {
                "route": "editorial_academic",
                "audience": "Neurosurgery faculty and residents",
                "communication_job": "Explain why the evidence changes a bounded clinical decision.",
                "art_direction": "An evidence-led epilepsy surgery conference talk with decisive figures at scale.",
                "page_system": "Editorial field with evidence-first reading paths.",
                "palette": {
                    "canvas": "#FFFFFF",
                    "ink": "#111827",
                    "primary": "#17365D",
                    "secondary": "#DCE6F1",
                    "signal": "#A13D3D",
                },
                "palette_rationale": "Quiet academic neutrals keep outcome evidence dominant.",
                "display_font": "Cambria",
                "body_font": "Arial",
                "title_style": "sentence_case",
                "motif": "Direct evidence annotations with a consistent caption rail.",
                "background_strategy": "dark_title_with_light_content",
                "layout_families": [
                    "full_bleed",
                    "editorial_split",
                    "figure_first",
                    "chart_first",
                    "open_comparison",
                    "process_flow",
                    "synthesis_field",
                    "table_stage",
                ],
                "forbidden_moves": ["repeated title underlines", "bullet walls"],
            },
            "title_slide_subtitle": "",
            "source_journal_club": str(journal),
            "source_pdf": str(source),
            "source_pdf_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "slides": slides,
            "coverage": {section: ["S01"] for section in guard.ARTICLE_REQUIRED_COVERAGE},
            "coverage_audit": {
                "required_dimensions": {
                    dimension: ["S02"] for dimension in guard.ARTICLE_REQUIRED_EVIDENCE_DIMENSIONS
                },
                "critical_items": [{
                    "id": "CI-01",
                    "summary": "Selection and treatment exposure determine interpretation",
                    "salience": "thesis-determining",
                    "disposition": "main",
                    "slide_ids": ["S02"],
                    "source": "Article Figure 1",
                    "rationale": "Without this evidence the audience would misread the treatment effect.",
                }],
                "longitudinal_result_coverage": {
                    "prespecified_timepoints": ["3 months", "1 year", "2 years"],
                    "shown_timepoints": ["3 months", "2 years"],
                    "trajectory_required": True,
                    "rationale": "The time course changes the clinical interpretation of benefit.",
                },
                "companion_evidence": [],
                "coverage_risks": [],
            },
            "result_checks": [
                {"claim": "Responders", "expected": "6/7", "actual": "6/7", "source": "Figure 3", "pass": True}
            ],
        }
        plan_path = root / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        asset = root / "figure3.png"
        asset.write_bytes(b"png")
        assets_path = root / "assets.json"
        assets_path.write_text(
            json.dumps({"assets": [{
                "asset_id": "figure-3",
                "kind": "article_figure",
                "source_label": "Figure 3",
                "output_path": str(asset),
                "transformation": "crop only",
                "citation": "Reyes et al. 2026",
                "destination_slides": ["S02"],
            }]}),
            encoding="utf-8",
        )
        qa_path = root / "qa.json"
        substantive_main = [
            slide for slide in slides
            if not slide["backup"] and slide["role"] not in {"title", "section"}
        ]
        qa_path.write_text(json.dumps({
            "schema": "grand_rounds_visual_qa_v2",
            "status": "pass",
            "inspected_slide_count": len(slides),
            "full_size_slide_count": len(slides),
            "contact_sheet_inspected": True,
            "repair_cycle_count": 1,
            "design_brief_match": True,
            "meaningful_visual_main_slide_count": len(substantive_main),
            "layout_family_counts": dict(Counter(slide["layout_family"] for slide in substantive_main)),
            "min_title_font_size_pt": 35,
            "min_body_font_size_pt": 18,
            "overflow_slides": [],
            "overlap_slides": [],
            "clipped_slides": [],
            "title_wrap_slides": [],
            "unresolved_placeholders": [],
            "illegible_asset_slides": [],
            "figure_scale_failures": [],
            "citation_failures": [],
            "chart_label_failures": [],
            "alignment_failures": [],
            "misleading_quantitative_encoding_slides": [],
            "color_overuse_slides": [],
            "filled_container_overuse_slides": [],
            "rounded_container_slides": [],
            "decorative_line_overuse_slides": [],
            "dark_background_drift_slides": [],
            "textbox_fit_failures": [],
            "bullet_wall_slides": [],
            "weak_visual_anchor_slides": [],
            "repetitive_layout_slides": [],
            "decorative_chrome_slides": [],
            "ui_panel_slides": [],
            "palette_drift_slides": [],
            "typography_inconsistency_slides": [],
            "spacing_inconsistency_slides": [],
            "redundant_slides": [],
            "orphan_context_slides": [],
            "title_slide_interpretive_copy_slides": [],
            "slogan_or_tagline_slides": [],
            "rhetorical_or_adversarial_copy_slides": [],
            "low_information_annotation_slides": [],
            "narrative_prose_slides": [],
            "unsupported_interpretation_slides": [],
            "word_fragmentation_slides": [],
            "numeric_token_split_slides": [],
            "semantic_legend_failures": [],
            "pasted_chart_legend_slides": [],
            "watermarked_asset_slides": [],
            "redundant_interpretive_band_slides": [],
            "summary_duplication_slides": [],
            "cross_platform_render_failures": [],
            "citation_font_size_pt": 10,
        }), encoding="utf-8")
        return {"deck": deck, "journal": journal, "plan": plan_path, "assets": assets_path, "qa": qa_path}

    def test_valid_article_package_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.metrics["pptx_slide_count"], 10)
            self.assertEqual(result.metrics["pptx_notes_count"], 10)

    def test_missing_coverage_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            del plan["coverage"]["Neurosurgical Relevance"]
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("Neurosurgical Relevance" in error for error in result.errors))

    def test_unresolved_visual_qa_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            qa = json.loads(paths["qa"].read_text(encoding="utf-8"))
            qa["status"] = "fail"
            qa["clipped_slides"] = [4]
            paths["qa"].write_text(json.dumps(qa), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("visual QA" in error for error in result.errors))

    def test_missing_interpretation_critical_dimension_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            del plan["coverage_audit"]["required_dimensions"]["intervention_and_comparator"]
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("intervention_and_comparator" in error for error in result.errors))

    def test_thesis_determining_item_cannot_be_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            item = plan["coverage_audit"]["critical_items"][0]
            item["disposition"] = "omit"
            item["slide_ids"] = []
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("cannot omit thesis-determining" in error for error in result.errors))

    def test_trajectory_requires_multiple_timepoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            plan["coverage_audit"]["longitudinal_result_coverage"]["shown_timepoints"] = ["2 years"]
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("at least two outcome timepoints" in error for error in result.errors))

    def test_human_style_qa_failure_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            qa = json.loads(paths["qa"].read_text(encoding="utf-8"))
            qa["ui_panel_slides"] = [5]
            paths["qa"].write_text(json.dumps(qa), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("ui_panel_slides" in error for error in result.errors))

    def test_color_overuse_qa_failure_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            qa = json.loads(paths["qa"].read_text(encoding="utf-8"))
            qa["color_overuse_slides"] = [4]
            paths["qa"].write_text(json.dumps(qa), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("color_overuse_slides" in error for error in result.errors))

    def test_baylor_surface_requires_explicit_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            plan["style_profile"] = "custom_directed"
            plan["design_brief"]["route"] = "custom_directed"
            plan["design_brief"]["surface_style"] = "baylor_minimal_academic"
            plan["design_brief"]["background_strategy"] = "white_only"
            plan["design_brief"]["palette"] = {
                "canvas": "#FFFFFF",
                "ink": "#111827",
                "primary": "#1F4E79",
                "secondary": "#4B5563",
                "rule": "#E5E7EB",
                "signal": "#B71C3A",
            }
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("human_style_constraints" in error for error in result.errors))

    def test_baylor_surface_requires_reference_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            plan["design_brief"]["surface_style"] = "baylor_minimal_academic"
            plan["design_brief"]["background_strategy"] = "white_only"
            plan["design_brief"]["palette"] = {
                "canvas": "#FFFFFF",
                "ink": "#111827",
                "primary": "#1F4E79",
                "secondary": "#4B5563",
                "rule": "#E5E7EB",
                "signal": "#B71C3A",
            }
            plan["design_brief"]["human_style_constraints"] = {
                "white_backgrounds_only": True,
                "primary_accent_count_max": 1,
                "signal_color_count_max": 1,
                "filled_content_containers_max_per_slide": 0,
                "rounded_content_containers": "none",
                "recurring_page_furniture": [
                    "short navy title rule",
                    "neutral footer rule",
                ],
                "chart_palette": "navy plus neutral gray",
                "color_use": "data and essential warnings only",
                "interpretive_band_policy": "only when it adds a nonredundant clinical or validity consequence",
                "chart_legend_policy": "native compact legend with labels matched to the estimand",
                "summary_duplication": "none",
            }
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("reference_alignment" in error for error in result.errors))

    def test_academic_copy_qa_failure_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            qa = json.loads(paths["qa"].read_text(encoding="utf-8"))
            qa["slogan_or_tagline_slides"] = [1]
            paths["qa"].write_text(json.dumps(qa), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("slogan_or_tagline_slides" in error for error in result.errors))

    def test_repetitive_layout_family_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            for slide in plan["slides"]:
                if not slide["backup"] and slide["role"] not in {"title", "section"}:
                    slide["layout_family"] = "figure_first"
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("layout_family" in error for error in result.errors))

    def test_article_interpretive_subtitle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            plan["title_slide_subtitle"] = "Feasibility Without Proof"
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("interpretive subtitle" in error for error in result.errors))

    def test_small_citation_font_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            qa = json.loads(paths["qa"].read_text(encoding="utf-8"))
            qa["citation_font_size_pt"] = 8
            paths["qa"].write_text(json.dumps(qa), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("citation_font_size_pt" in error for error in result.errors))

    def test_weak_visual_anchor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            plan["slides"][1]["visual_anchor"] = "Bullet list"
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("meaningful visual_anchor" in error for error in result.errors))

    def test_chart_label_failure_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            qa = json.loads(paths["qa"].read_text(encoding="utf-8"))
            qa["chart_label_failures"] = [6]
            paths["qa"].write_text(json.dumps(qa), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("chart_label_failures" in error for error in result.errors))

    def test_semantic_legend_failure_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            qa = json.loads(paths["qa"].read_text(encoding="utf-8"))
            qa["semantic_legend_failures"] = [8]
            paths["qa"].write_text(json.dumps(qa), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("semantic_legend_failures" in error for error in result.errors))

    def test_missing_summary_slide_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            plan["slides"][8]["title"] = "Clinical Application"
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("Summary or Main Takeaways" in error for error in result.errors))

    def test_missing_background_slide_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            plan["slides"][1]["title"] = "Clinical Phenotype"
            plan["slides"][1]["role"] = "clinical_context"
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("Background or Introduction" in error for error in result.errors))

    def test_background_slide_requires_clinical_foundation_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            plan["slides"][1]["source_sections"] = ["Study Architecture"]
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("map to Clinical Foundation" in error for error in result.errors))

    def test_verbose_content_title_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
            plan["slides"][1]["title"] = "This Academic Slide Title Contains Far Too Many Words"
            paths["plan"].write_text(json.dumps(plan), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("title exceeds 8 words" in error for error in result.errors))

    def test_misleading_quantitative_encoding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._package(Path(tmp))
            qa = json.loads(paths["qa"].read_text(encoding="utf-8"))
            qa["misleading_quantitative_encoding_slides"] = [7]
            paths["qa"].write_text(json.dumps(qa), encoding="utf-8")
            result = guard.validate_package(
                deck=paths["deck"], plan_path=paths["plan"], assets_path=paths["assets"],
                visual_qa_path=paths["qa"], source_journal_club=paths["journal"],
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("misleading_quantitative_encoding_slides" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
