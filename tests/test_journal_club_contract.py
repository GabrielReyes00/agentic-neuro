from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class JournalClubContractTests(unittest.TestCase):
    def test_cross_agent_adapters_point_to_shared_contract(self) -> None:
        paths = (
            ".agents/codex/skills/journal-club/SKILL.md",
            ".claude/commands/journal-club.md",
            ".gemini/commands/journal-club.md",
            ".gemini/commands/journal-club.toml",
            "plugins/agentic-neuro/commands/journal-club.md",
        )
        for relative_path in paths:
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn(".agents/shared/commands/journal-club.md", text)

    def test_shared_contract_uses_focused_modules_and_guard(self) -> None:
        contract = (ROOT / ".agents/shared/commands/journal-club.md").read_text(encoding="utf-8")
        for fragment in (
            "journal-club-analysis.md",
            "journal-club-artifact.md",
            "journal_club_guard.py",
            "Journal Club/Sources/<Short Article Title>.pdf",
            "Artifact is not mastery",
            "Combined Preparation",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, contract)

    def test_analysis_contract_keeps_appraisal_subordinate(self) -> None:
        analysis = (ROOT / ".agents/shared/commands/journal-club-analysis.md").read_text(encoding="utf-8")
        self.assertIn("Reporting guidelines\nare discovery aids", analysis)
        self.assertIn("Do not calculate a\nchecklist score", analysis)
        self.assertIn("Neurosurgery-Specific Threats", analysis)
        self.assertIn("Assume a medically literate intern", analysis)
        self.assertIn("Problem -> mechanism -> probable bias direction", analysis)

    def test_artifact_contract_requires_teaching_and_defense(self) -> None:
        artifact = (ROOT / ".agents/shared/commands/journal-club-artifact.md").read_text(encoding="utf-8")
        for fragment in (
            "Clinical Foundation",
            "Clinical Context Slide",
            "Essential Concepts for This Paper",
            "Plain-language meaning",
            "Results That Matter",
            "Limitations That Actually Matter",
            "Faculty Defense",
            "Mastery Objectives",
            "Source Trace",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, artifact)

    def test_root_router_distinguishes_analysis_from_deck_creation(self) -> None:
        root = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("assigned article PDF without a slide request -> `journal-club`", root)
        self.assertIn("journal club deck -> `grand-rounds`", root)
        self.assertIn("Journal Club/", root)


if __name__ == "__main__":
    unittest.main()
