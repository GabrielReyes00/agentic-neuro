#!/usr/bin/env python3
"""Estimate token overhead for intraoperative-guide workflow artifacts.

This is a calibration helper, not a billing meter. It uses the same rough
chars/4 estimate used in the dry-run analyses and writes a compact ledger that
can be compared across workflow architecture changes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent


def _stat(path: Path) -> dict:
    text = path.read_text(errors="ignore")
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "chars": len(text),
        "words": len(text.split()),
        "est_tokens_chars_div_4": len(text) // 4,
        "lines": text.count("\n") + 1,
    }


def _sum(files: Iterable[Path]) -> dict:
    stats = [_stat(p) for p in files if p.exists() and p.is_file()]
    return {
        "files": len(stats),
        "chars": sum(s["chars"] for s in stats),
        "words": sum(s["words"] for s in stats),
        "est_tokens_chars_div_4": sum(s["est_tokens_chars_div_4"] for s in stats),
        "lines": sum(s["lines"] for s in stats),
        "items": stats,
    }


def build_ledger(session_dir: Path, final_guide: Path | None = None) -> dict:
    session_dir = session_dir.resolve()
    final_files = [final_guide.resolve()] if final_guide and final_guide.exists() else []
    raw_rag = sorted(session_dir.glob("rag_q*.md"))
    verdicts = sorted((session_dir / "verdicts").glob("*.json"))
    structured = [
        session_dir / "decomposition.md",
        session_dir / "source_cards.jsonl",
        session_dir / "source_cards.md",
        session_dir / "coverage_ledger.json",
        session_dir / "research_brief.md",
        session_dir / "knowledge_map.json",
        session_dir / "knowledge_map.md",
    ]
    structured = [p for p in structured if p.exists()]
    all_files = [p for p in session_dir.rglob("*") if p.is_file()] + final_files
    downstream = structured + verdicts + final_files
    downstream_no_raw = [p for p in downstream if p not in raw_rag]
    return {
        "session_dir": str(session_dir.relative_to(REPO_ROOT)),
        "final_guide": str(final_guide.relative_to(REPO_ROOT)) if final_guide and final_guide.exists() else None,
        "estimator": "chars_div_4",
        "raw_rag_audit_only": _sum(raw_rag),
        "structured_artifacts": _sum(structured),
        "review_verdicts": _sum(verdicts),
        "final_guide_stats": _sum(final_files),
        "downstream_context_excluding_raw_rag": _sum(downstream_no_raw),
        "all_artifacts_including_raw_audit": _sum(all_files),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate operative workflow token overhead")
    parser.add_argument("session_dir", help="data/Sessions/<Title> directory")
    parser.add_argument("--final-guide", default="", help="Optional final or dry-run guide path")
    parser.add_argument("--output", default="", help="Output JSON path; defaults to <session_dir>/token_ledger.json")
    args = parser.parse_args()

    session_dir = Path(args.session_dir).resolve()
    final_guide = Path(args.final_guide).resolve() if args.final_guide else None
    ledger = build_ledger(session_dir, final_guide)
    output = Path(args.output) if args.output else session_dir / "token_ledger.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "raw_rag_est_tokens": ledger["raw_rag_audit_only"]["est_tokens_chars_div_4"],
        "downstream_no_raw_est_tokens": ledger["downstream_context_excluding_raw_rag"]["est_tokens_chars_div_4"],
        "all_artifacts_est_tokens": ledger["all_artifacts_including_raw_audit"]["est_tokens_chars_div_4"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
