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

    def test_service_log_adapters_point_to_shared_contract(self) -> None:
        paths = (
            ".agents/codex/skills/service-log/SKILL.md",
            ".claude/commands/service-log.md",
            ".gemini/commands/service-log.md",
            ".gemini/commands/service-log.toml",
            "plugins/agentic-neuro/commands/service-log.md",
        )
        for relative_path in paths:
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn(".agents/shared/commands/service-log.md", text)

    def test_service_log_contract_references_real_memory_commands(self) -> None:
        contract = (ROOT / ".agents/shared/commands/service-log.md").read_text()
        implementation = (ROOT / "src/study_memory.py").read_text()
        for command in (
            "rotation-current",
            "rotation-start",
            "startup-recall",
            "log-answer",
            "end-session",
        ):
            with self.subTest(command=command):
                self.assertIn(command, contract)
                self.assertIn(command, implementation)
        for flag in ("--lens", "--origin"):
            with self.subTest(flag=flag):
                self.assertIn(flag, contract)
                self.assertIn(flag, implementation)
        self.assertIn("service", implementation)

    def test_root_agent_instructions_route_service_log(self) -> None:
        contract = (ROOT / ".agents/shared/commands/service-log.md").read_text()
        for fragment in (
            "startup-recall --lens service",
            "Neurosurgery::Service Learning",
            "service_primary_formal_capped",
        ):
            with self.subTest(contract_fragment=fragment):
                self.assertIn(fragment, contract)
        for relative_path in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text()
                self.assertIn("service-log", text)
                self.assertIn(".agents/shared/commands/service-log.md", text)


if __name__ == "__main__":
    unittest.main()
