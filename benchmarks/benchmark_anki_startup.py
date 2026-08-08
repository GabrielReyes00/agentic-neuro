#!/usr/bin/env python3
"""Compare live Anki startup behavior with a repository baseline revision."""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DEFAULT_BASELINE = "bcb67ec"


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _baseline_source(ref: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{ref}:src/anki_feedback.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _profile(module: ModuleType, *, repeat: int) -> dict[str, Any]:
    original_invoke = module.invoke
    totals: list[float] = []
    connector_totals: list[float] = []
    call_counts: list[int] = []
    payload_sizes: list[int] = []
    action_counts: Counter[str] = Counter()

    # Warm model/cache state once; the benchmark is for routine startup, not a
    # first-install embedding download.
    module.build_session_anki_profile("EVD management in ICU", profile="memory")
    for _ in range(max(1, repeat)):
        calls: list[tuple[str, float]] = []

        def measured_invoke(action: str, timeout: float = 3.0, **params: Any) -> Any:
            started = time.perf_counter()
            try:
                return original_invoke(action, timeout=timeout, **params)
            finally:
                calls.append((action, (time.perf_counter() - started) * 1000))

        module.invoke = measured_invoke
        started = time.perf_counter()
        try:
            payload = module.build_session_anki_profile(
                "EVD management in ICU", profile="memory"
            )
        finally:
            module.invoke = original_invoke
        totals.append((time.perf_counter() - started) * 1000)
        connector_totals.append(sum(duration for _, duration in calls))
        call_counts.append(len(calls))
        payload_sizes.append(len(json.dumps(payload, separators=(",", ":")).encode("utf-8")))
        action_counts.update(action for action, _ in calls)
    return {
        "repeat": len(totals),
        "connector_calls_median": statistics.median(call_counts),
        "connector_ms_median": round(statistics.median(connector_totals), 2),
        "total_ms_median": round(statistics.median(totals), 2),
        "payload_bytes_median": statistics.median(payload_sizes),
        "actions": dict(sorted(action_counts.items())),
    }


def run(*, baseline_ref: str, repeat: int) -> dict[str, Any]:
    current = _load_module(ROOT / "src/anki_feedback.py", "anki_feedback_current_benchmark")
    with tempfile.TemporaryDirectory() as tmp:
        baseline_path = Path(tmp) / "anki_feedback_baseline.py"
        baseline_path.write_text(_baseline_source(baseline_ref), encoding="utf-8")
        baseline = _load_module(baseline_path, "anki_feedback_baseline_benchmark")
        before = _profile(baseline, repeat=repeat)
        after = _profile(current, repeat=repeat)

    def reduction(field: str) -> float:
        old = float(before[field])
        new = float(after[field])
        return round(100 * (old - new) / old, 1) if old else 0.0

    return {
        "schema_version": 1,
        "baseline_ref": baseline_ref,
        "topic": "EVD management in ICU",
        "before": before,
        "after": after,
        "change": {
            "connector_calls_reduction_pct": reduction("connector_calls_median"),
            "connector_time_reduction_pct": reduction("connector_ms_median"),
            "total_time_reduction_pct": reduction("total_ms_median"),
            "payload_bytes_change_pct": round(
                100 * (float(after["payload_bytes_median"]) - float(before["payload_bytes_median"]))
                / max(1.0, float(before["payload_bytes_median"])),
                1,
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run(baseline_ref=args.baseline_ref, repeat=args.repeat)
        result["status"] = "ok"
    except Exception as exc:
        result = {"status": "skipped", "reason": str(exc)}
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
