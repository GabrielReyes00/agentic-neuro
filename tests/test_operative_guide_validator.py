from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import operative_guide_validator as validator


class IncompleteVerdictChainTests(unittest.TestCase):
    def test_one_actionable_mastery_objective_is_structurally_valid(self) -> None:
        failures: list[str] = []
        validator._mastery_objectives(
            "## Mastery Objectives\n- Defend the operative bailout threshold.\n",
            ["## Mastery Objectives", "- Defend the operative bailout threshold."],
            failures,
        )
        self.assertEqual(failures, [])

    def test_incomplete_guide_can_name_a_missing_domain_as_unresolved(self) -> None:
        domain = next(
            item
            for item in validator.REQUIRED_DOMAINS
            if item.label == "neuromonitoring strategy"
        )
        sections = [
            (
                "Unresolved Or Weak Areas",
                "- Neuromonitoring strategy remains unresolved pending local protocol verification.",
            )
        ]
        self.assertTrue(validator._domain_named_as_unresolved(domain, sections))

    def _chain(self, root: Path, *, authorized_ids: list[str] | None) -> Path:
        guide = root / "Example Procedure.md"
        verdicts = root / "sessions" / "Example Procedure" / "verdicts"
        verdicts.mkdir(parents=True)
        (verdicts / "decomposition.json").write_text(
            json.dumps({"coverage_matrix_complete": True})
        )
        (verdicts / "research.json").write_text(
            json.dumps(
                {
                    "coverage_gate_met": True,
                    "current_evidence_required": False,
                }
            )
        )
        (verdicts / "map-review-cycle-1.json").write_text(
            json.dumps({"verdict": "MAP_APPROVED"})
        )
        (verdicts / "expert-review-cycle-1.json").write_text(
            json.dumps(
                {
                    "cycle": 1,
                    "verdict": "REVISION REQUIRED",
                    "blocking_gaps": [
                        {
                            "coverage_matrix_block": "CM-07",
                            "rubric_block": "bailout",
                        }
                    ],
                }
            )
        )
        (verdicts / "gap-repair-cycle-1.json").write_text(json.dumps({"cycle": 1}))
        if authorized_ids is not None:
            (verdicts / "incomplete-authorization.json").write_text(
                json.dumps(
                    {
                        "authorized": True,
                        "authorized_by": "user",
                        "authorization_context": "Use for a bounded rehearsal now.",
                        "unresolved_gap_ids": authorized_ids,
                    }
                )
            )
        return guide

    def test_revision_verdict_is_not_a_complete_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guide = self._chain(root, authorized_ids=["CM-07"])
            with patch.object(validator, "SESSIONS_DIR", root / "sessions"):
                failures = validator._verdict_chain_check(guide)
            self.assertTrue(any("must be 'APPROVED'" in item for item in failures))

    def test_explicit_incomplete_authorization_covers_latest_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guide = self._chain(root, authorized_ids=["CM-07"])
            with patch.object(validator, "SESSIONS_DIR", root / "sessions"):
                failures = validator._verdict_chain_check(
                    guide, allow_incomplete=True
                )
            self.assertEqual(failures, [])

    def test_incomplete_authorization_cannot_hide_an_unlisted_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            guide = self._chain(root, authorized_ids=["CM-02"])
            with patch.object(validator, "SESSIONS_DIR", root / "sessions"):
                failures = validator._verdict_chain_check(
                    guide, allow_incomplete=True
                )
            self.assertTrue(any("does not cover expert gaps" in item for item in failures))


if __name__ == "__main__":
    unittest.main()
