#!/usr/bin/env python3
"""Vault writer for the /grand-rounds presentation skill.

Responsibilities:
  - Write Presentations/Cases/<Title>.md or Presentations/Articles/<Title>.md.
  - Keep metadata YAML at the bottom of the file, never at the top.
  - Reject H1 headings because the filename is the Obsidian title.
  - Upsert Presentations/INDEX.md with one row per presentation.
  - Append rehearsal notes after optional post-creation practice.

The agent is responsible for clinical reasoning, citations, outline prose, and
deck generation. This module only persists presentation artifacts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


DEFAULT_VAULT_ROOT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
DEFAULT_DESKTOP = Path("/Users/gabrielreyes/Desktop")
DEFAULT_SESSIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "Sessions"
PRESENTATIONS_DIRNAME = "Presentations"
CASES_DIRNAME = "Cases"
ARTICLES_DIRNAME = "Articles"
INDEX_FILENAME = "INDEX.md"
INDEX_HEADER = (
    "| Presentation | Mode | Topic | Date | Deck | Summary |\n"
    "|--------------|------|-------|------|------|---------|\n"
)

_BOTTOM_YAML_RE = re.compile(
    r"(?P<body>.*?)(?P<yaml>^---\s*$\n.*?^---\s*$\n?)\Z",
    re.MULTILINE | re.DOTALL,
)
_TOP_H1_RE = re.compile(r"^\s*#\s+\S", re.MULTILINE)
_FORBIDDEN_FILENAME_CHARS_RE = re.compile(r"[^A-Za-z0-9 \-:']")
_ROMAN_NUMERAL_RE = re.compile(r"^(?=[IVXLCDM]+$)[IVXLCDM]+$", re.IGNORECASE)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_IMAGE_PLACEHOLDER_RE = re.compile(r"\b(?:INSERT|PLACEHOLDER):", re.IGNORECASE)
_CITATION_ANCHOR_RE = re.compile(r"\[(?:cite|ref|citation):[^\]]+\]", re.IGNORECASE)
_PHI_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("MRN", re.compile(r"\bMRN\s*[:#]?\s*[A-Za-z0-9-]{4,}\b", re.IGNORECASE)),
    ("DOB", re.compile(r"\b(?:DOB|date of birth)\s*[:#]?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", re.IGNORECASE)),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone number", re.compile(r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")),
    ("email address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("room number", re.compile(r"\b(?:room|rm)\s+\d{2,5}[A-Z]?\b", re.IGNORECASE)),
    (
        "exact clinical date",
        re.compile(
            r"\b(?:admitted|discharged|seen|clinic|surgery|operation|procedure|POD)\s+"
            r"(?:on\s+)?\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
            re.IGNORECASE,
        ),
    ),
)


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _title_case_slug(title: str) -> str:
    cleaned = _FORBIDDEN_FILENAME_CHARS_RE.sub("", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise ValueError("title yields empty filename slug")

    parts: list[str] = []
    for token in cleaned.split(" "):
        if token.isupper() and len(token) >= 2:
            parts.append(token)
        elif _ROMAN_NUMERAL_RE.match(token):
            parts.append(token.upper())
        elif "-" in token:
            parts.append("-".join(_title_case_word(part) for part in token.split("-")))
        else:
            parts.append(_title_case_word(token))
    return " ".join(parts)


def _title_case_word(word: str) -> str:
    if not word:
        return word
    if word.isupper() and len(word) >= 2:
        return word
    if _ROMAN_NUMERAL_RE.match(word):
        return word.upper()
    if word.lower() in {"vs", "v"}:
        return word.lower()
    return word[:1].upper() + word[1:].lower()


def _subdir_for_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized == "case":
        return CASES_DIRNAME
    if normalized in {"article", "journal", "journal-club"}:
        return ARTICLES_DIRNAME
    raise ValueError("mode must be 'case' or 'article'")


def _deck_path_for_title(title: str, desktop: Path = DEFAULT_DESKTOP) -> Path:
    return desktop / f"{_title_case_slug(title)}.pptx"


def _reject_h1(body: str) -> None:
    candidate = body.split("---", 1)[0] if "---" in body else body
    if _TOP_H1_RE.search(candidate):
        raise ValueError(
            "Presentation body must NOT contain an H1; filename is the Obsidian title."
        )


def _section_names(body: str) -> set[str]:
    return {match.group(1).strip().lower() for match in _SECTION_RE.finditer(body)}


def _has_section(sections: set[str], required: str) -> bool:
    needle = required.lower()
    return any(needle in section for section in sections)


def _scan_phi(text: str, mode: str) -> list[str]:
    """Return obvious PHI markers that should not enter presentation artifacts."""
    if mode.strip().lower() != "case":
        return []
    hits: list[str] = []
    for label, pattern in _PHI_PATTERNS:
        if pattern.search(text):
            hits.append(label)
    return hits


def _validate_quality_gate(
    *,
    mode: str,
    body: str,
    citations: list[str],
    image_manifest: list[str],
    presentation_risks: list[str],
    anticipated_questions: list[str],
    slide_titles: list[str],
) -> list[str]:
    """Return quality-gate failures for final presentation artifacts."""
    sections = _section_names(body)
    required = {
        "presentation arc",
        "slide outline and speaker notes",
        "citation list",
        "image manifest",
        "anticipated questions",
        "presentation risks",
        "what not to say",
    }
    failures = [
        f"missing section: {section}"
        for section in sorted(required)
        if not _has_section(sections, section)
    ]

    if mode.strip().lower() == "article":
        article_required = [
            "study design",
            "methods critique",
            "clinical impact",
        ]
        failures.extend(
            f"missing article critique section: {section}"
            for section in sorted(article_required)
            if not _has_section(sections, section)
        )

    if not slide_titles:
        failures.append("slide list is empty")
    if _IMAGE_PLACEHOLDER_RE.search(body) and not image_manifest:
        failures.append("image placeholders exist but image manifest is empty")
    if _CITATION_ANCHOR_RE.search(body) and not citations:
        failures.append("citation anchors exist but citation list is empty")
    if _has_section(sections, "anticipated questions") and not anticipated_questions:
        failures.append("anticipated questions section exists but anticipated question list is empty")
    if _has_section(sections, "presentation risks") and "no major presentation risks identified" not in body.lower():
        if not presentation_risks:
            failures.append("presentation risks section exists but risk list is empty")
    return failures


def _render_bottom_yaml(meta: dict[str, Any]) -> str:
    return "---\n" + yaml.safe_dump(meta, sort_keys=False).strip() + "\n---\n"


def _split_bottom_yaml(text: str) -> tuple[str, dict[str, Any] | None]:
    match = _BOTTOM_YAML_RE.match(text)
    if not match:
        return text, None
    body = match.group("body")
    yaml_block = match.group("yaml")
    inner = re.sub(r"^---\s*$\n", "", yaml_block, count=1, flags=re.MULTILINE)
    inner = re.sub(r"\n?---\s*$\n?", "", inner, count=1, flags=re.MULTILINE)
    try:
        parsed = yaml.safe_load(inner) or {}
    except yaml.YAMLError:
        parsed = None
    return body.rstrip() + "\n", parsed if isinstance(parsed, dict) else None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _table_cell(text: str | None) -> str:
    value = (text or "").replace("\n", " ").replace("|", "\\|").strip()
    return value or "-"


def _ensure_dirs(vault_root: Path) -> None:
    root = vault_root / PRESENTATIONS_DIRNAME
    (root / CASES_DIRNAME).mkdir(parents=True, exist_ok=True)
    (root / ARTICLES_DIRNAME).mkdir(parents=True, exist_ok=True)


def _manifest_path(title: str, sessions_dir: Path = DEFAULT_SESSIONS_DIR) -> Path:
    slug = _title_case_slug(title).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return sessions_dir / f"grand_rounds_{slug}_manifest.json"


def _write_manifest(
    *,
    title: str,
    mode: str,
    topic: str,
    attending_angle: str,
    vault_path: Path,
    deck_path: Path,
    slide_titles: list[str],
    image_manifest: list[str],
    citations: list[str],
    presentation_risks: list[str],
    anticipated_questions: list[str],
    quality_gate_failures: list[str],
    sessions_dir: Path = DEFAULT_SESSIONS_DIR,
) -> Path:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "title": _title_case_slug(title),
        "mode": mode.strip().lower(),
        "topic": topic,
        "attending_angle": attending_angle,
        "vault_path": str(vault_path),
        "deck_path": str(deck_path),
        "slide_titles": slide_titles,
        "image_manifest": image_manifest,
        "citations": citations,
        "presentation_risks": presentation_risks,
        "anticipated_questions": anticipated_questions,
        "quality_gate_failures": quality_gate_failures,
        "updated": _utc_iso(),
    }
    path = _manifest_path(title, sessions_dir)
    _atomic_write(path, json.dumps(manifest, indent=2) + "\n")
    return path


def _default_metadata(
    *,
    title: str,
    mode: str,
    topic: str,
    deck_path: Path,
    domain: str,
    citations: list[str],
    image_count: int,
    attending_angle: str,
    manifest_path: Path | None,
) -> dict[str, Any]:
    mode_lower = mode.strip().lower()
    normalized_mode = "article" if mode_lower in {"journal", "journal-club"} else mode_lower
    return {
        "aliases": [],
        "mode": normalized_mode,
        "topic": topic,
        "domain": domain or "general",
        "deck_path": str(deck_path),
        "attending_angle": attending_angle,
        "manifest_path": str(manifest_path) if manifest_path else "",
        "presentation_date": _utc_today(),
        "created": _utc_today(),
        "updated": _utc_iso(),
        "citation_count": len(citations),
        "image_placeholder_count": image_count,
        "tags": [
            "skill/grand-rounds",
            f"domain/{(domain or 'general').lower().replace(' ', '-')}",
            f"type/{'case' if normalized_mode == 'case' else 'article'}",
            "source/agent",
        ],
    }


def create_presentation(
    *,
    vault_root: Path,
    mode: str,
    title: str,
    body: str,
    topic: str,
    domain: str = "general",
    summary: str = "",
    deck_path: Path | None = None,
    citations: list[str] | None = None,
    image_count: int = 0,
    attending_angle: str = "",
    slide_titles: list[str] | None = None,
    image_manifest: list[str] | None = None,
    presentation_risks: list[str] | None = None,
    anticipated_questions: list[str] | None = None,
    require_quality_gate: bool = False,
    sessions_dir: Path = DEFAULT_SESSIONS_DIR,
    overwrite: bool = False,
) -> Path:
    """Create a presentation markdown note and upsert the global index."""
    _reject_h1(body)
    phi_hits = _scan_phi(body, mode)
    if phi_hits:
        raise ValueError(
            "Presentation body appears to contain PHI markers: "
            + ", ".join(sorted(set(phi_hits)))
            + ". Scrub identifiers before writing."
        )
    _ensure_dirs(vault_root)

    subdir = _subdir_for_mode(mode)
    clean_title = _title_case_slug(title)
    final_deck_path = deck_path or _deck_path_for_title(clean_title)
    out_path = vault_root / PRESENTATIONS_DIRNAME / subdir / f"{clean_title}.md"
    if out_path.exists() and not overwrite:
        raise FileExistsError(f"{out_path} already exists; pass --overwrite to replace")

    citation_list = citations or []
    slide_title_list = slide_titles or []
    image_manifest_list = image_manifest or []
    risk_list = presentation_risks or []
    anticipated_question_list = anticipated_questions or []
    quality_gate_failures = _validate_quality_gate(
        mode=mode,
        body=body,
        citations=citation_list,
        image_manifest=image_manifest_list,
        presentation_risks=risk_list,
        anticipated_questions=anticipated_question_list,
        slide_titles=slide_title_list,
    )
    if require_quality_gate and quality_gate_failures:
        raise ValueError("Quality gate failed: " + "; ".join(quality_gate_failures))

    manifest_path = _write_manifest(
        title=clean_title,
        mode=mode,
        topic=topic,
        attending_angle=attending_angle,
        vault_path=out_path,
        deck_path=final_deck_path,
        slide_titles=slide_title_list,
        image_manifest=image_manifest_list,
        citations=citation_list,
        presentation_risks=risk_list,
        anticipated_questions=anticipated_question_list,
        quality_gate_failures=quality_gate_failures,
        sessions_dir=sessions_dir,
    )
    meta = _default_metadata(
        title=clean_title,
        mode=mode,
        topic=topic,
        deck_path=final_deck_path,
        domain=domain,
        citations=citation_list,
        image_count=image_count,
        attending_angle=attending_angle,
        manifest_path=manifest_path,
    )
    if summary:
        meta["summary"] = summary

    content = body.rstrip() + "\n\n" + _render_bottom_yaml(meta)
    _atomic_write(out_path, content)
    upsert_index(
        vault_root=vault_root,
        title=clean_title,
        mode=mode,
        topic=topic,
        deck_path=final_deck_path,
        summary=summary,
        relative_path=out_path.relative_to(vault_root),
    )
    return out_path


def append_rehearsal_notes(
    *,
    vault_root: Path,
    target_path: Path,
    notes: str,
    weak_spots: list[str] | None = None,
) -> Path:
    """Append or replace a dated rehearsal notes section in a presentation note."""
    _reject_h1(notes)
    abs_path = target_path if target_path.is_absolute() else vault_root / target_path
    if not abs_path.exists():
        raise FileNotFoundError(f"presentation note not found: {abs_path}")

    original = abs_path.read_text(encoding="utf-8")
    body, meta = _split_bottom_yaml(original)
    if meta is None:
        raise ValueError("presentation note is missing bottom YAML metadata")

    date = _utc_today()
    section_lines = [f"## Rehearsal Notes - {date}", "", notes.strip()]
    if weak_spots:
        section_lines.extend(["", "### Weak Spots"])
        section_lines.extend(f"- {spot}" for spot in weak_spots if spot.strip())

    meta["updated"] = _utc_iso()
    meta["last_rehearsal"] = date

    content = body.rstrip() + "\n\n" + "\n".join(section_lines).rstrip()
    content += "\n\n" + _render_bottom_yaml(meta)
    _atomic_write(abs_path, content)
    return abs_path


def _read_index_rows(index_path: Path) -> list[str]:
    if not index_path.exists():
        return []
    rows: list[str] = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        stripped = line.strip()
        if stripped.startswith("| Presentation") or stripped.startswith("|--------------"):
            continue
        rows.append(line)
    return rows


def upsert_index(
    *,
    vault_root: Path,
    title: str,
    mode: str,
    topic: str,
    deck_path: Path,
    summary: str,
    relative_path: Path | None = None,
    date: str | None = None,
) -> Path:
    """Insert or replace a row in Presentations/INDEX.md."""
    _ensure_dirs(vault_root)
    mode_lower = mode.strip().lower()
    normalized_mode = "article" if mode_lower in {"journal", "journal-club"} else mode_lower
    rel = relative_path or (
        Path(PRESENTATIONS_DIRNAME)
        / _subdir_for_mode(normalized_mode)
        / f"{_title_case_slug(title)}.md"
    )
    index_path = vault_root / PRESENTATIONS_DIRNAME / INDEX_FILENAME
    existing = _read_index_rows(index_path)
    link_target = str(rel.with_suffix(""))
    marker = f"[[{link_target}]]"
    deck_label = Path(deck_path).name
    new_row = (
        f"| {marker} | {normalized_mode} | {_table_cell(topic)} | "
        f"{date or _utc_today()} | [{_table_cell(deck_label)}](<{deck_path}>) | "
        f"{_table_cell(summary)} |"
    )
    kept = [row for row in existing if marker not in row]
    kept.append(new_row)
    kept.sort()
    content = INDEX_HEADER + "\n".join(kept) + "\n"
    _atomic_write(index_path, content)
    return index_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Writer for /grand-rounds presentation notes.")
    parser.add_argument(
        "--action",
        required=True,
        choices=["create", "append-rehearsal", "upsert-index"],
    )
    parser.add_argument("--vault-root", default=str(DEFAULT_VAULT_ROOT))
    parser.add_argument("--sessions-dir", default=str(DEFAULT_SESSIONS_DIR))
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--overwrite", action="store_true")

    parser.add_argument("--mode", default=None, help="case or article")
    parser.add_argument("--title", default=None)
    parser.add_argument("--topic", default=None)
    parser.add_argument("--domain", default="general")
    parser.add_argument("--summary", default="")
    parser.add_argument("--deck-path", default=None)
    parser.add_argument("--attending-angle", default="")
    parser.add_argument("--citations", default="", help="Semicolon-separated citation labels.")
    parser.add_argument("--image-count", type=int, default=0)
    parser.add_argument("--slide-titles", default="", help="Semicolon-separated slide titles.")
    parser.add_argument("--image-manifest", default="", help="Semicolon-separated image placeholders.")
    parser.add_argument("--presentation-risks", default="", help="Semicolon-separated presentation risks.")
    parser.add_argument("--anticipated-questions", default="", help="Semicolon-separated anticipated questions.")
    parser.add_argument(
        "--require-quality-gate",
        action="store_true",
        help="Reject create if required sections/lists are missing.",
    )
    parser.add_argument("--body", default=None)
    parser.add_argument("--content", default=None, help="Alias for --body.")

    parser.add_argument("--target", default=None, help="Vault-relative or absolute note path.")
    parser.add_argument("--notes", default=None, help="Rehearsal notes to append.")
    parser.add_argument("--weak-spots", default="", help="Semicolon-separated rehearsal weak spots.")

    args = parser.parse_args(argv)
    vault_root = Path(args.vault_root)
    sessions_dir = Path(args.sessions_dir)
    body = args.body or args.content

    def emit(result: dict[str, Any]) -> None:
        if not args.quiet:
            print(json.dumps(result))

    if args.action == "create":
        if not args.mode:
            parser.error("--action create requires --mode")
        if not args.title:
            parser.error("--action create requires --title")
        if not args.topic:
            parser.error("--action create requires --topic")
        if not body:
            parser.error("--action create requires --body (or --content)")
        citations = [c.strip() for c in args.citations.split(";") if c.strip()]
        slide_titles = [s.strip() for s in args.slide_titles.split(";") if s.strip()]
        image_manifest = [i.strip() for i in args.image_manifest.split(";") if i.strip()]
        presentation_risks = [r.strip() for r in args.presentation_risks.split(";") if r.strip()]
        anticipated_questions = [q.strip() for q in args.anticipated_questions.split(";") if q.strip()]
        path = create_presentation(
            vault_root=vault_root,
            mode=args.mode,
            title=args.title,
            body=body,
            topic=args.topic,
            domain=args.domain,
            summary=args.summary,
            deck_path=Path(args.deck_path).expanduser() if args.deck_path else None,
            citations=citations,
            image_count=args.image_count,
            attending_angle=args.attending_angle,
            slide_titles=slide_titles,
            image_manifest=image_manifest,
            presentation_risks=presentation_risks,
            anticipated_questions=anticipated_questions,
            require_quality_gate=args.require_quality_gate,
            sessions_dir=sessions_dir,
            overwrite=args.overwrite,
        )
        emit({"ok": True, "action": "create", "path": str(path)})
    elif args.action == "append-rehearsal":
        if not args.target:
            parser.error("--action append-rehearsal requires --target")
        if not args.notes:
            parser.error("--action append-rehearsal requires --notes")
        weak_spots = [s.strip() for s in args.weak_spots.split(";") if s.strip()]
        path = append_rehearsal_notes(
            vault_root=vault_root,
            target_path=Path(args.target),
            notes=args.notes,
            weak_spots=weak_spots,
        )
        emit({"ok": True, "action": "append-rehearsal", "path": str(path)})
    elif args.action == "upsert-index":
        if not args.mode:
            parser.error("--action upsert-index requires --mode")
        if not args.title:
            parser.error("--action upsert-index requires --title")
        if not args.topic:
            parser.error("--action upsert-index requires --topic")
        deck_path = Path(args.deck_path).expanduser() if args.deck_path else _deck_path_for_title(args.title)
        path = upsert_index(
            vault_root=vault_root,
            title=args.title,
            mode=args.mode,
            topic=args.topic,
            deck_path=deck_path,
            summary=args.summary,
        )
        emit({"ok": True, "action": "upsert-index", "path": str(path)})
    return 0


if __name__ == "__main__":
    from _env_guard import check_environment

    check_environment("grand_rounds_writer.py")
    sys.exit(main())
