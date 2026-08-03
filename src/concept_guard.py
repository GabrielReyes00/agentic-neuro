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

try:
    from vault_schema import parse_frontmatter, split_frontmatter
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from .vault_schema import parse_frontmatter, split_frontmatter


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


def _section_body(text: str, heading: str) -> str | None:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$([\s\S]*?)(?=^## |\Z)",
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
    body, parsed_meta = split_frontmatter(text)
    meta = parsed_meta or {}
    if body.lstrip().startswith("# "):
        errors.append("concept note must not start with an H1 heading")
    if not re.search(r"^\*\*[^*\n]+?\*\*:\s+\S", body, flags=re.M):
        errors.append("concept note must open with a bold concept definition line")

    for heading in REQUIRED_HEADINGS:
        if not re.search(rf"^## {re.escape(heading)}\s*$", body, flags=re.M):
            errors.append(f"missing required heading: ## {heading}")
    archetype_count = sum(
        1 for heading in ARCHETYPE_HEADINGS if re.search(rf"^## {re.escape(heading)}\s*$", body, flags=re.M)
    )
    if archetype_count < 1:
        errors.append("concept note must include one archetype-specific execution section")

    quick_ref = _section_body(text, "Quick Reference")
    if quick_ref is not None and not re.search(r"^\s*[-*]\s+\S", quick_ref, flags=re.M):
        errors.append("Quick Reference must include concise bullets")

    clinical_use = _section_body(text, "Clinical Use")
    if clinical_use is not None and not clinical_use.strip():
        errors.append("Clinical Use must explain the management, diagnostic, operative, or prognostic consequence")

    mental_model = _section_body(text, "Durable Mental Model")
    if mental_model is not None and not mental_model.strip():
        errors.append("Durable Mental Model must contain a memorable mechanism, analogy, or decision rule")

    discriminators = _section_body(text, "Critical Discriminators")
    if discriminators is not None and not re.search(r"^\s*[-*]\s+\S", discriminators, flags=re.M):
        errors.append("Critical Discriminators must include clinically meaningful contrast bullets")

    execution = _section_body(text, "Execution Check")
    if execution is not None and not re.search(r"^\s*[-*]\s+\S", execution, flags=re.M):
        errors.append("Execution Check must include action-oriented bullets")

    related = _section_body(text, "Related In This Vault")
    if related is not None and not (
        WIKILINK_RE.search(related)
        or re.search(r"no\s+(?:verified\s+)?related\s+(?:vault\s+)?(?:note|artifact|link)", related, flags=re.I)
    ):
        errors.append("Related In This Vault requires verified wikilinks or an explicit no-related-note statement")

    references = _section_body(text, "References")
    if NUMERIC_OR_EVIDENCE_RE.search(body) and (not references or not REFERENCE_LINK_RE.search(references)):
        errors.append("trial, guideline, numeric, or classification claims require linked References")

    if not meta:
        errors.append("missing or invalid native YAML frontmatter")
    if meta:
        missing = REQUIRED_METADATA_KEYS - set(meta)
        for key in sorted(missing):
            errors.append(f"frontmatter missing key: {key}")
        tags = meta.get("tags")
        tag_values: set[str] = set()
        if isinstance(tags, (list, tuple)):
            tag_values.update(str(tag).strip() for tag in tags)
        elif isinstance(tags, str):
            tag_values.update(token.strip() for token in re.split(r"[,\s]+", tags) if token.strip())
        if "type/concept" not in tag_values:
            errors.append("frontmatter tags must include type/concept")
        if "source/agent" not in tag_values:
            errors.append("frontmatter tags must include source/agent")
        domains = _domain_tokens(meta.get("domain"))
        if not domains & CANONICAL_DOMAINS:
            errors.append("frontmatter domain must include a canonical domain slug")
        summary = meta.get("summary")
        if not isinstance(summary, str) or len(summary.split()) < 5:
            errors.append("frontmatter summary must be a useful one-line index summary")

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


def _refresh_vault_intelligence(vault_root: Path) -> None:
    try:
        import vault_index
    except ModuleNotFoundError:
        from . import vault_index
    vault_index.refresh_default_index_after_vault_write(vault_root=vault_root)


def install_draft(
    draft: Path,
    title: str,
    *,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    allow_protected: bool = False,
    allow_existing: bool = False,
) -> ValidationResult:
    safe_title = _safe_title(title)
    target = _target_path(vault_root, safe_title)
    if target.name in PROTECTED_FILENAMES and not allow_protected:
        return ValidationResult(str(target), ["protected concept note requires explicit allow_protected"])
    if target.exists() and not allow_existing:
        return ValidationResult(
            str(target),
            ["concept note already exists; read and merge it, then pass allow_existing"],
        )

    source_result = validate_file(draft)
    if not source_result.ok:
        return source_result

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(draft.read_text(encoding="utf-8"), encoding="utf-8")
    installed_result = validate_file(target)
    if installed_result.ok:
        _update_index(vault_root)
        _refresh_vault_intelligence(vault_root)
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
    install_parser.add_argument("--allow-existing", action="store_true")

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
            allow_existing=args.allow_existing,
        )

    print(_json_dumps(result.to_dict()))
    if not result.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
