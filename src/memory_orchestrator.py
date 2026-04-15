#!/usr/bin/env python3
"""Central CLI for long-term agentic memory.

This module is intentionally thin. The durable implementation lives in
knowledge_graph.py, but agent workflows should increasingly call this file so
the memory contract has one stable entry point as the backend evolves.
"""

from __future__ import annotations

import argparse
import json

from knowledge_graph import KnowledgeGraph


def _build_parser() -> argparse.ArgumentParser:
    """Build the memory orchestrator CLI parser."""
    parser = argparse.ArgumentParser(description="Agentic memory orchestrator")
    subparsers = parser.add_subparsers(dest="command")

    p_ra = subparsers.add_parser("record-answer", help="Record one active answer")
    p_ra.add_argument("--session-ts", required=True, dest="session_ts")
    p_ra.add_argument("--turn", required=True, type=int)
    p_ra.add_argument("--skill", required=True)
    p_ra.add_argument("--topic", required=True)
    p_ra.add_argument("--concept", required=True)
    p_ra.add_argument("--question", required=True)
    p_ra.add_argument("--answer", required=True)
    p_ra.add_argument("--correct", required=True, type=int, choices=[0, 1, 2])
    p_ra.add_argument("--correction", default="")
    p_ra.add_argument("--error-type", default="", dest="error_type")
    p_ra.add_argument("--misconception", default="")
    p_ra.add_argument("--root-cause", default="", dest="root_cause")
    p_ra.add_argument("--remediation", default="")
    p_ra.add_argument("--teaching-approach", default="", dest="teaching_approach")
    p_ra.add_argument("--retrieval-sources", default="", dest="retrieval_sources")
    p_ra.add_argument("--breakthrough", action="store_true")
    p_ra.add_argument("--insight", default="")
    p_ra.add_argument("--depth", type=int, default=1)
    p_ra.add_argument("--domain", default="")
    p_ra.add_argument("--response-confidence", default="", dest="response_confidence",
                      choices=["", "high", "low"])

    p_pt = subparsers.add_parser("record-passive", help="Record passive teaching under explicit session consent")
    p_pt.add_argument("--session-ts", required=True, dest="session_ts")
    p_pt.add_argument("--turn", required=True, type=int)
    p_pt.add_argument("--skill", required=True)
    p_pt.add_argument("--topic", required=True)
    p_pt.add_argument("--content", required=True)
    p_pt.add_argument("--concept", default="")
    p_pt.add_argument("--domain", default="")

    p_ms = subparsers.add_parser("session", help="Set memory mode for a session")
    p_ms.add_argument("--session-ts", required=True, dest="session_ts")
    p_ms.add_argument("--skill", required=True)
    p_ms.add_argument("--topic", default="")
    p_ms.add_argument("--enabled", action="store_true")
    p_ms.add_argument("--scope", default="", dest="consent_scope")
    p_ms.add_argument("--status", default="active", choices=["active", "complete", "paused"])
    p_ms.add_argument("--notes", default="")

    p_g = subparsers.add_parser("guidance", help="Get teaching guidance from memory")
    p_g.add_argument("query")
    p_g.add_argument("--topic", default=None)
    p_g.add_argument("--skill", default=None)
    p_g.add_argument("--max", type=int, default=5, dest="max_results")
    p_g.add_argument(
        "--semantic",
        action="store_true",
        dest="hybrid_semantic",
        help="Allow Lance semantic fallback when fast recall is sparse",
    )
    p_g.add_argument(
        "--no-hybrid-semantic",
        action="store_true",
        dest="no_hybrid_semantic",
        help="Disable Lance semantic fallback when structured recall is sparse",
    )
    p_g.add_argument(
        "--semantic-threshold",
        type=int,
        default=3,
        dest="semantic_threshold",
        help="Augment with semantic search when fast-path has fewer than this many hits (default 3)",
    )

    p_sp = subparsers.add_parser("study-plan", help="Build a memory-driven study plan")
    p_sp.add_argument("--hours", type=float, default=1.0)
    p_sp.add_argument("--rotation", default=None)
    p_sp.add_argument("--focus", default=None)

    subparsers.add_parser("doctor", help="Audit memory integrity")
    subparsers.add_parser("reindex-fts", help="Rebuild the memory FTS index")

    p_rb = subparsers.add_parser("rebuild", help="Rebuild missing derived rows from memory_events")
    p_rb.add_argument("--apply", action="store_true")

    p_cl = subparsers.add_parser("cleanup", help="Plan/apply safe duplicate cleanup")
    p_cl.add_argument("--apply", action="store_true")
    p_cl.add_argument("--backup", action="store_true")
    return parser


def _dispatch(args: argparse.Namespace, kg: KnowledgeGraph) -> dict:
    """Execute a parsed memory orchestrator command."""
    if args.command == "record-answer":
        return kg.log_answer(
            session_ts=args.session_ts,
            turn_number=args.turn,
            skill=args.skill,
            topic_name=args.topic,
            concept_text=args.concept,
            question_text=args.question,
            answer_text=args.answer,
            answer_correct=args.correct,
            correction_text=args.correction,
            error_type=args.error_type,
            misconception=args.misconception,
            root_cause=args.root_cause,
            remediation=args.remediation,
            teaching_approach=args.teaching_approach,
            retrieval_sources=args.retrieval_sources,
            breakthrough=args.breakthrough,
            insight_text=args.insight,
            domain=args.domain,
            depth=args.depth,
            response_confidence=args.response_confidence,
        )
    if args.command == "record-passive":
        if not kg.is_memory_session_enabled(args.session_ts, args.skill):
            return {
                "ok": False,
                "error": "passive memory capture requires an enabled memory_session",
                "hint": "Run: python3 src/memory_orchestrator.py session --session-ts TS --skill S --enabled --scope study_session",
            }
        event_id = kg.append_memory_event(
            event_type="passive_teaching",
            session_ts=args.session_ts,
            turn_number=args.turn,
            skill=args.skill,
            topic_name=args.topic,
            concept_text=args.concept,
            actor="agent",
            content_text=args.content,
            payload={"passive": True, "domain": args.domain},
            source=args.skill,
            domain=args.domain,
        )
        return {"ok": event_id > 0, "memory_event_id": event_id}
    if args.command == "session":
        return kg.set_memory_session(
            session_ts=args.session_ts,
            skill=args.skill,
            topic_text=args.topic,
            memory_enabled=args.enabled,
            consent_scope=args.consent_scope,
            status=args.status,
            notes=args.notes,
        )
    if args.command == "guidance":
        return kg.memory_guidance(
            args.query,
            topic_name=args.topic,
            skill=args.skill,
            max_results=args.max_results,
            hybrid_semantic=args.hybrid_semantic and not args.no_hybrid_semantic,
            semantic_fallback_threshold=max(0, args.semantic_threshold),
        )
    if args.command == "study-plan":
        return kg.study_plan(hours=args.hours, rotation=args.rotation, focus=args.focus)
    if args.command == "doctor":
        return kg.memory_doctor()
    if args.command == "reindex-fts":
        return kg.reindex_memory_fts()
    if args.command == "rebuild":
        return kg.memory_rebuild(apply=args.apply)
    if args.command == "cleanup":
        return kg.memory_cleanup_plan(apply=args.apply, backup=args.backup)
    return {"ok": False, "error": f"unknown command: {args.command}"}


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    kg = KnowledgeGraph()
    try:
        data = _dispatch(args, kg)
        print(json.dumps(data, indent=2, default=str))
    finally:
        kg.close()


if __name__ == "__main__":
    main()
