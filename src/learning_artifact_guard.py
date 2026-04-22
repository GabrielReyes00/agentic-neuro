#!/usr/bin/env python3
"""Quality gate and installer for learning workflow vault artifacts.

The heartbeat script is useful for crash-safe checkpoints, but final learning
skills need a richer reviewed artifact. This guard rejects thin checkpoint-only
notes and installs only notes with the skill-specific sections Gabriel expects.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_VAULT_ROOT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
PROJECT_SHADOW_FRAGMENT = "/agentic-neuro/Documents/Obsidian/"

ARTIFACT_CONFIG = {
    "study-session": {
        "dirname": "Review Sessions",
        "tag": "skill/study-session",
        "required_sections": [
            "Session Plan",
            "Question And Answer Log",
            "Component Outcomes",
            "Transfer Challenge",
            "Gaps And Error Metadata",
            "Next Session Priority",
        ],
        "markers": ["Correct:", "Partial:", "Incorrect:", "Transfer", "Next"],
    },
    "oral-boards": {
        "dirname": "Review Sessions",
        "tag": "skill/oral-boards",
        "required_sections": [
            "Opening Stem",
            "Stage Log",
            "Score",
            "Unsafe Issues",
            "Corrected Concepts",
            "Next Practice Targets",
        ],
        "markers": ["Stage", "Score", "Pass", "Borderline", "Fail", "Unsafe"],
    },
    "intern-bootcamp": {
        "dirname": "Review Sessions",
        "tag": "skill/intern-bootcamp",
        "required_sections": [
            "Scenario",
            "Decision Log",
            "Orders",
            "Escalation And Communication",
            "Chief Debrief",
            "Weaknesses And Error Types",
            "Next Targets",
        ],
        "markers": ["Decision", "Order", "Escalation", "SBAR", "I-PASS", "CUS"],
    },
    "rag-workflow": {
        "dirname": "Review Sessions",
        "tag": "skill/rag-workflow",
        "required_sections": [
            "Retrieval Summary",
            "Source Coverage",
            "Synthesis",
            "Gap Check",
            "Drill Or Application Log",
            "Next Targets",
        ],
        "markers": ["Source", "Gap", "Synthesis", "Question", "Application"],
    },
    "debrief": {
        "dirname": "Debriefs",
        "tag": "skill/debrief",
        "required_sections": [
            "Pathology One-Liner",
            "Mechanism",
            "Imaging",
            "Labs",
            "Consults",
            "Preop Course",
            "Intraop Concepts",
            "Postop Course",
            "Red Flags",
            "Intern Priorities",
            "Unknown Unknowns",
            "Related In This Vault",
        ],
        "markers": ["order", "escalat", "red flag", "imaging", "postop"],
    },
}

HEADING_RE = re.compile(r"(?im)^##\s+(.+?)\s*$")
TOP_H1_RE = re.compile(r"^\s*#\s+\S")
BOTTOM_YAML_RE = re.compile(r"(?ms)\n---\s*\n.*\n---\s*\Z")
PLACEHOLDER_RE = re.compile(r"<[^>\n]{2,80}>|\bTBD\b|\bTODO\b", re.IGNORECASE)
WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9/-]*\b")


@dataclass
class ArtifactResult:
    ok: bool
    path: str
    artifact_type: str
    section_count: int
    word_count: int
    errors: list[str]
    warnings: list[str]


def _normalize_heading(text: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9 ]+", " ", text).strip().lower()
    return re.sub(r"\s+", " ", clean)


def _slug_title(title: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", " ", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise ValueError("title produced an empty filename")
    return cleaned


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _has_section(headings: Iterable[str], expected: str) -> bool:
    expected_norm = _normalize_heading(expected)
    return any(
        heading == expected_norm
        or heading.startswith(expected_norm + " ")
        or expected_norm in heading
        for heading in headings
    )


def _bottom_yaml(artifact_type: str, title: str, domain: str, topic: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cfg = ARTIFACT_CONFIG[artifact_type]
    lines = [
        "---",
        f'title: "{title}"',
        f'date: "{today}"',
        f'skill: "{artifact_type}"',
        f'topic: "{topic}"',
        f'domain: "{domain}"',
        "status: complete",
        "tags:",
        "  - type/session" if cfg["dirname"] == "Review Sessions" else "  - type/reference",
        f"  - {cfg['tag']}",
        f"  - domain/{domain.lower().replace(' ', '-')}",
        "  - source/agent",
        "---",
    ]
    return "\n".join(lines) + "\n"


def _target_path(vault_root: Path, artifact_type: str, title: str) -> Path:
    cfg = ARTIFACT_CONFIG[artifact_type]
    return vault_root / cfg["dirname"] / f"{_slug_title(title)}.md"


def _upsert_index(vault_root: Path, artifact_type: str) -> None:
    cfg = ARTIFACT_CONFIG[artifact_type]
    dirname = cfg["dirname"]
    root = vault_root / dirname
    root.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in root.glob("*.md") if p.name != "INDEX.md")
    lines = [f"## {dirname} Index", ""]
    lines.extend(f"- [[{p.stem}]]" for p in files)
    (root / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_path(path: Path, artifact_type: str, vault_root: Path) -> list[str]:
    errors: list[str] = []
    expected_dir = vault_root / ARTIFACT_CONFIG[artifact_type]["dirname"]
    resolved = str(path.resolve())
    if PROJECT_SHADOW_FRAGMENT in resolved:
        errors.append(f"target is a workspace shadow path; write to the real vault under {expected_dir}")
    if not _is_under(path, expected_dir):
        errors.append(f"target must be under {expected_dir}")
    if path.suffix.lower() != ".md":
        errors.append("target must be a markdown file")
    return errors


def validate_content(
    text: str,
    artifact_type: str,
    *,
    min_words: int = 250,
    require_bottom_yaml: bool = True,
) -> tuple[list[str], list[str], dict[str, int]]:
    if artifact_type not in ARTIFACT_CONFIG:
        raise ValueError(f"unknown artifact type: {artifact_type}")

    errors: list[str] = []
    warnings: list[str] = []
    cfg = ARTIFACT_CONFIG[artifact_type]
    stripped = text.lstrip()
    if TOP_H1_RE.match(stripped):
        errors.append("vault artifact must not start with an H1 heading")
    if stripped.startswith("---"):
        errors.append("vault metadata must be bottom YAML, not top YAML")
    if require_bottom_yaml and not BOTTOM_YAML_RE.search(text.rstrip()):
        errors.append("missing bottom YAML metadata block")
    if PLACEHOLDER_RE.search(text):
        errors.append("unresolved placeholder/TODO text remains")

    headings = [_normalize_heading(h) for h in HEADING_RE.findall(text)]
    missing = [s for s in cfg["required_sections"] if not _has_section(headings, s)]
    if missing:
        errors.append("missing required sections: " + ", ".join(missing))

    word_count = len(WORD_RE.findall(text))
    if word_count < min_words:
        errors.append(f"artifact is too thin: {word_count} words; require at least {min_words}")

    marker_hits = sum(1 for marker in cfg["markers"] if marker.lower() in text.lower())
    if marker_hits < 2:
        errors.append("artifact lacks skill-specific evidence markers; likely a generic or checkpoint-only note")

    if "## Checkpoints" in text and len(headings) <= 3:
        errors.append("checkpoint-only note is not an acceptable final artifact")

    return errors, warnings, {"section_count": len(headings), "word_count": word_count}


def validate_file(
    path: Path,
    artifact_type: str,
    *,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    min_words: int = 250,
    require_bottom_yaml: bool = True,
) -> ArtifactResult:
    errors = _validate_path(path, artifact_type, vault_root)
    warnings: list[str] = []
    metrics = {"section_count": 0, "word_count": 0}
    if not path.exists():
        errors.append("target file does not exist")
    elif path.is_dir():
        errors.append("target path is a directory")
    else:
        text = path.read_text(encoding="utf-8")
        content_errors, content_warnings, metrics = validate_content(
            text,
            artifact_type,
            min_words=min_words,
            require_bottom_yaml=require_bottom_yaml,
        )
        errors.extend(content_errors)
        warnings.extend(content_warnings)
    return ArtifactResult(
        ok=not errors,
        path=str(path),
        artifact_type=artifact_type,
        section_count=metrics["section_count"],
        word_count=metrics["word_count"],
        errors=errors,
        warnings=warnings,
    )


def install_draft(
    draft_path: Path,
    artifact_type: str,
    title: str,
    *,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    topic: str = "",
    domain: str = "general",
    min_words: int = 250,
) -> ArtifactResult:
    text = draft_path.read_text(encoding="utf-8").rstrip()
    if not BOTTOM_YAML_RE.search(text):
        text += "\n\n" + _bottom_yaml(artifact_type, _slug_title(title), domain, topic or title)
    errors, warnings, metrics = validate_content(text, artifact_type, min_words=min_words)
    if errors:
        return ArtifactResult(
            ok=False,
            path=str(draft_path),
            artifact_type=artifact_type,
            section_count=metrics["section_count"],
            word_count=metrics["word_count"],
            errors=errors,
            warnings=warnings,
        )

    target = _target_path(vault_root, artifact_type, title)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n", encoding="utf-8")
    _upsert_index(vault_root, artifact_type)
    return validate_file(target, artifact_type, vault_root=vault_root, min_words=min_words)


def _emit(result: ArtifactResult, json_output: bool) -> None:
    if json_output:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
        return
    status = "PASS" if result.ok else "FAIL"
    print(f"{status}: {result.path}")
    print(f"sections={result.section_count} words={result.word_count}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    for error in result.errors:
        print(f"error: {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate/install learning workflow vault artifacts")
    parser.set_defaults(vault_root=str(DEFAULT_VAULT_ROOT), min_words=250, json=False)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--artifact-type", choices=sorted(ARTIFACT_CONFIG), required=True)
        p.add_argument("--vault-root", default=argparse.SUPPRESS)
        p.add_argument("--min-words", type=int, default=argparse.SUPPRESS)
        p.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check-draft")
    p_check.add_argument("--draft", required=True)
    add_common(p_check)

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("path")
    add_common(p_validate)

    p_install = sub.add_parser("install")
    p_install.add_argument("--draft", required=True)
    p_install.add_argument("--title", required=True)
    p_install.add_argument("--topic", default="")
    p_install.add_argument("--domain", default="general")
    add_common(p_install)

    args = parser.parse_args(argv)
    vault_root = Path(args.vault_root)
    if args.command == "check-draft":
        text = Path(args.draft).read_text(encoding="utf-8")
        errors, warnings, metrics = validate_content(
            text,
            args.artifact_type,
            min_words=args.min_words,
            require_bottom_yaml=False,
        )
        result = ArtifactResult(
            ok=not errors,
            path=args.draft,
            artifact_type=args.artifact_type,
            section_count=metrics["section_count"],
            word_count=metrics["word_count"],
            errors=errors,
            warnings=warnings,
        )
    elif args.command == "validate":
        result = validate_file(
            Path(args.path),
            args.artifact_type,
            vault_root=vault_root,
            min_words=args.min_words,
        )
    else:
        result = install_draft(
            Path(args.draft),
            args.artifact_type,
            args.title,
            vault_root=vault_root,
            topic=args.topic,
            domain=args.domain,
            min_words=args.min_words,
        )
    _emit(result, args.json)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
