import tempfile
import unittest
import re
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
    tu_refs = [
        f"TU-{((idx - 1) % chunk_count) + 1:02d}"
        for idx in range(1, question_count + 1)
    ]
    question_indices_by_tu: dict[str, list[int]] = {}
    for question_index, tu in enumerate(tu_refs):
        question_indices_by_tu.setdefault(tu, []).append(question_index)
    fact_refs_by_question: list[list[str]] = [[] for _ in range(question_count)]
    for chunk_idx in range(1, chunk_count + 1):
        tu = f"TU-{chunk_idx:02d}"
        question_indices = question_indices_by_tu.get(tu, [])
        if not question_indices:
            continue
        tu_fact_ids = [f"AF-{((chunk_idx - 1) * 3) + offset:03d}" for offset in range(1, 4)]
        for offset, fact_id in enumerate(tu_fact_ids):
            fact_refs_by_question[question_indices[offset % len(question_indices)]].append(fact_id)
        for question_index in question_indices:
            if not fact_refs_by_question[question_index]:
                fact_refs_by_question[question_index].append(tu_fact_ids[0])
    fact_refs = [", ".join(refs) for refs in fact_refs_by_question]
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
            "---",
            "artifact_type: study-material",
            "status: current",
            "domain: anatomy",
            "summary: Test source converted into active recall.",
            "aliases: []",
            "generated: 2026-04-21",
            "tags: [type/study-material, domain/anatomy]",
            "---",
            "",
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
        errors, warnings, metrics = guard.validate_content(_valid_note())
        self.assertEqual([], errors)
        self.assertEqual([], warnings)
        self.assertEqual(25, metrics["question_count"])
        self.assertEqual(25, metrics["answer_count"])
        self.assertEqual(30, metrics["atomic_fact_count"])

    def test_accepts_small_bank_when_source_coverage_is_complete(self):
        errors, _warnings, metrics = guard.validate_content(_valid_note(3, chunk_count=1))
        self.assertEqual([], errors)
        self.assertEqual(3, metrics["question_count"])

    def test_rejects_missing_answers(self):
        note = _valid_note().replace("<details><summary>Answer</summary>", "", 1)
        errors, _warnings, _metrics = guard.validate_content(note)
        self.assertIn("not every question has a <details> answer", "\n".join(errors))

    def test_rejects_shallow_fact_coverage_without_forcing_two_questions_per_slide(self):
        note = _valid_note(27, chunk_count=27)
        note = re.sub(r"(— AF-\d{3})(?:, AF-\d{3})+", r"\1", note)
        errors, _warnings, metrics = guard.validate_content(note)
        joined = "\n".join(errors)
        self.assertIn("does not cover the complete atomic fact ledger", joined)
        self.assertNotIn("question density too low", joined)
        self.assertEqual(81, metrics["atomic_fact_count"])

    def test_rejects_teaching_units_with_no_atomic_facts(self):
        note = _valid_note(25, chunk_count=10)
        shallow_note = note
        for idx in range(16, 31):
            shallow_note = shallow_note.replace(f"AF-{idx:03d}", f"XX-{idx:03d}")
        errors, _warnings, _metrics = guard.validate_content(shallow_note)
        self.assertIn("teaching units missing atomic facts", "\n".join(errors))

    def test_rejects_unassessed_teaching_unit_even_when_question_count_is_high(self):
        note = _valid_note(25, chunk_count=10).replace("— TU-10 —", "— TU-01 —")
        errors, _warnings, _metrics = guard.validate_content(note)
        self.assertIn("teaching units missing a mapped question: TU-10", "\n".join(errors))

    def test_rejects_one_question_that_claims_too_many_atomic_facts(self):
        note = _valid_note(25, chunk_count=10).replace(
            "— TU-01 — AF-001",
            "— TU-01 — AF-001, AF-002, AF-003, AF-004, AF-005",
            1,
        )
        errors, _warnings, _metrics = guard.validate_content(note)
        self.assertIn("questions reference more than 4 atomic facts", "\n".join(errors))

    def test_rejects_shadow_workspace_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agentic-neuro"
            shadow = root / "Documents" / "Obsidian" / "agentic-neuro" / "Study Material" / "Bad.md"
            shadow.parent.mkdir(parents=True)
            shadow.write_text(_valid_note(), encoding="utf-8")
            result = guard.validate_file(shadow, vault_root=Path(tmp) / "real-vault")
        self.assertFalse(result.ok)
        self.assertIn("target must be under", "\n".join(result.errors))

    def test_install_writes_to_real_vault_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            draft = tmp_root / "draft.md"
            draft.write_text(_valid_note(), encoding="utf-8")
            vault = tmp_root / "vault"
            result = guard.install_draft(draft, "Lab 9 - Test", vault_root=vault)
            target = vault / "Study Material" / "Lab 9 - Test.md"
            index = vault / "Study Material" / "INDEX.md"
            self.assertTrue(result.ok)
            self.assertTrue(target.exists())
            self.assertIn("[[Study Material/Lab 9 - Test|Lab 9 - Test]]", index.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
