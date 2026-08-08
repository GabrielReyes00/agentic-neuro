#!/usr/bin/env python3
"""Deterministic guards for module boundaries and retired code duplication."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
MODULE_LINE_BUDGETS = {
    "src/study_memory.py": 7800,
    "src/retrieval/pipeline.py": 3400,
    "src/retrieval/cli.py": 500,
}
RETIRED_LOCAL_HELPERS = frozenset({"_atomic_write", "_refresh_vault_intelligence"})


def _module_paths() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in SRC.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        modules[".".join(path.relative_to(ROOT).with_suffix("").parts)] = path
    return modules


def _top_level_nodes(nodes: Iterable[ast.stmt]) -> Iterable[ast.stmt]:
    for node in nodes:
        yield node
        if isinstance(node, ast.Try):
            yield from _top_level_nodes(node.body)
            for handler in node.handlers:
                yield from _top_level_nodes(handler.body)
            yield from _top_level_nodes(node.orelse)
            yield from _top_level_nodes(node.finalbody)
        elif isinstance(node, (ast.If, ast.With)):
            yield from _top_level_nodes(node.body)
            yield from _top_level_nodes(getattr(node, "orelse", []))


def _resolve_imports(module: str, tree: ast.Module, modules: dict[str, Path]) -> set[str]:
    stems = {name.rsplit(".", 1)[-1]: name for name in modules}
    package = module.split(".")[:-1]
    dependencies: set[str] = set()
    for node in _top_level_nodes(tree.body):
        if isinstance(node, ast.Import):
            for alias in node.names:
                candidate = alias.name if alias.name in modules else stems.get(alias.name.split(".")[0])
                if candidate in modules:
                    dependencies.add(candidate)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = max(0, len(package) - (node.level - 1))
                base_parts = package[:keep]
                if node.module:
                    base_parts.extend(node.module.split("."))
                    candidate = ".".join(base_parts)
                    if candidate in modules:
                        dependencies.add(candidate)
                else:
                    for alias in node.names:
                        candidate = ".".join([*base_parts, alias.name])
                        if candidate in modules:
                            dependencies.add(candidate)
            elif node.module:
                candidate = node.module if node.module in modules else stems.get(node.module.split(".")[0])
                if candidate in modules:
                    dependencies.add(candidate)
    return dependencies


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    visited: set[str] = set()
    active: list[str] = []
    found: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        visited.add(node)
        active.append(node)
        for dependency in sorted(graph[node]):
            if dependency in active:
                cycle = active[active.index(dependency):]
                rotations = [tuple(cycle[index:] + cycle[:index]) for index in range(len(cycle))]
                found.add(min(rotations))
            elif dependency not in visited:
                visit(dependency)
        active.pop()

    for node in sorted(graph):
        if node not in visited:
            visit(node)
    return [list(cycle) for cycle in sorted(found)]


def audit() -> dict[str, Any]:
    modules = _module_paths()
    trees = {
        module: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module, path in modules.items()
    }
    graph = {
        module: _resolve_imports(module, trees[module], modules)
        for module in modules
    }
    errors: list[dict[str, Any]] = []
    for cycle in _cycles(graph):
        errors.append({"code": "top_level_import_cycle", "modules": cycle})

    for relative, limit in MODULE_LINE_BUDGETS.items():
        lines = len((ROOT / relative).read_text(encoding="utf-8").splitlines())
        if lines > limit:
            errors.append(
                {"code": "module_line_budget", "path": relative, "lines": lines, "limit": limit}
            )

    for module, tree in trees.items():
        path = str(modules[module].relative_to(ROOT))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in RETIRED_LOCAL_HELPERS:
                errors.append({"code": "retired_duplicate_helper", "path": path, "name": node.name})

    pipeline_tree = trees["src.retrieval.pipeline"]
    if any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and any(isinstance(item, ast.Constant) and item.value == "__main__" for item in ast.walk(node.test))
        for node in pipeline_tree.body
    ):
        errors.append({"code": "library_owns_cli", "path": "src/retrieval/pipeline.py"})
    if "src.retrieval.batch" in graph["src.retrieval.pipeline"]:
        errors.append(
            {
                "code": "retrieval_dependency_inversion",
                "path": "src/retrieval/pipeline.py",
                "dependency": "src.retrieval.batch",
            }
        )

    return {
        "ok": not errors,
        "module_count": len(modules),
        "top_level_edge_count": sum(len(edges) for edges in graph.values()),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"code architecture: {'PASS' if result['ok'] else 'FAIL'}")
        for error in result["errors"]:
            print(f"- {error['code']}: {error}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

