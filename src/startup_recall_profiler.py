#!/usr/bin/env python3
"""Profile the startup-recall path used by study-review.

This is an agent/debugging helper. It does not write learner memory; it runs the
same read path as `study_memory.py startup-recall` and emits compact timing JSON.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
VAULT_ROOT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")


class TimingRecorder:
    def __init__(self) -> None:
        self.rows: list[dict[str, float | str]] = []
        self.totals: dict[str, float] = defaultdict(float)
        self.counts: dict[str, int] = defaultdict(int)

    def add(self, label: str, elapsed_ms: float) -> None:
        self.rows.append({"label": label, "ms": round(elapsed_ms, 3)})
        self.totals[label] += elapsed_ms
        self.counts[label] += 1

    def wrap(self, owner: Any, name: str, label: str | None = None) -> None:
        if not hasattr(owner, name):
            return
        original = getattr(owner, name)
        if not callable(original):
            return
        timing_label = label or name

        def timed(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                self.add(timing_label, (time.perf_counter() - start) * 1000)

        setattr(owner, name, timed)

    def aggregate(self) -> list[dict[str, float | int | str]]:
        rows: list[dict[str, float | int | str]] = []
        for label, total in sorted(self.totals.items(), key=lambda item: item[1], reverse=True):
            rows.append({
                "label": label,
                "total_ms": round(total, 3),
                "calls": self.counts[label],
                "avg_ms": round(total / max(1, self.counts[label]), 3),
            })
        return rows


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _read_doc_chars(doc_path: str) -> int | None:
    if not doc_path:
        return None
    path = Path(doc_path)
    candidates = [path]
    if not path.is_absolute():
        candidates.append(VAULT_ROOT / doc_path)
        candidates.append(REPO_ROOT / doc_path)
    for candidate in candidates:
        try:
            if candidate.exists():
                return len(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def _has_vault_payload(payload: dict[str, Any]) -> bool:
    text = json.dumps(payload, ensure_ascii=False)
    return "vault_retriever" in text or "vault_intelligence" in text or "vault_notes" in text


def _summarize_payload(payload: dict[str, Any], payload_chars: int, doc_chars: int | None) -> dict[str, Any]:
    startup = payload.get("startup_recall") if isinstance(payload.get("startup_recall"), dict) else {}
    brief = payload.get("planning_brief") if isinstance(payload.get("planning_brief"), dict) else {}
    handoff = brief.get("handoff") if isinstance(brief.get("handoff"), dict) else {}
    anki_status = startup.get("anki_feedback_status") if isinstance(startup.get("anki_feedback_status"), dict) else {}
    overlay = brief.get("anki_overlay") if isinstance(brief.get("anki_overlay"), dict) else {}
    return {
        "payload_chars": payload_chars,
        "doc_chars": doc_chars,
        "ready_to_teach": startup.get("ready_to_teach"),
        "pre_question_expansion_allowed": startup.get("pre_question_expansion_allowed"),
        "profile": startup.get("profile"),
        "mode": startup.get("mode"),
        "routing_required": startup.get("routing_required"),
        "auto_expanded": startup.get("auto_expanded"),
        "has_vault_payload": _has_vault_payload(payload),
        "anki_status": anki_status.get("status") or overlay.get("status"),
        "planning_brief_keys": sorted(str(key) for key in brief.keys()),
        "handoff_next_action_chars": len(str(handoff.get("next_action") or "")),
        "handoff_summary_chars": len(str(handoff.get("summary") or "")),
    }


def _instrument(recorder: TimingRecorder, study_memory: Any, anki_feedback: Any) -> None:
    for name in (
        "_get_db",
        "_migrate_schema",
        "resolve_topic",
        "retrieval_summary",
        "_planning_brief_for_summary",
        "_compact_doc_review_payload",
        "context_graph_focus_for_summary",
        "graph_signals_for_summary",
        "shadow_rule_signals_for_summary",
        "curated_summaries_for_summary",
    ):
        recorder.wrap(study_memory, name, f"study_memory.{name}")

    if anki_feedback is not None:
        for name in (
            "build_session_anki_profile",
            "invoke",
            "_load_chroma_collection",
            "_semantic_chroma_candidates",
            "_fetch_live_candidate_cards",
        ):
            recorder.wrap(anki_feedback, name, f"anki_feedback.{name}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    recorder = TimingRecorder()

    start = time.perf_counter()
    study_memory = importlib.import_module("study_memory")
    recorder.add("import.study_memory", (time.perf_counter() - start) * 1000)

    start = time.perf_counter()
    try:
        anki_feedback = importlib.import_module("anki_feedback")
    except Exception:
        anki_feedback = None
    recorder.add("import.anki_feedback", (time.perf_counter() - start) * 1000)

    _instrument(recorder, study_memory, anki_feedback)

    doc_chars = None
    if args.read_doc:
        start = time.perf_counter()
        doc_chars = _read_doc_chars(args.doc)
        recorder.add("doc.read", (time.perf_counter() - start) * 1000)

    start = time.perf_counter()
    conn = study_memory._get_db()
    recorder.add("startup.open_db_outer", (time.perf_counter() - start) * 1000)

    start = time.perf_counter()
    raw = study_memory.startup_recall(
        conn,
        topic=args.topic,
        doc_path=args.doc,
        global_mode=args.global_mode,
        limit=args.limit,
        scaffold_limit=args.scaffold_limit,
        include_global_scaffolds=args.include_global_scaffolds,
        context=args.context,
        lens=args.lens,
        service=args.service,
        site=args.site,
        rotation_id=args.rotation,
        profile=args.profile,
    )
    startup_ms = (time.perf_counter() - start) * 1000
    recorder.add("startup.recall_outer", startup_ms)

    payload = json.loads(raw)
    payload_chars = len(raw)
    summary = _summarize_payload(payload, payload_chars, doc_chars)
    summary["startup_recall_total_ms"] = round(startup_ms, 3)

    return {
        "ok": True,
        "command": {
            "topic": args.topic,
            "doc": args.doc,
            "global": args.global_mode,
            "profile": args.profile,
            "lens": args.lens,
            "context": args.context,
        },
        "summary": summary,
        "timings": recorder.aggregate(),
        "events": recorder.rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile study-review startup recall")
    parser.add_argument("--topic", default="")
    parser.add_argument("--doc", default="")
    parser.add_argument("--global", dest="global_mode", action="store_true")
    parser.add_argument("--profile", choices=["auto", "doc", "memory", "audit"], default="auto")
    parser.add_argument("--lens", choices=["formal", "general", "service"], default="formal")
    parser.add_argument("--context", default="")
    parser.add_argument("--service", default="")
    parser.add_argument("--site", default="")
    parser.add_argument("--rotation", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--scaffold-limit", type=int, default=None)
    parser.add_argument("--include-global-scaffolds", action="store_true")
    parser.add_argument("--read-doc", action="store_true", help="Also measure/find the target document size")
    args = parser.parse_args(argv)

    try:
        print(_json_dumps(run(args)))
        return 0
    except Exception as exc:  # noqa: BLE001 - diagnostic CLI should emit JSON on failure.
        print(_json_dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
