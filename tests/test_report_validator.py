import json
import tempfile
import unittest
from pathlib import Path

from src import report_validator


def _valid_report() -> str:
    objectives = "\n".join(
        f"- Distinguish management-changing feature {idx} from its closest mimic."
        for idx in range(1, 6)
    )
    numbers = "\n".join(
        f"| Parameter {idx} | Value {idx} | Context {idx} | Youmans 8th Ed, p. {700 + idx} |"
        for idx in range(1, 11)
    )
    return f"""---
domain: general
summary: "Operational test report for validator coverage."
tags: [type/report]
---

## Clinical Utility & Quick Reference
> **TL;DR:** This report summarizes a neurosurgical topic with operationally useful detail.

### When to Reference This Report
- Clinical scenario requiring a focused reference.

### Key Numbers at a Glance
| Parameter | Value | Context | Source |
|---|---|---|---|
{numbers}

### Decision Framework
1. **Identify the syndrome:** Decide whether the presentation matches the report topic.

## Body
Detailed source-grounded report content.

## Mastery Objectives
{objectives}
"""


def _valid_qualitative_report() -> str:
    return _valid_report().replace(
        "### Key Numbers at a Glance\n| Parameter | Value | Context | Source |\n|---|---|---|---|\n"
        + "\n".join(
            f"| Parameter {idx} | Value {idx} | Context {idx} | Youmans 8th Ed, p. {700 + idx} |"
            for idx in range(1, 11)
        ),
        "### Key Anchors at a Glance\n"
        "| Decision Or Structure | Anchor | Why It Matters | Source |\n"
        "|---|---|---|---|\n"
        "| Corridor selection | Preserve the safest working angle | Changes exposure risk | Youmans 8th Ed, p. 700 |",
    )


class ReportValidatorTests(unittest.TestCase):
    def test_one_high_density_mastery_objective_is_not_rejected_by_quota(self) -> None:
        report = _valid_report()
        report = report.replace(
            "\n".join(
                f"- Distinguish management-changing feature {idx} from its closest mimic."
                for idx in range(2, 6)
            ),
            "",
        )
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "Focused.md"
            report_path.write_text(report)
            failures = report_validator.validate(report_path)
        self.assertEqual(failures, [])

    def test_qualitative_anchor_table_passes_without_numeric_padding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "Qualitative.md"
            report_path.write_text(_valid_qualitative_report())
            failures = report_validator.validate(report_path)
        self.assertEqual(failures, [])

    def test_both_anchor_table_modes_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "Ambiguous.md"
            report_path.write_text(
                _valid_report().replace(
                    "### Decision Framework",
                    "### Key Anchors at a Glance\n"
                    "| Decision Or Structure | Anchor | Why It Matters | Source |\n"
                    "|---|---|---|---|\n"
                    "| Exposure | Preserve visualization | Avoid injury | Youmans 8th Ed, p. 700 |\n\n"
                    "### Decision Framework",
                )
            )
            failures = report_validator.validate(report_path)
        self.assertTrue(any("exactly one" in failure for failure in failures))

    def test_coverage_ledger_gap_status_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "Example.md"
            report_path.write_text(_valid_report())
            ledger_path = Path(tmp) / "coverage_ledger.json"
            ledger_path.write_text(
                json.dumps(
                    {
                        "blocks": {
                            "epidemiology": {"required": True, "status": "covered"},
                            "management": {"required": True, "status": "gap"},
                        }
                    }
                )
            )

            failures = report_validator.validate(report_path)
            failures.extend(report_validator.validate_coverage_ledger(ledger_path))

        self.assertTrue(any("management" in failure and "gap" in failure for failure in failures))

    def test_optional_coverage_ledger_gap_status_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "coverage_ledger.json"
            ledger_path.write_text(
                json.dumps(
                    {
                        "blocks": {
                            "operative_considerations": {"required": False, "status": "gap"},
                            "management": {"required": True, "status": "covered"},
                        }
                    }
                )
            )

            failures = report_validator.validate_coverage_ledger(ledger_path)

        self.assertEqual(failures, [])

    def test_textbook_label_with_pubmed_link_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "Example.md"
            report_path.write_text(
                _valid_report().replace(
                    "Youmans 8th Ed, p. 701",
                    "Youmans 8th Ed [PMID: 32541243](https://pubmed.ncbi.nlm.nih.gov/32541243)",
                    1,
                )
            )

            failures = report_validator.validate(report_path)

        self.assertTrue(any("textbook-style citation" in failure for failure in failures))

    def test_forbidden_report_yaml_metadata_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "Example.md"
            report_path.write_text(
                _valid_report().replace(
                    "tags: [type/report]\n---",
                    "tags: [type/report]\nprovenance: generated from cards\ninternal_knowledge_used: false\n---",
                )
            )

            failures = report_validator.validate(report_path)

        self.assertTrue(any("provenance" in failure for failure in failures))
        self.assertTrue(any("internal_knowledge_used" in failure for failure in failures))

    def test_fenced_yaml_metadata_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "Example.md"
            report_path.write_text(
                _valid_report().replace(
                    "---\ndomain: general\nsummary: \"Operational test report for validator coverage.\"\ntags: [type/report]\n---",
                    "```yaml\ndomain: general\nsummary: \"Operational test report for validator coverage.\"\ntags: [type/report]\n```",
                )
            )

            failures = report_validator.validate(report_path)

        self.assertTrue(any("fenced code block" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
