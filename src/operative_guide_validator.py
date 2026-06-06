#!/usr/bin/env python3
"""
Validator for Operative Guides/*.md structural compliance.

This guard checks that the guide contains the required first-principle
operative knowledge blocks, metadata placement, clean formatting, testable
Mastery Objectives, a verdict-chain audit trail, and a complexity-tiered
depth floor. It does not enforce arbitrary counts for steps, instruments,
or citations — content discipline is the reviewer's job, not the validator's.

Exit code: 0 if all checked guides pass, 1 if any fail.

Usage:
    python3 src/operative_guide_validator.py
    python3 src/operative_guide_validator.py "/path/to/Operative Guides/Topic.md"
    python3 src/operative_guide_validator.py --no-verdict-chain "/path/.../Topic.md"
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = REPO_ROOT / "data" / "Sessions"
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
WORKFLOW_MODE_MARKER_RE = re.compile(r"^[A-Z][A-Za-z ]+\s+Mode\s*:", re.MULTILINE)
WORKFLOW_STATUS_MARKER_RE = re.compile(r"^STATUS\s*:", re.MULTILINE)
RAG_CALLOUT_RE = re.compile(r"^>\s*\[!info\]\s*RAG Supplemented\s*$", re.MULTILINE)
ANY_RAG_CALLOUT_HINT_RE = re.compile(r"^>\s*\[!\w+\].*RAG", re.MULTILINE | re.IGNORECASE)
ANKI_ROUTING_HEADING_RE = re.compile(r"^#{2,4}\s+.*\b(Anki|Deck Routing|Procedure-Specific Deck)\b", re.MULTILINE)
WORKFLOW_MEMO_HEADING_RE = re.compile(
    r"^#{2,4}\s+.*\b(Completeness Review|Expert Review|Gap Repair|Repair Memo|Blocking Gaps|False Completeness Risks|Procedure Decomposition|Knowledge Map|Attending Defense Map|Workflow Ledger|Coverage Matrix)\b",
    re.MULTILINE | re.IGNORECASE,
)
OBJECTIVE_LINE_RE = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)(.+?)\s*$")
WEAK_OBJECTIVE_VERB_RE = re.compile(
    r"^(?:\*\*)?(?:know|understand|appreciate|be familiar with|review|learn)\b",
    re.IGNORECASE,
)
# Citation source allowlist. Populated from the live RAG corpus by
# scripts that write data/rag_textbook_sources.json (regenerate when the corpus
# changes). Falls back to a built-in keyset if the file is absent so the
# validator never hard-fails on a fresh checkout.
_SOURCE_ALLOWLIST_PATH = REPO_ROOT / "data" / "rag_textbook_sources.json"
_FALLBACK_CITATION_KEYS = [
    "Youmans", "Greenberg", "Rhoton", "Atlas Neurosurgical", "Atlas Emergency",
    "Operative Neurosurgical", "Fundamentals", "Essential Neurosurgery",
    "Comprehensive Neurosurgical", "Cranial Anatomy", "Brain Anatomy",
    "Imaging Anatomy", "Neuroanatomy Clinical", "Neuro ICU", "Neurosurgery Rounds",
    "Neurosurgery Board", "Intensive Neurosurgery", "Peripheral Nerve",
    "Handbook", "PMID", "DOI",
]


def _load_citation_keys() -> list[str]:
    try:
        data = json.loads(_SOURCE_ALLOWLIST_PATH.read_text(encoding="utf-8"))
        keys = data.get("citation_keys") or []
        return keys or _FALLBACK_CITATION_KEYS
    except (OSError, ValueError):
        return _FALLBACK_CITATION_KEYS


def _build_source_cite_re(keys: list[str]) -> re.Pattern[str]:
    # Accept both parenthetical "(...)" and bracketed "[...]" citations whose
    # delimited span names any known RAG source key. [^)\]] keeps the match
    # inside a single delimiter pair.
    alternation = "|".join(re.escape(k) for k in keys)
    return re.compile(rf"[\(\[](?:[^)\]]*(?:{alternation})[^)\]]*)[\)\]]", re.IGNORECASE)


CITATION_KEYS = _load_citation_keys()
SOURCE_CITE_RE = _build_source_cite_re(CITATION_KEYS)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
YAML_COMPLEXITY_RE = re.compile(r"^\s*complexity\s*:\s*([a-zA-Z_-]+)\s*$", re.MULTILINE)

# Complexity-tiered body floors. Reflect the 85% resident-mastery depth target.
MIN_BODY_CHARS_BY_COMPLEXITY = {
    "simple": 5000,
    "intermediate": 12000,
    "complex": 20000,
}
MIN_BODY_CHARS_DEFAULT = 7000  # fallback when complexity is not declared in YAML
MIN_SECTION_CHARS_BY_COMPLEXITY = {
    "simple": 80,
    "intermediate": 160,
    "complex": 220,
}
MIN_SECTION_CHARS_DEFAULT = 180


@dataclass(frozen=True)
class Domain:
    label: str
    patterns: tuple[re.Pattern[str], ...]
    absence_phrase: tuple[re.Pattern[str], ...] = ()  # explicit "not applicable" allowance


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Required first-principle knowledge blocks. The reviewer judges depth; the
# validator only checks that each block is addressed (or explicitly disclaimed
# where it may genuinely not apply for a given procedure).
REQUIRED_DOMAINS = [
    Domain(
        "surgical objective",
        (_rx(r"\bsurgical objective\b"), _rx(r"\boperative objective\b"), _rx(r"\bgoal of (surgery|operation)\b")),
    ),
    Domain(
        "pathology and natural history",
        (_rx(r"\bpathology\b"), _rx(r"\bnatural history\b"), _rx(r"\bpathophysiology\b"), _rx(r"\bdisease mechanism\b"), _rx(r"\bbiomechanics\b")),
    ),
    Domain(
        "workup and surgical decision-making",
        (_rx(r"\bworkup\b"), _rx(r"\bsurgical decision\b"), _rx(r"\bevaluation\b"), _rx(r"\bdiagnostic\b"), _rx(r"\bimaging\s+(interpretation|review)\b"), _rx(r"\bdecision[- ]making\b")),
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
        "anesthetic and physiologic plan",
        (_rx(r"\banesthe(t|s)i(c|a)\b"), _rx(r"\bphysiolog(ic|ical)\s+plan\b"), _rx(r"\bMAP\s*/\s*CPP\b"), _rx(r"\bbrain relaxation\b"), _rx(r"\bburst suppression\b")),
        absence_phrase=(_rx(r"\b(no|not|standard)\b[^.]{0,80}\bgeneral anesthesia\b"),),
    ),
    Domain(
        "neuromonitoring strategy",
        (_rx(r"\bneuromonitoring\b"), _rx(r"\bintraoperative monitoring\b"), _rx(r"\bIONM\b"), _rx(r"\bSSEP\b"), _rx(r"\bMEP\b"), _rx(r"\bEMG\b"), _rx(r"\bBAER\b"), _rx(r"\bcranial nerve monitoring\b")),
        absence_phrase=(_rx(r"\bneuromonitor\w*\b[^.]{0,120}\b(not used|omitted|not (required|indicated|applicable))\b"), _rx(r"\b(no|not)\b[^.]{0,60}\bneuromonitoring\b")),
    ),
    Domain(
        "step-by-step operative walkthrough",
        (_rx(r"\bstep[- ]?by[- ]?step\b"), _rx(r"\boperative walkthrough\b"), _rx(r"\boperative sequence\b")),
    ),
    Domain(
        "hemostasis strategy",
        (_rx(r"\bhemostasis\b"), _rx(r"\bbleeding control\b"), _rx(r"\bvascular control\b")),
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
        "endpoint / completion criteria",
        (_rx(r"\bendpoint\b"), _rx(r"\bcompletion criteria\b"), _rx(r"\bintraoperative confirmation\b"), _rx(r"\bdecompression endpoint\b"), _rx(r"\bresection (threshold|endpoint)\b")),
    ),
    Domain(
        "variants and intraoperative decision branches",
        (_rx(r"\bvariants?\b"), _rx(r"\bdecision branches?\b"), _rx(r"\bdecision tree\b"), _rx(r"\bconversion\b")),
        absence_phrase=(_rx(r"\b(no|not)\b[^.]{0,60}\b(variant|decision branch|alternate approach|conversion)\b"),),
    ),
    Domain(
        "closure and immediate postoperative management",
        (_rx(r"\bclosure\b"), _rx(r"\bpost[- ]?op(?:erative)?\s+management\b"), _rx(r"\bfirst 24 hours\b")),
    ),
    Domain(
        "complications and signatures",
        (_rx(r"\bcomplications?\b"), _rx(r"\bsignatures?\b"), _rx(r"\brescue\b")),
    ),
    Domain(
        "outcomes and evidence",
        (_rx(r"\boutcomes?\b"), _rx(r"\bevidence\b"), _rx(r"\bRCT\b"), _rx(r"\btrials?\b"), _rx(r"\bguidelines?\b"), _rx(r"\bmeta[- ]analysis\b")),
        absence_phrase=(_rx(r"\boutcomes?\b[^.]{0,120}\b(not applicable|no comparative trials|insufficient)\b"),),
    ),
    Domain(
        "patient-specific modifiers",
        (_rx(r"\bpatient[- ]specific\b"), _rx(r"\bhost factors?\b"), _rx(r"\bmodifiers?\b"), _rx(r"\banatomic variants?\b"), _rx(r"\bpediatric\b.*\b(modifications?|considerations?)\b"), _rx(r"\bcomorbid"),),
    ),
    Domain(
        "pre-scrub mental rehearsal",
        (_rx(r"\bpre[- ]?scrub\b"), _rx(r"\bmental rehearsal\b"), _rx(r"\bpre[- ]?op(?:erative)? checklist\b")),
    ),
    Domain(
        "related in this vault",
        (_rx(r"^related in this vault$"), _rx(r"\brelated\b.*\bvault\b")),
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


def _bottom_yaml_block(text: str) -> str:
    lines = text.splitlines()
    start = _bottom_yaml_start_line(text)
    if start is None:
        return ""
    return "\n".join(lines[start - 1 :])


def _declared_complexity(text: str) -> str | None:
    block = _bottom_yaml_block(text)
    if not block:
        return None
    match = YAML_COMPLEXITY_RE.search(block)
    if not match:
        return None
    val = match.group(1).strip().lower().replace("_", "-")
    if val in {"simple", "intermediate", "complex"}:
        return val
    if "complex" in val:
        return "complex"
    if "intermediate" in val:
        return "intermediate"
    if "simple" in val or "bedside" in val:
        return "simple"
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
    target = raw.split("|", 1)[0].split("#", 1)[0].strip()
    return target


def _domain_section(domain: Domain, sections: list[tuple[str, str]]) -> tuple[str, str] | None:
    for heading, body in sections:
        if any(pattern.search(heading) for pattern in domain.patterns):
            return heading, body
    return None


def _domain_addressed_in_body(domain: Domain, text: str) -> bool:
    """Fallback when a domain isn't its own H2 — search body prose for the
    block's signal patterns. Some Coverage Matrix blocks naturally fold under
    larger sections (e.g., op-note essentials inside Closure)."""
    return any(p.search(text) for p in domain.patterns)


def _domain_explicit_absence(domain: Domain, text: str) -> bool:
    if not domain.absence_phrase:
        return False
    return any(p.search(text) for p in domain.absence_phrase)


def _derive_title_from_path(path: Path) -> str:
    """Map a guide/dry-run path to its workflow title for verdict-chain lookup."""
    stem = path.stem
    if stem.endswith(" Dry Run"):
        stem = stem[: -len(" Dry Run")]
    return stem


def _verdict_chain_check(path: Path) -> list[str]:
    """Verify the machine-readable verdict chain is present and approving.

    Required files under data/Sessions/<Title>/verdicts/:
      - decomposition.json
      - research.json
      - map-review-cycle-<N>.json (most recent must be MAP_APPROVED)
      - expert-review-cycle-<N>.json (most recent must be APPROVED)
      - gap-repair-cycle-<N>.json for every REVISION REQUIRED cycle (presence checked
        only when expert-review cycles > 1)
    """
    failures: list[str] = []
    title = _derive_title_from_path(path)
    verdict_dir = SESSIONS_DIR / title / "verdicts"

    if not verdict_dir.exists():
        failures.append(
            f"verdict chain directory missing: {verdict_dir.relative_to(REPO_ROOT)}; "
            "workflow checkpoints did not record machine-readable verdicts"
        )
        return failures

    decomp = verdict_dir / "decomposition.json"
    if not decomp.exists():
        failures.append("verdict chain: decomposition.json missing")
    else:
        try:
            data = json.loads(decomp.read_text())
            if not data.get("coverage_matrix_complete", False):
                failures.append("verdict chain: decomposition.json has coverage_matrix_complete=false")
        except Exception as exc:
            failures.append(f"verdict chain: decomposition.json malformed ({exc})")

    research = verdict_dir / "research.json"
    if not research.exists():
        failures.append("verdict chain: research.json missing")
    else:
        try:
            data = json.loads(research.read_text())
            if not data.get("minimum_floor_met", False):
                shortfalls = data.get("blocks_covered_by_internal_knowledge_only", [])
                if not shortfalls:
                    failures.append(
                        "verdict chain: research.json minimum_floor_met=false and no internal-knowledge justifications recorded"
                    )
        except Exception as exc:
            failures.append(f"verdict chain: research.json malformed ({exc})")

    map_reviews = sorted(verdict_dir.glob("map-review-cycle-*.json"))
    if not map_reviews:
        failures.append("verdict chain: no map-review-cycle-*.json verdict found")
    else:
        latest = map_reviews[-1]
        try:
            data = json.loads(latest.read_text())
            if data.get("verdict") != "MAP_APPROVED":
                failures.append(
                    f"verdict chain: latest map-review ({latest.name}) verdict is "
                    f"{data.get('verdict')!r}, must be 'MAP_APPROVED'"
                )
        except Exception as exc:
            failures.append(f"verdict chain: {latest.name} malformed ({exc})")

    expert_reviews = sorted(verdict_dir.glob("expert-review-cycle-*.json"))
    if not expert_reviews:
        failures.append("verdict chain: no expert-review-cycle-*.json verdict found")
    else:
        latest = expert_reviews[-1]
        try:
            data = json.loads(latest.read_text())
            if data.get("verdict") != "APPROVED":
                failures.append(
                    f"verdict chain: latest expert-review ({latest.name}) verdict is "
                    f"{data.get('verdict')!r}, must be 'APPROVED'"
                )
            # Enforce frontier-outcomes gate for intermediate/complex via research.json,
            # but only call it out here if expert-review approved without it.
            try:
                research_data = json.loads((verdict_dir / "research.json").read_text())
                complexity = research_data.get("complexity", "")
                if complexity in {"intermediate", "complex"} and not research_data.get(
                    "frontier_outcomes_query_present", False
                ):
                    failures.append(
                        "verdict chain: research.json frontier_outcomes_query_present=false "
                        f"for {complexity} procedure; at least one outcomes query must omit --no-frontier"
                    )
            except Exception:
                # research.json issues already reported above
                pass
        except Exception as exc:
            failures.append(f"verdict chain: {latest.name} malformed ({exc})")

    # If any expert-review cycle returned REVISION REQUIRED, a matching gap-repair
    # verdict must exist.
    revision_cycles = []
    for review_path in expert_reviews:
        try:
            data = json.loads(review_path.read_text())
            if data.get("verdict") == "REVISION REQUIRED":
                revision_cycles.append(int(data.get("cycle", 0)))
        except Exception:
            continue
    for cycle in revision_cycles:
        repair = verdict_dir / f"gap-repair-cycle-{cycle}.json"
        if not repair.exists():
            failures.append(
                f"verdict chain: gap-repair-cycle-{cycle}.json missing for expert-review revision cycle {cycle}"
            )

    return failures


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


def validate(path: Path, require_verdict_chain: bool = True) -> list[str]:
    text = path.read_text()
    lines = text.splitlines()
    failures: list[str] = []

    for i, line in enumerate(lines, 1):
        if H1_RE.match(line):
            failures.append(f"line {i}: H1 heading is not allowed (filename is the title)")
            break

    if lines and lines[0].strip() == "---":
        failures.append("line 1: YAML front matter at top is not allowed (YAML belongs at bottom)")

    if WORKFLOW_MODE_MARKER_RE.search(text):
        failures.append("workflow mode markers belong outside the final guide body")

    if WORKFLOW_STATUS_MARKER_RE.search(text):
        failures.append("workflow status markers belong in chat or workflow artifacts, not in the guide body")

    if ANKI_ROUTING_HEADING_RE.search(text):
        failures.append("Anki deck-routing metadata must not appear as a guide body section")

    if WORKFLOW_MEMO_HEADING_RE.search(text):
        failures.append("workflow review or gap-repair memos must not appear in the final guide body")

    if ANY_RAG_CALLOUT_HINT_RE.search(text) and not RAG_CALLOUT_RE.search(text):
        failures.append("RAG callout present but malformed: use exactly `> [!info] RAG Supplemented`")

    bottom_yaml_line = _bottom_yaml_start_line(text)
    if bottom_yaml_line is None:
        failures.append("missing bottom YAML metadata block ending at EOF")

    complexity = _declared_complexity(text)
    body_floor = MIN_BODY_CHARS_BY_COMPLEXITY.get(complexity, MIN_BODY_CHARS_DEFAULT)
    section_floor = MIN_SECTION_CHARS_BY_COMPLEXITY.get(complexity, MIN_SECTION_CHARS_DEFAULT)

    if len(re.sub(r"\s+", "", text)) < body_floor:
        tier = complexity or "unspecified"
        failures.append(
            f"guide body is too sparse for the {tier} complexity tier "
            f"(non-whitespace characters below {body_floor}); declare `complexity: simple|intermediate|complex` "
            f"in bottom YAML if a different tier applies"
        )

    sections = _heading_sections(text)
    for domain in REQUIRED_DOMAINS:
        section = _domain_section(domain, sections)
        if section is None:
            # Allow domain to be addressed in body prose under a different heading
            # (Coverage Matrix is what matters, not exact heading text), or
            # explicitly disclaimed for domains that permit "not applicable."
            if _domain_explicit_absence(domain, text):
                continue
            if domain.label in {"patient-specific modifiers", "outcomes and evidence"} and _domain_addressed_in_body(domain, text):
                continue
            failures.append(f"missing operative domain: {domain.label}")
            continue
        heading, body = section
        if domain.label not in {"related in this vault"} and len(re.sub(r"\s+", "", body)) < section_floor:
            failures.append(
                f"operative domain `{domain.label}` is present but too thin under heading `{heading}` "
                f"(below {section_floor} non-whitespace chars for {complexity or 'default'} tier)"
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

    if require_verdict_chain:
        failures.extend(_verdict_chain_check(path))

    return failures


def _candidate_paths(args: list[str]) -> list[Path]:
    if args:
        return [Path(arg) for arg in args]
    if not GUIDES_DIR.exists():
        return []
    return sorted(path for path in GUIDES_DIR.glob("*.md") if path.name != "INDEX.md")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    require_verdict_chain = "--no-verdict-chain" not in flags

    paths = _candidate_paths(args)
    if not paths:
        print("No operative guides found to validate.")
        return 0

    had_failure = False
    for path in paths:
        if not path.exists():
            print(f"FAIL {path}: file does not exist")
            had_failure = True
            continue
        failures = validate(path, require_verdict_chain=require_verdict_chain)
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
