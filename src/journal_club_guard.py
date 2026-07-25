#!/usr/bin/env python3
"""Validate and install source-traceable Journal Club vault dossiers."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_VAULT_ROOT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
JOURNAL_CLUB_DIRNAME = "Journal Club"
SOURCES_DIRNAME = "Sources"

REQUIRED_HEADINGS = (
    "Start Here",
    "Clinical Foundation",
    "Essential Concepts for This Paper",
    "Why This Study Exists",
    "Study Architecture",
    "Results That Matter",
    "Figures and Tables Explained",
    "Interpretation",
    "Limitations That Actually Matter",
    "Neurosurgical Relevance",
    "Historical and Current Context",
    "Presentation Core",
    "Faculty Defense",
    "Mastery Objectives",
    "Source Trace",
    "References",
)

REQUIRED_METADATA_KEYS = {
    "aliases",
    "article_title",
    "authors",
    "journal",
    "year",
    "doi",
    "source_pdf",
    "source_package_status",
    "domain",
    "summary",
    "generated",
    "skill",
    "tags",
}

START_LABELS = (
    "Clinical Question",
    "One-Sentence Thesis",
    "Practice Verdict",
    "Thirty-Second Explanation",
)

INTERPRETATION_LABELS = (
    "Authors' Conclusion",
    "Data-Supported Conclusion",
    "Overclaim To Avoid",
)

PRESENTATION_LABELS = (
    "Central Thesis",
    "Data Worth Showing",
    "Discussion Priorities",
    "Spoken Arc",
    "What Not To Say",
)

LIMITATION_LABELS = (
    "Problem",
    "Why It Matters",
    "Threatened Conclusion",
    "Does The Main Finding Survive?",
)

ARTICLE_LOCATOR_RE = re.compile(
    r"\[(?:Article (?:PDF p\.\s*\d+|Table\s+[A-Za-z0-9.-]+|Figure\s+[A-Za-z0-9.-]+|"
    r"Supplement(?:\s+p\.\s*\d+|\s+[A-Za-z0-9.-]+)?|Abstract)|"
    r"Calculated from Article (?:Table|Figure|PDF p\.)[^\]]*)\]",
    re.I,
)

LINK_RE = re.compile(r"\[[^\]]+\]\(https?://[^)]+\)")
QUESTION_RE = re.compile(r"^###\s+Question:\s+\S", re.M | re.I)
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
H3_RE = re.compile(r"^###\s+(.+?)\s*$", re.M)
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)


@dataclass
class ValidationResult:
    path: str
    errors: list[str]
    metrics: dict[str, int] = field(default_factory=dict)
    source_pdf_path: str = ""
    index_path: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "path": self.path,
            "source_pdf_path": self.source_pdf_path,
            "index_path": self.index_path,
            "metrics": self.metrics,
            "errors": self.errors,
        }


def _safe_title(title: str) -> str:
    clean = re.sub(r"\s+", " ", title.strip())
    if not clean or "/" in clean or "\\" in clean or clean in {".", ".."}:
        raise ValueError("title must be a non-empty filename-safe article title")
    if clean.lower().startswith("journal club"):
        raise ValueError("title must not include a journal-club workflow prefix")
    if re.search(r"(?:^|\s)(?:19|20)\d{2}$", clean):
        raise ValueError("title must not end with a date suffix")
    return clean


def _target_path(vault_root: Path, title: str) -> Path:
    return vault_root / JOURNAL_CLUB_DIRNAME / f"{_safe_title(title)}.md"


def _source_target(vault_root: Path, title: str) -> Path:
    return vault_root / JOURNAL_CLUB_DIRNAME / SOURCES_DIRNAME / f"{_safe_title(title)}.pdf"


def _bottom_yaml_bounds(text: str) -> tuple[int, int] | None:
    lines = text.splitlines(keepends=True)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or lines[-1].strip() != "---":
        return None
    close_idx = len(lines) - 1
    open_idx = next(
        (i for i in range(close_idx - 1, -1, -1) if lines[i].strip() == "---"),
        None,
    )
    if open_idx is None:
        return None
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    return offsets[open_idx], offsets[close_idx + 1]


def _parse_bottom_yaml(text: str) -> dict[str, Any]:
    bounds = _bottom_yaml_bounds(text)
    if bounds is None:
        return {}
    block = text[bounds[0] : bounds[1]].splitlines()[1:-1]
    try:
        parsed = yaml.safe_load("\n".join(block))
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _section_body(text: str, heading: str) -> str | None:
    match = re.search(
        rf"^## {re.escape(heading)}\s*$([\s\S]*?)(?=^## |\n---\n|\Z)",
        text,
        flags=re.M,
    )
    return match.group(1).strip() if match else None


def _bold_label_present(text: str, label: str) -> bool:
    return bool(re.search(rf"\*\*{re.escape(label)}:\*\*", text, flags=re.I))


def _metadata_tags(meta: dict[str, Any]) -> set[str]:
    raw = meta.get("tags")
    if isinstance(raw, str):
        return {item.strip() for item in re.split(r"[,\s]+", raw) if item.strip()}
    if isinstance(raw, (list, tuple)):
        return {str(item).strip() for item in raw if str(item).strip()}
    return set()


def _physical_source_error(meta: dict[str, Any], vault_root: Path | None) -> str | None:
    if vault_root is None or meta.get("source_package_status") != "complete":
        return None
    source_pdf = str(meta.get("source_pdf") or "").strip()
    if not source_pdf:
        return "complete source package requires source_pdf metadata"
    if not (vault_root / source_pdf).is_file():
        return f"complete source package PDF is missing: {source_pdf}"
    return None


def validate_text(
    text: str,
    *,
    path: Path,
    vault_root: Path | None = None,
    check_physical_source: bool = False,
) -> ValidationResult:
    errors: list[str] = []
    stripped = text.lstrip()

    if re.search(r"^#\s+\S", text, flags=re.M):
        errors.append("vault note must not contain an H1 heading")
    if stripped.startswith("---\n"):
        errors.append("vault metadata must not be at the top; use bottom YAML only")

    heading_positions: list[int] = []
    for heading in REQUIRED_HEADINGS:
        match = re.search(rf"^## {re.escape(heading)}\s*$", text, flags=re.M)
        if not match:
            errors.append(f"missing required heading: ## {heading}")
        else:
            heading_positions.append(match.start())
    if len(heading_positions) == len(REQUIRED_HEADINGS) and heading_positions != sorted(heading_positions):
        errors.append("required dossier headings are out of dependency order")

    meta = _parse_bottom_yaml(text)
    if not meta:
        errors.append("missing or invalid bottom YAML metadata block")
    else:
        for key in sorted(REQUIRED_METADATA_KEYS - set(meta)):
            errors.append(f"bottom YAML missing key: {key}")
        if meta.get("skill") != "journal-club":
            errors.append("bottom YAML skill must be journal-club")
        status = meta.get("source_package_status")
        if status not in {"complete", "incomplete", "preliminary"}:
            errors.append("source_package_status must be complete, incomplete, or preliminary")
        for key in ("article_title", "authors", "journal", "domain", "summary", "generated"):
            if key in meta and not str(meta.get(key) or "").strip():
                errors.append(f"bottom YAML {key} must not be empty")
        year = str(meta.get("year") or "")
        if year and not re.fullmatch(r"(?:19|20)\d{2}", year):
            errors.append("bottom YAML year must be a four-digit year")
        doi = str(meta.get("doi") or "").strip()
        if doi and not DOI_RE.fullmatch(doi):
            errors.append("bottom YAML doi is not a valid DOI")
        source_pdf = str(meta.get("source_pdf") or "").strip()
        if status == "complete":
            if not source_pdf:
                errors.append("complete source package requires source_pdf metadata")
            elif not re.fullmatch(r"Journal Club/Sources/[^/]+\.pdf", source_pdf):
                errors.append("source_pdf must point to Journal Club/Sources/<Title>.pdf")
        tags = _metadata_tags(meta)
        for tag in ("skill/journal-club", "type/article"):
            if tag not in tags:
                errors.append(f"bottom YAML tags missing: {tag}")
        if check_physical_source:
            physical_error = _physical_source_error(meta, vault_root)
            if physical_error:
                errors.append(physical_error)

    start = _section_body(text, "Start Here") or ""
    for label in START_LABELS:
        if not _bold_label_present(start, label):
            errors.append(f"Start Here missing label: **{label}:**")

    essentials = _section_body(text, "Essential Concepts for This Paper") or ""
    technical_count = len(re.findall(r"\*\*Technical concept:\*\*", essentials, flags=re.I))
    plain_count = len(re.findall(r"\*\*Plain-language meaning:\*\*", essentials, flags=re.I))
    matters_count = len(re.findall(r"\*\*Why it matters here:\*\*", essentials, flags=re.I))
    teaching_triplets = min(technical_count, plain_count, matters_count)
    if teaching_triplets < 2:
        errors.append("Essential Concepts must include at least 2 complete technical translation triplets")

    results = _section_body(text, "Results That Matter") or ""
    header_line = next((line for line in results.splitlines() if line.strip().startswith("|")), "")
    normalized_header = re.sub(r"\s+", " ", header_line.lower())
    for column in ("finding", "reported result", "interpretation", "source"):
        if column not in normalized_header:
            errors.append(f"Results That Matter table missing column: {column}")

    article_locators = len(ARTICLE_LOCATOR_RE.findall(text))
    if meta.get("source_package_status") == "complete" and article_locators < 3:
        errors.append("complete dossiers require at least 3 article source locators")

    interpretation = _section_body(text, "Interpretation") or ""
    for label in INTERPRETATION_LABELS:
        if not _bold_label_present(interpretation, label):
            errors.append(f"Interpretation missing label: **{label}:**")

    limitations = _section_body(text, "Limitations That Actually Matter") or ""
    limitation_subsections = len(H3_RE.findall(limitations))
    complete_limitation_sets = min(
        len(re.findall(rf"\*\*{re.escape(label)}:\*\*", limitations, flags=re.I))
        for label in LIMITATION_LABELS
    ) if limitations else 0
    if limitation_subsections < 2 or complete_limitation_sets < 2:
        errors.append("Limitations That Actually Matter must include at least 2 consequence-framed limitations")

    context = _section_body(text, "Historical and Current Context") or ""
    for subsection in ("At Publication", "Current Context"):
        if not re.search(rf"^### {re.escape(subsection)}\s*$", context, flags=re.M):
            errors.append(f"Historical and Current Context missing: ### {subsection}")

    presentation = _section_body(text, "Presentation Core") or ""
    for label in PRESENTATION_LABELS:
        if not _bold_label_present(presentation, label):
            errors.append(f"Presentation Core missing label: **{label}:**")

    faculty = _section_body(text, "Faculty Defense") or ""
    faculty_questions = len(QUESTION_RE.findall(faculty))
    if faculty_questions < 4:
        errors.append("Faculty Defense must include at least 4 article-specific questions")

    objectives = _section_body(text, "Mastery Objectives") or ""
    mastery_objectives = len(re.findall(r"^\s*[-*]\s+\S", objectives, flags=re.M))
    if mastery_objectives < 5:
        errors.append("Mastery Objectives must include at least 5 testable objectives")

    source_trace = _section_body(text, "Source Trace") or ""
    if not _bold_label_present(source_trace, "Source-Package Limitations"):
        errors.append("Source Trace missing label: **Source-Package Limitations:**")

    references = _section_body(text, "References") or ""
    reference_links = len(LINK_RE.findall(references))
    minimum_links = 1 if meta.get("source_package_status") == "preliminary" else 2
    if reference_links < minimum_links:
        errors.append(f"References must include at least {minimum_links} linked source(s)")

    metrics = {
        "required_headings": sum(
            bool(re.search(rf"^## {re.escape(heading)}\s*$", text, flags=re.M))
            for heading in REQUIRED_HEADINGS
        ),
        "article_locators": article_locators,
        "teaching_triplets": teaching_triplets,
        "consequence_framed_limitations": complete_limitation_sets,
        "faculty_questions": faculty_questions,
        "mastery_objectives": mastery_objectives,
        "reference_links": reference_links,
    }
    return ValidationResult(str(path), errors, metrics=metrics)


def validate_file(
    path: Path,
    *,
    vault_root: Path | None = None,
    check_physical_source: bool = False,
) -> ValidationResult:
    if not path.exists():
        return ValidationResult(str(path), ["file does not exist"])
    return validate_text(
        path.read_text(encoding="utf-8"),
        path=path,
        vault_root=vault_root,
        check_physical_source=check_physical_source,
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _copy_pdf(source: Path, target: Path) -> None:
    if not source.is_file():
        raise ValueError(f"source PDF does not exist: {source}")
    with source.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ValueError(f"source file is not a PDF: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".pdf.tmp")
    shutil.copy2(source, tmp)
    tmp.replace(target)


def _update_index(vault_root: Path) -> Path:
    try:
        import index_builder
    except ModuleNotFoundError:
        from . import index_builder
    return index_builder.write_index(vault_root / JOURNAL_CLUB_DIRNAME, vault_root=vault_root)


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
    source_pdf: Path | None = None,
    overwrite: bool = False,
) -> ValidationResult:
    source_result = validate_file(draft)
    if not source_result.ok:
        return source_result

    safe_title = _safe_title(title)
    target = _target_path(vault_root, safe_title)
    source_target = _source_target(vault_root, safe_title)
    meta = _parse_bottom_yaml(draft.read_text(encoding="utf-8"))
    expected_source_rel = str(source_target.relative_to(vault_root))

    if target.exists() and not overwrite:
        source_result.errors.append(f"target already exists: {target}; pass --overwrite to replace")
        return source_result

    if source_pdf is not None and str(meta.get("source_pdf") or "") != expected_source_rel:
        source_result.errors.append(
            f"bottom YAML source_pdf must equal {expected_source_rel} when installing a PDF"
        )
        return source_result

    if meta.get("source_package_status") == "complete" and source_pdf is None and not source_target.exists():
        source_result.errors.append("complete source package requires --source-pdf or an existing installed source PDF")
        return source_result

    if source_pdf is not None:
        try:
            _copy_pdf(source_pdf, source_target)
        except ValueError as exc:
            source_result.errors.append(str(exc))
            return source_result

    _atomic_write(target, draft.read_text(encoding="utf-8"))
    installed = validate_file(target, vault_root=vault_root, check_physical_source=True)
    installed.source_pdf_path = str(source_target) if source_target.exists() else ""
    if installed.ok:
        index_path = _update_index(vault_root)
        installed.index_path = str(index_path)
        _refresh_vault_intelligence(vault_root)
    return installed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and install Journal Club dossiers")
    parser.add_argument("--vault-root", default=str(DEFAULT_VAULT_ROOT))
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("path")
    validate_parser.add_argument("--json", action="store_true")

    install_parser = sub.add_parser("install")
    install_parser.add_argument("--draft", required=True)
    install_parser.add_argument("--title", required=True)
    install_parser.add_argument("--source-pdf")
    install_parser.add_argument("--overwrite", action="store_true")
    install_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    vault_root = Path(args.vault_root)
    if args.command == "validate":
        result = validate_file(
            Path(args.path),
            vault_root=vault_root,
            check_physical_source=True,
        )
    else:
        result = install_draft(
            Path(args.draft),
            args.title,
            vault_root=vault_root,
            source_pdf=Path(args.source_pdf) if args.source_pdf else None,
            overwrite=args.overwrite,
        )

    print(json.dumps(result.to_dict(), separators=(",", ":")))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
