#!/usr/bin/env python3
"""Quality gate and installer for generated Study Material vault notes.

This script gives weaker agents a deterministic finish line for /study-material:
draft wherever the tool sandbox permits, then install only a structurally sound
note into the real Obsidian vault.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


DEFAULT_VAULT_ROOT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
STUDY_DIRNAME = "Study Material"
PROJECT_SHADOW_FRAGMENT = "/agentic-neuro/Documents/Obsidian/"

QUESTION_RE = re.compile(r"(?im)^(?:#{2,6}\s*)?(?:\*\*)?\[?Q\s*0*(\d+)\]?")
DETAILS_RE = re.compile(r"(?is)<details\b.*?</details>")
CLASS_RE = re.compile(
    r"\[(recall|spatial|discrimination|mechanism|integration|clinical|visual)\]",
    re.IGNORECASE,
)
TU_RE = re.compile(r"\bTU-\d{2,3}\b")
AF_RE = re.compile(r"\bAF-\d{3,4}\b")
SOURCE_REF_RE = re.compile(
    r"\b(?:slide|slides|page|pages|chunk|section|source)\s*[:#]?\s*\d*",
    re.IGNORECASE,
)
TOTAL_RE = re.compile(r"total\s+questions?\D{0,12}(\d+)", re.IGNORECASE)
CHUNKS_RE = re.compile(r"chunks\s+processed\D{0,12}(\d+)\s*/\s*(\d+)", re.IGNORECASE)
SECTION_RE_TEMPLATE = r"(?ims)^##\s+{heading}\s*$([\s\S]*?)(?=^##\s+|\Z)"


@dataclass
class GuardResult:
    ok: bool
    path: str
    question_count: int
    answer_count: int
    declared_total: int | None
    teaching_unit_count: int
    atomic_fact_count: int
    fact_coverage_count: int
    complexity_count: int
    chunks_processed: str | None
    errors: list[str]
    warnings: list[str]


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _question_blocks(text: str) -> list[str]:
    matches = list(QUESTION_RE.finditer(text))
    blocks: list[str] = []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        blocks.append(text[match.start() : end])
    return blocks


def _declared_total(text: str) -> int | None:
    match = TOTAL_RE.search(text)
    return int(match.group(1)) if match else None


def _chunk_status(text: str) -> tuple[int, int] | None:
    match = CHUNKS_RE.search(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _section(text: str, heading: str) -> str:
    pattern = SECTION_RE_TEMPLATE.format(heading=re.escape(heading))
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def _validate_path(path: Path, vault_root: Path) -> list[str]:
    errors: list[str] = []
    resolved = str(path.resolve())
    expected_dir = vault_root / STUDY_DIRNAME
    if PROJECT_SHADOW_FRAGMENT in resolved:
        errors.append(
            "target is a workspace shadow path; write to the real Obsidian vault under "
            f"{expected_dir}"
        )
    if not _is_under(path, expected_dir):
        errors.append(f"target must be under {expected_dir}")
    if path.suffix.lower() != ".md":
        errors.append("target must be a markdown file")
    return errors


def validate_content(
    text: str,
    *,
    min_questions: int = 25,
    min_questions_per_chunk: int = 2,
    min_facts_per_chunk: int = 2,
    min_fact_coverage: float = 0.70,
    require_chunks: bool = True,
    require_atomic_facts: bool = True,
    require_question_metadata: bool = True,
) -> tuple[list[str], list[str], dict[str, int | str | float | None]]:
    errors: list[str] = []
    warnings: list[str] = []

    stripped = text.lstrip()
    if stripped.startswith("# "):
        errors.append("vault note must not start with an H1 heading")
    if stripped.startswith("---"):
        errors.append("vault metadata must not be at the top; use bottom YAML only")

    lowered = text.lower()
    if "## concept summary" not in lowered:
        errors.append("missing required section: ## Concept Summary")
    if require_atomic_facts and "## source chunk inventory" not in lowered:
        errors.append("missing required section: ## Source Chunk Inventory")
    if require_atomic_facts and "## atomic fact ledger" not in lowered:
        errors.append("missing required section: ## Atomic Fact Ledger")
    if "## questions" not in lowered:
        errors.append("missing required section: ## Questions")

    blocks = _question_blocks(text)
    question_count = len(blocks)
    answer_count = len(DETAILS_RE.findall(text))
    declared_total = _declared_total(text)
    tu_ids = set(TU_RE.findall(text))
    complexities = {m.group(1).lower() for m in CLASS_RE.finditer(text)}
    chunks = _chunk_status(text)
    fact_ledger = _section(text, "Atomic Fact Ledger")
    atomic_facts = set(AF_RE.findall(fact_ledger))
    question_fact_refs = set()
    for block in blocks:
        question_fact_refs.update(AF_RE.findall(block))
    fact_coverage_ratio = (len(question_fact_refs & atomic_facts) / len(atomic_facts)) if atomic_facts else 0.0

    if question_count < min_questions:
        errors.append(f"too few questions: found {question_count}, require at least {min_questions}")
    if answer_count < question_count:
        errors.append(f"not every question has a <details> answer: {answer_count}/{question_count}")
    if declared_total is None:
        errors.append("missing Total Questions metadata")
    elif declared_total != question_count:
        errors.append(f"Total Questions metadata ({declared_total}) does not match parsed count ({question_count})")

    if len(complexities) < 3:
        errors.append("complexity mix is too narrow; require at least 3 question types")
    if not ({"mechanism", "discrimination", "integration", "clinical"} & complexities):
        errors.append("must include mechanism/discrimination/integration/clinical questions, not recall-only review")

    if require_chunks:
        if chunks is None:
            errors.append("missing Chunks Processed: N / N metadata")
        elif chunks[0] != chunks[1]:
            errors.append(f"chunk coverage incomplete: {chunks[0]} / {chunks[1]}")
        else:
            required_by_chunk = chunks[1] * min_questions_per_chunk
            if question_count < required_by_chunk:
                errors.append(
                    "question density too low for source coverage: "
                    f"{question_count} questions for {chunks[1]} chunks; require at least "
                    f"{required_by_chunk} ({min_questions_per_chunk}/chunk)"
                )
            if require_atomic_facts:
                required_facts = chunks[1] * min_facts_per_chunk
                if len(atomic_facts) < required_facts:
                    errors.append(
                        "atomic fact extraction too shallow: "
                        f"{len(atomic_facts)} facts for {chunks[1]} chunks; require at least "
                        f"{required_facts} ({min_facts_per_chunk}/chunk)"
                    )

    if require_atomic_facts:
        if not atomic_facts:
            errors.append("missing AF-### entries in ## Atomic Fact Ledger")
        elif fact_coverage_ratio < min_fact_coverage:
            errors.append(
                "question bank covers too few atomic facts: "
                f"{len(question_fact_refs & atomic_facts)}/{len(atomic_facts)} "
                f"({fact_coverage_ratio:.0%}); require at least {min_fact_coverage:.0%}"
            )

    if require_question_metadata and blocks:
        bad_complexity = []
        bad_tu = []
        bad_source = []
        bad_fact_ref = []
        for idx, block in enumerate(blocks, start=1):
            header = block.splitlines()[0] if block.splitlines() else ""
            if not CLASS_RE.search(header):
                bad_complexity.append(idx)
            if not TU_RE.search(header):
                bad_tu.append(idx)
            if not SOURCE_REF_RE.search(header):
                bad_source.append(idx)
            if require_atomic_facts and not AF_RE.search(header):
                bad_fact_ref.append(idx)
        if bad_complexity:
            errors.append(f"questions missing complexity in header: {bad_complexity[:8]}")
        if bad_tu:
            errors.append(f"questions missing TU id in header: {bad_tu[:8]}")
        if bad_source:
            errors.append(f"questions missing source reference in header: {bad_source[:8]}")
        if bad_fact_ref:
            errors.append(f"questions missing atomic fact references in header: {bad_fact_ref[:8]}")

    if question_count and len(tu_ids) and question_count < len(tu_ids):
        errors.append(f"1:1 TU-to-question mapping broken: {question_count} questions for {len(tu_ids)} TUs")
    elif question_count and not tu_ids:
        warnings.append("no TU ids found; generation may not be chunk mapped")

    metrics = {
        "question_count": question_count,
        "answer_count": answer_count,
        "declared_total": declared_total,
        "teaching_unit_count": len(tu_ids),
        "atomic_fact_count": len(atomic_facts),
        "fact_coverage_count": len(question_fact_refs & atomic_facts),
        "fact_coverage_ratio": fact_coverage_ratio,
        "complexity_count": len(complexities),
        "chunks_processed": f"{chunks[0]} / {chunks[1]}" if chunks else None,
    }
    return errors, warnings, metrics


def validate_file(
    path: Path,
    *,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    min_questions: int = 25,
    min_questions_per_chunk: int = 2,
    min_facts_per_chunk: int = 2,
    min_fact_coverage: float = 0.70,
    require_chunks: bool = True,
    require_atomic_facts: bool = True,
    require_question_metadata: bool = True,
) -> GuardResult:
    errors = _validate_path(path, vault_root)
    warnings: list[str] = []
    metrics: dict[str, int | str | None] = {
        "question_count": 0,
        "answer_count": 0,
        "declared_total": None,
        "teaching_unit_count": 0,
        "atomic_fact_count": 0,
        "fact_coverage_count": 0,
        "complexity_count": 0,
        "chunks_processed": None,
    }

    if not path.exists():
        errors.append("target file does not exist")
    elif path.is_dir():
        errors.append("target path is a directory")
    else:
        text = path.read_text(encoding="utf-8")
        content_errors, content_warnings, metrics = validate_content(
            text,
            min_questions=min_questions,
            min_questions_per_chunk=min_questions_per_chunk,
            min_facts_per_chunk=min_facts_per_chunk,
            min_fact_coverage=min_fact_coverage,
            require_chunks=require_chunks,
            require_atomic_facts=require_atomic_facts,
            require_question_metadata=require_question_metadata,
        )
        errors.extend(content_errors)
        warnings.extend(content_warnings)

    return GuardResult(
        ok=not errors,
        path=str(path),
        question_count=int(metrics["question_count"] or 0),
        answer_count=int(metrics["answer_count"] or 0),
        declared_total=metrics["declared_total"] if isinstance(metrics["declared_total"], int) else None,
        teaching_unit_count=int(metrics["teaching_unit_count"] or 0),
        atomic_fact_count=int(metrics["atomic_fact_count"] or 0),
        fact_coverage_count=int(metrics["fact_coverage_count"] or 0),
        complexity_count=int(metrics["complexity_count"] or 0),
        chunks_processed=metrics["chunks_processed"] if isinstance(metrics["chunks_processed"], str) else None,
        errors=errors,
        warnings=warnings,
    )


def _title_to_filename(title: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", " ", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise ValueError("title produced an empty filename")
    return f"{cleaned}.md"


def _upsert_index(study_dir: Path) -> None:
    files = sorted(p for p in study_dir.glob("*.md") if p.name != "INDEX.md")
    lines = ["## Study Material Index", ""]
    lines.extend(f"- [[{p.stem}]]" for p in files)
    (study_dir / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def install_draft(
    draft_path: Path,
    title: str,
    *,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    min_questions: int = 25,
    min_questions_per_chunk: int = 2,
    min_facts_per_chunk: int = 2,
    min_fact_coverage: float = 0.70,
    require_chunks: bool = True,
    require_atomic_facts: bool = True,
    require_question_metadata: bool = True,
) -> GuardResult:
    text = draft_path.read_text(encoding="utf-8")
    errors, warnings, _metrics = validate_content(
        text,
        min_questions=min_questions,
        min_questions_per_chunk=min_questions_per_chunk,
        min_facts_per_chunk=min_facts_per_chunk,
        min_fact_coverage=min_fact_coverage,
        require_chunks=require_chunks,
        require_atomic_facts=require_atomic_facts,
        require_question_metadata=require_question_metadata,
    )
    if errors:
        return GuardResult(
            ok=False,
            path=str(draft_path),
            question_count=int(_metrics["question_count"] or 0),
            answer_count=int(_metrics["answer_count"] or 0),
            declared_total=_metrics["declared_total"] if isinstance(_metrics["declared_total"], int) else None,
            teaching_unit_count=int(_metrics["teaching_unit_count"] or 0),
            atomic_fact_count=int(_metrics["atomic_fact_count"] or 0),
            fact_coverage_count=int(_metrics["fact_coverage_count"] or 0),
            complexity_count=int(_metrics["complexity_count"] or 0),
            chunks_processed=_metrics["chunks_processed"] if isinstance(_metrics["chunks_processed"], str) else None,
            errors=errors,
            warnings=warnings,
        )

    study_dir = vault_root / STUDY_DIRNAME
    study_dir.mkdir(parents=True, exist_ok=True)
    target = study_dir / _title_to_filename(title)
    target.write_text(text.rstrip() + "\n", encoding="utf-8")
    _upsert_index(study_dir)
    return validate_file(
        target,
        vault_root=vault_root,
        min_questions=min_questions,
        min_questions_per_chunk=min_questions_per_chunk,
        min_facts_per_chunk=min_facts_per_chunk,
        min_fact_coverage=min_fact_coverage,
        require_chunks=require_chunks,
        require_atomic_facts=require_atomic_facts,
        require_question_metadata=require_question_metadata,
    )


def _emit(result: GuardResult, json_output: bool) -> None:
    if json_output:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
        return
    status = "PASS" if result.ok else "FAIL"
    print(f"{status}: {result.path}")
    print(f"questions={result.question_count} answers={result.answer_count} declared={result.declared_total}")
    print(f"atomic_facts={result.atomic_fact_count} covered_facts={result.fact_coverage_count}")
    if result.chunks_processed:
        print(f"chunks={result.chunks_processed}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    for error in result.errors:
        print(f"error: {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate/install generated Study Material vault notes")
    parser.set_defaults(
        vault_root=str(DEFAULT_VAULT_ROOT),
        min_questions=25,
        min_questions_per_chunk=2,
        min_facts_per_chunk=2,
        min_fact_coverage=0.70,
        json=False,
        no_require_chunks=False,
        no_require_atomic_facts=False,
        no_require_question_metadata=False,
    )

    def add_common_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--vault-root", default=argparse.SUPPRESS)
        p.add_argument("--min-questions", type=int, default=argparse.SUPPRESS)
        p.add_argument("--min-questions-per-chunk", type=int, default=argparse.SUPPRESS)
        p.add_argument("--min-facts-per-chunk", type=int, default=argparse.SUPPRESS)
        p.add_argument("--min-fact-coverage", type=float, default=argparse.SUPPRESS)
        p.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        p.add_argument("--no-require-chunks", action="store_true", default=argparse.SUPPRESS)
        p.add_argument("--no-require-atomic-facts", action="store_true", default=argparse.SUPPRESS)
        p.add_argument("--no-require-question-metadata", action="store_true", default=argparse.SUPPRESS)

    add_common_options(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("path")
    add_common_options(p_validate)

    p_install = sub.add_parser("install")
    p_install.add_argument("--draft", required=True)
    p_install.add_argument("--title", required=True)
    add_common_options(p_install)

    args = parser.parse_args()
    vault_root = Path(args.vault_root)
    common = {
        "vault_root": vault_root,
        "min_questions": args.min_questions,
        "min_questions_per_chunk": args.min_questions_per_chunk,
        "min_facts_per_chunk": args.min_facts_per_chunk,
        "min_fact_coverage": args.min_fact_coverage,
        "require_chunks": not args.no_require_chunks,
        "require_atomic_facts": not args.no_require_atomic_facts,
        "require_question_metadata": not args.no_require_question_metadata,
    }

    if args.command == "validate":
        result = validate_file(Path(args.path), **common)
    else:
        result = install_draft(Path(args.draft), args.title, **common)

    _emit(result, args.json)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
