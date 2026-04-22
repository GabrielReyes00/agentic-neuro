#!/usr/bin/env python3
"""Central CLI for long-term agentic memory.

This module is intentionally thin. The durable implementation lives in
knowledge_graph.py, but agent workflows should increasingly call this file so
the memory contract has one stable entry point as the backend evolves.
"""

from __future__ import annotations

import argparse
import json
import sys

from knowledge_graph import KnowledgeGraph


def _try_enqueue_anki(args: argparse.Namespace, result: dict) -> None:
    """Best-effort real-time Anki queue append. Never raises.

    Writes one candidate per active answer so the queue-based flush can
    synthesize cloze cards. Suppression (correct + shallow, no signal) is
    handled inside `enqueue_candidate`.
    """
    try:
        exchange_id = int(result.get("exchange_id") or 0)
        if exchange_id <= 0:
            return
        from anki_realtime import enqueue_candidate
        enqueue_candidate(
            session_ts=args.session_ts,
            exchange_id=exchange_id,
            skill=args.skill,
            topic=args.topic,
            concept=args.concept,
            question=args.question,
            answer=args.answer,
            correction=getattr(args, "correction", "") or "",
            correct=args.correct,
            error_type=getattr(args, "error_type", "") or "",
            misconception=getattr(args, "misconception", "") or "",
            root_cause=getattr(args, "root_cause", "") or "",
            teaching_approach=getattr(args, "teaching_approach", "") or "",
            depth=getattr(args, "depth", 1) or 1,
            domain=getattr(args, "domain", "") or "",
            breakthrough=bool(getattr(args, "breakthrough", False)),
        )
    except Exception as exc:  # noqa: BLE001
        # Silent: learning sessions must never break because of Anki.
        print(f"[memory_orchestrator] anki enqueue skipped: {exc}", file=sys.stderr)


def _try_update_learner_model(kg: KnowledgeGraph, result: dict) -> None:
    """Best-effort adaptive learner model refresh for one exchange."""
    try:
        exchange_id = int(result.get("exchange_id") or 0)
        if exchange_id <= 0:
            return
        from learner_model import update_after_exchange
        lm = update_after_exchange(kg.conn, exchange_id)
        if lm.get("ok"):
            result["learner_model"] = lm
    except Exception as exc:  # noqa: BLE001
        print(f"[memory_orchestrator] learner model update skipped: {exc}", file=sys.stderr)


def _resolve_session_for_write(
    args: argparse.Namespace,
    kg: KnowledgeGraph,
    topic_attr: str = "topic",
) -> dict:
    """Resolve accidental per-turn timestamps to the active memory session."""
    resolution = {}
    if hasattr(args, "session_ts") and hasattr(kg, "resolve_memory_session"):
        resolution = kg.resolve_memory_session(
            session_ts=args.session_ts,
            skill=getattr(args, "skill", ""),
            topic_text=getattr(args, topic_attr, "") or "",
        )
        if resolution.get("ok") and resolution.get("session_ts"):
            args.session_ts = str(resolution["session_ts"])
    return resolution


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
    p_ra.add_argument("--error-process", default="", dest="error_process")
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

    p_cp = subparsers.add_parser("context-pack", help="Build a fixed-section V2 memory context pack")
    p_cp.add_argument("query")
    p_cp.add_argument("--topic", default=None)
    p_cp.add_argument("--skill", default=None)
    p_cp.add_argument("--intent", default="teach", choices=["teach", "review", "plan", "handoff"])
    p_cp.add_argument("--max-tokens", type=int, default=1200, dest="max_tokens")
    p_cp.add_argument("--text", action="store_true", help="Print plaintext context pack instead of JSON")

    p_dp = subparsers.add_parser("document-profile", help="Get or store a document study-mode profile")
    p_dp.add_argument("--doc", required=True, dest="doc_path")
    p_dp.add_argument("--doc-type", default="study-material", dest="doc_type")
    p_dp.add_argument("--content-sample", default="", dest="content_sample")
    p_dp.add_argument("--source-kind", default="", dest="source_kind",
                      choices=["", "review_material", "generated_report", "oral_board_case_seed", "primary_source", "study_material", "unknown"])
    p_dp.add_argument("--study-mode", default="", dest="study_mode",
                      choices=["", "ask", "rapid_review", "deep_understanding", "oral_boards"])
    p_dp.add_argument("--pacing-goal", default="", dest="pacing_goal",
                      choices=["", "throughput", "mastery", "exam_simulation", "user_selected"])
    p_dp.add_argument("--mode-reason", default="", dest="mode_reason")
    p_dp.add_argument("--confidence", type=float, default=None, dest="mode_confidence")
    p_dp.add_argument("--apply", action="store_true")
    p_dp.add_argument("--text", action="store_true")

    p_con = subparsers.add_parser("consolidate", help="Run V2 sleep-time memory consolidation")
    p_con.add_argument("--session-ts", default=None, dest="session_ts")
    p_con.add_argument("--mode", default="dry-run", choices=["dry-run", "apply"])
    p_con.add_argument("--no-embed", action="store_true", dest="no_embed")

    p_eval = subparsers.add_parser("eval-memory", help="Run local V2 memory regression checks")
    p_eval.add_argument("--suite", default="local")
    p_eval.add_argument("--write-report", default=None, dest="write_report")

    p_replay = subparsers.add_parser("replay-memory", help="Dry-run replay audit for V2 derived state")
    p_replay.add_argument("--from-events", action="store_true", dest="from_events")
    p_replay.add_argument("--dry-run", action="store_true", dest="dry_run")

    p_bf = subparsers.add_parser("backfill-v2", help="Plan/apply V2 backfill from existing memory rows")
    p_bf.add_argument("--apply", action="store_true")
    p_bf.add_argument("--limit", type=int, default=500)

    p_cls = subparsers.add_parser("classify-event", help="Classify which V2 memory write an agent should use")
    p_cls.add_argument("--content", required=True)
    p_cls.add_argument("--learner-answer", default="", dest="learner_answer")
    p_cls.add_argument("--correct", type=int, choices=[0, 1, 2], default=None)
    p_cls.add_argument("--teaching-only", action="store_true", dest="teaching_only")
    p_cls.add_argument("--case-context", default="", dest="case_context")
    p_cls.add_argument("--transfer-context", default="", dest="transfer_context")

    p_tr = subparsers.add_parser("record-transfer", help="Record cross-context transfer validation")
    p_tr.add_argument("--session-ts", required=True, dest="session_ts")
    p_tr.add_argument("--turn", required=True, type=int)
    p_tr.add_argument("--skill", required=True)
    p_tr.add_argument("--topic", required=True)
    p_tr.add_argument("--concept", required=True)
    p_tr.add_argument("--context", required=True, dest="transfer_context")
    p_tr.add_argument("--answer", default="", dest="learner_answer")
    p_tr.add_argument("--success", action="store_true")
    p_tr.add_argument("--transfer-level", default="applied_to_vignette", dest="transfer_level")
    p_tr.add_argument("--correction", default="")
    p_tr.add_argument("--error-type", default="", dest="error_type")
    p_tr.add_argument("--error-process", default="", dest="error_process")
    p_tr.add_argument("--domain", default="")

    p_case = subparsers.add_parser("record-case", help="Record a clinical or operative case memory")
    p_case.add_argument("--session-ts", required=True, dest="session_ts")
    p_case.add_argument("--turn", required=True, type=int)
    p_case.add_argument("--skill", required=True)
    p_case.add_argument("--topic", required=True)
    p_case.add_argument("--case-context", required=True, dest="case_context")
    p_case.add_argument("--decision-point", required=True, dest="decision_point")
    p_case.add_argument("--learner-action", default="", dest="learner_action")
    p_case.add_argument("--outcome", default="")
    p_case.add_argument("--teaching-target", default="", dest="teaching_target")
    p_case.add_argument("--concept", default="")
    p_case.add_argument("--domain", default="")

    p_core = subparsers.add_parser("promote-core-profile", help="Promote durable learner-profile memories")
    p_core.add_argument("--statement", default="")
    p_core.add_argument("--apply", action="store_true")

    p_rot = subparsers.add_parser("rotation-pack", help="Generate a pre-rotation memory pack")
    p_rot.add_argument("--rotation", required=True)
    p_rot.add_argument("--max", type=int, default=8, dest="max_items")
    p_rot.add_argument("--text", action="store_true")

    p_ss = subparsers.add_parser("session-summary", help="Summarize what changed in the learner model")
    p_ss.add_argument("--session-ts", required=True, dest="session_ts")
    p_ss.add_argument("--apply", action="store_true")
    p_ss.add_argument("--text", action="store_true")

    p_fin = subparsers.add_parser("finish-session", help="Close, summarize, consolidate, and audit a learning session")
    p_fin.add_argument("--session-ts", default="", dest="session_ts")
    p_fin.add_argument("--skill", default="")
    p_fin.add_argument("--topic", default="")
    p_fin.add_argument("--mode", default="dry-run", choices=["dry-run", "apply"])
    p_fin.add_argument("--repair-fragments", action="store_true", dest="repair_fragments")
    p_fin.add_argument("--window-minutes", type=int, default=240, dest="window_minutes")
    p_fin.add_argument("--no-embed", action="store_true", dest="no_embed")
    p_fin.add_argument("--text", action="store_true")

    p_cal = subparsers.add_parser("calibration-pack", help="Generate confidence-calibration teaching guidance")
    p_cal.add_argument("--max", type=int, default=8, dest="max_items")
    p_cal.add_argument("--text", action="store_true")

    p_sp = subparsers.add_parser("study-plan", help="Build a memory-driven study plan")
    p_sp.add_argument("--hours", type=float, default=1.0)
    p_sp.add_argument("--rotation", default=None)
    p_sp.add_argument("--focus", default=None)

    p_em = subparsers.add_parser("estimate-mastery", help="Estimate mastery for a topic/concept")
    p_em.add_argument("--topic", default="")
    p_em.add_argument("--concept", default="")

    p_ni = subparsers.add_parser("next-item", help="Pick the next adaptive learning item")
    p_ni.add_argument("--mode", default="zpd", choices=["eig", "zpd", "remediate"])
    p_ni.add_argument("--topic", default="")
    p_ni.add_argument("--limit", type=int, default=5)

    p_rec = subparsers.add_parser("recommend-approach", help="Recommend a teaching approach")
    p_rec.add_argument("--domain", default="")
    p_rec.add_argument("--topic-id", type=int, default=None, dest="topic_id")
    p_rec.add_argument("--concept", default="", dest="concept_text")
    p_rec.add_argument("--error-type", default="", dest="error_type")
    p_rec.add_argument("--difficulty-band", default="", dest="difficulty_band")

    p_probe = subparsers.add_parser("proactive-probe", help="Surface or pop unknown-unknown probes")
    p_probe.add_argument("--surface", action="store_true")
    p_probe.add_argument("--pop", action="store_true")
    p_probe.add_argument("--limit", type=int, default=5)
    p_probe.add_argument("--output", default="data/Sessions/proactive_probe.json")

    p_ts = subparsers.add_parser("tutor-strategy", help="Build hidden tutor control strategy")
    p_ts.add_argument("query")
    p_ts.add_argument("--topic", default="")
    p_ts.add_argument("--concept", default="")
    p_ts.add_argument("--skill", default="")
    p_ts.add_argument("--probe-json", default="")
    p_ts.add_argument("--output", default="")

    subparsers.add_parser("doctor", help="Audit memory integrity")
    subparsers.add_parser("reindex-fts", help="Rebuild the memory FTS index")

    p_rb = subparsers.add_parser("rebuild", help="Rebuild missing derived rows from memory_events")
    p_rb.add_argument("--apply", action="store_true")

    p_cl = subparsers.add_parser("cleanup", help="Plan/apply safe duplicate cleanup")
    p_cl.add_argument("--apply", action="store_true")
    p_cl.add_argument("--backup", action="store_true")

    # Real-time Anki integration
    p_fa = subparsers.add_parser(
        "flush-anki-queue",
        help="Synthesize queued Anki candidates into cloze cards and dispatch",
    )
    p_fa.add_argument("--dry-run", action="store_true", dest="dry_run")
    p_fa.add_argument("--skip-anki", action="store_true", dest="skip_anki")
    p_fa.add_argument("--anki-url", default="http://localhost:8765", dest="anki_url")
    p_fa.add_argument("--max-batch", type=int, default=8, dest="max_batch")
    p_fa.add_argument("--min-queue", type=int, default=1, dest="min_queue",
                      help="Skip flush if queue has fewer than N entries (for throttled flushes)")

    p_ss = subparsers.add_parser(
        "anki-stats-sync",
        help="Pull AnkiConnect review stats and fold into concept_mastery",
    )
    p_ss.add_argument("--anki-url", default="http://localhost:8765", dest="anki_url")

    return parser


def _dispatch(args: argparse.Namespace, kg: KnowledgeGraph) -> dict:
    """Execute a parsed memory orchestrator command."""
    if args.command == "record-answer":
        resolution = _resolve_session_for_write(args, kg)
        result = kg.log_answer(
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
            error_process=args.error_process,
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
        if resolution and (resolution.get("changed") or resolution.get("warning")):
            result["session_resolution"] = resolution
        # Real-time Anki queue enqueue — best effort, never blocks the caller.
        _try_enqueue_anki(args, result)
        _try_update_learner_model(kg, result)
        return result
    if args.command == "record-passive":
        resolution = _resolve_session_for_write(args, kg)
        if not kg.is_memory_session_enabled(args.session_ts, args.skill):
            return {
                "ok": False,
                "error": "passive memory capture requires an enabled memory_session",
                "hint": "Run: python3 src/memory_orchestrator.py session --session-ts TS --skill S --enabled --scope study_session",
                "session_resolution": resolution,
            }
        event_id = kg.append_memory_event(
            event_type="teaching_exposure",
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
        v2_result = {}
        if event_id > 0 and hasattr(kg, "record_passive_teaching_v2"):
            v2_result = kg.record_passive_teaching_v2(
                session_ts=args.session_ts,
                turn_number=args.turn,
                skill=args.skill,
                topic_name=args.topic,
                concept_text=args.concept,
                content_text=args.content,
                domain=args.domain,
                memory_event_id=event_id,
            )
        result = {"ok": event_id > 0, "memory_event_id": event_id, "memory_v2": v2_result}
        if resolution and (resolution.get("changed") or resolution.get("warning")):
            result["session_resolution"] = resolution
        return result
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
        guidance = kg.memory_guidance(
            args.query,
            topic_name=args.topic,
            skill=args.skill,
            max_results=args.max_results,
            hybrid_semantic=args.hybrid_semantic and not args.no_hybrid_semantic,
            semantic_fallback_threshold=max(0, args.semantic_threshold),
        )
        if hasattr(kg, "context_pack") and "context_pack" not in guidance:
            guidance["context_pack"] = kg.context_pack(
                args.query,
                topic_name=args.topic,
                skill=args.skill,
                intent="teach",
                max_tokens=900,
                log_retrieval=False,
            )
        return guidance
    if args.command == "context-pack":
        pack = kg.context_pack(
            args.query,
            topic_name=args.topic,
            skill=args.skill,
            intent=args.intent,
            max_tokens=args.max_tokens,
        )
        if args.text:
            return {"ok": True, "text": pack.get("text", "")}
        return pack
    if args.command == "document-profile":
        profile = kg.document_profile(
            doc_path=args.doc_path,
            doc_type=args.doc_type,
            content_sample=args.content_sample,
            source_kind=args.source_kind,
            preferred_study_mode=args.study_mode,
            pacing_goal=args.pacing_goal,
            mode_reason=args.mode_reason,
            mode_confidence=args.mode_confidence,
            apply=args.apply,
        )
        if args.text:
            mode = profile.get("preferred_study_mode") or "ask"
            source = profile.get("source_kind") or "unknown"
            ask = "yes" if profile.get("should_ask") else "no"
            lines = [
                f"Document: {profile.get('doc_path', args.doc_path)}",
                f"Source kind: {source}",
                f"Preferred study mode: {mode}",
                f"Pacing goal: {profile.get('pacing_goal') or 'user_selected'}",
                f"Mode confidence: {float(profile.get('mode_confidence') or 0.0):.2f}",
                f"Ask user before drilling: {ask}",
                f"Directive: {profile.get('agent_directive') or ''}",
            ]
            if profile.get("mode_reason"):
                lines.append(f"Reason: {profile['mode_reason']}")
            return {"ok": profile.get("ok", False), "text": "\n".join(lines)}
        return profile
    if args.command == "consolidate":
        return kg.consolidate_memory_v2(
            session_ts=args.session_ts,
            mode=args.mode,
            embed=not args.no_embed,
        )
    if args.command == "eval-memory":
        return kg.eval_memory(suite=args.suite, write_report=args.write_report)
    if args.command == "replay-memory":
        return kg.replay_memory_v2(
            from_events=bool(args.from_events),
            dry_run=True if not args.dry_run else args.dry_run,
        )
    if args.command == "backfill-v2":
        return kg.memory_v2_backfill(apply=args.apply, limit=args.limit)
    if args.command == "classify-event":
        return kg.classify_memory_capture_v2(
            content=args.content,
            learner_answer=args.learner_answer,
            answer_correct=args.correct,
            teaching_only=args.teaching_only,
            case_context=args.case_context,
            transfer_context=args.transfer_context,
        )
    if args.command == "record-transfer":
        resolution = _resolve_session_for_write(args, kg)
        result = kg.record_transfer_v2(
            session_ts=args.session_ts,
            turn_number=args.turn,
            skill=args.skill,
            topic_name=args.topic,
            concept_text=args.concept,
            transfer_context=args.transfer_context,
            learner_answer=args.learner_answer,
            success=args.success,
            transfer_level=args.transfer_level,
            correction_text=args.correction,
            error_type=args.error_type,
            error_process=args.error_process,
            domain=args.domain,
        )
        if resolution and (resolution.get("changed") or resolution.get("warning")):
            result["session_resolution"] = resolution
        return result
    if args.command == "record-case":
        resolution = _resolve_session_for_write(args, kg)
        result = kg.record_case_memory_v2(
            session_ts=args.session_ts,
            turn_number=args.turn,
            skill=args.skill,
            topic_name=args.topic,
            case_context=args.case_context,
            decision_point=args.decision_point,
            learner_action=args.learner_action,
            outcome=args.outcome,
            teaching_target=args.teaching_target,
            concept_text=args.concept,
            domain=args.domain,
        )
        if resolution and (resolution.get("changed") or resolution.get("warning")):
            result["session_resolution"] = resolution
        return result
    if args.command == "promote-core-profile":
        return kg.promote_core_profile_v2(statement=args.statement, apply=args.apply)
    if args.command == "rotation-pack":
        pack = kg.pre_rotation_pack_v2(args.rotation, max_items=args.max_items)
        if args.text:
            return {"ok": True, "text": pack.get("text", "")}
        return pack
    if args.command == "session-summary":
        summary = kg.session_summary_v2(session_ts=args.session_ts, apply=args.apply)
        if args.text:
            return {"ok": True, "text": summary.get("text", "")}
        return summary
    if args.command == "finish-session":
        result = kg.finish_learning_session_v2(
            session_ts=args.session_ts,
            skill=args.skill,
            topic_name=args.topic,
            mode=args.mode,
            repair_fragments=args.repair_fragments,
            window_minutes=args.window_minutes,
            embed=not args.no_embed,
        )
        if args.text:
            return {"ok": result.get("ok", False), "text": result.get("text", "")}
        return result
    if args.command == "calibration-pack":
        pack = kg.calibration_training_pack_v2(max_items=args.max_items)
        if args.text:
            return {"ok": True, "text": pack.get("text", "")}
        return pack
    if args.command == "study-plan":
        return kg.study_plan(hours=args.hours, rotation=args.rotation, focus=args.focus)
    if args.command == "estimate-mastery":
        from learner_model import estimate_mastery
        return estimate_mastery(kg.conn, topic=args.topic, concept=args.concept)
    if args.command == "next-item":
        from learner_model import next_item
        return next_item(kg.conn, mode=args.mode, topic=args.topic, limit=args.limit)
    if args.command == "recommend-approach":
        from teaching_recommender import recommend_approach
        return recommend_approach(
            kg.conn,
            domain=args.domain,
            topic_id=args.topic_id,
            concept_text=args.concept_text,
            error_type=args.error_type,
            difficulty_band=args.difficulty_band,
        )
    if args.command == "proactive-probe":
        from unknown_unknowns_scout import pop_probe, surface_unknown_unknowns
        if args.surface:
            return surface_unknown_unknowns(kg.conn, limit=args.limit)
        return pop_probe(kg.conn, output_path=args.output if args.pop or not args.surface else None)
    if args.command == "tutor-strategy":
        from tutor_strategy import _load_probe, build_tutor_strategy
        result = build_tutor_strategy(
            kg.conn,
            query=args.query,
            topic=args.topic,
            concept=args.concept,
            skill=args.skill,
            proactive_probe=_load_probe(args.probe_json) if args.probe_json else {},
        )
        if args.output:
            from pathlib import Path
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        return result
    if args.command == "doctor":
        return kg.memory_doctor()
    if args.command == "reindex-fts":
        return kg.reindex_memory_fts()
    if args.command == "rebuild":
        return kg.memory_rebuild(apply=args.apply)
    if args.command == "cleanup":
        return kg.memory_cleanup_plan(apply=args.apply, backup=args.backup)
    if args.command == "flush-anki-queue":
        from anki_realtime import QUEUE_PATH, _read_queue, flush_queue
        pending = _read_queue(QUEUE_PATH)
        if len(pending) < args.min_queue:
            return {
                "ok": True,
                "skipped": True,
                "reason": f"queue_size {len(pending)} < min_queue {args.min_queue}",
                "queue_size": len(pending),
            }
        return flush_queue(
            dry_run=args.dry_run,
            skip_anki=args.skip_anki,
            anki_url=args.anki_url,
            max_batch=args.max_batch,
        )
    if args.command == "anki-stats-sync":
        from anki_stats_sync import sync_stats
        result = sync_stats(anki_url=args.anki_url)
        return result.__dict__
    return {"ok": False, "error": f"unknown command: {args.command}"}


def main() -> None:
    quiet = "--quiet" in sys.argv[1:]
    if quiet:
        sys.argv = [sys.argv[0], *[arg for arg in sys.argv[1:] if arg != "--quiet"]]

    parser = _build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    kg = KnowledgeGraph()
    try:
        data = _dispatch(args, kg)
        if quiet:
            return
        if args.command in {
            "context-pack",
            "document-profile",
            "rotation-pack",
            "session-summary",
            "finish-session",
            "calibration-pack",
        } and getattr(args, "text", False):
            print(data.get("text", ""))
        else:
            print(json.dumps(data, indent=2, default=str))
    finally:
        kg.close()


if __name__ == "__main__":
    main()
