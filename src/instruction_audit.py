#!/usr/bin/env python3
"""Measure and lint the repository's active agent-instruction surface."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]

GROUP_PATTERNS: dict[str, tuple[str, ...]] = {
    "root_profiles": ("AGENTS.md", "CLAUDE.md", "GEMINI.md"),
    "shared_contracts": (".agents/shared/commands/*.md",),
    "shared_registries": (".agents/shared/*.json",),
    "codex_skills": (".agents/codex/skills/*/SKILL.md",),
    "codex_skill_metadata": (".agents/codex/skills/*/agents/openai.yaml",),
    "claude_wrappers": (".claude/commands/*.md",),
    "gemini_markdown_wrappers": (".gemini/commands/*.md",),
    "gemini_toml_wrappers": (".gemini/commands/*.toml",),
    "plugin_wrappers": ("plugins/agentic-neuro/commands/*.md",),
    "agent_manifests": (
        ".agents/plugins/*.json",
        "plugins/agentic-neuro/.codex-plugin/*.json",
    ),
}

SHARED_REF_RE = re.compile(r"\.agents/shared/commands/[A-Za-z0-9_.-]+\.md")
TASK_RE = re.compile(r"--task\s+([a-z][a-z0-9-]*)")
SHARED_DATA_REF_RE = re.compile(r"\.agents/shared/[A-Za-z0-9_./-]+\.json")
LOCAL_COMMAND_REF_RE = re.compile(r"`([a-z][a-z0-9-]+\.md)`")
SOURCE_REF_RE = re.compile(r"\bsrc/[A-Za-z0-9_./-]+\.py\b")
DATA_REFERENCE_RE = re.compile(r"\bdata/reference/[A-Za-z0-9_./-]+\.md\b")
WRAPPER_GROUPS = {
    "codex_skills",
    "claude_wrappers",
    "gemini_markdown_wrappers",
    "gemini_toml_wrappers",
    "plugin_wrappers",
    "codex_skill_metadata",
}
MAX_WRAPPER_WORDS = 120
BANNED_PATTERNS: dict[str, re.Pattern[str]] = {
    "stale_learner_profile": re.compile(
        r"Advanced MS4|entering neurosurgery internship", re.I
    ),
    "unverifiable_mastery_percentage": re.compile(
        r"target(?:ing)?\s+85%\s+(?:resident\s+)?mastery|85%\s+resident", re.I
    ),
    "stale_serial_retrieval": re.compile(
        r"serial per-domain|one focused serial RAG|30[–-]45 seconds is expected",
        re.I,
    ),
    "stale_bottom_yaml_adapter": re.compile(
        r"(?:description|guardrails?).{0,160}bottom YAML", re.I | re.S
    ),
    "forced_shift_debrief_phrase": re.compile(
        r"End the response with exactly:\s*`Do you want to complete a quick Socratic lesson",
        re.I,
    ),
    "stale_concept_quota": re.compile(
        r"(?:extract|write|promote|create)\s+(?:exactly\s+)?2\s*(?:[-–]|to)\s*5\s+(?:novel\s+)?concept",
        re.I,
    ),
    "stale_study_material_floor": re.compile(
        r"--min-(?:questions|questions-per-chunk|facts-per-chunk|fact-coverage)\b",
        re.I,
    ),
    "invalid_retrieval_status_ready": re.compile(
        r"retrieval_status[^\n]{0,80}(?:=|:|is)\s*`?ready\b",
        re.I,
    ),
    "stale_three_title_gate": re.compile(
        r"three-title gate|propose (?:exactly )?three titles|exactly three titles",
        re.I,
    ),
    "stale_current_outcomes_gate": re.compile(
        r"current_outcomes_source_present",
        re.I,
    ),
    "fixed_mastery_objective_quota": re.compile(
        r"Mastery Objectives[^\n]{0,100}(?:5\s*[-–]\s*10|5\s+to\s+10)",
        re.I,
    ),
    "raw_summary_as_routine_recall": re.compile(
        r"use\s+`?study_memory\.py summary`?\s+for\s+learner-state context",
        re.I,
    ),
}


def _paths_for(patterns: Iterable[str]) -> list[Path]:
    paths: set[Path] = set()
    for pattern in patterns:
        if any(char in pattern for char in "*?["):
            paths.update(ROOT.glob(pattern))
        else:
            path = ROOT / pattern
            if path.exists():
                paths.add(path)
    return sorted(path for path in paths if path.is_file())


def active_instruction_groups() -> dict[str, list[Path]]:
    return {name: _paths_for(patterns) for name, patterns in GROUP_PATTERNS.items()}


def active_instruction_paths() -> list[Path]:
    paths: set[Path] = set()
    for group_paths in active_instruction_groups().values():
        paths.update(group_paths)
    return sorted(paths)


def _find_local_cl100k_asset() -> Path:
    candidates = [
        Path(os.environ["TIKTOKEN_CL100K_PATH"])
        if os.environ.get("TIKTOKEN_CL100K_PATH")
        else None,
        Path("/private/tmp/agentic_neuro_cl100k_base.tiktoken"),
        ROOT / "data/runtime/cl100k_base.tiktoken",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise RuntimeError(
        "A real cl100k_base.tiktoken asset is required for instruction metrics. "
        "Set TIKTOKEN_CL100K_PATH or place the official asset at "
        "data/runtime/cl100k_base.tiktoken; do not substitute an estimated count."
    )


def _load_cl100k() -> Any:
    from tiktoken import Encoding
    from tiktoken.load import load_tiktoken_bpe

    return Encoding(
        name="cl100k_base_local",
        pat_str=(
            r"'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|"
            r"\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|"
            r"\s*[\r\n]|\s+(?!\S)|\s"
        ),
        mergeable_ranks=load_tiktoken_bpe(str(_find_local_cl100k_asset())),
        special_tokens={
            "<|endoftext|>": 100257,
            "<|fim_prefix|>": 100258,
            "<|fim_middle|>": 100259,
            "<|fim_suffix|>": 100260,
            "<|endofprompt|>": 100276,
        },
    )


def measure() -> dict[str, Any]:
    encoder = _load_cl100k()
    groups: dict[str, dict[str, int]] = {}
    for name, paths in active_instruction_groups().items():
        texts = [path.read_text(encoding="utf-8") for path in paths]
        groups[name] = {
            "files": len(paths),
            "lines": sum(len(text.splitlines()) for text in texts),
            "words": sum(len(text.split()) for text in texts),
            "cl100k_tokens": sum(len(encoder.encode(text)) for text in texts),
        }
    totals = {
        key: sum(group[key] for group in groups.values())
        for key in ("files", "lines", "words", "cl100k_tokens")
    }
    return {
        "tokenizer": "cl100k_base",
        "tokenizer_asset": str(_find_local_cl100k_asset()),
        "groups": groups,
        "total": totals,
    }


def _literal_assignment(path: Path, variable: str) -> Any:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == variable for target in targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"{variable} not found as a literal assignment in {path}")


def _banned_fragments(text: str) -> list[str]:
    return [code for code, pattern in BANNED_PATTERNS.items() if pattern.search(text)]


def _workflow_registry() -> dict[str, Any]:
    path = ROOT / ".agents/shared/workflow-registry.json"
    return json.loads(path.read_text(encoding="utf-8"))


def lint() -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    paths = active_instruction_paths()

    # Shared references are executable architecture: every named target must exist.
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for reference in sorted(set(SHARED_REF_RE.findall(text))):
            if not (ROOT / reference).is_file():
                errors.append(
                    {
                        "code": "missing_shared_contract",
                        "path": str(path.relative_to(ROOT)),
                        "value": reference,
                    }
                )
        for reference in sorted(set(SHARED_DATA_REF_RE.findall(text))):
            if not (ROOT / reference).is_file():
                errors.append(
                    {
                        "code": "missing_shared_registry",
                        "path": str(path.relative_to(ROOT)),
                        "value": reference,
                    }
                )
        for reference in sorted(set(SOURCE_REF_RE.findall(text))):
            if not (ROOT / reference).is_file():
                errors.append(
                    {
                        "code": "missing_instruction_script",
                        "path": str(path.relative_to(ROOT)),
                        "value": reference,
                    }
                )
        for reference in sorted(set(DATA_REFERENCE_RE.findall(text))):
            if not (ROOT / reference).is_file():
                errors.append(
                    {
                        "code": "missing_instruction_reference_data",
                        "path": str(path.relative_to(ROOT)),
                        "value": reference,
                    }
                )
        if path.parent == ROOT / ".agents/shared/commands":
            for reference in sorted(set(LOCAL_COMMAND_REF_RE.findall(text))):
                if not (path.parent / reference).is_file():
                    errors.append(
                        {
                            "code": "missing_local_command_contract",
                            "path": str(path.relative_to(ROOT)),
                            "value": reference,
                        }
                    )
        for code in _banned_fragments(text):
            errors.append(
                {
                    "code": code,
                    "path": str(path.relative_to(ROOT)),
                    "value": BANNED_PATTERNS[code].pattern,
                }
            )

    # Every documented vault task must be accepted by the implementation registry.
    task_policy = _literal_assignment(ROOT / "src/vault_index.py", "TASK_SECTION_POLICY")
    allowed_tasks = set(task_policy)
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for task in sorted(set(TASK_RE.findall(text))):
            if task not in allowed_tasks:
                errors.append(
                    {
                        "code": "unknown_vault_task",
                        "path": str(path.relative_to(ROOT)),
                        "value": task,
                    }
                )

    # The declarative registry must resolve every contract/module. Study review
    # resolves reviewable destinations from this registry at runtime; forcing
    # those roots to be duplicated in prose would recreate schema drift.
    registry = _workflow_registry()
    workflows = registry.get("workflows", {})
    required_fields = {
        "title",
        "description",
        "argument_hint",
        "contract",
        "vault_destination",
        "reviewable",
        "write_policy",
        "anki_policy",
    }
    if registry.get("schema_version") != 1:
        errors.append(
            {
                "code": "unsupported_workflow_registry_schema",
                "path": ".agents/shared/workflow-registry.json",
                "value": registry.get("schema_version"),
            }
        )
    review_startup = re.sub(
        r"\s+",
        " ",
        (ROOT / ".agents/shared/commands/study-review-startup.md").read_text(
            encoding="utf-8"
        ),
    )
    for name, workflow in workflows.items():
        missing = sorted(required_fields - set(workflow))
        if missing:
            errors.append(
                {
                    "code": "incomplete_workflow_registry_entry",
                    "path": ".agents/shared/workflow-registry.json",
                    "value": f"{name}: {', '.join(missing)}",
                }
            )
            continue
        references = [workflow["contract"], *workflow.get("modules", [])]
        for reference in references:
            if not (ROOT / reference).is_file():
                errors.append(
                    {
                        "code": "missing_workflow_module",
                        "path": ".agents/shared/workflow-registry.json",
                        "value": f"{name}: {reference}",
                    }
                )
        alias_for = workflow.get("alias_for")
        if alias_for and alias_for not in workflows:
            errors.append(
                {
                    "code": "unknown_workflow_alias_target",
                    "path": ".agents/shared/workflow-registry.json",
                    "value": f"{name}: {alias_for}",
                }
            )
        codex_ui = workflow.get("codex_ui")
        if codex_ui is not None:
            missing_ui = {
                "display_name",
                "short_description",
                "default_prompt",
            } - set(codex_ui)
            if missing_ui:
                errors.append(
                    {
                        "code": "incomplete_codex_ui_metadata",
                        "path": ".agents/shared/workflow-registry.json",
                        "value": f"{name}: {', '.join(sorted(missing_ui))}",
                    }
                )
        if workflow.get("reviewable") and not workflow.get("vault_destination"):
            errors.append(
                {
                    "code": "reviewable_workflow_missing_destination",
                    "path": ".agents/shared/workflow-registry.json",
                    "value": name,
                }
            )
        if workflow.get("generation_recall") == "document" and not workflow.get("vault_destination"):
            errors.append(
                {
                    "code": "document_recall_workflow_missing_destination",
                    "path": ".agents/shared/workflow-registry.json",
                    "value": name,
                }
            )

    for marker in ("workflow-registry.json", "reviewable"):
        if marker not in review_startup:
            errors.append(
                {
                    "code": "study_review_registry_resolution_missing",
                    "path": ".agents/shared/commands/study-review-startup.md",
                    "value": marker,
                }
            )

    manifest_path = ROOT / "plugins/agentic-neuro/.codex-plugin/plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    serialized_manifest = json.dumps(manifest).lower()
    if "brain dump" in serialized_manifest:
        errors.append(
            {
                "code": "stale_plugin_product_language",
                "path": str(manifest_path.relative_to(ROOT)),
                "value": "brain dump",
            }
        )
    for field in ("privacyPolicyURL", "termsOfServiceURL"):
        if field in manifest.get("interface", {}):
            errors.append(
                {
                    "code": "unsupported_plugin_legal_url",
                    "path": str(manifest_path.relative_to(ROOT)),
                    "value": field,
                }
            )

    # Runtime adapters are generated products. Any mismatch is policy drift.
    try:
        try:
            from sync_agent_adapters import expected_files
        except ModuleNotFoundError:  # imported as src.instruction_audit
            from .sync_agent_adapters import expected_files

        for path, expected in expected_files(registry).items():
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                errors.append(
                    {
                        "code": "adapter_drift",
                        "path": str(path.relative_to(ROOT)),
                        "value": "run python3 src/sync_agent_adapters.py",
                    }
                )
    except (OSError, ValueError, KeyError) as exc:
        errors.append(
            {
                "code": "adapter_generation_error",
                "path": "src/sync_agent_adapters.py",
                "value": str(exc),
            }
        )

    for group_name, group_paths in active_instruction_groups().items():
        if group_name not in WRAPPER_GROUPS:
            continue
        for path in group_paths:
            words = len(path.read_text(encoding="utf-8").split())
            if words > MAX_WRAPPER_WORDS:
                errors.append(
                    {
                        "code": "bloated_runtime_adapter",
                        "path": str(path.relative_to(ROOT)),
                        "value": f"{words} words > {MAX_WRAPPER_WORDS}",
                    }
                )

    # Empty tracked settings files and stale local allowlists previously created
    # no behavior while obscuring the real authority and broadening shell access.
    for relative in (
        ".claude/settings.json",
        ".gemini/settings.json",
        ".claude/settings.local.json",
    ):
        path = ROOT / relative
        if path.exists():
            errors.append(
                {
                    "code": "stale_runtime_settings",
                    "path": relative,
                    "value": "remove empty placeholder or stale local allowlist",
                }
            )

    counts: defaultdict[str, int] = defaultdict(int)
    for error in errors:
        counts[error["code"]] += 1
    return {
        "ok": not errors,
        "error_count": len(errors),
        "counts": dict(sorted(counts.items())),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("measure", "lint", "all"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result: dict[str, Any] = {}
    if args.command in {"measure", "all"}:
        result["measurement"] = measure()
    if args.command in {"lint", "all"}:
        result["lint"] = lint()

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if "measurement" in result:
            total = result["measurement"]["total"]
            print(
                "instructions: "
                f"{total['files']} files, {total['lines']} lines, "
                f"{total['words']} words, {total['cl100k_tokens']} cl100k tokens"
            )
        if "lint" in result:
            lint_result = result["lint"]
            print(
                f"instruction lint: {'PASS' if lint_result['ok'] else 'FAIL'} "
                f"({lint_result['error_count']} errors)"
            )
            for error in lint_result["errors"]:
                print(f"- {error['code']}: {error['path']}: {error['value']}")

    return 0 if result.get("lint", {"ok": True})["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
