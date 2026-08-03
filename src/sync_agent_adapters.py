#!/usr/bin/env python3
"""Generate thin runtime adapters from the canonical workflow registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / ".agents/shared/workflow-registry.json"


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


def _claude(name: str, workflow: dict) -> str:
    return f"""---
name: {name}
description: {workflow['description']}
---

# {workflow['title']}

Read `.agents/shared/workflow-registry.json`, then read and follow
`{workflow['contract']}`. The shared contract is the behavioral authority.
"""


def _gemini_markdown(name: str, workflow: dict) -> str:
    return f"""---
name: {name}
description: {workflow['description']}
---

# {workflow['title']}

Read `.agents/shared/workflow-registry.json`, then read and follow
`{workflow['contract']}`. This adapter adds no workflow policy.
"""


def _gemini_toml(name: str, workflow: dict) -> str:
    description = workflow["description"].replace('"', '\\"')
    return f'''description = "{description}"

prompt = """
ACTIVE COMMAND: /{name}
User input: {{{{args}}}}

Read `.agents/shared/workflow-registry.json`, then read and follow the canonical
contract below. Do not infer behavioral policy from this adapter.

@{{{workflow['contract']}}}
"""
'''


def _plugin(name: str, workflow: dict) -> str:
    return f"""---
description: {workflow['description']}
argument-hint: {workflow['argument_hint']}
---

# {workflow['title']}

The user invoked `/{name}` with: $ARGUMENTS

Read `.agents/shared/workflow-registry.json`, then read and follow
`{workflow['contract']}`. The shared contract is the behavioral authority.
"""


def _codex_skill(name: str, workflow: dict) -> str:
    note = workflow.get("codex_note")
    suffix = f"\nCodex runtime note: {note}\n" if note else ""
    description = workflow["description"]
    return f"""---
name: {name}
description: Use when Gabriel invokes /{name} or asks to {description[0].lower() + description[1:]}
---

# {workflow['title']}

Read `.agents/shared/workflow-registry.json`, then read and follow
`{workflow['contract']}` completely. The registry and shared contract own all
workflow behavior; do not duplicate or reinterpret it here.
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
        expected[ROOT / f".claude/commands/{name}.md"] = _claude(name, workflow)
        expected[ROOT / f".gemini/commands/{name}.md"] = _gemini_markdown(
            name, workflow
        )
        expected[ROOT / f".gemini/commands/{name}.toml"] = _gemini_toml(
            name, workflow
        )
        expected[ROOT / f"plugins/agentic-neuro/commands/{name}.md"] = _plugin(
            name, workflow
        )
        expected[ROOT / f".agents/codex/skills/{name}/SKILL.md"] = _codex_skill(
            name, workflow
        )
        if workflow.get("codex_ui"):
            expected[
                ROOT / f".agents/codex/skills/{name}/agents/openai.yaml"
            ] = _codex_ui(workflow)
    return expected


def sync(*, check: bool) -> list[str]:
    mismatches: list[str] = []
    for path, content in expected_files(_load_registry()).items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        mismatches.append(str(path.relative_to(ROOT)))
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
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
