"""Shared, domain-grouped INDEX.md renderer for the Obsidian vault.

This is a tool, not an LLM surface: it only reads files, extracts bottom-YAML
metadata, and renders deterministic markdown. No reasoning happens here.

Every folder index is rendered the same way: files are grouped under H2 domain
headings (canonical order), each file shown as a bold wikilink with its one-line
summary on an indented line beneath. A file is listed once, under its primary
domain; any further domains are noted inline as `· also: X`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

DEFAULT_VAULT_ROOT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")

# Folder -> whether files live in subdirectories (recursive glob).
INDEX_FOLDERS: dict[str, bool] = {
    "Reports": False,
    "Study Material": False,
    "Operative Guides": False,
    "Brain Dumps": False,
    "Concepts": False,
    "Consults": False,
    "Reference": False,
    "Presentations": True,
}

# Canonical display order. The first matching domain in this list becomes a
# file's primary (heading) domain; the rest trail as `· also:` notes.
CANONICAL_DOMAINS: list[tuple[str, set[str]]] = [
    ("Vascular", {"vascular", "cerebrovascular"}),
    ("Skull Base", {"skull-base", "skullbase"}),
    ("Tumor", {"tumor", "tumour", "oncology", "neuro-oncology"}),
    ("Spine", {"spine", "spinal"}),
    ("Trauma", {"trauma"}),
    (
        "Neurocritical Care",
        {
            "neurocritical-care",
            "neurocritical",
            "neurocrit",
            "neuro-critical-care",
            "neuro-icu",
            "critical-care",
        },
    ),
    ("Functional", {"functional"}),
    ("Pediatric", {"pediatric", "paediatric", "peds"}),
    ("Peripheral Nerve", {"peripheral-nerve"}),
    ("Anatomy", {"anatomy"}),
    ("General", {"general"}),
]
UNCATEGORIZED = "Uncategorized"

_ALIAS_TO_DISPLAY = {alias: display for display, aliases in CANONICAL_DOMAINS for alias in aliases}
_DOMAIN_ORDER = {display: i for i, (display, _) in enumerate(CANONICAL_DOMAINS)}
_DOMAIN_ORDER[UNCATEGORIZED] = len(CANONICAL_DOMAINS)

def _normalize_domain(raw: str) -> str | None:
    """Map a raw domain token to its canonical display name, or None."""
    token = raw.strip().lower()
    if token.startswith("domain/"):
        token = token[len("domain/") :]
    token = token.replace(" ", "-").replace("_", "-")
    return _ALIAS_TO_DISPLAY.get(token)


def _split_domain_field(value: Any) -> list[str]:
    """A domain field may be a list, or a string with '/' or ',' separators."""
    items: list[str] = []
    if isinstance(value, (list, tuple)):
        for entry in value:
            items.extend(re.split(r"[/,]", str(entry)))
    elif value is not None:
        items.extend(re.split(r"[/,]", str(value)))
    return [i for i in (s.strip() for s in items) if i]


def _domains_from_meta(meta: dict[str, Any]) -> list[str]:
    """Canonical, de-duplicated domains for a file, in canonical order."""
    raw_tokens = list(_split_domain_field(meta.get("domain")))
    tags = meta.get("tags")
    if isinstance(tags, (list, tuple)):
        raw_tokens.extend(str(t) for t in tags if str(t).strip().lower().startswith("domain/"))
    elif isinstance(tags, str):
        raw_tokens.extend(t for t in re.split(r"[,\s]+", tags) if t.lower().startswith("domain/"))

    found: list[str] = []
    for token in raw_tokens:
        display = _normalize_domain(token)
        if display and display not in found:
            found.append(display)
    found.sort(key=lambda d: _DOMAIN_ORDER[d])
    return found


def _parse_bottom_yaml(text: str) -> dict[str, Any]:
    """Parse the final fenced YAML block at the bottom of a vault note.

    Located by lines (last `---` line = close, nearest preceding `---` = open)
    so a thematic-break `---` or a stray separator earlier in the body does not
    swallow the real metadata block.
    """
    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or lines[-1].strip() != "---":
        return {}
    close = len(lines) - 1
    open_idx = next((i for i in range(close - 1, -1, -1) if lines[i].strip() == "---"), None)
    if open_idx is None:
        return {}
    inner = "\n".join(lines[open_idx + 1 : close])
    try:
        parsed = yaml.safe_load(inner)
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _display_from_meta(meta: dict[str, Any], stem: str) -> str:
    # The filename is the canonical title in Obsidian; only an explicit
    # `display:` overrides it. `aliases` are search terms, not display titles.
    display = meta.get("display")
    if isinstance(display, str) and display.strip():
        return display.strip()
    return stem


def extract_meta(path: Path, vault_root: Path) -> dict[str, Any]:
    """Extract grouping metadata from one vault note's bottom YAML."""
    text = path.read_text(encoding="utf-8")
    meta = _parse_bottom_yaml(text)
    domains = _domains_from_meta(meta)
    summary = meta.get("summary")
    summary = summary.strip() if isinstance(summary, str) else ""
    created = meta.get("created") or meta.get("date")
    created = str(created).strip() if created else ""
    rel = path.relative_to(vault_root).with_suffix("")
    display = _display_from_meta(meta, path.stem)
    return {
        "link_target": str(rel),
        "display": display,
        "summary": summary,
        "domains": domains,
        "primary": domains[0] if domains else UNCATEGORIZED,
        "secondary": domains[1:],
        "created": created,
        "extras": _inline_extras(meta),
        "sort_key": display.lower(),
    }


def _inline_extras(meta: dict[str, Any]) -> list[str]:
    """Optional inline tokens for richer notes (e.g. Presentations: mode, deck)."""
    extras: list[str] = []
    mode = meta.get("mode")
    if isinstance(mode, str) and mode.strip():
        extras.append(mode.strip())
    deck = meta.get("deck_path")
    if isinstance(deck, str) and deck.strip():
        extras.append(f"[{Path(deck).name}](<{deck.strip()}>)")
    return extras


def _render_entry(entry: dict[str, Any]) -> str:
    line = f"- **[[{entry['link_target']}|{entry['display']}]]**"
    notes: list[str] = list(entry.get("extras", []))
    if entry["secondary"]:
        notes.append("also: " + ", ".join(entry["secondary"]))
    if entry["created"]:
        notes.append(entry["created"])
    note_str = ("· " + " · ".join(notes)) if notes else ""
    # With a summary, notes trail it on an indented second line. Without one,
    # the notes ride inline on the title line so there is no orphan detail line.
    if entry["summary"]:
        detail = entry["summary"] + ((" " + note_str) if note_str else "")
        return line + "\n  " + detail
    if note_str:
        return line + " " + note_str
    return line


def render_index(entries: list[dict[str, Any]]) -> str:
    """Render domain-grouped markdown. No header line, no counts."""
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_domain.setdefault(entry["primary"], []).append(entry)

    blocks: list[str] = []
    ordered = sorted(by_domain, key=lambda d: _DOMAIN_ORDER.get(d, len(_DOMAIN_ORDER)))
    for domain in ordered:
        files = sorted(by_domain[domain], key=lambda e: e["sort_key"])
        bullets = "\n".join(_render_entry(e) for e in files)
        blocks.append(f"## {domain}\n\n{bullets}")
    return "\n\n".join(blocks) + "\n" if blocks else ""


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_index(folder: Path, *, vault_root: Path | None = None, recursive: bool = False) -> Path:
    """Regenerate <folder>/INDEX.md from the notes in that folder."""
    folder = Path(folder)
    if vault_root is None:
        vault_root = folder.parent
    glob = folder.rglob("*.md") if recursive else folder.glob("*.md")
    files = sorted(p for p in glob if p.name != "INDEX.md")
    entries = [extract_meta(p, vault_root) for p in files]
    index_path = folder / "INDEX.md"
    _atomic_write(index_path, render_index(entries))
    return index_path


def _resolve_folder(arg: str, vault_root: Path) -> tuple[Path, bool]:
    path = Path(arg)
    if path.is_absolute() or path.exists():
        name = path.name
        return path, INDEX_FOLDERS.get(name, False)
    return vault_root / arg, INDEX_FOLDERS.get(arg, False)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Regenerate domain-grouped vault INDEX.md files")
    parser.add_argument("folders", nargs="*", help="Folder name(s) under the vault, or paths")
    parser.add_argument("--all", action="store_true", help="Regenerate every known index folder")
    parser.add_argument("--vault-root", default=str(DEFAULT_VAULT_ROOT))
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root)
    targets: list[tuple[Path, bool]] = []
    if args.all:
        for name, recursive in INDEX_FOLDERS.items():
            folder = vault_root / name
            if folder.is_dir():
                targets.append((folder, recursive))
    for arg in args.folders:
        targets.append(_resolve_folder(arg, vault_root))

    if not targets:
        parser.error("specify folder name(s) or --all")

    for folder, recursive in targets:
        if not folder.is_dir():
            print(f"skip (missing): {folder}", file=sys.stderr)
            continue
        index_path = write_index(folder, vault_root=vault_root, recursive=recursive)
        print(f"wrote {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
