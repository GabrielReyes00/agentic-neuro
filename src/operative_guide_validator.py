#!/usr/bin/env python3
"""
Validator for Operative Guides/*.md structural compliance.

This guard is intentionally qualitative in shape: it checks that the guide
contains the required operative domains, metadata placement, clean formatting,
and testable Mastery Objectives. It does not enforce arbitrary counts for
operative steps, danger zones, instruments, pitfalls, or anatomy expansions.

Exit code: 0 if all checked guides pass, 1 if any fail.

Usage:
    python3 src/operative_guide_validator.py
    python3 src/operative_guide_validator.py "/path/to/Operative Guides/Topic.md"
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

VAULT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
GUIDES_DIR = VAULT / "Operative Guides"
LINK_DIRS = (
    VAULT / "Operative Guides",
    VAULT / "Reports",
    VAULT / "Consults",
    VAULT / "Study Material",
    VAULT / "Concepts",
)

H1_RE = re.compile(r"^#\s", re.MULTILINE)
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^#{2,4}\s+(.+?)\s*$", re.MULTILINE)
HEADING_WITH_POS_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$", re.MULTILINE)
H2_WITH_POS_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
GEN_MODE_RE = re.compile(r"^Generation Mode\s*:", re.MULTILINE)
STATUS_RE = re.compile(r"^STATUS\s*:", re.MULTILINE)
RAG_CALLOUT_RE = re.compile(r"^>\s*\[!info\]\s*RAG Supplemented\s*$", re.MULTILINE)
ANY_RAG_CALLOUT_HINT_RE = re.compile(r"^>\s*\[!\w+\].*RAG", re.MULTILINE | re.IGNORECASE)
ANKI_ROUTING_HEADING_RE = re.compile(r"^#{2,4}\s+.*\b(Anki|Deck Routing|Procedure-Specific Deck)\b", re.MULTILINE)
WORKFLOW_MEMO_HEADING_RE = re.compile(
    r"^#{2,4}\s+.*\b(Completeness Review|Expert Review|Gap Repair|Repair Memo|Blocking Gaps|False Completeness Risks|Procedure Decomposition|Knowledge Map|Attending Defense Map|Workflow Ledger)\b",
    re.MULTILINE | re.IGNORECASE,
)
OBJECTIVE_LINE_RE = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)(.+?)\s*$")
WEAK_OBJECTIVE_VERB_RE = re.compile(
    r"^(?:\*\*)?(?:know|understand|appreciate|be familiar with|review|learn)\b",
    re.IGNORECASE,
)
SOURCE_CITE_RE = re.compile(
    r"\((?:[^)]*(?:Youmans|Greenberg|Rhoton|Atlas|Operative Neurosurgical Techniques|Handbook|PMID|DOI)[^)]*)\)",
    re.IGNORECASE,
)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MIN_BODY_CHARS = 7000
MIN_SECTION_CHARS = 180


@dataclass(frozen=True)
class Domain:
    label: str
    patterns: tuple[re.Pattern[str], ...]


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


REQUIRED_DOMAINS = [
    Domain(
        "surgical objective",
        (_rx(r"\bsurgical objective\b"), _rx(r"\boperative objective\b"), _rx(r"\bgoal of (surgery|operation)\b")),
    ),
    Domain(
        "indications, contraindications, and approach selection",
        (_rx(r"\bindications?\b"), _rx(r"\bcontraindications?\b"), _rx(r"\bapproach selection\b")),
    ),
    Domain(
        "preoperative planning",
        (_rx(r"\bpre[- ]?operative planning\b"), _rx(r"\bpreop(?:erative)? plan\b"), _rx(r"\bplanning\b")),
    ),
    Domain(
        "room, positioning, and equipment setup",
        (_rx(r"\b(positioning|setup|equipment|instruments?|room setup)\b"),),
    ),
    Domain(
        "step-by-step operative walkthrough",
        (_rx(r"\bstep[- ]?by[- ]?step\b"), _rx(r"\boperative walkthrough\b"), _rx(r"\boperative sequence\b")),
    ),
    Domain(
        "critical moments",
        (_rx(r"\bcritical moments?\b"), _rx(r"\bcritical maneuvers?\b"), _rx(r"\btechnical inflection\b")),
    ),
    Domain(
        "anatomy expansion",
        (_rx(r"\banatomy\b"), _rx(r"\banatomic(?:al)? expansion\b"), _rx(r"\bsurgical anatomy\b")),
    ),
    Domain(
        "pitfalls and fail-safe plans",
        (_rx(r"\bpitfalls?\b"), _rx(r"\bfail[- ]?safes?\b"), _rx(r"\bbail[- ]?outs?\b")),
    ),
    Domain(
        "closure and immediate postoperative management",
        (_rx(r"\bclosure\b"), _rx(r"\bpost[- ]?op(?:erative)?\b"), _rx(r"\bfirst 24 hours\b")),
    ),
    Domain(
        "complications and signatures",
        (_rx(r"\bcomplications?\b"), _rx(r"\bsignatures?\b"), _rx(r"\brescue\b")),
    ),
    Domain(
        "related in this vault",
        (_rx(r"^related in this vault$"), _rx(r"\brelated\b.*\bvault\b")),
    ),
]

OPTIONAL_BUT_EXPECTED_DOMAINS = [
    Domain(
        "variants and intraoperative decision branches",
        (_rx(r"\bvariants?\b"), _rx(r"\bdecision branches?\b"), _rx(r"\bdecision tree\b"), _rx(r"\bconversion\b")),
    ),
]


def _bottom_yaml_start_line(text: str) -> int | None:
    lines = text.splitlines()
    if not lines or lines[-1].strip() != "---":
        return None
    for idx in range(len(lines) - 2, -1, -1):
        if lines[idx].strip() == "---":
            return idx + 1
    return None


def _strip_objective_markup(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"^`(.*?)`", r"\1", text)
    return text.strip()


def _headings(text: str) -> list[str]:
    return [m.group(1).strip() for m in HEADING_RE.finditer(text)]


def _heading_sections(text: str) -> list[tuple[str, str]]:
    matches = list(H2_WITH_POS_RE.finditer(text))
    sections: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections.append((heading, text[start:end].strip()))
    return sections


def _vault_titles() -> set[str]:
    titles: set[str] = set()
    for directory in LINK_DIRS:
        if not directory.exists():
            continue
        for path in directory.glob("*.md"):
            titles.add(path.stem)
    return titles


def _wikilink_target(raw: str) -> str:
    # Obsidian supports [[Note]], [[Note#Heading]], and [[Note|Alias]].
    target = raw.split("|", 1)[0].split("#", 1)[0].strip()
    return target


def _domain_section(domain: Domain, sections: list[tuple[str, str]]) -> tuple[str, str] | None:
    for heading, body in sections:
        if any(pattern.search(heading) for pattern in domain.patterns):
            return heading, body
    return None


def _mastery_objectives(text: str, lines: list[str], failures: list[str]) -> None:
    h2_positions = [(m.group(1).strip(), text.count("\n", 0, m.start()) + 1) for m in H2_RE.finditer(text)]
    bottom_yaml_line = _bottom_yaml_start_line(text)
    mastery_positions = [(name, ln) for name, ln in h2_positions if name == "Mastery Objectives"]
    if not mastery_positions:
        failures.append("missing required H2 `## Mastery Objectives`")
        return

    _, mastery_line = mastery_positions[0]
    if bottom_yaml_line is not None and mastery_line >= bottom_yaml_line:
        failures.append(f"line {mastery_line}: `## Mastery Objectives` must appear before bottom YAML metadata")

    next_mastery_h2 = next((ln for _, ln in h2_positions if ln > mastery_line), len(lines) + 1)
    section_end = min(next_mastery_h2, bottom_yaml_line or len(lines) + 1)
    section_lines = lines[mastery_line : section_end - 1]
    objectives: list[tuple[int, str]] = []
    for offset, line in enumerate(section_lines, mastery_line + 1):
        match = OBJECTIVE_LINE_RE.match(line)
        if match:
            objective = _strip_objective_markup(match.group(1))
            if objective:
                objectives.append((offset, objective))

    if len(objectives) < 5 or len(objectives) > 10:
        failures.append(
            f"line {mastery_line}: `## Mastery Objectives` must contain 5-10 objective list items "
            f"(found {len(objectives)})"
        )

    for ln, objective in objectives:
        if WEAK_OBJECTIVE_VERB_RE.search(objective):
            failures.append(
                f"line {ln}: weak Mastery Objective verb in `{objective[:80]}`; use a testable action verb"
            )


def validate(path: Path) -> list[str]:
    text = path.read_text()
    lines = text.splitlines()
    failures: list[str] = []

    for i, line in enumerate(lines, 1):
        if H1_RE.match(line):
            failures.append(f"line {i}: H1 heading is not allowed (filename is the title)")
            break

    if lines and lines[0].strip() == "---":
        failures.append("line 1: YAML front matter at top is not allowed (YAML belongs at bottom)")

    if GEN_MODE_RE.search(text):
        failures.append("legacy `Generation Mode:` tag is banned")

    if STATUS_RE.search(text):
        failures.append("status marker is banned; surface status in chat, not in the artifact")

    if ANKI_ROUTING_HEADING_RE.search(text):
        failures.append("Anki deck-routing metadata must not appear as a guide body section")

    if WORKFLOW_MEMO_HEADING_RE.search(text):
        failures.append("workflow review or gap-repair memos must not appear in the final guide body")

    if ANY_RAG_CALLOUT_HINT_RE.search(text) and not RAG_CALLOUT_RE.search(text):
        failures.append("RAG callout present but malformed: use exactly `> [!info] RAG Supplemented`")

    bottom_yaml_line = _bottom_yaml_start_line(text)
    if bottom_yaml_line is None:
        failures.append("missing bottom YAML metadata block ending at EOF")

    if len(re.sub(r"\s+", "", text)) < MIN_BODY_CHARS:
        failures.append(
            f"guide body is too sparse for a standalone operative reference "
            f"(non-whitespace characters below {MIN_BODY_CHARS})"
        )

    sections = _heading_sections(text)
    for domain in REQUIRED_DOMAINS:
        section = _domain_section(domain, sections)
        if section is None:
            failures.append(f"missing operative domain: {domain.label}")
            continue
        heading, body = section
        if domain.label not in {"related in this vault"} and len(re.sub(r"\s+", "", body)) < MIN_SECTION_CHARS:
            failures.append(
                f"operative domain `{domain.label}` is present but too thin under heading `{heading}`"
            )

    # This domain can be omitted for a very linear procedure, but the guide must
    # explicitly say that no meaningful variants/branches apply.
    for domain in OPTIONAL_BUT_EXPECTED_DOMAINS:
        if _domain_section(domain, sections) is None and not re.search(
            r"\b(no|not)\b.{0,60}\b(variant|decision branch|alternate approach|conversion)\b",
            text,
            re.IGNORECASE | re.DOTALL,
        ):
            failures.append(
                f"missing or unjustified operative domain: {domain.label}; "
                "include it or briefly state why it does not apply"
            )

    if RAG_CALLOUT_RE.search(text) and len(SOURCE_CITE_RE.findall(text)) < 3:
        failures.append(
            "RAG callout is present but source citation density is too low; "
            "cite retrieved textbook or literature sources at the relevant claims"
        )

    wikilinks = [_wikilink_target(match.group(1)) for match in WIKILINK_RE.finditer(text)]
    if wikilinks and VAULT.exists():
        valid_titles = _vault_titles()
        missing = sorted({target for target in wikilinks if target and target not in valid_titles})
        if missing:
            failures.append(
                "unverified wikilink target(s): "
                + ", ".join(f"[[{target}]]" for target in missing[:10])
                + (" ..." if len(missing) > 10 else "")
            )

    _mastery_objectives(text, lines, failures)
    return failures


def _candidate_paths(args: list[str]) -> list[Path]:
    if args:
        return [Path(arg) for arg in args]
    if not GUIDES_DIR.exists():
        return []
    return sorted(path for path in GUIDES_DIR.glob("*.md") if path.name != "INDEX.md")


def main(argv: list[str]) -> int:
    paths = _candidate_paths(argv[1:])
    if not paths:
        print("No operative guides found to validate.")
        return 0

    had_failure = False
    for path in paths:
        if not path.exists():
            print(f"FAIL {path}: file does not exist")
            had_failure = True
            continue
        failures = validate(path)
        if failures:
            had_failure = True
            print(f"FAIL {path}")
            for failure in failures:
                print(f"  - {failure}")
        else:
            print(f"PASS {path}")

    return 1 if had_failure else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
