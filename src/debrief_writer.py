#!/usr/bin/env python3
"""Vault writer for the /debrief skill.

Responsibilities:
  - Write a new Debriefs/<Title>.md when no merge target exists.
  - Append a dated encounter section to an existing Debriefs file when a
    merge target was chosen by the assembler (or --merge-into is passed).
  - Keep metadata YAML at the BOTTOM of the file (never top) per vault rules.
  - Never emit an H1 title (filename is the title in Obsidian).
  - Upsert Debriefs/INDEX.md with one row per debrief.

The LLM (Gemini or Claude) is responsible for generating the prose body;
this writer only persists and merges. Deterministic, no LLM calls.
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
DEBRIEFS_DIRNAME = "Debriefs"
INDEX_FILENAME = "INDEX.md"
INDEX_HEADER = (
    "| Debrief | Pathology | Domain | Last Encounter | Encounters | Summary |\n"
    "|---------|-----------|--------|----------------|------------|---------|\n"
)


# Match the trailing YAML metadata block (project standard: YAML at bottom).
_BOTTOM_YAML_RE = re.compile(
    r"(?P<body>.*?)(?P<yaml>^---\s*$\n.*?^---\s*$\n?)\Z",
    re.MULTILINE | re.DOTALL,
)

# Forbidden: H1 at top of file (vault rule).
_TOP_H1_RE = re.compile(r"^\s*#\s+\S", re.MULTILINE)


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _title_case_slug(pathology: str) -> str:
    """Title-case filename slug — no underscores, no dates, no H1."""
    cleaned = re.sub(r"[^A-Za-z0-9 \-]", "", pathology).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise ValueError("pathology yields empty filename slug")
    # Title-case words; keep uppercase tokens (e.g. TLIF, ACA) intact.
    parts = []
    for word in cleaned.split(" "):
        if word.isupper() and len(word) >= 2:
            parts.append(word)
        else:
            parts.append(word.capitalize())
    return " ".join(parts)


def _reject_h1(body: str) -> None:
    if _TOP_H1_RE.search(body.split("---", 1)[0] if "---" in body else body):
        raise ValueError(
            "Debrief body must NOT contain an H1 — filename is the title in Obsidian."
        )


def _render_bottom_yaml(meta: dict[str, Any]) -> str:
    return "---\n" + yaml.safe_dump(meta, sort_keys=False).strip() + "\n---\n"


def _default_metadata(
    pathology: str,
    title: str,
    domain: str | None,
    key_terms: list[str],
    encounters: int = 1,
    last_encounter: str | None = None,
) -> dict[str, Any]:
    last = last_encounter or _utc_today()
    return {
        "aliases": [],
        "pathology": pathology,
        "domain": domain or "general",
        "encounters": encounters,
        "last_encounter": last,
        "created": _utc_today(),
        "key_terms": key_terms or [],
        "tags": [
            "skill/debrief",
            f"domain/{(domain or 'general').lower().replace(' ', '-')}",
            "type/reference",
            "source/agent",
        ],
    }


# ── File I/O ─────────────────────────────────────────────────────────────────


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _split_bottom_yaml(text: str) -> tuple[str, dict[str, Any] | None]:
    """Split a vault file into (body, parsed_yaml). Returns (text, None) if no bottom YAML."""
    m = _BOTTOM_YAML_RE.match(text)
    if not m:
        return text, None
    body = m.group("body")
    yaml_block = m.group("yaml")
    # Strip --- fences.
    inner = re.sub(r"^---\s*$\n", "", yaml_block, count=1, flags=re.MULTILINE)
    inner = re.sub(r"\n?---\s*$\n?", "", inner, count=1, flags=re.MULTILINE)
    try:
        parsed = yaml.safe_load(inner) or {}
    except yaml.YAMLError:
        parsed = None
    return body.rstrip() + "\n", parsed if isinstance(parsed, dict) else None


# ── Public API ───────────────────────────────────────────────────────────────


def create_debrief(
    vault_root: Path,
    pathology: str,
    body: str,
    domain: str | None = None,
    key_terms: list[str] | None = None,
    summary: str | None = None,
    title: str | None = None,
) -> Path:
    """Write a new Debriefs/<Title>.md. Errors if the file already exists."""
    _reject_h1(body)
    title = title or _title_case_slug(pathology)
    out_path = vault_root / DEBRIEFS_DIRNAME / f"{title}.md"
    if out_path.exists():
        raise FileExistsError(f"{out_path} already exists; use merge_into_debrief")
    meta = _default_metadata(pathology, title, domain, key_terms or [])
    if summary:
        meta["summary"] = summary
    content = body.rstrip() + "\n\n" + _render_bottom_yaml(meta)
    _atomic_write(out_path, content)
    return out_path


def merge_into_debrief(
    vault_root: Path,
    target_path: Path,
    body: str,
    encounter_label: str | None = None,
    new_key_terms: list[str] | None = None,
    summary_update: str | None = None,
) -> Path:
    """Append a new dated encounter section to an existing debrief.

    The appended section header is `## Encounter — <YYYY-MM-DD> — <label>`.
    Metadata at the bottom is updated: encounters += 1, last_encounter = today,
    key_terms merged.
    """
    _reject_h1(body)
    abs_path = target_path if target_path.is_absolute() else vault_root / target_path
    if not abs_path.exists():
        raise FileNotFoundError(f"merge target not found: {abs_path}")

    original = _read_text(abs_path)
    body_text, meta = _split_bottom_yaml(original)
    if meta is None:
        # File has no bottom YAML — treat the whole file as body and
        # synthesize metadata (defensive: should not happen for agent-written files).
        body_text = original.rstrip() + "\n"
        meta = _default_metadata(
            pathology=abs_path.stem,
            title=abs_path.stem,
            domain=None,
            key_terms=[],
            encounters=0,
        )

    date = _utc_today()
    header = f"## Encounter — {date}"
    if encounter_label:
        header += f" — {encounter_label}"

    appended_body = body_text.rstrip() + "\n\n" + header + "\n\n" + body.strip() + "\n"

    # Update metadata.
    meta["encounters"] = int(meta.get("encounters", 0) or 0) + 1
    meta["last_encounter"] = date
    if new_key_terms:
        existing_terms = set(meta.get("key_terms") or [])
        merged_terms = existing_terms.union(new_key_terms)
        # Preserve deterministic order: existing first, then new alphabetized.
        ordered = list(meta.get("key_terms") or []) + sorted(
            merged_terms - set(meta.get("key_terms") or [])
        )
        meta["key_terms"] = ordered
    if summary_update:
        meta["summary"] = summary_update

    content = appended_body + "\n" + _render_bottom_yaml(meta)
    _atomic_write(abs_path, content)
    return abs_path


# ── INDEX.md upsert ──────────────────────────────────────────────────────────


def _read_index_rows(index_path: Path) -> list[str]:
    """Return existing data rows from INDEX.md (skipping header + separator)."""
    if not index_path.exists():
        return []
    lines = index_path.read_text(encoding="utf-8").splitlines()
    data_rows: list[str] = []
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        # Skip header + alignment separator.
        if set(line.replace("|", "").replace(" ", "")) <= {"-", ":"}:
            continue
        if line.strip().startswith("| Debrief") or line.strip().startswith("|Debrief"):
            continue
        data_rows.append(line)
    return data_rows


def upsert_index(
    vault_root: Path,
    title: str,
    pathology: str,
    domain: str,
    last_encounter: str,
    encounters: int,
    summary: str,
) -> Path:
    """Insert or replace a row in Debriefs/INDEX.md."""
    index_path = vault_root / DEBRIEFS_DIRNAME / INDEX_FILENAME
    existing = _read_index_rows(index_path)
    new_row = (
        f"| [[{DEBRIEFS_DIRNAME}/{title}|{title}]] | {pathology} | {domain} | "
        f"{last_encounter} | {encounters} | {summary} |"
    )
    marker = f"[[{DEBRIEFS_DIRNAME}/{title}|"
    kept = [row for row in existing if marker not in row]
    kept.append(new_row)
    kept.sort()
    content = INDEX_HEADER + "\n".join(kept) + "\n"
    _atomic_write(index_path, content)
    return index_path


# ── CLI ──────────────────────────────────────────────────────────────────────
# Flat --action flag instead of subcommands: LLMs reliably pass named flags
# but often mis-order positional subcommands, causing argparse "invalid choice"
# errors. --content is accepted as an alias for --body for the same reason.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Writer for /debrief vault notes (new + merge-append).",
    )
    parser.add_argument(
        "--action", required=True,
        choices=["create", "merge", "upsert-index"],
        help="Operation: create | merge | upsert-index",
    )
    # Shared flags
    parser.add_argument("--vault-root", default=str(DEFAULT_VAULT_ROOT))
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress stdout success message (errors still go to stderr).")

    # create / merge shared
    _body_group = parser.add_mutually_exclusive_group()
    _body_group.add_argument("--body", default=None, help="Markdown body (no H1).")
    _body_group.add_argument("--content", default=None,
                             help="Alias for --body (accepted for LLM ergonomics).")
    parser.add_argument("--pathology", default=None)
    parser.add_argument("--domain", default=None)
    parser.add_argument("--key-terms", default="", help="Comma-separated key terms.")
    parser.add_argument("--summary", default=None)
    parser.add_argument("--title", default=None, help="Override Title Case slug (create only).")

    # merge only
    parser.add_argument("--target", default=None,
                        help="Vault-relative or absolute path to existing debrief (merge only).")
    parser.add_argument("--label", default=None,
                        help="Short encounter label appended to section header (merge only).")

    # upsert-index only
    parser.add_argument("--last-encounter", default=None)
    parser.add_argument("--encounters", type=int, default=None)

    args = parser.parse_args(argv)
    vault_root = Path(args.vault_root)

    # Resolve --content alias
    body = args.body or args.content

    def _emit(result: dict) -> None:
        if not args.quiet:
            print(json.dumps(result))

    if args.action == "create":
        if not body:
            parser.error("--action create requires --body (or --content)")
        if not args.pathology:
            parser.error("--action create requires --pathology")
        key_terms = [t.strip() for t in args.key_terms.split(",") if t.strip()]
        path = create_debrief(
            vault_root=vault_root,
            pathology=args.pathology,
            body=body,
            domain=args.domain,
            key_terms=key_terms,
            summary=args.summary,
            title=args.title,
        )
        _emit({"ok": True, "action": "create", "path": str(path)})
    elif args.action == "merge":
        if not body:
            parser.error("--action merge requires --body (or --content)")
        if not args.target:
            parser.error("--action merge requires --target")
        key_terms = [t.strip() for t in args.key_terms.split(",") if t.strip()]
        path = merge_into_debrief(
            vault_root=vault_root,
            target_path=Path(args.target),
            body=body,
            encounter_label=args.label,
            new_key_terms=key_terms,
            summary_update=args.summary,
        )
        _emit({"ok": True, "action": "merge", "path": str(path)})
    elif args.action == "upsert-index":
        if not args.title:
            parser.error("--action upsert-index requires --title")
        if not args.pathology:
            parser.error("--action upsert-index requires --pathology")
        if not args.domain:
            parser.error("--action upsert-index requires --domain")
        if not args.last_encounter:
            parser.error("--action upsert-index requires --last-encounter")
        if args.encounters is None:
            parser.error("--action upsert-index requires --encounters")
        if not args.summary:
            parser.error("--action upsert-index requires --summary")
        path = upsert_index(
            vault_root=vault_root,
            title=args.title,
            pathology=args.pathology,
            domain=args.domain,
            last_encounter=args.last_encounter,
            encounters=args.encounters,
            summary=args.summary,
        )
        _emit({"ok": True, "action": "upsert-index", "path": str(path)})
    return 0


if __name__ == "__main__":
    from _env_guard import check_environment
    check_environment("debrief_writer.py")
    sys.exit(main())
