from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.run_artifacts import load_manifest
from src.workflow_runtime import (
    WorkflowSpecError,
    advance_state,
    advance_workflow_run,
    compile_registry,
    compile_workflow,
    initial_state,
    resolve_workflow,
    start_workflow,
)


def test_registry_compiles_every_canonical_workflow() -> None:
    compiled = compile_registry()
    assert len(compiled) == 12
    assert set(compiled) == {
        "anki-maintenance",
        "consult",
        "generate-report",
        "grand-rounds",
        "inbox-workflow",
        "intraoperative-guide",
        "journal-club",
        "memory-maintenance",
        "refactor-manual-note",
        "shift-debrief",
        "study-material",
        "study-review",
    }
    assert compiled["consult"].run_state == "none"
    assert compiled["study-review"].run_state == "learner_memory"
    assert compiled["generate-report"].run_state == "manifest"
    assert compiled["anki-maintenance"].mode == "approval_gate"
    assert compiled["memory-maintenance"].mode == "approval_gate"


def test_alias_resolves_to_one_canonical_graph() -> None:
    canonical, alias_spec = resolve_workflow("service-log")
    _, direct_spec = resolve_workflow("shift-debrief")
    assert canonical == "shift-debrief"
    assert alias_spec == direct_spec


def test_graph_rejects_undeclared_cycle() -> None:
    raw = {
        "execution": {
            "mode": "conversation_loop",
            "run_state": "none",
            "entry": "a",
            "nodes": [
                {
                    "id": "a",
                    "kind": "loop",
                    "context": "conversation",
                    "load": [],
                    "edges": [{"to": "a", "when": "again"}],
                },
                {
                    "id": "done",
                    "kind": "terminal",
                    "context": "conversation",
                    "load": [],
                    "edges": [],
                },
            ],
        }
    }
    with pytest.raises(WorkflowSpecError, match="unreachable nodes"):
        compile_workflow("bad", raw)
    raw["execution"]["nodes"][0]["edges"].append({"to": "done", "when": "end"})
    with pytest.raises(WorkflowSpecError, match="loop=true"):
        compile_workflow("bad", raw)


def test_transition_requires_exact_declared_outcome() -> None:
    _, spec = resolve_workflow("consult")
    state = initial_state(spec)
    state = advance_state(spec, state, "answer_ready")
    assert state["current_node"] == "answer"
    with pytest.raises(WorkflowSpecError, match="matched 0 edges"):
        advance_state(spec, state, "invented")


def test_graph_rejects_ambiguous_duplicate_outcome() -> None:
    raw = {
        "execution": {
            "mode": "direct",
            "run_state": "none",
            "entry": "start",
            "nodes": [
                {
                    "id": "start",
                    "kind": "intake",
                    "context": "conversation",
                    "load": [],
                    "edges": [
                        {"to": "left", "when": "ready"},
                        {"to": "right", "when": "ready"},
                    ],
                },
                {
                    "id": "left", "kind": "terminal", "context": "conversation",
                    "load": [], "edges": [],
                },
                {
                    "id": "right", "kind": "terminal", "context": "conversation",
                    "load": [], "edges": [],
                },
            ],
        }
    }
    with pytest.raises(WorkflowSpecError, match="outcomes must be unique"):
        compile_workflow("ambiguous", raw)


def test_manifest_workflow_persists_graph_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        started = start_workflow(
            "generate-report",
            "topic-a",
            title="Topic A",
            root=root,
        )
        assert started["persistent"] is True
        run_dir = Path(started["run_dir"])
        manifest = load_manifest(run_dir, root=root)
        assert manifest["status"] == "running"
        assert manifest["workflow_state"]["current_node"] == "plan"
        updated = advance_workflow_run(run_dir, "planned", root=root)
        assert updated["current_node"] == "research"
        assert load_manifest(run_dir, root=root)["workflow_state"] == updated


def test_terminal_transition_completes_manifest_run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = Path(
            start_workflow("shift-debrief", "terminal", root=root)["run_dir"]
        )
        for outcome in ("deidentified", "drafted", "passed", "installed"):
            advance_workflow_run(run_dir, outcome, root=root)
        manifest = load_manifest(run_dir, root=root)
        assert manifest["status"] == "completed"
        assert manifest["workflow_state"]["current_node"] == "done"


def test_direct_workflow_has_no_filesystem_side_effect() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        started = start_workflow("consult", "question", root=root)
        assert started["persistent"] is False
        assert list(root.iterdir()) == []


def test_isolated_context_is_explicit_and_rare() -> None:
    compiled = compile_registry()
    isolated = [
        (workflow.name, node.id)
        for workflow in compiled.values()
        for node in workflow.nodes
        if node.context == "isolated"
    ]
    assert isolated == [
        ("intraoperative-guide", "map-review"),
        ("intraoperative-guide", "independent-review"),
    ]


def test_optional_learning_branches_are_explicit() -> None:
    compiled = compile_registry()
    expected = {
        "consult": "review",
        "grand-rounds": "rehearsal",
        "journal-club": "mastery",
        "shift-debrief": "review",
    }
    for workflow, node in expected.items():
        assert node in compiled[workflow].node_map
        assert compiled[workflow].node_map[node].kind == "loop"


def test_intraoperative_map_is_built_before_independent_map_review() -> None:
    spec = compile_registry()["intraoperative-guide"]
    assert spec.node_map["research"].edges[0].to == "knowledge-map"
    assert spec.node_map["knowledge-map"].edges[0].to == "map-review"
    assert spec.node_map["map-review"].context == "isolated"
    assert spec.node_map["independent-review"].context == "isolated"
