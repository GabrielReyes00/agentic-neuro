from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src import brain_dump_guard as guard


def _valid_note(extra: str = "") -> str:
    return f"""## Clinical Focus

- **EVD Transport:** Practical implications of drain state and pressure-gradient risk during movement.
- **Local Protocol:** Which transport order details require point-of-care confirmation.

## Priority Takeaways

- Confirm drain state before transport; do not treat unverified local memory as a protocol.

## Clinical & Anatomical Synthesis

A patient with an external ventricular drain can experience clinically meaningful pressure-gradient changes when drainage height, clamping state, or transport positioning changes. The generalizable principle is not a universal clamp-or-do-not-clamp rule; it is that drain state, leveling, and monitoring plan must be made explicit before movement (Youmans & Winn, 8th ed., Vol. 4, p. 122).

## Operational Mental Models

### The Pressure Column Handoff

A transport handoff should preserve the intended CSF pressure column: know whether the system is open, clamped, or leveled before the patient moves.
{extra}

## Institutional & Local Clarifications

- Confirm the exact institutional transport protocol with the supervising team.

## Mastery Objectives

- Explain why drain state matters during transport.
- Identify which local protocol question must be confirmed before movement.

## Related In This Vault

- Related reference to verify when available.

## References

- Guideline/formal guidance: [Verification source](https://doi.org/10.1000/example)

---
tags: [skill/brain-dump, domain/neurocritical-care, type/reference, source/user]
generated: 2026-05-25
skill: brain-dump
provenance: "reported service teaching with source-grounded mechanism"
internal_knowledge_used: false
---
"""


class BrainDumpGuardTests(unittest.TestCase):
    def test_valid_note_installs_into_brain_dumps_and_updates_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "draft.md"
            draft.write_text(_valid_note(), encoding="utf-8")

            result = guard.install_draft(draft, "EVD Transport Management", vault_root=root / "vault")
            target = root / "vault" / "Brain Dumps" / "EVD Transport Management.md"
            index = root / "vault" / "Brain Dumps" / "INDEX.md"

            self.assertTrue(result.ok)
            self.assertTrue(target.exists())
            self.assertIn("[[Brain Dumps/EVD Transport Management|", index.read_text(encoding="utf-8"))

    def test_existing_note_can_be_reinstalled_with_preserved_body_and_new_encounter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "draft.md"
            vault = root / "vault"
            draft.write_text(_valid_note(), encoding="utf-8")
            guard.install_draft(draft, "EVD Transport Management", vault_root=vault)

            revised = _valid_note("\n## Brain Dump - 2026-05-26\n\n- Recheck leveling after transfer using the local transport pathway.")
            draft.write_text(revised, encoding="utf-8")
            result = guard.install_draft(draft, "EVD Transport Management", vault_root=vault)
            installed = (vault / "Brain Dumps" / "EVD Transport Management.md").read_text(encoding="utf-8")

            self.assertTrue(result.ok)
            self.assertIn("## Clinical Focus", installed)
            self.assertIn("## Brain Dump - 2026-05-26", installed)

    def test_rejects_common_direct_identifiers(self) -> None:
        variants = {
            "MRN: 1234567": "medical record number",
            "DOB: 01/02/1980": "date of birth",
            "Room 432": "room or bed identifier",
            "admitted on 05/20/2026": "exact clinical timeline date",
            "Patient Name: Test Person": "named patient",
            "contact test.person@example.com": "email address",
        }
        for inserted, expected in variants.items():
            with self.subTest(inserted=inserted):
                result = guard.validate_text(_valid_note(f"\n- {inserted}"), path=Path("draft.md"))
                self.assertFalse(result.ok)
                self.assertIn(expected, "\n".join(result.errors))

    def test_rejects_missing_required_heading(self) -> None:
        note = _valid_note().replace("## Operational Mental Models", "## Action")
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("missing required heading: ## Operational Mental Models", result.errors)

    def test_rejects_references_without_external_hyperlink(self) -> None:
        note = _valid_note().replace(
            "[Verification source](https://doi.org/10.1000/example)", "Verification source"
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("References must include at least one linked external reference", result.errors)

    def test_rejects_unlabelled_reference_bullets(self) -> None:
        note = _valid_note().replace("Guideline/formal guidance: ", "")
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("References must label evidence type for each support item", result.errors)

    def test_rejects_clinical_focus_without_bullets(self) -> None:
        note = _valid_note().replace(
            "- **EVD Transport:** Practical implications of drain state and pressure-gradient risk during movement.\n"
            "- **Local Protocol:** Which transport order details require point-of-care confirmation.\n",
            "EVD transport and local protocol confirmation.\n",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("Clinical Focus must include concise bullet topics", result.errors)

    def test_rejects_missing_synthesis_inline_citation(self) -> None:
        note = _valid_note().replace(
            " (Youmans & Winn, 8th ed., Vol. 4, p. 122)",
            "",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn(
            "Clinical & Anatomical Synthesis must include academic inline citations",
            result.errors,
        )

    def test_rejects_unnamed_operational_mental_model(self) -> None:
        note = _valid_note().replace(
            "### The Pressure Column Handoff\n\n",
            "",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("Operational Mental Models must include at least one named model subheading", result.errors)

    def test_rejects_missing_priority_takeaways_bullets(self) -> None:
        note = _valid_note().replace(
            "- Confirm drain state before transport; do not treat unverified local memory as a protocol.\n",
            "No bullet.\n",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("Priority Takeaways must include 1 to 3 bullet takeaways", result.errors)

    def test_rejects_verbose_priority_takeaways(self) -> None:
        note = _valid_note().replace(
            "Confirm drain state before transport; do not treat unverified local memory as a protocol.",
            "Confirm drain state before transport and then carefully think through every possible source of pressure gradient error before moving any patient anywhere while reviewing the entire broader transport workflow and every possible monitoring contingency",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertTrue(
            any(error.startswith("Priority Takeaways bullets must be succinct") for error in result.errors),
            result.errors,
        )

    def test_rejects_high_stakes_without_guideline_or_primary_source(self) -> None:
        note = _valid_note().replace("Guideline/formal guidance: ", "External review: ")
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn(
            "Medication or operative-strategy artifacts must include Guideline/formal guidance or Primary study support, or explicitly state in Institutional & Local Clarifications why unavailable",
            result.errors,
        )

    def test_allows_high_stakes_with_explicit_unavailable_primary_support_note(self) -> None:
        note = _valid_note().replace("Guideline/formal guidance: ", "External review: ").replace(
            "- Confirm the exact institutional transport protocol with the supervising team.",
            "- No guideline/formal guidance or primary study was identified for the local transport protocol; confirm it with the supervising team.",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertTrue(result.ok, result.errors)


if __name__ == "__main__":
    unittest.main()
