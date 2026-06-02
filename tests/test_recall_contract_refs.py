from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RecallContractReferenceTests(unittest.TestCase):
    def test_cross_agent_study_review_adapters_require_startup_recall(self) -> None:
        paths = (
            ".agents/codex/skills/study-review/SKILL.md",
            ".claude/commands/study-review.md",
            ".gemini/commands/study-review.md",
            "plugins/agentic-neuro/commands/study-review.md",
        )
        for relative_path in paths:
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn("startup-recall", text)
                self.assertIn("planning_brief", text)

    def test_shared_learning_startup_contract_uses_orchestrated_recall(self) -> None:
        paths = (
            ".agents/shared/commands/learning-session-contract.md",
            ".agents/shared/commands/memory-operations.md",
            ".agents/shared/commands/memory-retrieval.md",
            ".agents/shared/commands/study-review.md",
        )
        stale_startup_fragments = (
            'summary --topic "<doc topic>" --limit 8 --scaffold-limit 2 --include-curated --include-model --brief-only',
            "summary --limit 12 --scaffold-limit 0 --include-curated --include-model --brief-only",
        )
        for relative_path in paths:
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn("startup-recall", text)
                for fragment in stale_startup_fragments:
                    self.assertNotIn(fragment, text)

    def test_root_agent_instructions_share_startup_recall_invariant(self) -> None:
        for relative_path in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn("startup-recall", text)
                self.assertIn("Raw `summary`", text)


if __name__ == "__main__":
    unittest.main()
