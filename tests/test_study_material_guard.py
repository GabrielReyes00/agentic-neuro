import tempfile
import unittest
from pathlib import Path

from src import study_material_guard as guard


def _valid_note(question_count: int = 25, chunk_count: int = 10) -> str:
    summary = "\n".join(
        f"### TU-{idx:02d}: Concept {idx}\n- High-yield fact {idx} with clinical consequence."
        for idx in range(1, chunk_count + 1)
    )
    inventory = "\n".join(
        f"| Slide {idx} | TU-{idx:02d} | Content slide {idx} | 3 |"
        for idx in range(1, chunk_count + 1)
    )
    fact_lines = []
    fact_id = 1
    for chunk_idx in range(1, chunk_count + 1):
        for _fact_idx in range(1, 4):
            fact_lines.append(
                f"- AF-{fact_id:03d} | TU-{chunk_idx:02d} | Slide {chunk_idx} | "
                f"Atomic tested fact {fact_id}."
            )
            fact_id += 1
    facts = "\n".join(fact_lines)
    fact_total = len(fact_lines)
    covered_fact_count = max(int(fact_total * 0.75), question_count)
    covered_fact_count = min(covered_fact_count, fact_total)
    fact_refs = [
        f"AF-{((idx - 1) % covered_fact_count) + 1:03d}"
        for idx in range(1, question_count + 1)
    ]
    # Ensure the first covered facts appear at least once for deterministic coverage.
    for idx in range(min(covered_fact_count, question_count)):
        fact_refs[idx] = f"AF-{idx + 1:03d}"
    tu_refs = [
        f"TU-{((idx - 1) % chunk_count) + 1:02d}"
        for idx in range(1, question_count + 1)
    ]
    slide_refs = [
        ((idx - 1) % chunk_count) + 1
        for idx in range(1, question_count + 1)
    ]
    complexity_counts = {
        "recall": 0,
        "spatial": 0,
        "discrimination": 0,
        "mechanism": 0,
        "integration": 0,
    }
    complexities = ["recall", "spatial", "discrimination", "mechanism", "integration"]
    question_chunks = []
    for idx in range(1, question_count + 1):
        complexity = complexities[(idx - 1) % len(complexities)]
        complexity_counts[complexity] += 1
        question_chunks.append(
            "\n".join(
                [
                    f"### Q{idx} [{complexity}] (Slide {slide_refs[idx - 1]}) — "
                    f"{tu_refs[idx - 1]} — {fact_refs[idx - 1]}",
                    f"**Question {idx}?**",
                    "",
                    "<details><summary>Answer</summary>",
                    "",
                    "Answer with explanation, discriminator, and management consequence.",
                    "",
                    "</details>",
                ]
            )
        )
    mix = " / ".join(f"{count} {name}" for name, count in complexity_counts.items())
    return "\n".join(
        [
            "**Source:** Test deck.pptx | **Generated:** 2026-04-21 | **Total Questions:** "
            f"{question_count}",
            f"**Complexity Mix:** {mix}",
            f"**Chunks Processed:** {chunk_count} / {chunk_count}",
            "",
            "## Source Chunk Inventory",
            "| Source | TU | Status | Atomic Facts |",
            "|---|---|---|---:|",
            inventory,
            "",
            "## Atomic Fact Ledger",
            facts,
            "",
            "## Concept Summary",
            summary,
            "",
            "## Questions",
            "\n\n---\n\n".join(question_chunks),
        ]
    )


class StudyMaterialGuardTests(unittest.TestCase):
    def test_valid_generated_note_passes(self):
        errors, warnings, metrics = guard.validate_content(_valid_note(), min_questions=25)
        self.assertEqual([], errors)
        self.assertEqual([], warnings)
        self.assertEqual(25, metrics["question_count"])
        self.assertEqual(25, metrics["answer_count"])
        self.assertEqual(30, metrics["atomic_fact_count"])

    def test_rejects_too_few_questions(self):
        errors, _warnings, metrics = guard.validate_content(_valid_note(16, chunk_count=5), min_questions=25)
        self.assertIn("too few questions", "\n".join(errors))
        self.assertEqual(16, metrics["question_count"])

    def test_rejects_missing_answers(self):
        note = _valid_note().replace("<details><summary>Answer</summary>", "", 1)
        errors, _warnings, _metrics = guard.validate_content(note, min_questions=25)
        self.assertIn("not every question has a <details> answer", "\n".join(errors))

    def test_rejects_one_question_per_slide_compression(self):
        errors, _warnings, metrics = guard.validate_content(_valid_note(27, chunk_count=27), min_questions=25)
        joined = "\n".join(errors)
        self.assertIn("question density too low", joined)
        self.assertEqual(81, metrics["atomic_fact_count"])

    def test_rejects_atomic_fact_under_extraction(self):
        note = _valid_note(25, chunk_count=10)
        shallow_note = note
        for idx in range(16, 31):
            shallow_note = shallow_note.replace(f"AF-{idx:03d}", f"XX-{idx:03d}")
        errors, _warnings, _metrics = guard.validate_content(shallow_note, min_questions=25)
        self.assertIn("atomic fact extraction too shallow", "\n".join(errors))

    def test_rejects_shadow_workspace_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agentic-neuro"
            shadow = root / "Documents" / "Obsidian" / "agentic-neuro" / "Study Material" / "Bad.md"
            shadow.parent.mkdir(parents=True)
            shadow.write_text(_valid_note(), encoding="utf-8")
            result = guard.validate_file(shadow, vault_root=Path(tmp) / "real-vault", min_questions=25)
        self.assertFalse(result.ok)
        self.assertIn("target must be under", "\n".join(result.errors))

    def test_install_writes_to_real_vault_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            draft = tmp_root / "draft.md"
            draft.write_text(_valid_note(), encoding="utf-8")
            vault = tmp_root / "vault"
            result = guard.install_draft(draft, "Lab 9 - Test", vault_root=vault, min_questions=25)
            target = vault / "Study Material" / "Lab 9 - Test.md"
            index = vault / "Study Material" / "INDEX.md"
            self.assertTrue(result.ok)
            self.assertTrue(target.exists())
            self.assertIn("[[Lab 9 - Test]]", index.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
