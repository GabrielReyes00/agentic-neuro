#!/usr/bin/env python3
"""Ablate flat instructions against the typed, projected workflow harness."""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import behavioral_eval  # noqa: E402
import code_architecture_audit  # noqa: E402
import instruction_audit  # noqa: E402
import workflow_runtime  # noqa: E402


MINIMUM_STARTUP_REDUCTION_PCT = 40.0
MAXIMUM_ENTRY_TOKENS = 10_000


def _mutations() -> list[tuple[str, str, Callable[[dict[str, Any]], None]]]:
    def dangling(raw: dict[str, Any]) -> None:
        raw["execution"]["nodes"][0]["edges"][0]["to"] = "missing-node"

    def duplicate_outcome(raw: dict[str, Any]) -> None:
        raw["execution"]["nodes"][0]["edges"].append(
            copy.deepcopy(raw["execution"]["nodes"][0]["edges"][0])
        )

    def undeclared_cycle(raw: dict[str, Any]) -> None:
        answer = next(node for node in raw["execution"]["nodes"] if node["id"] == "answer")
        answer["edges"].append({"to": "scope", "when": "restart"})

    def unreachable(raw: dict[str, Any]) -> None:
        raw["execution"]["nodes"].append({
            "id": "orphan", "kind": "terminal", "context": "conversation",
            "load": [], "edges": [],
        })

    def invalid_isolation(raw: dict[str, Any]) -> None:
        raw["execution"]["nodes"][0]["context"] = "isolated"

    def missing_load(raw: dict[str, Any]) -> None:
        raw["execution"]["nodes"][0]["load"] = ["missing/contract.md"]

    return [
        ("dangling_edge", "edge target", dangling),
        ("ambiguous_outcome", "outcomes must be unique", duplicate_outcome),
        ("undeclared_cycle", "must declare loop=true", undeclared_cycle),
        ("unreachable_node", "unreachable nodes", unreachable),
        ("invalid_isolated_context", "isolated context requires manifest", invalid_isolation),
        ("missing_load_reference", "missing load reference", missing_load),
    ]


def _validation_ablation() -> dict[str, Any]:
    registry = workflow_runtime.load_registry()
    baseline = registry["workflows"]["consult"]
    rows = []
    for name, expected_error, mutate in _mutations():
        raw = copy.deepcopy(baseline)
        mutate(raw)
        # The ablated comparator represents an untyped JSON/config-only harness:
        # every mutation remains syntactically valid and therefore "passes".
        json.loads(json.dumps(raw))
        detected = False
        actual_error = ""
        try:
            workflow_runtime.compile_workflow("consult", raw)
        except workflow_runtime.WorkflowSpecError as exc:
            actual_error = str(exc)
            detected = expected_error in actual_error
        rows.append({
            "mutation": name,
            "json_only_accepts": True,
            "typed_validator_detected": detected,
            "error": actual_error,
        })
    detected = sum(int(row["typed_validator_detected"]) for row in rows)
    return {
        "mutations": len(rows),
        "json_only_detection_rate": 0.0,
        "typed_detection_rate": round(detected / max(1, len(rows)), 3),
        "cases": rows,
    }


def _compile_latency(repeat: int) -> dict[str, Any]:
    durations = []
    for _ in range(max(1, repeat)):
        started = time.perf_counter()
        workflow_runtime.compile_registry()
        durations.append((time.perf_counter() - started) * 1000)
    ordered = sorted(durations)
    p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
    return {
        "repeat": len(durations),
        "median_ms": round(statistics.median(durations), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "min_ms": round(min(durations), 3),
        "max_ms": round(max(durations), 3),
    }


def run(repeat: int = 100) -> dict[str, Any]:
    instructions = instruction_audit.measure()
    startup = instructions["runtime_startup"]
    selected = [item["selected_tokens"] for item in startup["workflows"].values()]
    validation = _validation_ablation()
    behavior = behavioral_eval.validate_suite()
    architecture = code_architecture_audit.audit()
    checks = {
        "minimum_startup_reduction": (
            float(startup["minimum_reduction_pct"]) >= MINIMUM_STARTUP_REDUCTION_PCT
        ),
        "entry_context_budget": max(selected, default=0) <= MAXIMUM_ENTRY_TOKENS,
        "typed_mutation_detection": validation["typed_detection_rate"] == 1.0,
        "behavior_suite": bool(behavior["ok"]),
        "code_architecture": bool(architecture["ok"]),
    }
    return {
        "schema_version": 1,
        "instruction_ablation": {
            "comparator": "flat registry plus workflow entry contracts",
            "treatment": "typed runtime projection plus only entry-node loads",
            "workflow_count": len(startup["workflows"]),
            "median_reduction_pct": startup["median_reduction_pct"],
            "minimum_reduction_pct": startup["minimum_reduction_pct"],
            "maximum_selected_tokens": max(selected, default=0),
            "workflows": startup["workflows"],
        },
        "validation_ablation": validation,
        "compile_latency": _compile_latency(repeat),
        "behavioral_coverage": {
            "route_cases": behavior["route_cases"],
            "graph_scenarios": behavior["graph_scenarios"],
            "canonical_graphs": len(behavior["graph_coverage"]),
        },
        "architecture": architecture,
        "checks": checks,
        "ok": all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=100)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = run(args.repeat)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if (not args.check or result["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
