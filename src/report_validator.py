#!/usr/bin/env python3
"""
Validator for Reports/*.md structural compliance with the generate-report contract.

Checks (per file):
  - First H2 is exactly `## Clinical Utility & Quick Reference`.
  - Within that section, in order:
      * a TL;DR blockquote starting `> **TL;DR:**`
      * H3 `### When to Reference This Report`
      * H3 `### Key Numbers at a Glance` or `### Key Anchors at a Glance`
      * H3 `### Decision Framework`
  - The selected anchor H3 is followed by its canonical Markdown table header.
  - H2 `## Mastery Objectives` appears after the opening block with testable,
    action-verb objectives.
  - Workflow mode markers are kept out of the final report body.
  - No H1 (`^# `) anywhere in the file.
  - YAML metadata uses native Obsidian frontmatter at the top.
  - If a RAG callout is present, it uses the exact sanctioned form
    `> [!info] RAG Supplemented` (case-sensitive, on its own line).
  - Native frontmatter excludes workflow provenance and internal-knowledge tracking keys.
  - Textbook-style labels are not paired with PubMed/DOI links.
  - Optional coverage ledger gate: if `--coverage-ledger` is supplied, required
    ledger blocks must not have gap-like statuses.

Exit code: 0 if all reports pass, 1 if any fail.

Usage:
    python3 src/report_validator.py
    python3 src/report_validator.py "/path/to/Reports/Topic.md"
    python3 src/report_validator.py "/path/to/Reports/Topic.md" \
      --coverage-ledger data/Sessions/Topic/coverage_ledger.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from vault_schema import split_frontmatter
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from .vault_schema import split_frontmatter

VAULT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
REPORTS_DIR = VAULT / "Reports"

REQUIRED_H2 = "## Clinical Utility & Quick Reference"
WHEN_H3 = "### When to Reference This Report"
NUMBERS_H3 = "### Key Numbers at a Glance"
ANCHORS_H3 = "### Key Anchors at a Glance"
DECISION_H3 = "### Decision Framework"
TLDR_RE = re.compile(r"^>\s*\*\*TL;DR:\*\*", re.MULTILINE)
NUMBERS_HEADER_RE = re.compile(
    r"^\|\s*Parameter\s*\|\s*Value\s*\|\s*Context\s*\|\s*Source\s*\|",
    re.MULTILINE,
)
ANCHORS_HEADER_RE = re.compile(
    r"^\|\s*Decision Or Structure\s*\|\s*Anchor\s*\|\s*Why It Matters\s*\|\s*Source\s*\|",
    re.MULTILINE | re.IGNORECASE,
)
WORKFLOW_MODE_MARKER_RE = re.compile(r"^[A-Z][A-Za-z ]+\s+Mode\s*:", re.MULTILINE)
H1_RE = re.compile(r"^#\s", re.MULTILINE)
RAG_CALLOUT_RE = re.compile(r"^>\s*\[!info\]\s*RAG Supplemented\s*$", re.MULTILINE)
ANY_RAG_CALLOUT_HINT_RE = re.compile(r"^>\s*\[!\w+\].*RAG", re.MULTILINE | re.IGNORECASE)
FENCED_YAML_RE = re.compile(r"^```ya?ml\s*$", re.MULTILINE | re.IGNORECASE)
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
OBJECTIVE_LINE_RE = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)(.+?)\s*$")
WEAK_OBJECTIVE_VERB_RE = re.compile(
    r"^(?:\*\*)?(?:know|understand|appreciate|be familiar with|review|learn)\b",
    re.IGNORECASE,
)

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
TEXTBOOK_LINK_CONTEXT_RE = re.compile(
    r"(?:Youmans|Greenberg|Handbook|Atlas|Operative Neurosurgical Techniques|Rhoton|StatPearls|Comprehensive Neurosurgical|Neurosurgery Board Review|Neuro ICU)[^\n|]{0,80}\[[^\]]+\]\(https?://(?:pubmed\.ncbi\.nlm\.nih\.gov|doi\.org)/[^)]+\)",
    re.IGNORECASE,
)
FORBIDDEN_YAML_KEY_RE = re.compile(r"^\s*(?:provenance|internal_knowledge_used)\s*:", re.IGNORECASE)
GAP_STATUSES = {"gap", "gapped", "missing", "uncovered", "incomplete"}


def _strip_objective_markup(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"^`(.*?)`", r"\1", text)
    return text.strip()


def validate(path: Path) -> list[str]:
    """Return a list of failure messages. Empty list = pass."""
    raw_text = path.read_text()
    text, parsed_meta = split_frontmatter(raw_text)
    meta = parsed_meta or {}
    lines = text.splitlines()
    failures: list[str] = []

    # No H1 anywhere
    for i, line in enumerate(lines, 1):
        if H1_RE.match(line):
            failures.append(f"line {i}: H1 heading is not allowed (filename is the title)")
            break

    if not meta:
        failures.append("missing or invalid native YAML frontmatter")
    else:
        for key in ("domain", "summary"):
            if not str(meta.get(key) or "").strip():
                failures.append(f"frontmatter `{key}` is required for report indexing")
    fenced_yaml = FENCED_YAML_RE.search(text)
    if fenced_yaml:
        line_no = text.count("\n", 0, fenced_yaml.start()) + 1
        failures.append(f"line {line_no}: YAML metadata must use native frontmatter, not a fenced code block")

    for key in ("provenance", "internal_knowledge_used"):
        if key in meta:
            failures.append(f"frontmatter key `{key}` is not allowed in final Reports metadata")

    m = WORKFLOW_MODE_MARKER_RE.search(text)
    if m:
        line_no = text.count("\n", 0, m.start()) + 1
        failures.append(f"line {line_no}: workflow mode markers belong outside the final report body; use the RAG callout when retrieval was used")

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
    present_str = ", ".join(found_names) if found_names else "none"
    anchor_names = [name for name in found_names if name in {NUMBERS_H3, ANCHORS_H3}]
    if len(anchor_names) != 1:
        failures.append(
            "Clinical Utility section must contain exactly one topic-shaped anchor H3: "
            f"`{NUMBERS_H3}` or `{ANCHORS_H3}` (found: {present_str})"
        )
    expected_order = [WHEN_H3, anchor_names[0] if len(anchor_names) == 1 else None, DECISION_H3]
    expected_order = [name for name in expected_order if name]
    positions = [found_names.index(name) if name in found_names else -1 for name in expected_order]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        failures.append(
            "Clinical Utility section: required H3 children are missing or out of order "
            f"(found: {present_str})"
        )

    # Numbers table header
    anchor_h3 = next(((name, ln) for name, ln in h3_positions if name in {NUMBERS_H3, ANCHORS_H3}), None)
    numbers_h3 = anchor_h3[1] if anchor_h3 and anchor_h3[0] == NUMBERS_H3 else None
    if anchor_h3 is not None:
        anchor_name, anchor_line = anchor_h3
        window = "\n".join(lines[anchor_line : anchor_line + 12])
        expected_header = (
            "| Parameter | Value | Context | Source |"
            if anchor_name == NUMBERS_H3
            else "| Decision Or Structure | Anchor | Why It Matters | Source |"
        )
        header_re = NUMBERS_HEADER_RE if anchor_name == NUMBERS_H3 else ANCHORS_HEADER_RE
        if not header_re.search(window):
            failures.append(
                f"line {anchor_line}: `{anchor_name}` must be followed by a table "
                f"with header `{expected_header}`"
            )

    # Mastery Objectives section: required after opening block.
    h2_positions = [(m.group(1).strip(), text.count("\n", 0, m.start()) + 1) for m in H2_RE.finditer(text)]
    mastery_positions = [(name, ln) for name, ln in h2_positions if name == "Mastery Objectives"]
    if not mastery_positions:
        failures.append("missing required H2 `## Mastery Objectives`")
    else:
        mastery_name, mastery_line = mastery_positions[0]
        if mastery_line <= first_h2:
            failures.append(f"line {mastery_line}: `## Mastery Objectives` must appear after the opening Clinical Utility section")
        next_mastery_h2 = next((ln for _, ln in h2_positions if ln > mastery_line), len(lines) + 1)
        section_end = next_mastery_h2
        mastery_lines = lines[mastery_line: section_end - 1]
        objectives: list[tuple[int, str]] = []
        for offset, line in enumerate(mastery_lines, mastery_line + 1):
            match = OBJECTIVE_LINE_RE.match(line)
            if match:
                objective = _strip_objective_markup(match.group(1))
                if objective:
                    objectives.append((offset, objective))
        if not objectives:
            failures.append(
                f"line {mastery_line}: `## Mastery Objectives` must contain testable list items"
            )
        for ln, objective in objectives:
            if WEAK_OBJECTIVE_VERB_RE.search(objective):
                failures.append(
                    f"line {ln}: weak Mastery Objective verb in `{objective[:80]}`; "
                    "use a testable action verb"
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

    for i, line in enumerate(lines, 1):
        if TEXTBOOK_LINK_CONTEXT_RE.search(line):
            failures.append(
                f"line {i}: textbook-style citation is paired with a PubMed/DOI link; "
                "cite the textbook as book/page or cite the actual article label"
            )

    return failures


def _ledger_blocks(payload: object) -> list[tuple[str, dict[str, object]]]:
    if not isinstance(payload, dict):
        return []
    raw_blocks = payload.get("blocks")
    if isinstance(raw_blocks, dict):
        return [(str(name), block) for name, block in raw_blocks.items() if isinstance(block, dict)]
    if isinstance(raw_blocks, list):
        blocks: list[tuple[str, dict[str, object]]] = []
        for idx, block in enumerate(raw_blocks, 1):
            if not isinstance(block, dict):
                continue
            name = str(block.get("block_id") or block.get("domain") or block.get("name") or f"block_{idx}")
            blocks.append((name, block))
        return blocks
    return []


def validate_coverage_ledger(path: Path) -> list[str]:
    failures: list[str] = []
    if not path.exists():
        return [f"coverage ledger does not exist: {path}"]
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"coverage ledger is not valid JSON: {exc}"]

    blocks = _ledger_blocks(payload)
    if not blocks:
        return ["coverage ledger has no `blocks` object/list"]

    for name, block in blocks:
        required = block.get("required", True)
        if required is False:
            continue
        status = str(block.get("status") or "").strip().lower()
        review_status = str(block.get("review_status") or "").strip().lower()
        if status in GAP_STATUSES or review_status in GAP_STATUSES:
            failure_status = status if status in GAP_STATUSES else review_status
            failures.append(f"coverage block `{name}` has gap status `{failure_status}`")
    return failures


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate generated report structure and optional coverage ledger.")
    parser.add_argument("files", nargs="*", type=Path, help="Report markdown file(s) to validate.")
    parser.add_argument(
        "--coverage-ledger",
        type=Path,
        help="Optional report coverage_ledger.json. Only valid when validating one report file.",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args(sys.argv[1:])
    if args.coverage_ledger and len(args.files) != 1:
        print("--coverage-ledger can only be used when validating exactly one report file.", file=sys.stderr)
        return 1

    if args.files:
        files = args.files
    else:
        if not REPORTS_DIR.is_dir():
            print(f"Reports directory not found: {REPORTS_DIR}", file=sys.stderr)
            return 1
        files = sorted(p for p in REPORTS_DIR.glob("*.md") if p.name != "INDEX.md")

    if not files:
        print("No report files found.", file=sys.stderr)
        return 1

    total_failures = 0
    for path in files:
        if not path.exists():
            total_failures += 1
            print(f"FAIL  {path}")
            print("        - file does not exist")
            continue
        failures = validate(path)
        if args.coverage_ledger:
            failures.extend(validate_coverage_ledger(args.coverage_ledger))
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
