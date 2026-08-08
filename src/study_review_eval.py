#!/usr/bin/env python3
"""Provider-neutral transcript evaluation for the study-review tutor contract.

The grader consumes structured judgments about a candidate transcript.  A
human or independent model must inspect the prose and supply those judgments;
the deterministic grader never pretends keyword matching proves pedagogy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from runtime_paths import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover
    from .runtime_paths import REPO_ROOT


DEFAULT_SUITE = REPO_ROOT / "evals/study_review_cases.json"
VALID_STAGES = frozenset({"precommitment", "after_commitment"})
VALID_PHASES = frozenset({"orient", "deepen", "connect", "remediate", "consolidate"})
VALID_SOURCE_ACTIONS = frozenset({"none", "proportional", "verify_current_primary"})


class StudyReviewEvalError(ValueError):
    pass


def load_suite(path: Path = DEFAULT_SUITE) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("cases"), list):
        raise StudyReviewEvalError("study-review suite must use schema_version 1 with cases[]")
    return payload


def validate_suite(path: Path = DEFAULT_SUITE) -> dict[str, Any]:
    errors: list[str] = []
    ids: set[str] = set()
    coverage: set[str] = set()
    for case in load_suite(path)["cases"]:
        case_id = str(case.get("id") or "")
        if not case_id or case_id in ids:
            errors.append(f"duplicate or missing case id: {case_id!r}")
            continue
        ids.add(case_id)
        stage = str(case.get("stage") or "")
        coverage.add(stage)
        if stage not in VALID_STAGES:
            errors.append(f"{case_id}: invalid stage {stage!r}")
        if not str(case.get("prompt") or "").strip() or not str(case.get("context") or "").strip():
            errors.append(f"{case_id}: prompt and context are required")
        expected = case.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"{case_id}: expected must be an object")
            continue
        if expected.get("phase") not in VALID_PHASES:
            errors.append(f"{case_id}: invalid phase")
        if expected.get("source_action") not in VALID_SOURCE_ACTIONS:
            errors.append(f"{case_id}: invalid source_action")
        for key in ("question_count", "claims_count", "nearby_nodes_max", "max_hops"):
            if not isinstance(expected.get(key), int) or int(expected[key]) < 0:
                errors.append(f"{case_id}: {key} must be a nonnegative integer")
        for key in ("required_repair_elements", "forbidden_repair_elements"):
            if not isinstance(expected.get(key), list):
                errors.append(f"{case_id}: {key} must be a list")
    return {
        "ok": not errors,
        "cases": len(ids),
        "stage_coverage": sorted(coverage),
        "errors": errors,
    }


def emit_prompt_rows(path: Path = DEFAULT_SUITE) -> list[dict[str, Any]]:
    contract_paths = (
        ".agents/shared/commands/study-review-startup.md",
        ".agents/shared/commands/tutor-state.md",
        ".agents/shared/commands/study-review-turn.md",
        ".agents/shared/commands/adaptive-teaching-doctrine.md",
    )
    system = "\n\n".join((REPO_ROOT / relative).read_text(encoding="utf-8") for relative in contract_paths)
    return [
        {
            "case_id": case["id"],
            "system": system,
            "scenario": {key: case[key] for key in ("stage", "prompt", "context")},
            "instruction": (
                "Produce the learner-facing response. A separate blinded judge will label its "
                "question count, answer revelation, repair elements, phase, source action, "
                "persistence status, independently graded claim count, expansion count/hops, "
                "and PGY calibration using the repository rubric."
            ),
        }
        for case in load_suite(path)["cases"]
    ]


def _prediction_rows(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StudyReviewEvalError(f"judgment line {line_no}: {exc}") from exc
        case_id = str(row.get("case_id") or "")
        if not case_id or case_id in rows:
            raise StudyReviewEvalError(f"judgment line {line_no}: duplicate or missing case_id")
        rows[case_id] = row
    return rows


def _grade_case(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key in (
        "question_count", "reveals_answer", "phase", "source_action",
        "persistence_status", "claims_count", "pgy_calibration",
    ):
        if actual.get(key) != expected.get(key):
            mismatches.append(f"{key}: expected {expected.get(key)!r}, got {actual.get(key)!r}")
    for key in ("nearby_nodes_max", "max_hops"):
        observed_key = "nearby_nodes_introduced" if key == "nearby_nodes_max" else key
        observed = actual.get(observed_key)
        if not isinstance(observed, int) or observed > int(expected[key]):
            mismatches.append(f"{observed_key}: expected <= {expected[key]}, got {observed!r}")
    elements = set(actual.get("repair_elements") or [])
    missing = sorted(set(expected["required_repair_elements"]) - elements)
    forbidden = sorted(set(expected["forbidden_repair_elements"]) & elements)
    if missing:
        mismatches.append("missing repair elements: " + ", ".join(missing))
    if forbidden:
        mismatches.append("forbidden repair elements: " + ", ".join(forbidden))
    return mismatches


def grade_judgments(judgments_path: Path, suite_path: Path = DEFAULT_SUITE) -> dict[str, Any]:
    cases = {case["id"]: case for case in load_suite(suite_path)["cases"]}
    rows = _prediction_rows(judgments_path)
    results = []
    for case_id, case in cases.items():
        mismatches = _grade_case(case["expected"], rows.get(case_id, {}))
        results.append({"case_id": case_id, "passed": not mismatches, "mismatches": mismatches})
    unknown = sorted(set(rows) - set(cases))
    missing = sorted(set(cases) - set(rows))
    passed = sum(1 for row in results if row["passed"])
    return {
        "ok": not unknown and not missing and passed == len(cases),
        "cases": len(cases),
        "case_accuracy": round(passed / max(1, len(cases)), 3),
        "missing_judgments": missing,
        "unknown_judgments": unknown,
        "case_results": results,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    emit = sub.add_parser("emit")
    emit.add_argument("--output", type=Path, required=True)
    grade = sub.add_parser("grade")
    grade.add_argument("--judgments", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate":
        result = validate_suite(args.suite)
    elif args.command == "emit":
        rows = emit_prompt_rows(args.suite)
        _write_jsonl(args.output, rows)
        result = {"ok": True, "rows": len(rows), "output": str(args.output)}
    else:
        result = grade_judgments(args.judgments, args.suite)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
