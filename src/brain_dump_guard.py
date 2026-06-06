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
    "Clinical Focus",
    "Priority Takeaways",
    "Clinical & Anatomical Synthesis",
    "Operational Mental Models",
    "Institutional & Local Clarifications",
    "Mastery Objectives",
    "Related In This Vault",
    "References",
)
REQUIRED_METADATA_KEYS = {
    "tags",
    "generated",
    "skill",
    "provenance",
    "internal_knowledge_used",
}
SOURCE_TIER_LABELS = (
    "Internal textbook RAG",
    "External review",
    "Guideline/formal guidance",
    "Primary study",
)
HIGH_STAKES_SOURCE_RE = re.compile(
    r"\b(?:medication|medications|postoperative|postop|analgesia|analgesic|pain plan|"
    r"opioid|opioids|NSAID|NSAIDs|gabapentin|gabapentinoid|muscle relaxant|"
    r"operative|surgical approach|approach selection|ACDF|lordosis|deformity|threshold|"
    r"EVD|external ventricular drain|CSF drainage|drain state|transport protocol)\b",
    re.I,
)
INLINE_CITATION_RE = re.compile(
    r"\((?:"
    r"[A-Z][A-Za-z'`.-]+(?:\s+(?:&|and)\s+[A-Z][A-Za-z'`.-]+|\s+et\s+al\.)?,\s*(?:19|20)\d{2}"
    r"|Youmans\s+&\s+Winn,\s*8th\s+ed\.[^)]*"
    r"|[A-Z][A-Za-z'`.-]+\s+et\s+al\.,\s*(?:19|20)\d{2}"
    r"|PROSPECT,\s*(?:19|20)\d{2}"
    r")\)",
    re.I,
)
HIGH_STAKES_NO_GUIDELINE_RE = re.compile(
    r"\b(?:no|not|none|unable to identify|did not identify|not located|not found)\b"
    r"[\s\S]{0,120}\b(?:guideline|formal guidance|primary stud(?:y|ies)|primary source)\b",
    re.I,
)
PRIORITY_TAKEAWAY_MAX_WORDS = 32


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"))


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


def _section_body(text: str, heading: str) -> str | None:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$([\s\S]*?)(?=^## |\n---\n|\Z)",
        text,
        flags=re.M,
    )
    return match.group(1) if match else None


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

    clinical_focus = _section_body(text, "Clinical Focus")
    if clinical_focus:
        bullets = re.findall(r"^\s*[-*]\s+\S.*$", clinical_focus, flags=re.M)
        if not bullets:
            errors.append("Clinical Focus must include concise bullet topics")

    priority_body = _section_body(text, "Priority Takeaways")
    if priority_body:
        bullets = re.findall(r"^\s*[-*]\s+\S.*$", priority_body, flags=re.M)
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

    synthesis_body = _section_body(text, "Clinical & Anatomical Synthesis")
    if synthesis_body and not INLINE_CITATION_RE.search(synthesis_body):
        errors.append(
            "Clinical & Anatomical Synthesis must include academic inline citations"
        )

    mental_models_body = _section_body(text, "Operational Mental Models")
    if mental_models_body and not re.search(r"^###\s+\S+", mental_models_body, flags=re.M):
        errors.append("Operational Mental Models must include at least one named model subheading")

    references_body = _section_body(text, "References")
    if references_body and not re.search(r"\[[^\]]+\]\(https?://[^)]+\)", references_body):
        errors.append("References must include at least one linked external reference")
    if references_body and not any(f"{label}:" in references_body for label in SOURCE_TIER_LABELS):
        errors.append("References must label evidence type for each support item")
    if references_body:
        for line in references_body.splitlines():
            stripped_line = line.strip()
            if stripped_line.startswith("- ") and not any(
                stripped_line.startswith(f"- {label}:") for label in SOURCE_TIER_LABELS
            ):
                errors.append(f"reference bullet missing evidence-type label: {stripped_line[:80]}")
    if (
        references_body
        and HIGH_STAKES_SOURCE_RE.search(text)
        and not any(
            f"{label}:" in references_body
            for label in ("Guideline/formal guidance", "Primary study")
        )
        and not HIGH_STAKES_NO_GUIDELINE_RE.search(
            _section_body(text, "Institutional & Local Clarifications") or ""
        )
    ):
        errors.append(
            "Medication or operative-strategy artifacts must include Guideline/formal guidance or Primary study support, or explicitly state in Institutional & Local Clarifications why unavailable"
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

    print(_json_dumps(result.to_dict()))
    if not result.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
