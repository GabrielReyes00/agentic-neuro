#!/usr/bin/env python3
"""Generate thin runtime adapters from the canonical workflow registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from workflow_runtime import runtime_projection
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from .workflow_runtime import runtime_projection


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / ".agents/shared/workflow-registry.json"
PLUGIN_ROOT = ROOT / "plugins/agentic-neuro"
PLUGIN_RESOURCES = PLUGIN_ROOT / "resources"
MANAGED_PATTERNS = (
    ".agents/shared/runtime/*.json",
    ".agents/codex/skills/*/SKILL.md",
    ".agents/codex/skills/*/agents/openai.yaml",
    ".claude/commands/*.md",
    ".gemini/commands/*.md",
    ".gemini/commands/*.toml",
    "plugins/agentic-neuro/commands/*.md",
    "plugins/agentic-neuro/skills/*/SKILL.md",
    "plugins/agentic-neuro/resources/**/*",
)


def _load_registry() -> dict:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    workflows = data.get("workflows")
    if not isinstance(workflows, dict) or not workflows:
        raise ValueError("workflow registry has no workflows")
    for name, workflow in workflows.items():
        missing = {
            field
            for field in ("title", "description", "argument_hint", "contract")
            if not workflow.get(field)
        }
        if missing:
            raise ValueError(f"{name}: missing registry fields {sorted(missing)}")
    return data


def _contract_list(projection: dict) -> str:
    execution = projection["execution"]
    entry = next(node for node in execution["nodes"] if node["id"] == execution["entry"])
    contracts = dict.fromkeys((projection["contract"], *entry["load"]))
    return ", ".join(f"`{path}`" for path in contracts)


def _claude(name: str, workflow: dict, projection: dict) -> str:
    return f"""---
name: {name}
description: {workflow['description']}
---

# {workflow['title']}

Read `.agents/shared/runtime/{name}.json` and
`.agents/shared/commands/workflow-runtime.md`, then the entry contracts:
{_contract_list(projection)}. Load later contracts only after a declared
transition. Shared contracts remain the behavioral authority.
"""


def _gemini_markdown(name: str, workflow: dict, projection: dict) -> str:
    return f"""---
name: {name}
description: {workflow['description']}
---

# {workflow['title']}

Read `.agents/shared/runtime/{name}.json` and
`.agents/shared/commands/workflow-runtime.md`, then the entry contracts:
{_contract_list(projection)}. Load later contracts only after a declared
transition. This adapter adds no workflow policy.
"""


def _gemini_toml(name: str, workflow: dict, projection: dict) -> str:
    description = workflow["description"].replace('"', '\\"')
    return f'''description = "{description}"

prompt = """
ACTIVE COMMAND: /{name}
User input: {{{{args}}}}

Read the generated selected-workflow spec below, then
`.agents/shared/commands/workflow-runtime.md`, then the entry contracts:
{_contract_list(projection)}. Load later contracts only after a declared
transition. Do not infer behavioral policy from this adapter.

@{{.agents/shared/runtime/{name}.json}}
"""
'''


def _plugin(name: str, workflow: dict, projection: dict) -> str:
    execution = projection["execution"]
    entry = next(node for node in execution["nodes"] if node["id"] == execution["entry"])
    contracts = dict.fromkeys((projection["contract"], *entry["load"]))
    bundled_contracts = ", ".join(
        f"`resources/{path}`" for path in contracts
    )
    return f"""---
description: {workflow['description']}
argument-hint: {workflow['argument_hint']}
---

# {workflow['title']}

The user invoked `/{name}` with: $ARGUMENTS

Resolve the plugin root from this command file. Read `resources/AGENTS.md`,
`resources/.agents/shared/runtime/{name}.json`, and
`resources/.agents/shared/commands/workflow-runtime.md`, then the entry
contracts: {bundled_contracts}. These are generated mirrors of the canonical
`.agents/shared/commands/` contracts. Load later contracts only after a declared
transition.
"""


def _plugin_skill(name: str, workflow: dict, projection: dict) -> str:
    execution = projection["execution"]
    entry = next(node for node in execution["nodes"] if node["id"] == execution["entry"])
    contracts = dict.fromkeys((projection["contract"], *entry["load"]))
    bundled_contracts = ", ".join(f"`../../resources/{path}`" for path in contracts)
    description = workflow["description"]
    return f"""---
name: {name}
description: Use when Gabriel invokes /{name} or asks to {description[0].lower() + description[1:]}
---

# {workflow['title']}

Resolve the plugin root from this skill directory. Read
`../../resources/AGENTS.md`, `../../resources/.agents/shared/runtime/{name}.json`,
and `../../resources/.agents/shared/commands/workflow-runtime.md`, then the entry
contracts: {bundled_contracts}. These generated mirrors preserve the canonical
`.agents/shared/commands/` behavior. Load later contracts only after a declared
transition.
"""


def _codex_skill(name: str, workflow: dict, projection: dict) -> str:
    note = workflow.get("codex_note")
    suffix = f"\nCodex runtime note: {note}\n" if note else ""
    description = workflow["description"]
    return f"""---
name: {name}
description: Use when Gabriel invokes /{name} or asks to {description[0].lower() + description[1:]}
---

# {workflow['title']}

Read `.agents/shared/runtime/{name}.json` and
`.agents/shared/commands/workflow-runtime.md` completely, then the entry
contracts: {_contract_list(projection)}. Load later contracts only after a
declared transition. Shared contracts own behavior; do not reinterpret them.
{suffix}"""


def _codex_ui(workflow: dict) -> str:
    ui = workflow["codex_ui"]
    return "\n".join(
        (
            "interface:",
            f"  display_name: {json.dumps(ui['display_name'])}",
            f"  short_description: {json.dumps(ui['short_description'])}",
            f"  default_prompt: {json.dumps(ui['default_prompt'])}",
            "",
        )
    )


def expected_files(registry: dict) -> dict[Path, str]:
    expected: dict[Path, str] = {}
    for name, workflow in registry["workflows"].items():
        projection = runtime_projection(name, registry=registry)
        expected[ROOT / f".agents/shared/runtime/{name}.json"] = (
            json.dumps(projection, indent=2, sort_keys=True) + "\n"
        )
        expected[ROOT / f".claude/commands/{name}.md"] = _claude(
            name, workflow, projection
        )
        expected[ROOT / f".gemini/commands/{name}.md"] = _gemini_markdown(
            name, workflow, projection
        )
        expected[ROOT / f".gemini/commands/{name}.toml"] = _gemini_toml(
            name, workflow, projection
        )
        expected[ROOT / f"plugins/agentic-neuro/commands/{name}.md"] = _plugin(
            name, workflow, projection
        )
        expected[ROOT / f".agents/codex/skills/{name}/SKILL.md"] = _codex_skill(
            name, workflow, projection
        )
        if workflow.get("codex_ui"):
            expected[
                ROOT / f".agents/codex/skills/{name}/agents/openai.yaml"
            ] = _codex_ui(workflow)
    return expected


def expected_plugin_files(registry: dict) -> dict[Path, str | bytes]:
    """Return a self-contained generated mirror of plugin instruction assets."""
    expected: dict[Path, str | bytes] = {
        PLUGIN_RESOURCES / "AGENTS.md": (ROOT / "AGENTS.md").read_text(encoding="utf-8"),
    }
    for name, workflow in registry["workflows"].items():
        projection = runtime_projection(name, registry=registry)
        expected[PLUGIN_ROOT / f"skills/{name}/SKILL.md"] = _plugin_skill(
            name, workflow, projection
        )
    shared_root = ROOT / ".agents/shared"
    for source in (
        *sorted((shared_root / "commands").glob("*.md")),
        *sorted((shared_root / "runtime").glob("*.json")),
        shared_root / "workflow-registry.json",
        shared_root / "workflow-schema.json",
        shared_root / "presentation-styles.json",
    ):
        relative = source.relative_to(ROOT)
        expected[PLUGIN_RESOURCES / relative] = source.read_text(encoding="utf-8")
    assets_root = shared_root / "assets"
    if assets_root.exists():
        for source in sorted(path for path in assets_root.rglob("*") if path.is_file()):
            expected[PLUGIN_RESOURCES / source.relative_to(ROOT)] = source.read_bytes()
    maintenance_root = ROOT / "docs" / "maintenance"
    for source in sorted(maintenance_root.glob("*.md")):
        expected[PLUGIN_RESOURCES / source.relative_to(ROOT)] = source.read_text(
            encoding="utf-8"
        )
    return expected


def unexpected_managed_files(expected: dict[Path, str | bytes]) -> list[Path]:
    """Return stale generated files without deleting them implicitly."""
    actual: set[Path] = set()
    for pattern in MANAGED_PATTERNS:
        actual.update(path for path in ROOT.glob(pattern) if path.is_file())
    return sorted(actual - set(expected))


def sync(*, check: bool) -> list[str]:
    mismatches: list[str] = []
    registry = _load_registry()
    expected = {**expected_files(registry), **expected_plugin_files(registry)}
    if check:
        mismatches.extend(
            f"unexpected:{path.relative_to(ROOT)}"
            for path in unexpected_managed_files(expected)
        )
    for path, content in expected.items():
        current = (
            path.read_bytes()
            if isinstance(content, bytes) and path.exists()
            else path.read_text(encoding="utf-8")
            if path.exists()
            else None
        )
        if current == content:
            continue
        mismatches.append(str(path.relative_to(ROOT)))
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="report drift without writing files"
    )
    args = parser.parse_args()
    mismatches = sync(check=args.check)
    if mismatches:
        action = "drift" if args.check else "updated"
        print(f"{action}: {len(mismatches)} adapter(s)")
        for path in mismatches:
            print(path)
        return 1 if args.check else 0
    print("adapters synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
