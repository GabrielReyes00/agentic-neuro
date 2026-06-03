from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src import brain_dump_guard as guard


def _valid_note(extra: str = "") -> str:
    return f"""## De-identified Teaching Trigger

A postoperative patient with an external ventricular drain required transport planning.

## Extraction Map

- EVD transport teaching --> transport action? --> local protocol + mechanism --> confirm drain state

## Priority Takeaways

- Confirm drain state before transport; do not trust unverified local memory.

## Reported Teaching

- Service teaching - locally confirm: clarify drain clamping and leveling practice before transport.

## Verified Bridge

- Source-grounded: rapid changes in CSF drainage can alter intracranial pressure relationships.

## Operational Consequence

- Confirm the service-specific transport order before moving the patient.
{extra}

## Clarify Or Verify Locally

- Confirm the exact institutional transport protocol with the supervising team.

## Mastery Objectives

- Explain why drain state matters during transport.
- Identify which local protocol question must be confirmed before movement.

## Related In This Vault

- Related reference to verify when available.

## Sources

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

            revised = _valid_note("\n## Brain Dump - 2026-05-26\n\n- Service teaching - locally confirm: recheck leveling after transfer.")
            draft.write_text(revised, encoding="utf-8")
            result = guard.install_draft(draft, "EVD Transport Management", vault_root=vault)
            installed = (vault / "Brain Dumps" / "EVD Transport Management.md").read_text(encoding="utf-8")

            self.assertTrue(result.ok)
            self.assertIn("## De-identified Teaching Trigger", installed)
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

    def test_rejects_missing_provenance_tier_or_required_heading(self) -> None:
        note = _valid_note().replace("Source-grounded", "Supported").replace(
            "Service teaching - locally confirm", "Taught on rounds"
        ).replace("## Operational Consequence", "## Action")
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("missing required heading: ## Operational Consequence", result.errors)
        self.assertIn("artifact must identify at least one approved provenance tier", result.errors)

    def test_rejects_sources_without_external_hyperlink(self) -> None:
        note = _valid_note().replace(
            "[Verification source](https://doi.org/10.1000/example)", "Verification source"
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("Sources must include at least one linked external reference", result.errors)

    def test_rejects_unlabelled_source_bullets(self) -> None:
        note = _valid_note().replace("Guideline/formal guidance: ", "")
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("Sources must label evidence type for each support item", result.errors)

    def test_rejects_extraction_map_table(self) -> None:
        note = _valid_note().replace(
            "- EVD transport teaching --> transport action? --> local protocol + mechanism --> confirm drain state\n",
            "| Raw fragment | Interpreted question | Verification target | Final teaching point |\n"
            "|---|---|---|---|\n"
            "| EVD transport teaching | What transport detail changes action? | Local protocol plus source-grounded mechanism | Confirm drain state and leveling before movement |\n",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn(
            "Extraction Map must use terse '-->' flow lines, not a markdown table",
            result.errors,
        )

    def test_rejects_missing_extraction_map_flow(self) -> None:
        note = _valid_note().replace(
            "- EVD transport teaching --> transport action? --> local protocol + mechanism --> confirm drain state\n",
            "- No flow.\n",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("Extraction Map must include at least one '-->' flow line", result.errors)

    def test_rejects_verbose_extraction_map_node(self) -> None:
        note = _valid_note().replace(
            "local protocol + mechanism",
            "local protocol and the detailed source grounded mechanism that explains pressure gradients",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertTrue(
            any(error.startswith("extraction flow node too long") for error in result.errors),
            result.errors,
        )

    def test_rejects_missing_priority_takeaways_bullets(self) -> None:
        note = _valid_note().replace(
            "- Confirm drain state before transport; do not trust unverified local memory.\n",
            "No bullet.\n",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("Priority Takeaways must include 1 to 3 bullet takeaways", result.errors)

    def test_rejects_verbose_priority_takeaways(self) -> None:
        note = _valid_note().replace(
            "Confirm drain state before transport; do not trust unverified local memory.",
            "Confirm drain state before transport and then carefully think through every possible source of pressure gradient error before moving any patient anywhere",
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
            "Medication or operative-strategy artifacts must include Guideline/formal guidance or Primary study support, or explicitly state why unavailable",
            result.errors,
        )


if __name__ == "__main__":
    unittest.main()
