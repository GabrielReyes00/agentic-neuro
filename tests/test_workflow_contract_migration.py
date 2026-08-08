from __future__ import annotations

import json
from pathlib import Path

from src.workflow_runtime import compile_registry


ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ROOT / ".agents/shared/commands"


def _registry() -> dict:
    return json.loads(
        (ROOT / ".agents/shared/workflow-registry.json").read_text(encoding="utf-8")
    )["workflows"]


def test_every_canonical_contract_is_loaded_at_entry() -> None:
    workflows = _registry()
    for name, workflow in workflows.items():
        if workflow.get("alias_for"):
            continue
        entry = workflow["execution"]["entry"]
        node = next(item for item in workflow["execution"]["nodes"] if item["id"] == entry)
        assert workflow["contract"] in node["load"], name


def test_every_workflow_specific_phase_module_is_typed() -> None:
    workflows = _registry()
    for name, workflow in workflows.items():
        if workflow.get("alias_for"):
            continue
        prefix = f"{name}-"
        phase_files = {
            path.name
            for path in COMMANDS.glob(f"{prefix}*.md")
        }
        loaded = {
            Path(reference).name
            for node in workflow["execution"]["nodes"]
            for reference in node["load"]
        }
        assert phase_files <= loaded, f"{name}: untyped phase modules {phase_files - loaded}"


def test_manifest_workflows_use_one_run_scoped_path_convention() -> None:
    workflows = _registry()
    for name, workflow in workflows.items():
        if workflow.get("alias_for"):
            continue
        if workflow["execution"]["run_state"] != "manifest":
            continue
        contract = (ROOT / workflow["contract"]).read_text(encoding="utf-8")
        assert "RUN_DIR" in contract, name
        assert "data/Sessions/<Title>" not in contract, name
        assert "data/Sessions/journal_club_" not in contract, name
        assert "data/Sessions/shift_debrief_" not in contract, name
        assert "data/Sessions/study_material_" not in contract, name


def test_learning_modules_are_jit_loaded_on_explicit_learning_branches() -> None:
    compiled = compile_registry()
    branches = {
        "consult": "review",
        "grand-rounds": "rehearsal",
        "journal-club": "mastery",
        "shift-debrief": "review",
        "study-material": "drill",
        "study-review": "turn",
    }
    for workflow_name, branch_name in branches.items():
        spec = compiled[workflow_name]
        branch = spec.node_map[branch_name]
        loaded = {Path(reference).name for reference in branch.load}
        assert "adaptive-teaching-doctrine.md" in loaded
        if workflow_name == "study-review":
            # The typed assessment transaction owns the one-per-turn Anki
            # disposition.  Card quality is loaded only when that disposition
            # is enqueue, so routine turns do not preload the full Anki policy.
            assert "anki-session-workflow.md" not in loaded
            assert "study-review-turn.md" in loaded
        else:
            assert "anki-session-workflow.md" in loaded
            assert "memory-operations.md" in loaded

        for node in spec.nodes:
            if node.id == branch_name:
                continue
            if workflow_name == "study-review" and node.id == "end":
                continue
            if node.kind in {"intake", "retrieve", "reason", "validate", "write"}:
                assert "anki-session-workflow.md" not in {
                    Path(reference).name for reference in node.load
                }


def test_external_and_persistent_maintenance_flows_have_approval_nodes() -> None:
    compiled = compile_registry()
    for name in ("anki-maintenance", "memory-maintenance", "inbox-workflow"):
        spec = compiled[name]
        assert spec.mode == "approval_gate"
        approval = [node for node in spec.nodes if node.kind == "approval"]
        assert len(approval) == 1
        assert {edge.when for edge in approval[0].edges} >= {"approved", "declined"}
