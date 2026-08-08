from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from study_review_eval import emit_prompt_rows, grade_judgments, load_suite, validate_suite


def test_study_review_eval_suite_is_valid_and_covers_both_boundaries() -> None:
    report = validate_suite()
    assert report["ok"] is True
    assert report["cases"] >= 7
    assert report["stage_coverage"] == ["after_commitment", "precommitment"]


def test_emitted_prompts_load_only_study_review_teaching_authority() -> None:
    rows = emit_prompt_rows()
    assert len(rows) == len(load_suite()["cases"])
    assert "tutor_state.phase_controller" in rows[0]["system"]
    assert "bounded repair bundle" in rows[0]["system"]
    assert "generate-report" not in rows[0]["system"]


def test_exact_structured_judgments_pass_and_boundary_violation_fails(tmp_path: Path) -> None:
    suite = load_suite()
    judgments = []
    for case in suite["cases"]:
        expected = case["expected"]
        judgments.append({
            "case_id": case["id"],
            "question_count": expected["question_count"],
            "reveals_answer": expected["reveals_answer"],
            "phase": expected["phase"],
            "source_action": expected["source_action"],
            "persistence_status": expected["persistence_status"],
            "claims_count": expected["claims_count"],
            "pgy_calibration": expected["pgy_calibration"],
            "nearby_nodes_introduced": expected["nearby_nodes_max"],
            "max_hops": expected["max_hops"],
            "repair_elements": expected["required_repair_elements"],
        })
    path = tmp_path / "judgments.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in judgments))
    assert grade_judgments(path)["ok"] is True

    judgments[-1]["nearby_nodes_introduced"] = 3
    judgments[-1]["max_hops"] = 2
    judgments[-1]["repair_elements"].append("two_hop_expansion")
    path.write_text("".join(json.dumps(row) + "\n" for row in judgments))
    failed = grade_judgments(path)
    assert failed["ok"] is False
    assert failed["case_results"][-1]["passed"] is False
