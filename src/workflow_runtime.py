#!/usr/bin/env python3
"""Typed, framework-free workflow graph compiler and state-transition kernel."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from run_artifacts import (
        load_manifest,
        start_run,
        transition_run,
        update_workflow_state,
    )
    from runtime_paths import REPO_ROOT, RUNTIME_DIR
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from .run_artifacts import (
        load_manifest,
        start_run,
        transition_run,
        update_workflow_state,
    )
    from .runtime_paths import REPO_ROOT, RUNTIME_DIR


REGISTRY_PATH = REPO_ROOT / ".agents/shared/workflow-registry.json"
SUPPORTED_REGISTRY_SCHEMA = 2
VALID_MODES = frozenset({"direct", "artifact_graph", "conversation_loop", "approval_gate"})
VALID_RUN_STATES = frozenset({"none", "manifest", "learner_memory"})
VALID_NODE_KINDS = frozenset(
    {"intake", "reason", "retrieve", "write", "validate", "approval", "loop", "terminal"}
)
VALID_CONTEXTS = frozenset({"conversation", "run_scoped", "isolated"})


class WorkflowSpecError(ValueError):
    """Raised when the registry cannot compile to an unambiguous workflow."""


@dataclass(frozen=True)
class EdgeSpec:
    to: str
    when: str
    loop: bool = False
    terminal_status: str = ""


@dataclass(frozen=True)
class NodeSpec:
    id: str
    kind: str
    context: str
    load: tuple[str, ...]
    edges: tuple[EdgeSpec, ...]


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    mode: str
    run_state: str
    entry: str
    nodes: tuple[NodeSpec, ...]

    @property
    def node_map(self) -> dict[str, NodeSpec]:
        return {node.id: node for node in self.nodes}


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if int(payload.get("schema_version", 0)) != SUPPORTED_REGISTRY_SCHEMA:
        raise WorkflowSpecError(
            f"workflow registry schema {payload.get('schema_version')} is unsupported; "
            f"expected {SUPPORTED_REGISTRY_SCHEMA}"
        )
    return payload


def _compile_node(workflow: str, raw: dict[str, Any]) -> NodeSpec:
    node_id = str(raw.get("id", ""))
    kind = str(raw.get("kind", ""))
    context = str(raw.get("context", ""))
    if not node_id:
        raise WorkflowSpecError(f"{workflow}: node missing id")
    if kind not in VALID_NODE_KINDS:
        raise WorkflowSpecError(f"{workflow}/{node_id}: invalid kind {kind!r}")
    if context not in VALID_CONTEXTS:
        raise WorkflowSpecError(f"{workflow}/{node_id}: invalid context {context!r}")
    loads = tuple(str(item) for item in raw.get("load", []))
    for reference in loads:
        if not (REPO_ROOT / reference).is_file():
            raise WorkflowSpecError(f"{workflow}/{node_id}: missing load reference {reference}")
    edges = tuple(
        EdgeSpec(
            to=str(edge.get("to", "")),
            when=str(edge.get("when", "")),
            loop=bool(edge.get("loop", False)),
            terminal_status=str(edge.get("terminal_status", "")),
        )
        for edge in raw.get("edges", [])
    )
    if any(not edge.to or not edge.when for edge in edges):
        raise WorkflowSpecError(f"{workflow}/{node_id}: every edge needs to and when")
    if kind == "terminal" and edges:
        raise WorkflowSpecError(f"{workflow}/{node_id}: terminal node cannot have edges")
    return NodeSpec(node_id, kind, context, loads, edges)


def compile_workflow(name: str, raw: dict[str, Any]) -> WorkflowSpec:
    execution = raw.get("execution")
    if not isinstance(execution, dict):
        raise WorkflowSpecError(f"{name}: canonical workflow missing execution graph")
    mode = str(execution.get("mode", ""))
    run_state = str(execution.get("run_state", ""))
    entry = str(execution.get("entry", ""))
    if mode not in VALID_MODES:
        raise WorkflowSpecError(f"{name}: invalid execution mode {mode!r}")
    if run_state not in VALID_RUN_STATES:
        raise WorkflowSpecError(f"{name}: invalid run state {run_state!r}")
    nodes = tuple(_compile_node(name, item) for item in execution.get("nodes", []))
    node_map = {node.id: node for node in nodes}
    if len(node_map) != len(nodes):
        raise WorkflowSpecError(f"{name}: duplicate node id")
    if entry not in node_map:
        raise WorkflowSpecError(f"{name}: entry node {entry!r} is missing")
    for node in nodes:
        if node.context == "isolated" and run_state != "manifest":
            raise WorkflowSpecError(
                f"{name}/{node.id}: isolated context requires manifest run state"
            )
        if node.context == "isolated" and node.kind != "validate":
            raise WorkflowSpecError(
                f"{name}/{node.id}: isolated context is reserved for validation"
            )
    for node in nodes:
        outcomes = [edge.when for edge in node.edges]
        if len(outcomes) != len(set(outcomes)):
            raise WorkflowSpecError(
                f"{name}/{node.id}: edge outcomes must be unique"
            )
        for edge in node.edges:
            if edge.to not in node_map:
                raise WorkflowSpecError(f"{name}/{node.id}: edge target {edge.to!r} is missing")
            target_is_terminal = node_map[edge.to].kind == "terminal"
            if edge.terminal_status and edge.terminal_status not in {
                "completed",
                "abandoned",
                "failed",
            }:
                raise WorkflowSpecError(
                    f"{name}/{node.id}: invalid terminal status {edge.terminal_status!r}"
                )
            if edge.terminal_status and not target_is_terminal:
                raise WorkflowSpecError(
                    f"{name}/{node.id}: terminal_status requires a terminal target"
                )

    reachable: set[str] = set()
    frontier = [entry]
    while frontier:
        current = frontier.pop()
        if current in reachable:
            continue
        reachable.add(current)
        frontier.extend(edge.to for edge in node_map[current].edges)
    unreachable = sorted(set(node_map) - reachable)
    if unreachable:
        raise WorkflowSpecError(f"{name}: unreachable nodes: {', '.join(unreachable)}")
    if not any(node.kind == "terminal" for node in nodes):
        raise WorkflowSpecError(f"{name}: graph has no terminal node")

    # Back-edges are valid only when labeled as intentional loops. This catches
    # accidental graph cycles without forbidding Socratic or repair iteration.
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        visiting.append(node_id)
        for edge in node_map[node_id].edges:
            if edge.to in visiting and not edge.loop:
                raise WorkflowSpecError(
                    f"{name}: cycle {node_id} -> {edge.to} must declare loop=true"
                )
            if edge.to not in visited and edge.to not in visiting:
                visit(edge.to)
        visiting.pop()
        visited.add(node_id)

    visit(entry)
    return WorkflowSpec(name=name, mode=mode, run_state=run_state, entry=entry, nodes=nodes)


def compile_registry(path: Path = REGISTRY_PATH) -> dict[str, WorkflowSpec]:
    registry = load_registry(path)
    workflows = registry.get("workflows", {})
    compiled: dict[str, WorkflowSpec] = {}
    for name, raw in workflows.items():
        if raw.get("alias_for"):
            continue
        compiled[name] = compile_workflow(name, raw)
    for name, raw in workflows.items():
        alias = str(raw.get("alias_for", ""))
        if alias and alias not in compiled:
            raise WorkflowSpecError(f"{name}: alias target {alias!r} is not canonical")
    return compiled


def resolve_workflow(name: str, path: Path = REGISTRY_PATH) -> tuple[str, WorkflowSpec]:
    registry = load_registry(path)
    workflows = registry["workflows"]
    if name not in workflows:
        raise WorkflowSpecError(f"unknown workflow: {name}")
    canonical = str(workflows[name].get("alias_for") or name)
    return canonical, compile_workflow(canonical, workflows[canonical])


def runtime_projection(
    name: str,
    path: Path = REGISTRY_PATH,
    *,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Small generated execution surface for one invoked workflow."""
    registry = registry if registry is not None else load_registry(path)
    workflows = registry["workflows"]
    if name not in workflows:
        raise WorkflowSpecError(f"unknown workflow: {name}")
    invoked = workflows[name]
    canonical_name = str(invoked.get("alias_for") or name)
    canonical = workflows[canonical_name]
    projection = {
        "schema_version": 1,
        "generated_from": ".agents/shared/workflow-registry.json",
        "runtime_contract": ".agents/shared/commands/workflow-runtime.md",
        "invoked_as": name,
        "canonical_workflow": canonical_name,
        "contract": str(invoked.get("contract") or canonical["contract"]),
        "vault_destination": invoked.get("vault_destination", canonical.get("vault_destination")),
        "binary_destination": invoked.get("binary_destination", canonical.get("binary_destination")),
        "reviewable": bool(invoked.get("reviewable", canonical.get("reviewable", False))),
        "generation_recall": invoked.get("generation_recall", canonical.get("generation_recall")),
        "write_policy": invoked.get("write_policy", canonical.get("write_policy")),
        "anki_policy": invoked.get("anki_policy", canonical.get("anki_policy")),
        "execution": canonical["execution"],
    }
    return projection


def initial_state(spec: WorkflowSpec) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "workflow": spec.name,
        "mode": spec.mode,
        "run_state": spec.run_state,
        "current_node": spec.entry,
        "completed_nodes": [],
        "transition_count": 0,
    }


def advance_state(spec: WorkflowSpec, state: dict[str, Any], outcome: str) -> dict[str, Any]:
    current = str(state.get("current_node", ""))
    node = spec.node_map.get(current)
    if node is None:
        raise WorkflowSpecError(f"{spec.name}: state points to unknown node {current!r}")
    matches = [edge for edge in node.edges if edge.when == outcome]
    if len(matches) != 1:
        raise WorkflowSpecError(
            f"{spec.name}/{current}: outcome {outcome!r} matched {len(matches)} edges"
        )
    updated = dict(state)
    completed = list(updated.get("completed_nodes", []))
    if current not in completed:
        completed.append(current)
    updated["completed_nodes"] = completed
    updated["current_node"] = matches[0].to
    updated["transition_count"] = int(updated.get("transition_count", 0)) + 1
    updated["last_outcome"] = outcome
    return updated


def start_workflow(
    name: str,
    run_id: str,
    *,
    title: str = "",
    root: Path = RUNTIME_DIR,
) -> dict[str, Any]:
    canonical, spec = resolve_workflow(name)
    state = initial_state(spec)
    state["invoked_as"] = name
    if spec.run_state != "manifest":
        return {"canonical_workflow": canonical, "persistent": False, "state": state}
    started = start_run(
        canonical,
        run_id,
        title=title,
        workflow_state=state,
        root=root,
    )
    started["manifest"] = transition_run(
        Path(started["run_dir"]),
        "running",
        root=root,
    )
    return {"canonical_workflow": canonical, "persistent": True, **started}


def advance_workflow_run(
    run_dir: Path,
    outcome: str,
    *,
    root: Path = RUNTIME_DIR,
) -> dict[str, Any]:
    manifest = load_manifest(run_dir, root=root)
    state = dict(manifest.get("workflow_state") or {})
    canonical, spec = resolve_workflow(str(state.get("workflow", "")))
    del canonical
    updated = advance_state(spec, state, outcome)
    update_workflow_state(run_dir, updated, root=root)
    destination = spec.node_map[updated["current_node"]]
    if destination.kind == "terminal":
        source = spec.node_map[str(state["current_node"])]
        edge = next(edge for edge in source.edges if edge.when == outcome)
        transition_run(
            run_dir,
            edge.terminal_status or "completed",
            root=root,
        )
    return updated


def runtime_plan(name: str) -> dict[str, Any]:
    canonical, spec = resolve_workflow(name)
    return {
        "canonical_workflow": canonical,
        "spec": {
            **asdict(spec),
            "nodes": [asdict(node) for node in spec.nodes],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--json", action="store_true")
    plan = subparsers.add_parser("plan")
    plan.add_argument("workflow")
    start = subparsers.add_parser("start")
    start.add_argument("workflow")
    start.add_argument("--run-id", required=True)
    start.add_argument("--title", default="")
    advance = subparsers.add_parser("advance")
    advance.add_argument("--run-dir", type=Path, required=True)
    advance.add_argument("--outcome", required=True)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            compiled = compile_registry()
            result = {"ok": True, "workflow_count": len(compiled), "workflows": sorted(compiled)}
        elif args.command == "plan":
            result = runtime_plan(args.workflow)
        elif args.command == "start":
            result = start_workflow(args.workflow, args.run_id, title=args.title)
        else:
            result = advance_workflow_run(args.run_dir, args.outcome)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"ok": False, "error": str(exc)}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
