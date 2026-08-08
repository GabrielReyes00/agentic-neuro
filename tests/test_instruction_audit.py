from __future__ import annotations

import json
import unittest
from pathlib import Path

from src import instruction_audit
from src.sync_agent_adapters import (
    expected_files,
    expected_plugin_files,
    unexpected_managed_files,
)


ROOT = Path(__file__).resolve().parents[1]


def test_generated_surface_has_no_unregistered_files() -> None:
    registry = json.loads((ROOT / ".agents/shared/workflow-registry.json").read_text())
    expected = {**expected_files(registry), **expected_plugin_files(registry)}
    assert unexpected_managed_files(expected) == []


class InstructionArchitectureTests(unittest.TestCase):
    def test_instruction_counter_uses_official_tiktoken_encoding(self) -> None:
        encoder = instruction_audit._load_cl100k()
        self.assertEqual(encoder.name, "cl100k_base")
        self.assertEqual(encoder.encode("neurosurgery"), [818, 44486, 85392])
        self.assertEqual(
            instruction_audit.measure()["tokenizer_asset"],
            "tiktoken:cl100k_base",
        )

    def test_selected_runtime_specs_reduce_entry_prompt_load(self) -> None:
        runtime = instruction_audit.measure()["runtime_startup"]
        self.assertGreater(runtime["minimum_reduction_pct"], 0)
        self.assertGreater(runtime["median_reduction_pct"], 50)

    def test_shared_contract_reference_graph_is_acyclic_and_reachable(self) -> None:
        graph = instruction_audit.contract_reference_graph()
        self.assertEqual(graph["cycles"], [])
        self.assertEqual(graph["unreachable"], [])
        self.assertGreaterEqual(graph["nodes"], 50)

    def test_repository_instruction_lint_passes(self) -> None:
        result = instruction_audit.lint()
        self.assertTrue(result["ok"], result["errors"])

    def test_workflow_registry_uses_typed_execution_schema(self) -> None:
        registry = json.loads(
            (ROOT / ".agents/shared/workflow-registry.json").read_text()
        )
        self.assertEqual(registry["schema_version"], 2)
        self.assertEqual(
            registry["schema"],
            ".agents/shared/workflow-schema.json",
        )
        for name, workflow in registry["workflows"].items():
            with self.subTest(workflow=name):
                if workflow.get("alias_for"):
                    self.assertNotIn("execution", workflow)
                else:
                    self.assertIn("execution", workflow)

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
            "Write data/Sessions/<Title>/draft.md": "legacy_title_session_path",
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
        self.assertEqual(len(expected), len(registry["workflows"]) * 6 + ui_file_count)
        for path, content in expected.items():
            with self.subTest(path=path):
                self.assertTrue(path.is_file())
                self.assertEqual(path.read_text(), content)
                if ".agents/shared/runtime/" in str(path):
                    payload = json.loads(content)
                    self.assertEqual(payload["schema_version"], 1)
                    self.assertLessEqual(len(content.split()), 350)
                else:
                    self.assertLessEqual(
                        len(content.split()), instruction_audit.MAX_WRAPPER_WORDS
                    )

    def test_refactor_manual_note_capability_contracts_are_wired(self) -> None:
        registry = json.loads(
            (ROOT / ".agents/shared/workflow-registry.json").read_text()
        )
        workflow = registry["workflows"]["refactor-manual-note"]
        for flag in ("answer", "expand", "verify", "distill", "visualize"):
            with self.subTest(flag=flag):
                self.assertIn(f"[{flag}]", workflow["argument_hint"])
        self.assertEqual(
            workflow["binary_destination"],
            "z_Images/<Descriptive Visual Name>.<ext>",
        )

        base_contract = (ROOT / workflow["contract"]).read_text()
        augmentation_name = "refactor-manual-note-augmentation.md"
        visualize_name = "refactor-manual-note-visualize.md"
        self.assertIn(augmentation_name, base_contract)
        self.assertIn(visualize_name, base_contract)
        self.assertIn("The default is **refactor only**", base_contract)
        self.assertIn("one flowing note", base_contract)

        augmentation = (
            ROOT / ".agents/shared/commands" / augmentation_name
        ).read_text()
        for required in (
            "[? question text]",
            "ignore `[[wikilinks]]`",
            "finds no markers, perform the base refactor",
            "rewrite the surrounding prose",
            "Do not preserve the question",
            "selective gap repair",
            "## Verification Workflow",
            "## Distillation Workflow",
            "## Rapid Review",
            "target audience",
            "current primary guidance",
        ):
            with self.subTest(required=required):
                self.assertIn(required, augmentation)
        self.assertNotIn("[!question]", augmentation)

        visualize = (
            ROOT / ".agents/shared/commands" / visualize_name
        ).read_text()
        for required in (
            "Zero new visuals",
            "**Source visual:**",
            "**Generated schematic:**",
            "z_Images/<Descriptive Title Case Name>.<ext>",
            "src/vault_library.py refresh",
            "zero integrity failures",
        ):
            with self.subTest(required=required):
                self.assertIn(required, visualize)


if __name__ == "__main__":
    unittest.main()
