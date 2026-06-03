#!/usr/bin/env python3
"""Validate and install de-identified Brain Dumps vault artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_VAULT_ROOT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
BRAIN_DUMP_DIRNAME = "Brain Dumps"
REQUIRED_HEADINGS = (
    "De-identified Teaching Trigger",
    "Extraction Map",
    "Priority Takeaways",
    "Reported Teaching",
    "Verified Bridge",
    "Operational Consequence",
    "Clarify Or Verify Locally",
    "Mastery Objectives",
    "Related In This Vault",
    "Sources",
)
REQUIRED_METADATA_KEYS = {
    "tags",
    "generated",
    "skill",
    "provenance",
    "internal_knowledge_used",
}
PROVENANCE_LABELS = (
    "Source-grounded",
    "Service teaching - locally confirm",
    "Clinical knowledge - verify",
)
SOURCE_TIER_LABELS = (
    "Internal textbook RAG",
    "External review",
    "Guideline/formal guidance",
    "Primary study",
)
HIGH_STAKES_SOURCE_RE = re.compile(
    r"\b(?:medication|medications|postoperative|postop|analgesia|analgesic|pain plan|"
    r"opioid|opioids|NSAID|NSAIDs|gabapentin|gabapentinoid|muscle relaxant|"
    r"operative|surgical approach|approach selection|ACDF|lordosis|deformity|threshold)\b",
    re.I,
)
EXTRACTION_MAP_MAX_NODE_WORDS = 8
PRIORITY_TAKEAWAY_MAX_WORDS = 16
PHI_PATTERNS = (
    ("medical record number", re.compile(r"\b(?:mrn|medical record number)\s*[:#-]?\s*\d{4,}\b", re.I)),
    ("named patient", re.compile(r"\b(?:patient name|pt name)\s*:\s*\S+", re.I)),
    ("date of birth", re.compile(r"\b(?:dob|date of birth)\s*[:#-]?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", re.I)),
    ("room or bed identifier", re.compile(r"\b(?:room|rm|bed)\s*[:#-]?\s*[A-Z]?\d{2,}[A-Z]?\b", re.I)),
    (
        "exact clinical timeline date",
        re.compile(
            r"\b(?:admitted|admission|operated|operation|surgery|presented|transferred|discharged|date of service|dos)"
            r"\s*(?:on|:)?\s*\d{1,4}[/-]\d{1,2}[/-]\d{1,4}\b",
            re.I,
        ),
    ),
    ("email address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("phone number", re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")),
)


@dataclass
class ValidationResult:
    path: str
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "path": self.path, "errors": self.errors}


def _safe_title(title: str) -> str:
    clean = re.sub(r"\s+", " ", title.strip())
    if not clean or "/" in clean or "\\" in clean or clean in {".", ".."}:
        raise ValueError("title must be a non-empty filename-safe topic title")
    return clean


def _target_path(vault_root: Path, title: str) -> Path:
    return vault_root / BRAIN_DUMP_DIRNAME / f"{_safe_title(title)}.md"


def _bottom_yaml(text: str) -> str | None:
    match = re.search(r"(?:^|\n)---\n(?P<yaml>[\s\S]*?)\n---\s*$", text)
    return match.group("yaml") if match else None


def validate_text(text: str, *, path: Path) -> ValidationResult:
    errors: list[str] = []
    stripped = text.lstrip()
    if stripped.startswith("# "):
        errors.append("vault note must not start with an H1 heading")
    if stripped.startswith("---\n"):
        errors.append("vault metadata must not be at the top; use bottom YAML only")

    for heading in REQUIRED_HEADINGS:
        if not re.search(rf"^## {re.escape(heading)}\s*$", text, flags=re.M):
            errors.append(f"missing required heading: ## {heading}")

    yaml_text = _bottom_yaml(text)
    if yaml_text is None:
        errors.append("missing bottom YAML metadata block")
    else:
        keys = set(re.findall(r"^([a-z_]+):", yaml_text, flags=re.M))
        for key in sorted(REQUIRED_METADATA_KEYS - keys):
            errors.append(f"bottom YAML missing key: {key}")
        if not re.search(r"^skill:\s*brain-dump\s*$", yaml_text, flags=re.M):
            errors.append("bottom YAML skill must be brain-dump")

    if not any(label in text for label in PROVENANCE_LABELS):
        errors.append("artifact must identify at least one approved provenance tier")

    priority_match = re.search(
        r"^## Priority Takeaways\s*$([\s\S]*?)(?=^## |\n---\n|\Z)", text, flags=re.M
    )
    if priority_match:
        bullets = re.findall(r"^\s*[-*]\s+\S.*$", priority_match.group(1), flags=re.M)
        if not bullets:
            errors.append("Priority Takeaways must include 1 to 3 bullet takeaways")
        if len(bullets) > 3:
            errors.append("Priority Takeaways must include no more than 3 bullets")
        for bullet in bullets:
            words = re.findall(r"\b[\w/+.-]+\b", bullet)
            if len(words) > PRIORITY_TAKEAWAY_MAX_WORDS:
                errors.append(
                    "Priority Takeaways bullets must be succinct "
                    f"({len(words)} words, max {PRIORITY_TAKEAWAY_MAX_WORDS}): {bullet[:80]}"
                )

    extraction_match = re.search(
        r"^## Extraction Map\s*$([\s\S]*?)(?=^## |\n---\n|\Z)", text, flags=re.M
    )
    if extraction_match:
        extraction_body = extraction_match.group(1)
        if "|" in extraction_body:
            errors.append("Extraction Map must use terse '-->' flow lines, not a markdown table")
        flow_lines = [
            line.strip().lstrip("-").strip()
            for line in extraction_body.splitlines()
            if "-->" in line
        ]
        if not flow_lines:
            errors.append("Extraction Map must include at least one '-->' flow line")
        for line in flow_lines:
            if line.count("-->") < 2:
                errors.append(f"extraction flow must have at least 3 nodes: {line[:80]}")
            for node in [part.strip(" `") for part in line.split("-->")]:
                word_count = len(re.findall(r"\b[\w/+.-]+\b", node))
                if word_count > EXTRACTION_MAP_MAX_NODE_WORDS:
                    errors.append(
                        "extraction flow node too long "
                        f"({word_count} words, max {EXTRACTION_MAP_MAX_NODE_WORDS}): {node[:80]}"
                    )

    sources_match = re.search(
        r"^## Sources\s*$([\s\S]*?)(?=^## |\n---\n|\Z)", text, flags=re.M
    )
    if sources_match and not re.search(r"\[[^\]]+\]\(https?://[^)]+\)", sources_match.group(1)):
        errors.append("Sources must include at least one linked external reference")
    if sources_match and not any(f"{label}:" in sources_match.group(1) for label in SOURCE_TIER_LABELS):
        errors.append("Sources must label evidence type for each support item")
    if sources_match:
        for line in sources_match.group(1).splitlines():
            stripped_line = line.strip()
            if stripped_line.startswith("- ") and not any(
                stripped_line.startswith(f"- {label}:") for label in SOURCE_TIER_LABELS
            ):
                errors.append(f"source bullet missing evidence-type label: {stripped_line[:80]}")
    if (
        sources_match
        and HIGH_STAKES_SOURCE_RE.search(text)
        and not any(
            f"{label}:" in sources_match.group(1)
            for label in ("Guideline/formal guidance", "Primary study")
        )
    ):
        errors.append(
            "Medication or operative-strategy artifacts must include Guideline/formal guidance or Primary study support, or explicitly state why unavailable"
        )

    for label, pattern in PHI_PATTERNS:
        if pattern.search(text):
            errors.append(f"possible PHI detected: {label}")

    mastery_match = re.search(
        r"^## Mastery Objectives\s*$([\s\S]*?)(?=^## |\n---\n|\Z)", text, flags=re.M
    )
    if mastery_match:
        objective_count = len(re.findall(r"^\s*[-*]\s+\S+", mastery_match.group(1), flags=re.M))
        if objective_count < 2:
            errors.append("Mastery Objectives must include at least 2 bullet objectives")

    return ValidationResult(str(path), errors)


def validate_file(path: Path) -> ValidationResult:
    if not path.exists():
        return ValidationResult(str(path), ["file does not exist"])
    return validate_text(path.read_text(encoding="utf-8"), path=path)


def _update_index(vault_root: Path) -> None:
    try:
        import index_builder
    except ModuleNotFoundError:  # imported as part of the `src` package
        from . import index_builder
    index_builder.write_index(vault_root / BRAIN_DUMP_DIRNAME, vault_root=vault_root)


def install_draft(draft: Path, title: str, *, vault_root: Path = DEFAULT_VAULT_ROOT) -> ValidationResult:
    source_result = validate_file(draft)
    if not source_result.ok:
        return source_result

    safe_title = _safe_title(title)
    target = _target_path(vault_root, safe_title)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(draft.read_text(encoding="utf-8"), encoding="utf-8")
    installed_result = validate_file(target)
    if installed_result.ok:
        _update_index(vault_root)
    return installed_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and install Brain Dumps vault notes")
    parser.add_argument("--vault-root", default=str(DEFAULT_VAULT_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("path")

    install_parser = sub.add_parser("install")
    install_parser.add_argument("--draft", required=True)
    install_parser.add_argument("--title", required=True)

    args = parser.parse_args()
    vault_root = Path(args.vault_root)
    if args.command == "validate":
        result = validate_file(Path(args.path))
    else:
        result = install_draft(Path(args.draft), args.title, vault_root=vault_root)

    print(json.dumps(result.to_dict(), indent=2))
    if not result.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
