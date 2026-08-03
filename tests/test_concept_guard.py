from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src import concept_guard as guard


def _valid_note(extra: str = "") -> str:
    return f"""---
aliases: [ENRICH, lobar ICH trial]
created: 2026-06-06
extracted_from: "generate-report: Intracerebral Hemorrhage Management"
domain: vascular
summary: "Trial card for selecting lobar ICH patients for early minimally invasive evacuation."
tags: [type/concept, domain/vascular, source/agent]
---

**ENRICH Trial**: A randomized trial showing that early minimally invasive parafascicular surgery improves functional outcome for selected lobar intracerebral hemorrhage.

## Quick Reference

- **Population:** Spontaneous supratentorial lobar ICH, 30-80 mL, treated within 24 hours.
- **Core number:** Favorable mRS 0-3 outcome improved with surgery in the selected lobar cohort.

## Clinical Use

Use the trial to defend early surgical evaluation for a patient with a lobar hematoma who is still inside the operative time window. The concept changes triage because deep hemorrhage and lobar hemorrhage do not carry the same expected surgical benefit.

## Durable Mental Model

Lobar hemorrhage is a corridor problem: if the route avoids eloquent deep nuclei, removing mass effect can help. Deep hemorrhage is a tissue-disruption problem where the operative path can erase the benefit.

## Evidence Card

| Element | Clinical Anchor |
|---|---|
| Trial type | Multicenter randomized trial |
| Selection | Lobar ICH, 30-80 mL, within 24 hours |
| Use | Early neurosurgical triage for appropriate lobar hematoma |

## Critical Discriminators

- **ENRICH vs. MISTIE III:** ENRICH tested early parafascicular surgery in a more selected operative subgroup.
- **Lobar vs. deep ICH:** Lobar location is the key surgical selection boundary.

## Execution Check

- Identify whether the hematoma is lobar or deep before invoking ENRICH.
- State the time window and volume range when defending a surgical evaluation.
{extra}

## Related In This Vault

- [[Reports/Intracerebral Hemorrhage Management|Intracerebral Hemorrhage Management]]

## References

- Primary study: [Early Minimally Invasive Removal of Intracerebral Hemorrhage](https://doi.org/10.1056/NEJMoa2308440).
"""


class ConceptGuardTests(unittest.TestCase):
    def test_valid_note_installs_and_updates_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "draft.md"
            draft.write_text(_valid_note(), encoding="utf-8")

            result = guard.install_draft(draft, "ENRICH Trial", vault_root=root / "vault")
            target = root / "vault" / "Concepts" / "ENRICH Trial.md"
            index = root / "vault" / "Concepts" / "INDEX.md"

            self.assertTrue(result.ok, result.errors)
            self.assertTrue(target.exists())
            self.assertIn("[[Concepts/ENRICH Trial|ENRICH Trial]]", index.read_text(encoding="utf-8"))
            self.assertIn("Trial card for selecting lobar ICH", index.read_text(encoding="utf-8"))

    def test_rejects_missing_universal_heading(self) -> None:
        note = _valid_note().replace("## Durable Mental Model", "## Memory Hook")
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("missing required heading: ## Durable Mental Model", result.errors)

    def test_rejects_missing_archetype_section(self) -> None:
        note = _valid_note().replace("## Evidence Card", "## Details")
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("concept note must include one archetype-specific execution section", result.errors)

    def test_rejects_numeric_claims_without_linked_references(self) -> None:
        note = _valid_note().replace(
            "## References\n\n- Primary study: [Early Minimally Invasive Removal of Intracerebral Hemorrhage](https://doi.org/10.1056/NEJMoa2308440).\n",
            "",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("trial, guideline, numeric, or classification claims require linked References", result.errors)

    def test_rejects_missing_summary_and_domain(self) -> None:
        note = _valid_note().replace("domain: vascular\n", "").replace(
            'summary: "Trial card for selecting lobar ICH patients for early minimally invasive evacuation."\n',
            "",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertIn("frontmatter missing key: domain", result.errors)
        self.assertIn("frontmatter missing key: summary", result.errors)

    def test_accepts_one_high_density_bullet_per_execution_section(self) -> None:
        note = _valid_note().replace(
            "- **Core number:** Favorable mRS 0-3 outcome improved with surgery in the selected lobar cohort.\n",
            "",
        ).replace(
            "- **Lobar vs. deep ICH:** Lobar location is the key surgical selection boundary.\n",
            "",
        ).replace(
            "- State the time window and volume range when defending a surgical evaluation.\n",
            "",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertTrue(result.ok, result.errors)

    def test_accepts_explicit_absence_of_related_note(self) -> None:
        note = _valid_note().replace(
            "- [[Reports/Intracerebral Hemorrhage Management|Intracerebral Hemorrhage Management]]",
            "- No verified related vault note identified.",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertTrue(result.ok, result.errors)

    def test_rejects_protected_install_without_explicit_allow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "draft.md"
            draft.write_text(_valid_note(), encoding="utf-8")
            result = guard.install_draft(
                draft,
                "Neurosurgery Consult Workflow",
                vault_root=root / "vault",
            )
            self.assertFalse(result.ok)
            self.assertIn("protected concept note requires explicit allow_protected", result.errors)

    def test_rejects_unreviewed_overwrite_of_any_existing_concept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "draft.md"
            draft.write_text(_valid_note(), encoding="utf-8")
            target = root / "vault" / "Concepts" / "ENRICH Trial.md"
            target.parent.mkdir(parents=True)
            target.write_text(_valid_note("\n- Existing user-authored point."), encoding="utf-8")

            result = guard.install_draft(draft, "ENRICH Trial", vault_root=root / "vault")

            self.assertFalse(result.ok)
            self.assertIn("concept note already exists", result.errors[0])
            self.assertIn("Existing user-authored point", target.read_text(encoding="utf-8"))

    def test_allows_explicit_reviewed_merge_of_existing_concept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft = root / "draft.md"
            draft.write_text(_valid_note("\n- Preserved and merged point."), encoding="utf-8")
            target = root / "vault" / "Concepts" / "ENRICH Trial.md"
            target.parent.mkdir(parents=True)
            target.write_text(_valid_note(), encoding="utf-8")

            result = guard.install_draft(
                draft,
                "ENRICH Trial",
                vault_root=root / "vault",
                allow_existing=True,
            )

            self.assertTrue(result.ok, result.errors)
            self.assertIn("Preserved and merged point", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
