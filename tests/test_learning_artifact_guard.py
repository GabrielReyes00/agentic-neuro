import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from src import learning_artifact_guard as guard


def _body_for(artifact_type: str) -> str:
    sections = guard.ARTIFACT_CONFIG[artifact_type]["required_sections"]
    chunks = []
    for section in sections:
        chunks.append(
            "\n".join(
                [
                    f"## {section}",
                    "",
                    f"{section} content with concrete clinical details, source-linked decisions, "
                    "and a learner-facing consequence. Correct: one item was handled well. "
                    "Partial: one item required repair. Incorrect: one unsafe or incomplete "
                    "answer was corrected. Transfer was tested through a new context. "
                    "Next action is explicit and narrow.",
                ]
            )
        )
    return "\n\n".join(chunks)


class LearningArtifactGuardTests(unittest.TestCase):
    def test_all_artifact_types_have_valid_body(self):
        for artifact_type in guard.ARTIFACT_CONFIG:
            with self.subTest(artifact_type=artifact_type):
                errors, warnings, metrics = guard.validate_content(
                    _body_for(artifact_type),
                    artifact_type,
                    min_words=120,
                    require_bottom_yaml=False,
                )
                self.assertEqual([], errors)
                self.assertEqual([], warnings)
                self.assertGreaterEqual(metrics["section_count"], 5)

    def test_rejects_checkpoint_only_review(self):
        text = "\n".join(
            [
                "## Checkpoints",
                "",
                "### Checkpoint - Turn 1",
                "**Status**: IN-PROGRESS",
            ]
        )
        errors, _warnings, _metrics = guard.validate_content(
            text,
            "study-session",
            min_words=10,
            require_bottom_yaml=False,
        )
        joined = "\n".join(errors)
        self.assertIn("missing required sections", joined)
        self.assertIn("checkpoint-only", joined)

    def test_rejects_shadow_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agentic-neuro"
            shadow = root / "Documents" / "Obsidian" / "agentic-neuro" / "Review Sessions" / "Bad.md"
            shadow.parent.mkdir(parents=True)
            shadow.write_text(_body_for("oral-boards"), encoding="utf-8")
            result = guard.validate_file(
                shadow,
                "oral-boards",
                vault_root=Path(tmp) / "real-vault",
                min_words=120,
                require_bottom_yaml=False,
            )
        self.assertFalse(result.ok)
        self.assertIn("target must be under", "\n".join(result.errors))

    def test_install_adds_bottom_yaml_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "draft.md"
            draft.write_text(_body_for("intern-bootcamp"), encoding="utf-8")
            vault = root / "vault"
            result = guard.install_draft(
                draft,
                "intern-bootcamp",
                "Cross Cover Crisis",
                vault_root=vault,
                topic="postop deterioration",
                domain="general",
                min_words=120,
            )
            target = vault / "Review Sessions" / "Cross Cover Crisis.md"
            index = vault / "Review Sessions" / "INDEX.md"
            self.assertTrue(result.ok)
            self.assertTrue(target.exists())
            self.assertIn("status: complete", target.read_text(encoding="utf-8"))
            self.assertIn("[[Cross Cover Crisis]]", index.read_text(encoding="utf-8"))

    def test_check_draft_cli_does_not_require_vault_path_or_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "draft.md"
            draft.write_text(_body_for("debrief"), encoding="utf-8")
            with redirect_stdout(StringIO()):
                rc = guard.main([
                    "check-draft",
                    "--draft", str(draft),
                    "--artifact-type", "debrief",
                    "--min-words", "120",
                ])
        self.assertEqual(0, rc)


if __name__ == "__main__":
    unittest.main()
