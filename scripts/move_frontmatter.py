#!/usr/bin/env python3
"""Vault format normalizer.

Walk every markdown file under the agentic-neuro Obsidian vault and enforce
the two cardinal rules (corrected by the user 6+ times):

    1. NO top-of-file YAML frontmatter (`---` block at the very top)
       — moved to the BOTTOM of the file
    2. NO H1 heading (`# Title`) as first non-blank content line
       — stripped (filename IS the Obsidian title)

Idempotent: running it on a clean vault is a no-op. Skips protected concept
notes. Reports a summary of fixes per folder.

Usage:
    python3 scripts/move_frontmatter.py [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VAULT_ROOT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")

TARGET_FOLDERS = (
    "Concepts",
    "Reports",
    "Operative Guides",
    "Study Material",
    "Review Sessions",
    "Error Atlas",
    "ACGME Canvases",
    "Dashboard.md",        # individual file allowed
    "ACGME Readiness.md",
)

# Concept notes that the user manually authored — leave them alone.
PROTECTED = {
    "Neurosurgery Consult Workflow.md",
    "Neurosurgery Consult Checklists by Pathology.md",
    "Peripheral Nerve Injury Classifications (Seddon & Sunderland).md",
}

YAML_BLOCK_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def fix_file(path: Path, dry_run: bool = False) -> dict:
    """Fix one markdown file. Returns dict of fixes applied."""
    fixes = {"moved_yaml": False, "stripped_h1": False}
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return fixes

    original = content

    # ── Fix 1: top-of-file YAML → move to bottom ───────────────────────────
    if content.lstrip().startswith("---"):
        # Find where the leading whitespace ends
        leading_ws_len = len(content) - len(content.lstrip())
        body_after_ws = content[leading_ws_len:]
        m = YAML_BLOCK_RE.match(body_after_ws)
        if m:
            yaml_block = m.group(0).rstrip("\n")
            rest = body_after_ws[m.end():].lstrip("\n")
            if rest.strip():
                content = rest.rstrip() + "\n\n" + yaml_block + "\n"
                fixes["moved_yaml"] = True
            # If no body, file is YAML-only — leave as-is.

    # ── Fix 2: H1 heading at top → strip ───────────────────────────────────
    stripped = content.lstrip()
    first_line = stripped.split("\n", 1)[0] if stripped else ""
    if first_line.startswith("# "):
        # Strip the H1 line + any blank line after it
        leading_ws = content[:len(content) - len(stripped)]
        rest = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        content = leading_ws + rest.lstrip("\n")
        fixes["stripped_h1"] = True

    if content != original and not dry_run:
        path.write_text(content, encoding="utf-8")
    return fixes


def iter_targets() -> list[Path]:
    out: list[Path] = []
    for entry in TARGET_FOLDERS:
        p = VAULT_ROOT / entry
        if p.is_file() and p.suffix == ".md":
            out.append(p)
        elif p.is_dir():
            for f in sorted(p.glob("*.md")):
                if f.name in PROTECTED:
                    continue
                out.append(f)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = iter_targets()
    moved = 0
    stripped = 0
    touched: list[str] = []
    for f in files:
        fixes = fix_file(f, dry_run=args.dry_run)
        if fixes["moved_yaml"] or fixes["stripped_h1"]:
            touched.append(
                f"  {f.relative_to(VAULT_ROOT)}"
                f" [{'YAML' if fixes['moved_yaml'] else ''}"
                f"{'+' if fixes['moved_yaml'] and fixes['stripped_h1'] else ''}"
                f"{'H1' if fixes['stripped_h1'] else ''}]"
            )
        moved += int(fixes["moved_yaml"])
        stripped += int(fixes["stripped_h1"])

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Scanned {len(files)} files")
    print(f"{prefix}Moved YAML to bottom: {moved}")
    print(f"{prefix}Stripped H1 heading:  {stripped}")
    if touched:
        print(f"{prefix}Affected files:")
        for line in touched:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
