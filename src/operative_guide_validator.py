#!/usr/bin/env python3
"""
Validator for Operative Guides/*.md structural compliance.

This guard checks that the guide contains the required first-principle
operative knowledge blocks, metadata placement, clean formatting, testable
Mastery Objectives, and a verdict-chain audit trail. It does not enforce length
or count proxies for clinical depth; the Coverage Matrix and independent review
own semantic readiness.

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

try:
    from vault_schema import split_frontmatter
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from .vault_schema import split_frontmatter
try:
    from runtime_paths import RUNTIME_DIR
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from .runtime_paths import RUNTIME_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = RUNTIME_DIR
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


def _current_evidence_source_present(research_data: dict) -> bool:
    """Read the decision-sensitive current-source gate with legacy fallbacks."""
    if "current_evidence_source_present" in research_data:
        return bool(research_data["current_evidence_source_present"])
    if "current_outcomes_source_present" in research_data:
        return bool(research_data["current_outcomes_source_present"])
    return bool(research_data.get("frontier_outcomes_query_present", False))


def _current_outcomes_source_present(research_data: dict) -> bool:
    """Compatibility alias for verdicts and callers using the former name."""
    return _current_evidence_source_present(research_data)


def _current_evidence_required(research_data: dict) -> bool:
    """Use the decision-sensitive gate; retain strict legacy behavior."""
    if "current_evidence_required" in research_data:
        return bool(research_data["current_evidence_required"])
    return research_data.get("complexity") in {"intermediate", "complex"}


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


def _domain_named_as_unresolved(
    domain: Domain, sections: list[tuple[str, str]]
) -> bool:
    """Allow an explicitly incomplete guide to name, rather than hide, a block."""
    unresolved = next(
        (
            body
            for heading, body in sections
            if heading.strip().lower() == "unresolved or weak areas"
        ),
        "",
    )
    return bool(unresolved) and _domain_addressed_in_body(domain, unresolved)


def _derive_title_from_path(path: Path) -> str:
    """Map a guide/dry-run path to its workflow title for verdict-chain lookup."""
    stem = path.stem
    if stem.endswith(" Dry Run"):
        stem = stem[: -len(" Dry Run")]
    return stem


def _verdict_chain_check(path: Path, *, allow_incomplete: bool = False) -> list[str]:
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
            coverage_gate_met = data.get(
                "coverage_gate_met",
                data.get("minimum_floor_met", False),
            )
            if not coverage_gate_met:
                shortfalls = data.get("blocks_covered_by_internal_knowledge_only", [])
                if not shortfalls:
                    failures.append(
                        "verdict chain: research.json coverage_gate_met=false and no internal-knowledge justifications recorded"
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
    latest_expert_data: dict = {}
    if not expert_reviews:
        failures.append("verdict chain: no expert-review-cycle-*.json verdict found")
    else:
        latest = expert_reviews[-1]
        try:
            data = json.loads(latest.read_text())
            latest_expert_data = data
            expert_verdict = data.get("verdict")
            incomplete_revision = (
                allow_incomplete and expert_verdict == "REVISION REQUIRED"
            )
            if expert_verdict != "APPROVED" and not incomplete_revision:
                failures.append(
                    f"verdict chain: latest expert-review ({latest.name}) verdict is "
                    f"{data.get('verdict')!r}, must be 'APPROVED'"
                )
            # Enforce current evidence when the procedure's decisions require it.
            try:
                research_data = json.loads((verdict_dir / "research.json").read_text())
                complexity = research_data.get("complexity", "")
                current_source = _current_evidence_source_present(research_data)
                if (
                    _current_evidence_required(research_data)
                    and not current_source
                    and not incomplete_revision
                ):
                    failures.append(
                        "verdict chain: research.json current_evidence_source_present=false "
                        f"for {complexity or 'this'} procedure with current_evidence_required=true; "
                        "verify a decision-relevant current source"
                    )
            except Exception:
                # research.json issues already reported above
                pass
        except Exception as exc:
            failures.append(f"verdict chain: {latest.name} malformed ({exc})")

    if allow_incomplete:
        authorization = verdict_dir / "incomplete-authorization.json"
        if not authorization.exists():
            failures.append(
                "verdict chain: incomplete-authorization.json missing for incomplete install"
            )
        else:
            try:
                auth = json.loads(authorization.read_text())
                if auth.get("authorized") is not True or auth.get("authorized_by") != "user":
                    failures.append(
                        "verdict chain: incomplete authorization must record authorized=true and authorized_by='user'"
                    )
                accepted = {
                    str(item).strip()
                    for item in auth.get("unresolved_gap_ids", [])
                    if str(item).strip()
                }
                blocking = latest_expert_data.get("blocking_gaps", [])
                required = {
                    str(
                        gap.get("coverage_matrix_block")
                        or gap.get("rubric_block")
                        or ""
                    ).strip()
                    for gap in blocking
                    if isinstance(gap, dict)
                }
                required.discard("")
                missing = sorted(required - accepted)
                if not accepted:
                    failures.append(
                        "verdict chain: incomplete authorization requires unresolved_gap_ids"
                    )
                elif missing:
                    failures.append(
                        "verdict chain: incomplete authorization does not cover expert gaps: "
                        + ", ".join(missing)
                    )
                if not str(auth.get("authorization_context") or "").strip():
                    failures.append(
                        "verdict chain: incomplete authorization requires authorization_context"
                    )
            except Exception as exc:
                failures.append(
                    f"verdict chain: incomplete-authorization.json malformed ({exc})"
                )

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
    mastery_positions = [(name, ln) for name, ln in h2_positions if name == "Mastery Objectives"]
    if not mastery_positions:
        failures.append("missing required H2 `## Mastery Objectives`")
        return

    _, mastery_line = mastery_positions[0]
    next_mastery_h2 = next((ln for _, ln in h2_positions if ln > mastery_line), len(lines) + 1)
    section_end = next_mastery_h2
    section_lines = lines[mastery_line : section_end - 1]
    objectives: list[tuple[int, str]] = []
    for offset, line in enumerate(section_lines, mastery_line + 1):
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
                f"line {ln}: weak Mastery Objective verb in `{objective[:80]}`; use a testable action verb"
            )


def validate(
    path: Path,
    require_verdict_chain: bool = True,
    *,
    allow_incomplete: bool = False,
) -> list[str]:
    raw_text = path.read_text()
    text, parsed_meta = split_frontmatter(raw_text)
    meta = parsed_meta or {}
    lines = text.splitlines()
    failures: list[str] = []

    for i, line in enumerate(lines, 1):
        if H1_RE.match(line):
            failures.append(f"line {i}: H1 heading is not allowed (filename is the title)")
            break

    if not meta:
        failures.append("missing or invalid native YAML frontmatter")
    else:
        for key in ("domain", "summary", "provenance", "complexity"):
            if not str(meta.get(key) or "").strip():
                failures.append(f"frontmatter `{key}` is required for operative guides")
        if not isinstance(meta.get("internal_knowledge_used"), bool):
            failures.append("frontmatter `internal_knowledge_used` must be true or false")

    status = str(meta.get("status") or "current").strip().lower()
    if status not in {"current", "incomplete"}:
        failures.append("frontmatter status must be current or incomplete")
    complexity = str(meta.get("complexity") or "").strip().lower()
    if complexity and complexity not in {"simple", "intermediate", "complex"}:
        failures.append("frontmatter complexity must be simple, intermediate, or complex")
    if status == "incomplete":
        if not allow_incomplete:
            failures.append(
                "incomplete guide requires explicit --allow-incomplete validation"
            )
        if not re.search(r"^## Unresolved Or Weak Areas\s*$", text, flags=re.M):
            failures.append(
                "incomplete guide requires `## Unresolved Or Weak Areas`"
            )
    elif allow_incomplete:
        failures.append("--allow-incomplete requires frontmatter status: incomplete")

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

    sections = _heading_sections(text)
    for domain in REQUIRED_DOMAINS:
        if domain.label == "pre-scrub mental rehearsal" and complexity == "simple":
            continue
        section = _domain_section(domain, sections)
        if section is None:
            # Allow domain to be addressed in body prose under a different heading
            # (Coverage Matrix is what matters, not exact heading text), or
            # explicitly disclaimed for domains that permit "not applicable."
            if _domain_explicit_absence(domain, text):
                continue
            if allow_incomplete and _domain_named_as_unresolved(domain, sections):
                continue
            if domain.label in {"patient-specific modifiers", "outcomes and evidence"} and _domain_addressed_in_body(domain, text):
                continue
            failures.append(f"missing operative domain: {domain.label}")
            continue
        _heading, _body = section

    if RAG_CALLOUT_RE.search(text) and not SOURCE_CITE_RE.search(text):
        failures.append(
            "RAG callout is present but no recognized source citation appears; "
            "cite retrieved sources at the claims they support"
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
        failures.extend(
            _verdict_chain_check(path, allow_incomplete=allow_incomplete)
        )

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
    allow_incomplete = "--allow-incomplete" in flags

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
        failures = validate(
            path,
            require_verdict_chain=require_verdict_chain,
            allow_incomplete=allow_incomplete,
        )
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
