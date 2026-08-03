from __future__ import annotations

import json
import unittest
from pathlib import Path

from src import instruction_audit
from src.sync_agent_adapters import expected_files


ROOT = Path(__file__).resolve().parents[1]


class InstructionArchitectureTests(unittest.TestCase):
    def test_repository_instruction_lint_passes(self) -> None:
        result = instruction_audit.lint()
        self.assertTrue(result["ok"], result["errors"])

    def test_lint_patterns_catch_previously_silent_failures(self) -> None:
        fixtures = {
            "Targeting 85% resident mastery": "unverifiable_mastery_percentage",
            "Run serial per-domain retrieval": "stale_serial_retrieval",
            "Gabriel is an Advanced MS4": "stale_learner_profile",
            "Gemini guardrails: write bottom YAML": "stale_bottom_yaml_adapter",
            (
                "End the response with exactly: `Do you want to complete a quick "
                "Socratic lesson on these items?`"
            ): "forced_shift_debrief_phrase",
            "Extract 2-5 novel concepts from the report": "stale_concept_quota",
            "validate --min-questions 25": "stale_study_material_floor",
            "retrieval_status: ready": "invalid_retrieval_status_ready",
            "Propose three titles before proceeding": "stale_three_title_gate",
            "current_outcomes_source_present: true": "stale_current_outcomes_gate",
            "Mastery Objectives require 5-10 bullets": "fixed_mastery_objective_quota",
            "Use `study_memory.py summary` for learner-state context": "raw_summary_as_routine_recall",
        }
        for text, expected in fixtures.items():
            with self.subTest(expected=expected):
                self.assertIn(expected, instruction_audit._banned_fragments(text))

    def test_every_runtime_adapter_matches_registry_generated_content(self) -> None:
        registry = json.loads(
            (ROOT / ".agents/shared/workflow-registry.json").read_text()
        )
        expected = expected_files(registry)
        ui_file_count = sum(
            bool(workflow.get("codex_ui"))
            for workflow in registry["workflows"].values()
        )
        self.assertEqual(len(expected), len(registry["workflows"]) * 5 + ui_file_count)
        for path, content in expected.items():
            with self.subTest(path=path):
                self.assertTrue(path.is_file())
                self.assertEqual(path.read_text(), content)
                self.assertLessEqual(
                    len(content.split()), instruction_audit.MAX_WRAPPER_WORDS
                )


if __name__ == "__main__":
    unittest.main()
