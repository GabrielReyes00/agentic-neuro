#!/usr/bin/env python3
"""Static audit for Gemini CLI harness reliability.

Focuses on deterministic routing, internal-command exposure, and hard gates for
critical workflows (Anki validation + per-turn logging hooks).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def run_checks() -> List[Check]:
    checks: List[Check] = []

    gemini_md = _read(ROOT / "GEMINI.md")
    anki_md = _read(ROOT / ".gemini" / "commands" / "anki-sync.md")
    anki_toml = _read(ROOT / ".gemini" / "commands" / "anki-sync.toml")
    rag_toml = _read(ROOT / ".gemini" / "commands" / "rag-workflow.toml")
    study_toml = _read(ROOT / ".gemini" / "commands" / "study-session.toml")
    study_material_toml = _read(ROOT / ".gemini" / "commands" / "study-material.toml")
    generate_report_md = _read(ROOT / ".gemini" / "commands" / "generate-report.md")
    generate_report_toml = _read(ROOT / ".gemini" / "commands" / "generate-report.toml")
    anki_cli = _read(ROOT / "src" / "anki_sync_cli.py")

    checks.append(Check(
        name="routing_gate_present",
        ok="Mandatory Turn Gateway" in gemini_md and "src/gemini_query_gate.py" in gemini_md,
        detail="GEMINI.md should require deterministic non-slash routing via gemini_query_gate.py",
    ))

    checks.append(Check(
        name="internal_rag_transform_not_exposed",
        ok=not (ROOT / ".gemini" / "commands" / "rag-transform.toml").exists(),
        detail=".gemini/commands/rag-transform.toml should not exist (internal sub-task only)",
    ))

    checks.append(Check(
        name="anki_cli_validation_command",
        ok="def validate_final_cards" in anki_cli and '"validate_final_cards": validate_final_cards' in anki_cli,
        detail="anki_sync_cli.py should expose validate_final_cards",
    ))

    checks.append(Check(
        name="anki_cli_dispatch_uses_validation_gate",
        ok="_validate_final_cards_payload()" in anki_cli and "Error in validate_final_cards" in anki_cli,
        detail="dispatch path should call strict final_cards validation",
    ))

    checks.append(Check(
        name="anki_command_mentions_validation_gate",
        ok="Step 6.5" in anki_md and "validate_final_cards" in anki_md and "validation_report" in anki_md,
        detail="anki-sync.md should include explicit step 6.5 CLI gate and validation_report schema",
    ))

    checks.append(Check(
        name="anki_toml_mentions_step_6_5",
        ok="6.5" in anki_toml and "validate_final_cards" in anki_toml,
        detail="anki-sync.toml should include step 6.5 gate",
    ))

    checks.append(Check(
        name="rag_workflow_uses_log_turn",
        ok="./src/log_turn.sh" in rag_toml,
        detail="rag-workflow.toml should require log_turn wrapper",
    ))

    checks.append(Check(
        name="study_session_uses_log_turn",
        ok="./src/log_turn.sh" in study_toml,
        detail="study-session.toml should require log_turn wrapper",
    ))

    checks.append(Check(
        name="study_material_uses_log_turn",
        ok="./src/log_turn.sh" in study_material_toml,
        detail="study-material.toml should require log_turn wrapper",
    ))

    checks.append(Check(
        name="log_turn_script_exists",
        ok=(ROOT / "src" / "log_turn.sh").exists(),
        detail="src/log_turn.sh should exist",
    ))

    checks.append(Check(
        name="query_gate_script_exists",
        ok=(ROOT / "src" / "gemini_query_gate.py").exists(),
        detail="src/gemini_query_gate.py should exist",
    ))

    checks.append(Check(
        name="universal_post_session_hook_script_exists",
        ok=(ROOT / "src" / "universal_post_session_hook.py").exists(),
        detail="src/universal_post_session_hook.py should exist for deterministic post-session finalization",
    ))

    checks.append(Check(
        name="gemini_md_uses_universal_hook_script",
        ok="src/universal_post_session_hook.py" in gemini_md and "post_session_hook_report.json" in gemini_md,
        detail="GEMINI.md should route universal post-session work through universal_post_session_hook.py with report output",
    ))

    checks.append(Check(
        name="generate_report_hard_verification_present",
        ok="src/universal_post_session_hook.py" in generate_report_md
        and "post_session_hook_report.json" in generate_report_md
        and "Hard verification" in generate_report_md,
        detail="generate-report.md should invoke the hook runner and define hard verification behavior",
    ))

    checks.append(Check(
        name="generate_report_toml_mentions_hard_verification",
        ok="post_session_hook_report.json" in generate_report_toml and "HARD VERIFICATION REQUIREMENT" in generate_report_toml,
        detail="generate-report.toml should require explicit post-session verification reporting",
    ))

    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Gemini harness files")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    checks = run_checks()
    failed = [c for c in checks if not c.ok]

    if args.json:
        print(json.dumps({
            "ok": not failed,
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "checks": [asdict(c) for c in checks],
        }, indent=2))
    else:
        print("Gemini Harness Audit")
        print("====================")
        for c in checks:
            status = "PASS" if c.ok else "FAIL"
            print(f"[{status}] {c.name}: {c.detail}")
        print("--------------------")
        print(f"Result: {len(checks) - len(failed)}/{len(checks)} checks passed")

    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
