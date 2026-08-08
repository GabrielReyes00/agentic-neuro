from __future__ import annotations

from src import code_architecture_audit


def test_code_architecture_has_no_guarded_regressions() -> None:
    result = code_architecture_audit.audit()
    assert result["ok"], result["errors"]
    assert result["module_count"] >= 40

