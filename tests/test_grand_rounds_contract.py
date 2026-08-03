from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from src import grand_rounds_guard as guard


ROOT = Path(__file__).resolve().parents[1]


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class GrandRoundsContractTests(unittest.TestCase):
    def test_router_uses_mode_specific_modules(self) -> None:
        router = (ROOT / ".agents/shared/commands/grand-rounds.md").read_text()
        for name in (
            "grand-rounds-case.md",
            "grand-rounds-article.md",
            "grand-rounds-deck.md",
            "grand-rounds-visual-design.md",
            "grand-rounds-rehearsal.md",
            "grand_rounds_guard.py",
        ):
            self.assertIn(name, router)

    def test_article_mode_consumes_a_complete_dossier_and_pdf(self) -> None:
        article = _normalized(
            (ROOT / ".agents/shared/commands/grand-rounds-article.md").read_text()
        )
        for fragment in (
            "source_package_status: complete",
            "coverage_audit",
            "asset_manifest.json",
            "result_checks",
            "backup slides",
            "speaker notes",
        ):
            self.assertIn(fragment, article)

    def test_deck_contract_uses_executable_qa_schema_and_real_render(self) -> None:
        deck = (ROOT / ".agents/shared/commands/grand-rounds-deck.md").read_text()
        for fragment in (
            "@oai/artifact-tool",
            "Render every slide",
            "visual_qa.json",
            "visual-qa-template",
            "grand_rounds_guard.py",
            "Speaker notes are embedded",
            "zero-valued or absent outcomes",
            "publisher prose and page furniture",
            "editable PowerPoint tables",
            "grand_rounds_deck_plan_v2",
            "visual_anchor",
            "layout_family",
            "repair_cycle_count",
            "meaningful_visual_main_slide_count",
        ):
            self.assertIn(fragment, deck)
        template = guard.visual_qa_template(slide_count=1)
        self.assertEqual(template["schema"], guard.VISUAL_QA_SCHEMA)
        for key in guard.VISUAL_QA_EMPTY_LIST_KEYS:
            self.assertEqual(template[key], [])

    def test_visual_design_uses_one_declarative_style_registry(self) -> None:
        visual = _normalized(
            (ROOT / ".agents/shared/commands/grand-rounds-visual-design.md").read_text()
        )
        style = json.loads(
            (ROOT / ".agents/shared/presentation-styles.json").read_text()
        )["styles"]["baylor_minimal_academic"]
        for fragment in (
            "Required Design Brief",
            "sentence case",
            "meaningful visual or evidence anchor",
            "55-75%",
            "three consecutive",
            "repeated title underlines",
            "Fresh-Eyes Visual Critique",
            "Baylor Minimal Academic Surface",
            "reference_alignment",
            "native compact legend",
            "Editorial Subtraction Pass",
        ):
            self.assertIn(fragment, visual)
        self.assertEqual(style["palette"]["primary"], "#1F4E79")
        self.assertEqual(style["constraints"]["chart_palette"], "navy plus neutral gray")
        self.assertEqual(
            style["constraints"]["filled_content_containers_max_per_slide"], 0
        )
        self.assertEqual(style["font_floors_pt"]["body"], 13.5)

    def test_article_contract_preserves_economy_and_evidence_dimensions(self) -> None:
        article = _normalized(
            (ROOT / ".agents/shared/commands/grand-rounds-article.md").read_text()
        ).lower()
        for fragment in (
            "slide separation test",
            "separation_rationale",
            "every article deck ends with one main",
            "main takeaways",
            "initial-strategy trials separate assignment from treatment received",
            "companion evidence",
            "longitudinal_results",
            "interpretation_and_bias",
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
            text = (ROOT / relative).read_text()
            self.assertIn(".agents/shared/commands/grand-rounds.md", text)
            self.assertLessEqual(len(text.split()), 120)


if __name__ == "__main__":
    unittest.main()
