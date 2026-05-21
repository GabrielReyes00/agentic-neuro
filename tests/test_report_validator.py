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
    return f"""## Clinical Utility & Quick Reference
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

---
tags: [type/report]
---
"""


class ReportValidatorTests(unittest.TestCase):
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
                    "---\ntags: [type/report]\n---",
                    "```yaml\ntags: [type/report]\n```",
                )
            )

            failures = report_validator.validate(report_path)

        self.assertTrue(any("fenced code block" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()
