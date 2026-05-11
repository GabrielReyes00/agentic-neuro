#!/usr/bin/env python3
"""
Validator for Reports/*.md structural compliance with the generate-report contract.

Checks (per file):
  - First H2 is exactly `## Clinical Utility & Quick Reference`.
  - Within that section, in order:
      * a TL;DR blockquote starting `> **TL;DR:**`
      * H3 `### When to Reference This Report`
      * H3 `### Key Numbers at a Glance`
      * H3 `### Decision Framework`
  - `### Key Numbers at a Glance` is followed by a Markdown table whose header
    row matches `| Parameter | Value | Context | Source |` (whitespace-tolerant).
  - No `Generation Mode:` line anywhere in the file (legacy anti-pattern).
  - No H1 (`^# `) anywhere in the file.
  - YAML metadata appears at the bottom, not the top (no `---` on line 1).
  - If a RAG callout is present, it uses the exact sanctioned form
    `> [!info] RAG Supplemented` (case-sensitive, on its own line).

Exit code: 0 if all reports pass, 1 if any fail.

Usage:
    python3 src/report_validator.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

VAULT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
REPORTS_DIR = VAULT / "Reports"

REQUIRED_H2 = "## Clinical Utility & Quick Reference"
REQUIRED_H3_ORDER = [
    "### When to Reference This Report",
    "### Key Numbers at a Glance",
    "### Decision Framework",
]
TLDR_RE = re.compile(r"^>\s*\*\*TL;DR:\*\*", re.MULTILINE)
NUMBERS_HEADER_RE = re.compile(
    r"^\|\s*Parameter\s*\|\s*Value\s*\|\s*Context\s*\|\s*Source\s*\|",
    re.MULTILINE,
)
GEN_MODE_RE = re.compile(r"^Generation Mode\s*:", re.MULTILINE)
H1_RE = re.compile(r"^#\s", re.MULTILINE)
RAG_CALLOUT_RE = re.compile(r"^>\s*\[!info\]\s*RAG Supplemented\s*$", re.MULTILINE)
ANY_RAG_CALLOUT_HINT_RE = re.compile(r"^>\s*\[!\w+\].*RAG", re.MULTILINE | re.IGNORECASE)

# Matches a single existing markdown link target, with no nested brackets in the label.
EXISTING_LINK_RE = re.compile(r"\[[^\[\]]*\]\(https?://[^)]+\)")
RAW_PMID_RE = re.compile(r"PMID[: ](\d{6,9})(?!\d)")
RAW_DOI_RE = re.compile(r"(?<!/)DOI[: ](10\.[\w./\-]+)")

# Detect a journal-style citation token: `Author YYYY` or `Author et al., YYYY`.
JOURNAL_CITE_RE = re.compile(r"\b[A-Z][a-zA-Z\-]+(?:\s+et\s+al\.?)?,?\s+(\d{4})\b")
# Pre-1980 historical refs (e.g., Cushing 1901, Simpson 1957) predate PubMed indexing
# and are not reliably linkable; exempt them from the hyperlink rule.
HISTORICAL_YEAR_CUTOFF = 1980
# Textbook / guideline / non-linkable patterns to exempt from the "must be linked" rule.
TEXTBOOK_HINT_RE = re.compile(
    r"\b(?:Youmans|Greenberg|Handbook|Atlas|Operative Neurosurgical Techniques|Rhoton|StatPearls|p\.\s*\d+|\d(?:st|nd|rd|th)\s+Ed\b|Cranial Anatomy|Comprehensive Neurosurgical)",
    re.IGNORECASE,
)


def validate(path: Path) -> list[str]:
    """Return a list of failure messages. Empty list = pass."""
    text = path.read_text()
    lines = text.splitlines()
    failures: list[str] = []

    # No H1 anywhere
    for i, line in enumerate(lines, 1):
        if H1_RE.match(line):
            failures.append(f"line {i}: H1 heading is not allowed (filename is the title)")
            break

    # No YAML at top
    if lines and lines[0].strip() == "---":
        failures.append("line 1: YAML front matter at top is not allowed (YAML belongs at bottom)")

    # Legacy generation-mode header
    m = GEN_MODE_RE.search(text)
    if m:
        line_no = text.count("\n", 0, m.start()) + 1
        failures.append(f"line {line_no}: legacy `Generation Mode:` tag is banned (use the sanctioned RAG callout instead)")

    # First H2 must be the required block
    first_h2 = next((i for i, line in enumerate(lines, 1) if line.startswith("## ")), None)
    if first_h2 is None:
        failures.append("no H2 heading found")
        return failures
    if lines[first_h2 - 1].strip() != REQUIRED_H2:
        failures.append(
            f"line {first_h2}: first H2 must be exactly `{REQUIRED_H2}` "
            f"(found `{lines[first_h2 - 1].strip()}`)"
        )

    # Within the Clinical Utility section: locate end (next H2 or EOF)
    next_h2 = next(
        (i for i, line in enumerate(lines[first_h2:], first_h2 + 1) if line.startswith("## ")),
        len(lines) + 1,
    )
    section = "\n".join(lines[first_h2 - 1 : next_h2 - 1])

    # TL;DR blockquote
    tldr_m = TLDR_RE.search(section)
    if not tldr_m:
        failures.append(f"line {first_h2}: missing blockquoted TL;DR (`> **TL;DR:** ...`) in Clinical Utility section")

    # H3 children in order
    h3_positions: list[tuple[str, int]] = []
    for offset, line in enumerate(lines[first_h2 - 1 : next_h2 - 1]):
        if line.startswith("### "):
            h3_positions.append((line.strip(), first_h2 + offset))

    found_names = [h[0] for h in h3_positions]
    required_iter = iter(REQUIRED_H3_ORDER)
    next_required = next(required_iter, None)
    matched_order: list[tuple[str, int]] = []
    for name, ln in h3_positions:
        if name == next_required:
            matched_order.append((name, ln))
            next_required = next(required_iter, None)
    missing = REQUIRED_H3_ORDER[len(matched_order):]
    if missing:
        present_str = ", ".join(found_names) if found_names else "none"
        for m_name in missing:
            failures.append(
                f"Clinical Utility section: missing or out-of-order H3 `{m_name}` "
                f"(H3 children found, in order: {present_str})"
            )

    # Numbers table header
    numbers_h3 = next((ln for name, ln in h3_positions if name == "### Key Numbers at a Glance"), None)
    if numbers_h3 is not None:
        # Look at the 12 lines after the heading for the canonical table header
        window = "\n".join(lines[numbers_h3 : numbers_h3 + 12])
        if not NUMBERS_HEADER_RE.search(window):
            failures.append(
                f"line {numbers_h3}: `### Key Numbers at a Glance` must be followed by a table "
                f"with header `| Parameter | Value | Context | Source |`"
            )

    # RAG callout sanity (optional, but if hinted must be exact)
    if ANY_RAG_CALLOUT_HINT_RE.search(text) and not RAG_CALLOUT_RE.search(text):
        failures.append(
            "RAG callout present but malformed: must be exactly `> [!info] RAG Supplemented` on its own line"
        )

    # Key Numbers table Source column: every journal-style citation must be hyperlinked.
    if numbers_h3 is not None:
        table_lines: list[tuple[int, str]] = []
        in_table = False
        for offset, line in enumerate(lines[numbers_h3 : numbers_h3 + 60]):
            ln = numbers_h3 + offset + 1
            if line.lstrip().startswith("|") and "---" not in line and line.strip().count("|") >= 4:
                table_lines.append((ln, line))
                in_table = True
            elif in_table and not line.lstrip().startswith("|"):
                break
        # Skip header row (first table row).
        for ln, row in table_lines[1:]:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if not cells:
                continue
            source = cells[-1]
            # Skip if cell is empty or already contains a markdown link.
            if not source or "](http" in source:
                continue
            # Skip if cell looks like a textbook / guideline-only reference.
            if TEXTBOOK_HINT_RE.search(source) and not JOURNAL_CITE_RE.search(source):
                continue
            # Skip if no journal-style author-year citation is present, or if every
            # author-year citation in the cell is pre-1980 (historical, unindexed).
            cite_matches = JOURNAL_CITE_RE.findall(source)
            if not cite_matches:
                continue
            if all(int(y) < HISTORICAL_YEAR_CUTOFF for y in cite_matches):
                continue
            failures.append(
                f"line {ln}: Key Numbers Source `{source[:60]}…` has a journal-style citation but no hyperlink"
            )

    # Hyperlinking: every PMID and DOI token must be inside a markdown link.
    masked = EXISTING_LINK_RE.sub("", text)
    raw_pmids: list[tuple[int, str]] = []
    for m in RAW_PMID_RE.finditer(masked):
        line_no = masked.count("\n", 0, m.start()) + 1
        raw_pmids.append((line_no, m.group(0)))
    raw_dois: list[tuple[int, str]] = []
    for m in RAW_DOI_RE.finditer(masked):
        line_no = masked.count("\n", 0, m.start()) + 1
        raw_dois.append((line_no, m.group(0)))
    for line_no, token in raw_pmids[:5]:
        failures.append(f"line ~{line_no}: raw `{token}` must be a clickable markdown link to https://pubmed.ncbi.nlm.nih.gov/<id>/")
    if len(raw_pmids) > 5:
        failures.append(f"... and {len(raw_pmids) - 5} more raw PMID tokens")
    for line_no, token in raw_dois[:5]:
        failures.append(f"line ~{line_no}: raw `{token}` must be a clickable markdown link to https://doi.org/<id>")
    if len(raw_dois) > 5:
        failures.append(f"... and {len(raw_dois) - 5} more raw DOI tokens")

    return failures


def main() -> int:
    if not REPORTS_DIR.is_dir():
        print(f"Reports directory not found: {REPORTS_DIR}", file=sys.stderr)
        return 1

    files = sorted(p for p in REPORTS_DIR.glob("*.md") if p.name != "INDEX.md")
    if not files:
        print("No report files found.", file=sys.stderr)
        return 1

    total_failures = 0
    for path in files:
        failures = validate(path)
        if failures:
            total_failures += 1
            print(f"FAIL  {path.name}")
            for f in failures:
                print(f"        - {f}")
        else:
            print(f"PASS  {path.name}")

    print()
    if total_failures:
        print(f"{total_failures} of {len(files)} reports failed validation.")
        return 1
    print(f"All {len(files)} reports passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
