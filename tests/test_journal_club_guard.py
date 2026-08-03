from __future__ import annotations

import tempfile
import unittest
import re
from pathlib import Path

from src import journal_club_guard as guard


def _valid_note(*, status: str = "complete", source_pdf: str = "Journal Club/Sources/Hybrid Epilepsy Surgery.pdf") -> str:
    return f"""---
aliases: [combined resection and RNS]
article_title: "Combined Surgical Resection and Responsive Neurostimulation for Drug-Resistant Epilepsy: A Case Series"
authors: "Reyes G, Giridharan N, Shofty B, et al."
journal: "Operative Neurosurgery"
year: 2026
doi: "10.1227/ons.0000000000001962"
source_pdf: "{source_pdf}"
source_package_status: {status}
domain: functional
summary: "Hybrid resection and RNS case series for selected unresectable focal epilepsy."
generated: 2026-06-22
skill: journal-club
tags: [skill/journal-club, type/article, domain/functional, source/article]
---

**Citation:** Reyes et al. Operative Neurosurgery. 2026.

## Start Here

**Clinical Question:** Can partial resection plus RNS help selected patients whose seizure onset zone cannot be completely resected?

**One-Sentence Thesis:** A hybrid operation was feasible in a selected case series, but comparative efficacy remains unproven.

**Practice Verdict:** Hypothesis-generating support for multidisciplinary selection, not a new standard of care.

**Thirty-Second Explanation:** The operation removes safely resectable epileptogenic tissue and uses RNS to monitor and stimulate unresectable residual regions.

## Clinical Foundation

### Rapid Orientation

Drug-resistant focal epilepsy can arise from an epileptogenic network that overlaps eloquent cortex. Resection offers the greatest chance of seizure freedom when the clinically relevant network can be removed safely; RNS is a palliative closed-loop option when it cannot.

### Resident Deep Model

The decision is whether concordant localization permits complete safe resection. When a causal component is resectable but another localized component overlaps eloquent tissue, a hybrid strategy partitions treatment across resection and neuromodulation.

## Essential Concepts for This Paper

**Technical concept:** Epileptogenic zone

**Plain-language meaning:** The tissue whose removal or disconnection is necessary and sufficient for seizure freedom.

**Why it matters here:** The hybrid strategy assumes part of that network can be removed while another part must remain.

**Technical concept:** Responsive neurostimulation

**Plain-language meaning:** An implanted device detects selected electrographic patterns and delivers programmed stimulation.

**Why it matters here:** RNS is intended to treat and monitor the residual unresectable network rather than replace the resection.

## Why This Study Exists

Some patients fall between complete resection and neuromodulation alone. The paper describes a hybrid strategy for that selection problem.

## Study Architecture

This was a retrospective, single-center case series of seven selected patients treated between 2020 and 2022, without a control group. Outcomes were seizure frequency, seizure-free periods, severity, subjective changes, and complications. [Article PDF p. 2]

## Results That Matter

| Finding | Reported Result | Interpretation | Source |
|---|---|---|---|
| Mean seizure reduction | 79.3% among 7 patients | The average suggests benefit but can conceal nonresponse. | [Article PDF p. 1, Table 1] |
| Final seizure freedom | 3/7 patients (42.9%) | Encouraging selected-patient outcome without a counterfactual. | [Article PDF p. 1] |
| Complications | 0/7 reported | Feasibility signal, not a precise safety estimate. | [Article PDF p. 1] |

The range of seizure-frequency reduction was 0%-100%, demonstrating clinically important heterogeneity. [Article PDF p. 1]

## Figures and Tables Explained

### Table 1

The patient-level table is necessary because the mean can hide the nonresponder. It demonstrates heterogeneity but cannot isolate the contribution of resection from RNS.

## Interpretation

**Authors' Conclusion:** The combined approach may benefit selected patients with unresectable eloquent or secondary foci.

**Data-Supported Conclusion:** The series demonstrates feasibility and favorable outcomes in some highly selected patients.

**Overclaim To Avoid:** The study proves superiority over subtotal resection or RNS alone.

## Limitations That Actually Matter

### No counterfactual for the combined treatment

**Problem:** There was no subtotal-resection-only or RNS-only comparator.

**Why It Matters:** Improvement cannot be attributed to the combination or partitioned between its components.

**Threatened Conclusion:** Comparative efficacy of the hybrid strategy.

**Does The Main Finding Survive?:** Feasibility survives; superiority does not.

### Selection and outcome ascertainment

**Problem:** Seven multidisciplinary-selected patients were reviewed retrospectively with partly subjective outcomes.

**Why It Matters:** Favorable selection and reporting can inflate apparent benefit.

**Threatened Conclusion:** Expected benefit in routine candidates.

**Does The Main Finding Survive?:** The signal justifies study and discussion, not population-level prediction.

## Neurosurgical Relevance

The concept applies when a resectable driver coexists with an unresectable eloquent or secondary focus and both are supported by concordant localization. It does not justify combining procedures when localization is poor or complete safe resection is feasible.

## Historical and Current Context

### At Publication

Resection and RNS were established separately, while evidence for a planned hybrid operation remained limited [External context: Nair 2020].

### Current Context

The paper remains an early feasibility and selection report rather than comparative evidence.

Before this paper, resection and RNS were used mainly as separate strategies.

This paper added or contested the feasibility of a deliberately planned hybrid operation.

Today, the report supports selected-case discussion but not comparative superiority.

## Presentation Core

**Central Thesis:** Hybrid surgery is a network-partitioning strategy for selected unresectable focal epilepsy, supported here by feasibility rather than comparative proof.

**Clinical Context Slide:** Drug resistance, concordant localization, eloquent overlap, and the treatment-selection gap.

**Data Worth Showing:** Seven patients, 79.3% mean seizure reduction, 0%-100% range, 3/7 final seizure freedom, and 0 reported complications.

**Central Visual:** The patient-level outcome table because it reveals the heterogeneity hidden by the mean.

**Discussion Priorities:** Patient selection, contribution of each treatment component, and how RNS recordings should influence interpretation.

**Spoken Arc:** Define the selection gap, explain the hybrid logic, show individual outcomes, then bound the conclusion.

**What Not To Say:** Do not call the approach superior or generalizable from this uncontrolled series.

## Faculty Defense

### Question: What is the strongest finding?

The approach was technically feasible and some selected patients had substantial seizure improvement.

### Question: Why can the paper not establish synergy?

There is no comparator and both treatment components change over time.

### Question: What number most needs unpacking?

The 79.3% mean because the 0%-100% range reveals heterogeneity.

### Question: Who is the intended candidate?

A patient with a safely resectable component and a localized unresectable eloquent or secondary component.

## Mastery Objectives

- Explain the clinical selection gap addressed by hybrid surgery.
- Reconstruct the study design and outcome measures.
- State the decisive results with denominators.
- Explain why feasibility does not establish comparative efficacy.
- Identify the strongest selection and attribution limitations.
- Defend a bounded practice verdict before faculty.

## Source Trace

Article-derived claims use PDF page, table, or figure locators. External context uses linked citations.

**Source-Package Limitations:** No protocol or statistical analysis plan was available.

## References

- Primary article: [Reyes et al., 2026](https://doi.org/10.1227/ons.0000000000001962)
- External context: [Nair et al., 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7538230/)
"""


class JournalClubGuardTests(unittest.TestCase):
    def test_valid_note_installs_source_and_updates_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            draft = root / "draft.md"
            pdf = root / "article.pdf"
            draft.write_text(_valid_note(), encoding="utf-8")
            pdf.write_bytes(b"%PDF-1.4\n% test\n")

            result = guard.install_draft(
                draft,
                "Hybrid Epilepsy Surgery",
                vault_root=vault,
                source_pdf=pdf,
            )

            self.assertTrue(result.ok, result.errors)
            self.assertTrue((vault / "Journal Club" / "Hybrid Epilepsy Surgery.md").exists())
            self.assertTrue((vault / "Journal Club" / "Sources" / "Hybrid Epilepsy Surgery.pdf").exists())
            index = (vault / "Journal Club" / "INDEX.md").read_text(encoding="utf-8")
            self.assertIn("[[Journal Club/Hybrid Epilepsy Surgery|Hybrid Epilepsy Surgery]]", index)

    def test_complete_note_requires_installed_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "vault" / "Journal Club" / "Hybrid Epilepsy Surgery.md"
            note.parent.mkdir(parents=True)
            note.write_text(_valid_note(), encoding="utf-8")

            result = guard.validate_file(
                note,
                vault_root=root / "vault",
                check_physical_source=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any("source package PDF is missing" in error for error in result.errors))

    def test_preliminary_note_can_omit_pdf(self) -> None:
        note = _valid_note(status="preliminary", source_pdf="")
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertTrue(result.ok, result.errors)

    def test_rejects_missing_teaching_translation(self) -> None:
        note = _valid_note().replace("**Technical concept:** Responsive neurostimulation", "**Concept:** Responsive neurostimulation")
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertTrue(any("translation triplet" in error for error in result.errors))

    def test_rejects_generic_unstructured_limitations(self) -> None:
        section = guard._section_body(_valid_note(), "Limitations That Actually Matter")
        self.assertIsNotNone(section)
        note = _valid_note().replace(section or "", "- Small sample.\n- Retrospective design.")
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertTrue(any("interpretation-changing limitation" in error for error in result.errors))

    def test_rejects_thin_faculty_defense(self) -> None:
        note = _valid_note().replace("### Question:", "### Prompt:")
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertTrue(any("Faculty Defense" in error for error in result.errors))

    def test_rejects_result_row_without_locator(self) -> None:
        note = _valid_note().replace(
            "[Article PDF p. 1, Table 1]",
            "[paper]",
            1,
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertFalse(result.ok)
        self.assertTrue(any("row 1 lacks an article source locator" in error for error in result.errors))

    def test_accepts_one_complete_translation_triplet(self) -> None:
        note = _valid_note().replace(
            """\n**Technical concept:** Responsive neurostimulation

**Plain-language meaning:** An implanted device detects selected electrographic patterns and delivers programmed stimulation.

**Why it matters here:** RNS is intended to treat and monitor the residual unresectable network rather than replace the resection.\n""",
            "\n",
        )
        result = guard.validate_text(note, path=Path("draft.md"))
        self.assertTrue(result.ok, result.errors)

    def test_rejects_overwrite_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            draft = root / "draft.md"
            pdf = root / "article.pdf"
            draft.write_text(_valid_note(), encoding="utf-8")
            pdf.write_bytes(b"%PDF-1.4\n% test\n")
            first = guard.install_draft(draft, "Hybrid Epilepsy Surgery", vault_root=vault, source_pdf=pdf)
            second = guard.install_draft(draft, "Hybrid Epilepsy Surgery", vault_root=vault, source_pdf=pdf)
            self.assertTrue(first.ok, first.errors)
            self.assertFalse(second.ok)
            self.assertTrue(any("target already exists" in error for error in second.errors))


if __name__ == "__main__":
    unittest.main()
