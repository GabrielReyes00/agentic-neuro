from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GrandRoundsContractTests(unittest.TestCase):
    def test_router_uses_mode_specific_modules(self) -> None:
        router = (ROOT / ".agents/shared/commands/grand-rounds.md").read_text(encoding="utf-8")
        for name in (
            "grand-rounds-case.md",
            "grand-rounds-article.md",
            "grand-rounds-deck.md",
            "grand-rounds-visual-design.md",
            "grand-rounds-rehearsal.md",
            "grand_rounds_guard.py",
        ):
            self.assertIn(name, router)

    def test_article_mode_consumes_journal_club_and_pdf(self) -> None:
        article = (ROOT / ".agents/shared/commands/grand-rounds-article.md").read_text(encoding="utf-8")
        for fragment in (
            "source_package_status: complete",
            "Coverage Ledger",
            "asset_manifest.json",
            "result_checks",
            "backup slides",
        ):
            self.assertIn(fragment, article)
        self.assertIn("speaker\nnotes", article.lower())

    def test_deck_contract_requires_real_render_and_guard(self) -> None:
        deck = (ROOT / ".agents/shared/commands/grand-rounds-deck.md").read_text(encoding="utf-8")
        for fragment in (
            "@oai/artifact-tool",
            "Render every slide",
            "visual_qa.json",
            "grand_rounds_guard.py",
            "Speaker notes are embedded",
            "zero-valued or absent outcomes",
            "chart_label_failures",
            "alignment_failures",
            "misleading_quantitative_encoding_slides",
            "color_overuse_slides",
            "filled_container_overuse_slides",
            "rounded_container_slides",
            "decorative_line_overuse_slides",
            "textbox_fit_failures",
            "publisher prose and page furniture",
            "editable PowerPoint tables",
            "grand_rounds_deck_plan_v2",
            "visual_anchor",
            "layout_family",
            "repair_cycle_count",
            "meaningful_visual_main_slide_count",
            "redundant_slides",
            "semantic_legend_failures",
            "watermarked_asset_slides",
            "redundant_interpretive_band_slides",
            "cross_platform_render_failures",
            "10-12 pt",
            "interpretive",
        ):
            self.assertIn(fragment, deck)

    def test_visual_design_contract_requires_academic_art_direction(self) -> None:
        visual = (ROOT / ".agents/shared/commands/grand-rounds-visual-design.md").read_text(encoding="utf-8")
        for fragment in (
            "Required Design Brief",
            "sentence case",
            "meaningful visual or evidence anchor",
            "55-75%",
            "white_only",
            "three consecutive",
            "repeated title underlines",
            "Fresh-Eyes Visual Critique",
            "Baylor Minimal Academic Surface",
            "navy plus neutral gray",
            "filled_content_containers_max_per_slide",
            "Human-edited journal-club exemplar",
            "Editorial subtraction pass",
            "reference_alignment",
            "native compact legend",
            "#1F4E79",
            "34-38 pt",
            "13.5-16 pt",
        ):
            self.assertIn(fragment, visual)

    def test_article_contract_requires_slide_economy(self) -> None:
        article = (ROOT / ".agents/shared/commands/grand-rounds-article.md").read_text(encoding="utf-8")
        for fragment in (
            "Slide separation test",
            "separation_rationale",
            "Every article deck requires one final main slide",
            "Main Takeaways",
            "Clinical Context",
            "preference-sensitive initial-strategy trial",
            "Verified longer-term or companion evidence",
        ):
            self.assertIn(fragment, article)

    def test_all_adapters_route_to_shared_authority(self) -> None:
        for relative in (
            ".agents/codex/skills/grand-rounds/SKILL.md",
            ".claude/commands/grand-rounds.md",
            ".gemini/commands/grand-rounds.md",
            ".gemini/commands/grand-rounds.toml",
            "plugins/agentic-neuro/commands/grand-rounds.md",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(".agents/shared/commands/grand-rounds.md", text)


if __name__ == "__main__":
    unittest.main()
