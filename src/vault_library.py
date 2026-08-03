#!/usr/bin/env python3
"""Integrity and full-text catalog for durable non-Markdown vault files.

This is the binary half of vault intelligence. It fingerprints managed PDFs
and PowerPoints, verifies their container structure, extracts searchable text,
and records backlinks to notes that declare or embed each file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

try:
    from vault_schema import parse_frontmatter
except ModuleNotFoundError:
    from .vault_schema import parse_frontmatter


DEFAULT_VAULT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "vault_index.db"
MANAGED_ROOTS = {
    ("Journal Club", "Sources"),
    ("Presentations", "Decks"),
    ("Study Material", "Sources"),
    ("Reference", "Files"),
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
SUPPORTED_EXTENSIONS = {".pdf", ".pptx", *IMAGE_EXTENSIONS}
WIKILINK_RE = re.compile(r"!?\[\[([^\]|#]+)")


def _utc_iso(timestamp: float | None = None) -> str:
    dt = (
        datetime.fromtimestamp(timestamp, timezone.utc)
        if timestamp is not None
        else datetime.now(timezone.utc)
    )
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _xml_text(payload: bytes) -> str:
    root = ElementTree.fromstring(payload)
    text = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
    return " ".join(text)


def _inspect_pptx(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"CRC failure in {bad_member}")
        names = archive.namelist()
        if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
            raise ValueError("missing required PowerPoint package members")
        slide_names = sorted(
            name
            for name in names
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        )
        note_names = sorted(
            name
            for name in names
            if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", name)
        )
        media_names = [name for name in names if name.startswith("ppt/media/")]
        chunks: list[str] = []
        for name in slide_names + note_names:
            try:
                chunks.append(_xml_text(archive.read(name)))
            except ElementTree.ParseError:
                continue
    return {
        "integrity_status": "pass",
        "integrity_detail": "PowerPoint ZIP package and CRC checks passed",
        "page_count": 0,
        "slide_count": len(slide_names),
        "media_count": len(media_names),
        "content_text": "\n".join(chunk for chunk in chunks if chunk),
    }


def _inspect_pdf(path: Path) -> dict[str, Any]:
    if not path.read_bytes()[:5] == b"%PDF-":
        raise ValueError("missing PDF header")
    try:
        from pypdf import PdfReader
    except ImportError:
        return {
            "integrity_status": "pass",
            "integrity_detail": "PDF header passed; pypdf unavailable for page validation",
            "page_count": 0,
            "slide_count": 0,
            "media_count": 0,
            "content_text": "",
        }
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            chunks.append("")
    return {
        "integrity_status": "pass",
        "integrity_detail": "PDF parsed successfully",
        "page_count": len(reader.pages),
        "slide_count": 0,
        "media_count": 0,
        "content_text": "\n".join(chunks),
    }


def _inspect_image(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".svg":
        ElementTree.parse(path)
        detail = "SVG XML parsed successfully"
    else:
        try:
            from PIL import Image
        except ImportError:
            detail = "Image file present; Pillow unavailable for decode validation"
        else:
            with Image.open(path) as image:
                image.verify()
            detail = "Raster image decoded successfully"
    return {
        "integrity_status": "pass",
        "integrity_detail": detail,
        "page_count": 0,
        "slide_count": 0,
        "media_count": 0,
        "content_text": "",
    }


def _iter_managed_files(vault: Path) -> Iterable[Path]:
    for first, second in sorted(MANAGED_ROOTS):
        root = vault / first / second
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                yield path
    image_root = vault / "z_Images"
    if image_root.is_dir():
        for path in sorted(image_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                yield path


def _candidate_targets(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        found = WIKILINK_RE.findall(value)
        if found:
            yield from found
        elif value.lower().endswith((".pdf", ".pptx")):
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from _candidate_targets(item)


def _normalized_target(target: str) -> str:
    return target.strip().replace("\\", "/").lstrip("/")


def _note_backlinks(vault: Path) -> dict[str, list[str]]:
    links: dict[str, set[str]] = {}
    for note in vault.rglob("*.md"):
        rel = note.relative_to(vault)
        if rel.parts[0].startswith("."):
            continue
        text = note.read_text(encoding="utf-8", errors="replace")
        meta = parse_frontmatter(text)
        targets = list(WIKILINK_RE.findall(text))
        for value in meta.values():
            targets.extend(_candidate_targets(value))
        for raw_target in targets:
            target = _normalized_target(raw_target)
            candidate = vault / target
            if not candidate.is_file() and "/" not in target:
                image_candidate = vault / "z_Images" / target
                if image_candidate.is_file():
                    candidate = image_candidate
            if not candidate.suffix and candidate.with_suffix(".md").is_file():
                candidate = candidate.with_suffix(".md")
            if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS:
                key = str(candidate.relative_to(vault))
                links.setdefault(key, set()).add(str(rel))
    return {key: sorted(value) for key, value in links.items()}


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_files (
            path TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            extension TEXT NOT NULL,
            category TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            modified_at TEXT NOT NULL,
            indexed_at TEXT NOT NULL,
            integrity_status TEXT NOT NULL,
            integrity_detail TEXT NOT NULL,
            page_count INTEGER NOT NULL,
            slide_count INTEGER NOT NULL,
            media_count INTEGER NOT NULL,
            linked_notes_json TEXT NOT NULL,
            content_text TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS vault_files_fts
        USING fts5(path UNINDEXED, name, content_text)
        """
    )


def refresh(vault: Path, db: Path) -> dict[str, Any]:
    db.parent.mkdir(parents=True, exist_ok=True)
    backlinks = _note_backlinks(vault)
    records: list[dict[str, Any]] = []
    for path in _iter_managed_files(vault):
        rel = path.relative_to(vault)
        try:
            if path.suffix.lower() == ".pdf":
                inspected = _inspect_pdf(path)
            elif path.suffix.lower() == ".pptx":
                inspected = _inspect_pptx(path)
            else:
                inspected = _inspect_image(path)
        except Exception as exc:
            inspected = {
                "integrity_status": "fail",
                "integrity_detail": str(exc),
                "page_count": 0,
                "slide_count": 0,
                "media_count": 0,
                "content_text": "",
            }
        records.append(
            {
                "path": str(rel),
                "name": path.name,
                "extension": path.suffix.lower().lstrip("."),
                "category": "/".join(rel.parts[:2]),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
                "modified_at": _utc_iso(path.stat().st_mtime),
                "indexed_at": _utc_iso(),
                "linked_notes_json": json.dumps(backlinks.get(str(rel), [])),
                **inspected,
            }
        )

    with sqlite3.connect(db) as connection:
        _ensure_schema(connection)
        connection.execute("DELETE FROM vault_files")
        connection.execute("DELETE FROM vault_files_fts")
        for record in records:
            connection.execute(
                """
                INSERT INTO vault_files (
                    path, name, extension, category, sha256, size_bytes,
                    modified_at, indexed_at, integrity_status, integrity_detail,
                    page_count, slide_count, media_count, linked_notes_json,
                    content_text
                ) VALUES (
                    :path, :name, :extension, :category, :sha256, :size_bytes,
                    :modified_at, :indexed_at, :integrity_status, :integrity_detail,
                    :page_count, :slide_count, :media_count, :linked_notes_json,
                    :content_text
                )
                """,
                record,
            )
            connection.execute(
                "INSERT INTO vault_files_fts(path, name, content_text) VALUES (?, ?, ?)",
                (record["path"], record["name"], record["content_text"]),
            )

    failures = [item for item in records if item["integrity_status"] != "pass"]
    return {
        "vault": str(vault),
        "database": str(db),
        "file_count": len(records),
        "pdf_count": sum(item["extension"] == "pdf" for item in records),
        "pptx_count": sum(item["extension"] == "pptx" for item in records),
        "image_count": sum(
            f".{item['extension']}" in IMAGE_EXTENSIONS for item in records
        ),
        "linked_file_count": sum(bool(json.loads(item["linked_notes_json"])) for item in records),
        "integrity_failures": [
            {"path": item["path"], "detail": item["integrity_detail"]}
            for item in failures
        ],
    }


def search(db: Path, query: str, limit: int) -> list[dict[str, Any]]:
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT f.path, f.name, f.extension, f.category, f.integrity_status,
                   f.page_count, f.slide_count, f.media_count,
                   f.linked_notes_json,
                   snippet(vault_files_fts, 2, '[', ']', ' … ', 18) AS snippet
            FROM vault_files_fts
            JOIN vault_files AS f ON f.path = vault_files_fts.path
            WHERE vault_files_fts MATCH ?
            ORDER BY bm25(vault_files_fts)
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
    results = [dict(row) for row in rows]
    for result in results:
        result["linked_notes"] = json.loads(result.pop("linked_notes_json"))
    return results


def audit(db: Path) -> dict[str, Any]:
    with sqlite3.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT path, extension, sha256, size_bytes, integrity_status,
                   integrity_detail, page_count, slide_count, media_count,
                   linked_notes_json
            FROM vault_files ORDER BY path
            """
        ).fetchall()
    files = [dict(row) for row in rows]
    for item in files:
        item["linked_notes"] = json.loads(item.pop("linked_notes_json"))
    return {
        "file_count": len(files),
        "integrity_failures": [
            item for item in files if item["integrity_status"] != "pass"
        ],
        "unlinked_files": [item["path"] for item in files if not item["linked_notes"]],
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("refresh")
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    subparsers.add_parser("audit")
    args = parser.parse_args()

    if args.command == "refresh":
        result: Any = refresh(args.vault.expanduser().resolve(), args.db.resolve())
    elif args.command == "search":
        result = search(args.db.resolve(), args.query, args.limit)
    else:
        result = audit(args.db.resolve())
    print(json.dumps(result, indent=2))
    return 1 if isinstance(result, dict) and result.get("integrity_failures") else 0


if __name__ == "__main__":
    raise SystemExit(main())
