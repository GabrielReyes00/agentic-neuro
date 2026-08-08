from __future__ import annotations

from benchmarks.benchmark_agent_harness import run


def test_harness_ablation_meets_correctness_and_context_gates() -> None:
    result = run(repeat=2)
    assert result["ok"], result["checks"]
    assert result["validation_ablation"]["typed_detection_rate"] == 1.0
    assert result["validation_ablation"]["json_only_detection_rate"] == 0.0
    assert result["instruction_ablation"]["minimum_reduction_pct"] >= 40.0
