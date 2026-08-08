#!/usr/bin/env python3
"""Validate agent-behavior cases and grade provider-neutral model decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from runtime_paths import REPO_ROOT
    from workflow_runtime import advance_state, initial_state, resolve_workflow
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from .runtime_paths import REPO_ROOT
    from .workflow_runtime import advance_state, initial_state, resolve_workflow


DEFAULT_SUITE = REPO_ROOT / "evals/agent_behavior_cases.json"
BUILTIN_ROUTES = frozenset({"clinical-answer", "repository-audit"})
RESPONSE_SHAPES = frozenset({
    "action_first", "artifact_workflow", "comprehensive_teaching", "concise_fact",
    "draft_then_approval", "findings_only", "one_question",
})
EVIDENCE_POLICIES = frozenset({"none", "proportional", "mini_rag", "current_primary"})
MUTATION_POLICIES = frozenset({"read_only", "requested_artifact", "approval_required"})
MEMORY_POLICIES = frozenset({"none", "learner_memory", "service_isolated"})
PREDICTION_FIELDS = (
    "route", "response_shape", "evidence_policy", "mutation_policy", "memory_policy"
)


class BehavioralEvalError(ValueError):
    """Raised when an eval suite or prediction file violates its contract."""


def load_suite(path: Path = DEFAULT_SUITE) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise BehavioralEvalError("behavior suite must use schema_version 1")
    return payload


def _route_exists(route: str) -> bool:
    if route in BUILTIN_ROUTES:
        return True
    try:
        resolve_workflow(route)
    except Exception:
        return False
    return True


def validate_suite(path: Path = DEFAULT_SUITE) -> dict[str, Any]:
    suite = load_suite(path)
    errors: list[str] = []
    ids: set[str] = set()
    route_coverage: set[str] = set()

    for case in suite.get("route_cases", []):
        case_id = str(case.get("id", ""))
        if not case_id or case_id in ids:
            errors.append(f"duplicate or missing case id: {case_id!r}")
            continue
        ids.add(case_id)
        if not str(case.get("prompt", "")).strip() or not str(case.get("rubric", "")).strip():
            errors.append(f"{case_id}: prompt and rubric are required")
        expected = case.get("expected") or {}
        route = str(expected.get("route", ""))
        route_coverage.add(route)
        if not _route_exists(route):
            errors.append(f"{case_id}: unknown route {route!r}")
        if expected.get("response_shape") not in RESPONSE_SHAPES:
            errors.append(f"{case_id}: invalid response_shape")
        if expected.get("evidence_policy") not in EVIDENCE_POLICIES:
            errors.append(f"{case_id}: invalid evidence_policy")
        if expected.get("mutation_policy") not in MUTATION_POLICIES:
            errors.append(f"{case_id}: invalid mutation_policy")
        if expected.get("memory_policy") not in MEMORY_POLICIES:
            errors.append(f"{case_id}: invalid memory_policy")

    graph_coverage: set[str] = set()
    graph_results: list[dict[str, Any]] = []
    for scenario in suite.get("graph_scenarios", []):
        scenario_id = str(scenario.get("id", ""))
        if not scenario_id or scenario_id in ids:
            errors.append(f"duplicate or missing case id: {scenario_id!r}")
            continue
        ids.add(scenario_id)
        workflow = str(scenario.get("workflow", ""))
        try:
            canonical, spec = resolve_workflow(workflow)
            graph_coverage.add(canonical)
            state = initial_state(spec)
            visited = [state["current_node"]]
            for outcome in scenario.get("outcomes", []):
                state = advance_state(spec, state, str(outcome))
                visited.append(state["current_node"])
            terminal = str(state["current_node"])
            if terminal != str(scenario.get("expected_terminal", "")):
                errors.append(
                    f"{scenario_id}: ended at {terminal!r}, expected "
                    f"{scenario.get('expected_terminal')!r}"
                )
            missing = sorted(set(scenario.get("required_nodes", [])) - set(visited))
            if missing:
                errors.append(f"{scenario_id}: required nodes not visited: {', '.join(missing)}")
            if spec.node_map[terminal].kind != "terminal":
                errors.append(f"{scenario_id}: final node {terminal!r} is not terminal")
            graph_results.append({
                "id": scenario_id,
                "workflow": canonical,
                "visited": visited,
                "terminal": terminal,
            })
        except Exception as exc:
            errors.append(f"{scenario_id}: {exc}")

    return {
        "ok": not errors,
        "route_cases": len(suite.get("route_cases", [])),
        "graph_scenarios": len(suite.get("graph_scenarios", [])),
        "route_coverage": sorted(route_coverage),
        "graph_coverage": sorted(graph_coverage),
        "graph_results": graph_results,
        "errors": errors,
    }


def emit_prompt_rows(path: Path = DEFAULT_SUITE) -> list[dict[str, Any]]:
    root_policy = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    instruction = (
        "Return one JSON object with keys case_id, route, response_shape, "
        "evidence_policy, mutation_policy, and memory_policy. Choose values from: "
        f"response_shape={sorted(RESPONSE_SHAPES)}, evidence_policy={sorted(EVIDENCE_POLICIES)}, "
        f"mutation_policy={sorted(MUTATION_POLICIES)}, memory_policy={sorted(MEMORY_POLICIES)}."
    )
    return [
        {
            "case_id": case["id"],
            "system": root_policy,
            "instruction": instruction,
            "user": case["prompt"],
        }
        for case in load_suite(path).get("route_cases", [])
    ]


def _load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BehavioralEvalError(f"prediction line {line_no}: {exc}") from exc
        case_id = str(row.get("case_id", ""))
        if not case_id or case_id in rows:
            raise BehavioralEvalError(f"prediction line {line_no}: duplicate or missing case_id")
        rows[case_id] = row
    return rows


def grade_predictions(
    predictions_path: Path,
    *,
    suite_path: Path = DEFAULT_SUITE,
) -> dict[str, Any]:
    cases = {case["id"]: case for case in load_suite(suite_path).get("route_cases", [])}
    predictions = _load_predictions(predictions_path)
    unknown = sorted(set(predictions) - set(cases))
    missing = sorted(set(cases) - set(predictions))
    per_field = {field: {"correct": 0, "total": len(cases)} for field in PREDICTION_FIELDS}
    case_results: list[dict[str, Any]] = []
    for case_id, case in cases.items():
        expected = case["expected"]
        prediction = predictions.get(case_id, {})
        mismatches = []
        for field in PREDICTION_FIELDS:
            if prediction.get(field) == expected[field]:
                per_field[field]["correct"] += 1
            else:
                mismatches.append({
                    "field": field,
                    "expected": expected[field],
                    "actual": prediction.get(field),
                })
        case_results.append({"case_id": case_id, "passed": not mismatches, "mismatches": mismatches})
    total_fields = len(cases) * len(PREDICTION_FIELDS)
    correct_fields = sum(value["correct"] for value in per_field.values())
    for value in per_field.values():
        value["accuracy"] = round(value["correct"] / max(1, value["total"]), 3)
    return {
        "ok": not missing and not unknown and correct_fields == total_fields,
        "cases": len(cases),
        "complete_case_accuracy": round(
            sum(1 for result in case_results if result["passed"]) / max(1, len(cases)), 3
        ),
        "field_accuracy": round(correct_fields / max(1, total_fields), 3),
        "per_field": per_field,
        "missing_predictions": missing,
        "unknown_predictions": unknown,
        "case_results": case_results,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    emit = sub.add_parser("emit")
    emit.add_argument("--output", type=Path, required=True)
    grade = sub.add_parser("grade")
    grade.add_argument("--predictions", type=Path, required=True)
    grade.add_argument("--minimum-field-accuracy", type=float, default=1.0)
    args = parser.parse_args()

    if args.command == "validate":
        result = validate_suite(args.suite)
    elif args.command == "emit":
        rows = emit_prompt_rows(args.suite)
        _write_jsonl(args.output, rows)
        result = {"ok": True, "rows": len(rows), "output": str(args.output)}
    else:
        result = grade_predictions(args.predictions, suite_path=args.suite)
        result["ok"] = bool(
            not result["missing_predictions"]
            and not result["unknown_predictions"]
            and result["field_accuracy"] >= args.minimum_field_accuracy
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
