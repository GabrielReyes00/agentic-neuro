#!/usr/bin/env python3
"""Validate and install clinical concept cards in the Obsidian vault."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_VAULT_ROOT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
CONCEPT_DIRNAME = "Concepts"
PROTECTED_FILENAMES = {
    "Neurosurgery Consult Workflow.md",
    "Neurosurgery Consult Checklists by Pathology.md",
    "Peripheral Nerve Injury Classifications (Seddon & Sunderland).md",
}
REQUIRED_HEADINGS = (
    "Quick Reference",
    "Clinical Use",
    "Durable Mental Model",
    "Critical Discriminators",
    "Execution Check",
    "Related In This Vault",
)
ARCHETYPE_HEADINGS = (
    "Surgical Coordinates",
    "Evidence Card",
    "Consequence Matrix",
    "Bedside Decision Rule",
    "Imaging Read",
)
REQUIRED_METADATA_KEYS = {
    "aliases",
    "created",
    "extracted_from",
    "tags",
    "domain",
    "summary",
}
CANONICAL_DOMAINS = {
    "vascular",
    "skull-base",
    "tumor",
    "spine",
    "trauma",
    "neurocritical-care",
    "functional",
    "pediatric",
    "peripheral-nerve",
    "anatomy",
    "general",
}
NUMERIC_OR_EVIDENCE_RE = re.compile(
    r"\b(?:trial|guideline|NNT|ARR|mRS|odds ratio|hazard ratio|sensitivity|specificity|"
    r"\d+(?:\.\d+)?\s*(?:%|mL|mmHg|hours?|days?|weeks?|months?|years?)|"
    r"Type\s+[IVX]+|Class\s+[IVX]+)\b",
    re.I,
)
REFERENCE_LINK_RE = re.compile(r"\[[^\]]+\]\(https?://[^)]+\)")
WIKILINK_RE = re.compile(r"\[\[[^\]]+\]\]")


@dataclass
class ValidationResult:
    path: str
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "path": self.path, "errors": self.errors}


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _safe_title(title: str) -> str:
    clean = re.sub(r"\s+", " ", title.strip())
    if not clean or "/" in clean or "\\" in clean or clean in {".", ".."}:
        raise ValueError("title must be a non-empty filename-safe concept title")
    return clean


def _target_path(vault_root: Path, title: str) -> Path:
    return vault_root / CONCEPT_DIRNAME / f"{_safe_title(title)}.md"


def _bottom_yaml(text: str) -> str | None:
    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or lines[-1].strip() != "---":
        return None
    close = len(lines) - 1
    open_idx = next((idx for idx in range(close - 1, -1, -1) if lines[idx].strip() == "---"), None)
    if open_idx is None:
        return None
    return "\n".join(lines[open_idx + 1 : close])


def _parse_bottom_yaml(text: str) -> dict[str, Any]:
    yaml_text = _bottom_yaml(text)
    if yaml_text is None:
        return {}
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _section_body(text: str, heading: str) -> str | None:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$([\s\S]*?)(?=^## |\n---\n|\Z)",
        text,
        flags=re.M,
    )
    return match.group(1) if match else None


def _domain_tokens(value: Any) -> set[str]:
    tokens: set[str] = set()
    raw_items: list[str] = []
    if isinstance(value, (list, tuple)):
        raw_items.extend(str(item) for item in value)
    elif value is not None:
        raw_items.extend(re.split(r"[,/]", str(value)))
    for item in raw_items:
        token = item.strip().lower().replace(" ", "-").replace("_", "-")
        if token:
            tokens.add(token)
    return tokens


def validate_text(text: str, *, path: Path) -> ValidationResult:
    errors: list[str] = []
    stripped = text.lstrip()
    if stripped.startswith("# "):
        errors.append("concept note must not start with an H1 heading")
    if stripped.startswith("---\n"):
        errors.append("concept metadata belongs in bottom YAML")
    if not re.search(r"^\*\*[^*\n]+?\*\*:\s+\S", text, flags=re.M):
        errors.append("concept note must open with a bold concept definition line")

    for heading in REQUIRED_HEADINGS:
        if not re.search(rf"^## {re.escape(heading)}\s*$", text, flags=re.M):
            errors.append(f"missing required heading: ## {heading}")
    archetype_count = sum(
        1 for heading in ARCHETYPE_HEADINGS if re.search(rf"^## {re.escape(heading)}\s*$", text, flags=re.M)
    )
    if archetype_count < 1:
        errors.append("concept note must include one archetype-specific execution section")

    quick_ref = _section_body(text, "Quick Reference")
    if quick_ref and len(re.findall(r"^\s*[-*]\s+\S", quick_ref, flags=re.M)) < 2:
        errors.append("Quick Reference must include at least 2 concise bullets")

    clinical_use = _section_body(text, "Clinical Use")
    if clinical_use and len(re.findall(r"\w+", clinical_use)) < 20:
        errors.append("Clinical Use must explain the management, diagnostic, operative, or prognostic consequence")

    mental_model = _section_body(text, "Durable Mental Model")
    if mental_model and len(re.findall(r"\w+", mental_model)) < 12:
        errors.append("Durable Mental Model must contain a memorable mechanism, analogy, or decision rule")

    discriminators = _section_body(text, "Critical Discriminators")
    if discriminators and len(re.findall(r"^\s*[-*]\s+\S", discriminators, flags=re.M)) < 2:
        errors.append("Critical Discriminators must include at least 2 bullets")

    execution = _section_body(text, "Execution Check")
    if execution and len(re.findall(r"^\s*[-*]\s+\S", execution, flags=re.M)) < 2:
        errors.append("Execution Check must include at least 2 action-oriented bullets")

    related = _section_body(text, "Related In This Vault")
    if related and not WIKILINK_RE.search(related):
        errors.append("Related In This Vault must include at least one wikilink")

    references = _section_body(text, "References")
    if NUMERIC_OR_EVIDENCE_RE.search(text) and (not references or not REFERENCE_LINK_RE.search(references)):
        errors.append("trial, guideline, numeric, or classification claims require linked References")

    yaml_text = _bottom_yaml(text)
    if yaml_text is None:
        errors.append("missing bottom YAML metadata block")
    meta = _parse_bottom_yaml(text)
    if meta:
        missing = REQUIRED_METADATA_KEYS - set(meta)
        for key in sorted(missing):
            errors.append(f"bottom YAML missing key: {key}")
        tags = meta.get("tags")
        tag_values: set[str] = set()
        if isinstance(tags, (list, tuple)):
            tag_values.update(str(tag).strip() for tag in tags)
        elif isinstance(tags, str):
            tag_values.update(token.strip() for token in re.split(r"[,\s]+", tags) if token.strip())
        if "type/concept" not in tag_values:
            errors.append("bottom YAML tags must include type/concept")
        if "source/agent" not in tag_values:
            errors.append("bottom YAML tags must include source/agent")
        domains = _domain_tokens(meta.get("domain"))
        if not domains & CANONICAL_DOMAINS:
            errors.append("bottom YAML domain must include a canonical domain slug")
        summary = meta.get("summary")
        if not isinstance(summary, str) or len(summary.split()) < 5:
            errors.append("bottom YAML summary must be a useful one-line index summary")

    return ValidationResult(str(path), errors)


def validate_file(path: Path) -> ValidationResult:
    if not path.exists():
        return ValidationResult(str(path), ["file does not exist"])
    return validate_text(path.read_text(encoding="utf-8"), path=path)


def _update_index(vault_root: Path) -> None:
    try:
        import index_builder
    except ModuleNotFoundError:
        from . import index_builder
    index_builder.write_index(vault_root / CONCEPT_DIRNAME, vault_root=vault_root)


def install_draft(
    draft: Path,
    title: str,
    *,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    allow_protected: bool = False,
) -> ValidationResult:
    safe_title = _safe_title(title)
    target = _target_path(vault_root, safe_title)
    if target.name in PROTECTED_FILENAMES and not allow_protected:
        return ValidationResult(str(target), ["protected concept note requires explicit allow_protected"])

    source_result = validate_file(draft)
    if not source_result.ok:
        return source_result

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(draft.read_text(encoding="utf-8"), encoding="utf-8")
    installed_result = validate_file(target)
    if installed_result.ok:
        _update_index(vault_root)
    return installed_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and install Concepts vault notes")
    parser.add_argument("--vault-root", default=str(DEFAULT_VAULT_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("path")

    install_parser = sub.add_parser("install")
    install_parser.add_argument("--draft", required=True)
    install_parser.add_argument("--title", required=True)
    install_parser.add_argument("--allow-protected", action="store_true")

    args = parser.parse_args()
    vault_root = Path(args.vault_root)
    if args.command == "validate":
        result = validate_file(Path(args.path))
    else:
        result = install_draft(
            Path(args.draft),
            args.title,
            vault_root=vault_root,
            allow_protected=args.allow_protected,
        )

    print(_json_dumps(result.to_dict()))
    if not result.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
