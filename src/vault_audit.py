#!/usr/bin/env python3
"""Read-only structural audit for the residency vault."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    from vault_schema import has_legacy_metadata, parse_frontmatter
except ModuleNotFoundError:
    from .vault_schema import has_legacy_metadata, parse_frontmatter


DEFAULT_VAULT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
ARTIFACT_ROOTS = {
    "Shift Debriefs",
    "Concepts",
    "Consults",
    "Journal Club",
    "Operative Guides",
    "Presentations",
    "Reference",
    "Reports",
    "Residency",
    "Study Material",
}
IGNORED_ROOTS = {".agents", ".git", ".obsidian", ".trash", "ACGME Canvases", "_Templates"}
WIKILINK_RE = re.compile(r"!?\[\[([^\]|#]+)")
H1_RE = re.compile(r"^\s*#\s+\S", re.MULTILINE)
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)


def _active_notes(vault: Path) -> list[Path]:
    return [
        path
        for path in sorted(vault.rglob("*.md"))
        if path.relative_to(vault).parts[0] not in IGNORED_ROOTS
    ]


def _file_maps(vault: Path) -> tuple[set[str], dict[str, list[str]]]:
    paths: set[str] = set()
    basenames: dict[str, list[str]] = defaultdict(list)
    for path in vault.rglob("*"):
        if not path.is_file() or path.relative_to(vault).parts[0] in {".git", ".trash"}:
            continue
        rel = path.relative_to(vault).as_posix()
        paths.add(rel.casefold())
        paths.add(str(Path(rel).with_suffix("")).casefold())
        basenames[path.name.casefold()].append(rel)
        basenames[path.stem.casefold()].append(rel)
    return paths, basenames


def _resolve_link(target: str, paths: set[str], basenames: dict[str, list[str]]) -> bool:
    normalized = re.sub(r"\s+", " ", target).strip().replace("\\", "/").lstrip("/")
    if not normalized:
        return True
    if normalized.casefold() in paths:
        return True
    name = Path(normalized).name.casefold()
    return bool(basenames.get(name))


def audit(vault: Path) -> dict[str, Any]:
    paths, basenames = _file_maps(vault)
    notes = _active_notes(vault)
    native_frontmatter_missing: list[str] = []
    legacy_metadata: list[str] = []
    metadata_gaps: list[dict[str, Any]] = []
    h1_notes: list[str] = []
    unresolved: dict[str, set[str]] = defaultdict(set)
    statuses: Counter[str] = Counter()
    artifact_types: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    lineage_failures: list[dict[str, str]] = []
    title_paths: dict[str, list[str]] = defaultdict(list)

    for path in notes:
        rel = path.relative_to(vault)
        text = path.read_text(encoding="utf-8", errors="replace")
        meta = parse_frontmatter(text)
        if rel.parts[0] in ARTIFACT_ROOTS and path.name != "INDEX.md":
            if not meta:
                native_frontmatter_missing.append(str(rel))
            if has_legacy_metadata(text):
                legacy_metadata.append(str(rel))
            missing = [
                key
                for key in ("artifact_type", "status", "domain", "summary")
                if not meta.get(key)
            ]
            if missing:
                metadata_gaps.append({"path": str(rel), "missing": missing})
            if H1_RE.search(
                text[text.find("\n---\n") + 5 :] if text.startswith("---\n") else text
            ):
                h1_notes.append(str(rel))

        if path.name != "INDEX.md":
            statuses[str(meta.get("status") or "unspecified")] += 1
            artifact_types[str(meta.get("artifact_type") or "unspecified")] += 1
            domain = meta.get("domain") or "unspecified"
            if isinstance(domain, list):
                domains.update(str(item) for item in domain)
            else:
                domains[str(domain)] += 1
            title_paths[path.stem.casefold()].append(str(rel))

        linkable_text = FENCED_CODE_RE.sub("", text)
        for target in WIKILINK_RE.findall(linkable_text):
            if not _resolve_link(target, paths, basenames):
                unresolved[target].add(str(rel))

        source_pdf = str(meta.get("source_pdf") or "")
        if source_pdf and not (vault / source_pdf).is_file():
            lineage_failures.append(
                {"path": str(rel), "field": "source_pdf", "target": source_pdf}
            )
        deck_path = str(meta.get("deck_path") or "")
        if deck_path and not (vault / deck_path).is_file():
            lineage_failures.append(
                {"path": str(rel), "field": "deck_path", "target": deck_path}
            )

    duplicate_titles = {
        paths[0].rsplit("/", 1)[-1].removesuffix(".md"): paths
        for paths in title_paths.values()
        if len(paths) > 1
    }
    unresolved_rows = [
        {"target": target, "referenced_by": sorted(referrers)}
        for target, referrers in sorted(unresolved.items(), key=lambda item: item[0].casefold())
    ]
    return {
        "vault": str(vault),
        "active_note_count": len(notes),
        "native_frontmatter_missing": native_frontmatter_missing,
        "legacy_metadata": legacy_metadata,
        "metadata_gaps": metadata_gaps,
        "h1_notes": h1_notes,
        "lineage_failures": lineage_failures,
        "unresolved_wikilinks": unresolved_rows,
        "duplicate_titles": duplicate_titles,
        "status_counts": dict(sorted(statuses.items())),
        "artifact_type_counts": dict(sorted(artifact_types.items())),
        "domain_counts": dict(sorted(domains.items())),
        "ok": not any(
            (
                native_frontmatter_missing,
                legacy_metadata,
                metadata_gaps,
                lineage_failures,
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit(args.vault.expanduser().resolve())
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
