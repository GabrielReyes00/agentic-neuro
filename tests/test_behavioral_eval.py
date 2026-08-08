from __future__ import annotations

import json
from pathlib import Path

from src.behavioral_eval import (
    emit_prompt_rows,
    grade_predictions,
    load_suite,
    validate_suite,
)


def test_behavior_suite_covers_all_canonical_graphs() -> None:
    result = validate_suite()
    assert result["ok"], result["errors"]
    assert result["route_cases"] >= 10
    assert result["graph_scenarios"] >= 12
    assert set(result["graph_coverage"]) == {
        "anki-maintenance", "consult", "generate-report", "grand-rounds",
        "inbox-workflow", "intraoperative-guide", "journal-club",
        "memory-maintenance", "refactor-manual-note", "shift-debrief",
        "study-material", "study-review",
    }


def test_emitted_prompts_do_not_include_expected_decisions() -> None:
    rows = emit_prompt_rows()
    assert rows
    assert all("expected" not in row for row in rows)
    assert all("rubric" not in row for row in rows)
    assert all("AGENTS.md" not in row["system"] for row in rows)


def test_prediction_grader_reports_field_level_mismatch(tmp_path: Path) -> None:
    suite = load_suite()
    rows = []
    for case in suite["route_cases"]:
        row = {"case_id": case["id"], **case["expected"]}
        rows.append(row)
    rows[0]["route"] = "consult"
    path = tmp_path / "predictions.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    result = grade_predictions(path)
    assert not result["ok"]
    assert result["field_accuracy"] < 1.0
    assert result["per_field"]["route"]["correct"] == len(rows) - 1
