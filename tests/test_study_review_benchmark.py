from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark_study_review


def test_study_review_benchmark_uses_safe_copy_and_enforces_caps(tmp_path: Path) -> None:
    result = benchmark_study_review.run(
        database=tmp_path / "not-yet-provisioned.db",
        topic="subarachnoid hemorrhage",
        repeat=1,
    )
    assert result["ok"] is True
    assert result["database_was_copied"] is False
    assert result["startup_state"]["active_nodes"] <= 8
    assert result["startup_state"]["maximum_hops"] == 1
