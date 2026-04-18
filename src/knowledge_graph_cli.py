#!/usr/bin/env python3
"""Command-line interface for knowledge_graph.py."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from kg_constants import BASE_DIR
from knowledge_graph import KnowledgeGraph, _DEPTH_LABELS


def _print_status(data: dict) -> None:
    """Pretty-print the status summary."""
    if not data:
        print("No data available.")
        return

    print("=" * 60)
    print("  KNOWLEDGE GRAPH STATUS")
    print("=" * 60)
    print(f"  Total topics:  {data.get('total_topics', 0)}")
    print(f"  Total events:  {data.get('total_events', 0)}")
    print(f"  Avg confidence: {data.get('avg_confidence', 0.0):.3f}")
    print()

    # By category
    by_cat = data.get("by_category", {})
    if by_cat:
        print("  Topics by Category:")
        for cat, cnt in by_cat.items():
            print(f"    {cat:<25s} {cnt:>4d}")
        print()

    # By depth
    by_depth = data.get("by_depth", {})
    if by_depth:
        print("  Topics by Depth:")
        for key, cnt in by_depth.items():
            level = int(key.replace("depth_", ""))
            label = _DEPTH_LABELS.get(level, f"level-{level}")
            print(f"    {level} ({label:<22s}) {cnt:>4d}")
        print()

    # Recent topics
    recent = data.get("recent_topics", [])
    if recent:
        print("  Recent Topics (last 10):")
        print(f"    {'Topic':<35s} {'Conf':>6s} {'Depth':>6s}  Last Seen")
        print(f"    {'-'*35} {'-'*6} {'-'*6}  {'-'*20}")
        for t in recent:
            name = t.get("canonical_name", "?")[:35]
            conf = t.get("confidence", 0.0)
            depth = t.get("depth", 0)
            last = (t.get("last_seen") or "")[:19]
            print(f"    {name:<35s} {conf:>6.3f} {depth:>6d}  {last}")

    print("=" * 60)


def _print_topic_detail(data: dict) -> None:
    """Pretty-print topic detail."""
    if "error" in data:
        print(f"Error: {data['error']}")
        return

    topic = data.get("topic", {})
    summary = data.get("summary", {})
    events = data.get("events", [])

    print("=" * 60)
    print(f"  TOPIC: {topic.get('display_name', topic.get('canonical_name', '?'))}")
    print("=" * 60)
    print(f"  Canonical:     {topic.get('canonical_name', '')}")
    print(f"  Category:      {topic.get('category', '') or '(none)'}")
    print(f"  Confidence:    {summary.get('current_confidence', 0.0):.3f}")
    depth = summary.get("current_depth", 0)
    print(f"  Depth:         {depth} ({_DEPTH_LABELS.get(depth, '?')})")
    print(f"  Encounters:    {summary.get('total_encounters', 0)}")
    print(f"  First seen:    {(summary.get('first_seen') or '')[:19]}")
    print(f"  Last seen:     {(summary.get('last_seen') or '')[:19]}")
    aliases = json.loads(topic.get("aliases", "[]")) if topic.get("aliases") else []
    if aliases:
        print(f"  Aliases:       {', '.join(aliases)}")
    print()

    if events:
        print(f"  Signal History ({len(events)} events):")
        print(f"    {'Timestamp':<20s} {'Source':<12s} {'Signal':<22s} {'Depth':>5s} {'Delta':>7s}")
        print(f"    {'-'*20} {'-'*12} {'-'*22} {'-'*5} {'-'*7}")
        for e in events[:30]:  # cap display at 30
            ts = (e.get("timestamp") or "")[:19]
            src = (e.get("source") or "")[:12]
            sig = (e.get("signal_type") or "")[:22]
            dep = e.get("depth_at_event", 0)
            delta = e.get("confidence_delta", 0.0)
            sign = "+" if delta >= 0 else ""
            print(f"    {ts:<20s} {src:<12s} {sig:<22s} {dep:>5d} {sign}{delta:>6.3f}")
        if len(events) > 30:
            print(f"    ... and {len(events) - 30} more events")

    # Concept mastery dictionary
    cm = data.get("concept_mastery", {})
    known = cm.get("known", [])
    unknown = cm.get("unknown", [])
    if known or unknown:
        print()
        print(f"  Concept Mastery ({len(known)} known, {len(unknown)} gaps):")
        if known:
            print(f"    ✅ KNOWN:")
            for c in known:
                confirmed = c.get("times_confirmed", 0)
                print(f"       • {c['concept_text']} (confirmed {confirmed}x, last: {c.get('last_updated', '')[:10]})")
        if unknown:
            print(f"    ❌ GAPS:")
            for c in unknown:
                missed = c.get("times_missed", 0)
                line = f"       • {c['concept_text']} (missed {missed}x, last: {c.get('last_updated', '')[:10]})"
                if c.get("error_type"):
                    line += f"\n         ↳ Error type: {c['error_type']}"
                if c.get("misconception"):
                    line += f"\n         ↳ Misconception: {c['misconception']}"
                if c.get("remediation"):
                    line += f"\n         ↳ Remediation: {c['remediation']}"
                print(line)

    print("=" * 60)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, default=str))


def _print_counted(key: str, data: list) -> None:
    _print_json({key: data, "count": len(data)})



def _dispatch_command(args: argparse.Namespace, kg: KnowledgeGraph) -> None:
    """Execute a parsed knowledge-graph CLI command."""
    if args.command == "status":
        data = kg.status()
        _print_status(data)

    elif args.command == "topic_detail":
        data = kg.topic_detail(args.topic)
        _print_topic_detail(data)

    elif args.command == "log_event":
        event_id = kg.log_signal(
            topic_name=args.topic,
            source=args.source,
            signal_type=args.signal_type,
            depth_at_event=args.depth,
            category=args.category,
        )
        print(f"Logged {args.signal_type} event #{event_id} for '{args.topic}' (source={args.source}, depth={args.depth})")

    elif args.command == "log_bootcamp":
        # Map outcome to signal type
        outcome_map = {
            "pass": "correct_recall",
            "partial": "partial_recall",
            "fail": "incorrect_recall",
        }
        signal = outcome_map.get(args.outcome.lower(), "partial_recall")
        meta = {"module": args.module, "outcome": args.outcome}

        # Parse calibration signals if provided [Refinement #1]
        if args.calibration:
            try:
                cal_data = json.loads(args.calibration)
                if isinstance(cal_data, list) and cal_data:
                    meta["calibration"] = cal_data
            except json.JSONDecodeError:
                print("Warning: --calibration must be valid JSON, ignoring", file=sys.stderr)

        topics = [t.strip() for t in args.topics.split(",") if t.strip()]
        weaknesses = [w.strip() for w in args.weaknesses.split(",") if w.strip()] if args.weaknesses else []

        for topic in topics:
            kg.log_signal(
                topic_name=topic,
                source="bootcamp",
                signal_type=signal,
                depth_at_event=3,
                metadata=meta,
            )

        for weakness in weaknesses:
            kg.log_signal(
                topic_name=weakness,
                source="bootcamp",
                signal_type="weakness_identified",
                depth_at_event=3,
                metadata=meta,
            )

        cal_count = len(meta.get("calibration", []))
        cal_msg = f", {cal_count} calibration signal(s)" if cal_count else ""
        print(f"Logged {len(topics)} topic(s) and {len(weaknesses)} weakness(es) from bootcamp module '{args.module}'{cal_msg}")

    elif args.command == "log_study":
        topics = [t.strip() for t in args.topics.split(",") if t.strip()]
        understood = [c.strip() for c in args.understood.split(",") if c.strip()] if args.understood else []
        gaps = [c.strip() for c in args.gaps.split(",") if c.strip()] if args.gaps else []
        gap_details = None
        if args.gap_details:
            try:
                gap_details = json.loads(args.gap_details)
            except json.JSONDecodeError:
                print("Warning: --gap-details must be valid JSON, ignoring", file=sys.stderr)
        kg.log_study_session(
            topics=topics,
            understood=understood,
            gaps=gaps,
            gap_details=gap_details,
            depth=args.depth,
            source=args.source,
        )
        n_gaps = len(gaps) + (len(gap_details) if gap_details else 0)
        print(f"Logged study session: {len(topics)} topic(s), {len(understood)} understood, {n_gaps} gap(s)")

    elif args.command == "log_pattern":
        kg.log_learning_pattern(
            pattern_type=args.pattern_type,
            description=args.description,
            evidence=args.evidence,
        )
        print(f"Logged learning pattern: {args.pattern_type}")

    elif args.command == "add_topic":
        canonical = KnowledgeGraph._normalize_topic(args.name)
        topic_id = kg._upsert_topic(canonical, args.name, args.category)

        if args.priority is not None:
            try:
                now = datetime.now(timezone.utc).isoformat()
                domain = args.category or "general"
                with kg.conn:
                    kg.conn.execute(
                        """INSERT OR IGNORE INTO curriculum_topics
                           (domain, topic_name, display_name, priority, source, added_ts)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (domain, canonical, args.name, args.priority, args.source, now),
                    )
                print(f"Added topic '{args.name}' (id={topic_id}) with curriculum priority={args.priority}, source='{args.source}'")
            except Exception as exc:
                print(f"Topic created but curriculum entry failed: {exc}", file=sys.stderr)
        else:
            print(f"Added topic '{args.name}' (id={topic_id}, category='{args.category}')")

    elif args.command == "backfill":
        result = kg.backfill_from_telemetry(args.telemetry)
        print(f"Backfill complete: {result['topics_created']} topics created, {result['events_logged']} events logged")

    elif args.command == "load_curriculum":
        result = kg.load_curriculum(args.path)
        print(f"Curriculum loaded: {result['loaded']} topics, {result['skipped']} already existed")

    elif args.command == "gaps":
        recs = kg.generate_recommendations(
            n=args.top,
            rotation_filter=args.rotation,
            apply_decay_first=True,
        )
        print(kg.format_recommendations(recs, rotation=args.rotation))

    elif args.command == "apply_decay":
        kg.apply_decay()
        print("Decay applied to all topics.")

    elif args.command == "sync_anki":
        result = kg.sync_anki(url=args.url)
        if result.get("status") == "unavailable":
            print(f"Anki is not available: {result.get('reason', 'unknown')}")
        elif result.get("status") == "synced":
            print(f"Anki sync complete: {result['cards']} cards, {result['matched']} matched to topics, {result['unmatched']} unmatched")
        else:
            print(f"Anki sync: {result}")

    elif args.command == "dashboard":
        data = kg.dashboard()
        _print_json(data)

    elif args.command == "topics":
        data = kg.topics_list(
            domain=args.domain,
            min_confidence=args.min_confidence,
            max_confidence=args.max_confidence,
            depth=args.depth,
            sort_by=args.sort,
            only_studied=args.only_studied,
            limit=args.limit,
        )
        _print_json(data)

    elif args.command == "activity":
        data = kg.activity_feed(n=args.n)
        _print_json(data)

    elif args.command == "review_queue":
        data = kg.get_review_queue(n=args.n, domain=args.domain)
        _print_counted("due_concepts", data)

    elif args.command == "context":
        data = kg.learner_context(args.query)
        output_str = json.dumps(data, indent=2, default=str)
        print(output_str)
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output_str, encoding="utf-8")

    elif args.command == "milestone_report":
        data = kg.milestone_report()
        _print_json(data)

    elif args.command == "transfer_candidates":
        data = kg.get_transfer_candidates(n=args.n)
        _print_counted("candidates", data)

    elif args.command == "log_transfer":
        kg.log_transfer_outcome(
            concept_text=args.concept,
            topic_name=args.topic,
            new_context=args.context,
            success=args.success,
        )
        outcome = "SUCCESS" if args.success else "FAILURE"
        print(f"Logged transfer {outcome}: '{args.concept}' tested in context: '{args.context}'")

    elif args.command == "cognitive_patterns":
        data = kg.detect_cognitive_patterns()
        _print_counted("patterns", data)

    elif args.command == "calibration_profile":
        data = kg.compute_calibration_profile()
        _print_json(data)

    elif args.command == "confusable_pairs":
        data = kg.get_confusable_pairs(topic=args.topic)
        _print_counted("pairs", data)

    elif args.command == "doc_status":
        data = kg.get_doc_status(args.doc_path)
        _print_json(data)

    elif args.command == "log_doc_progress":
        covered = [c.strip() for c in args.covered.split(",") if c.strip()] if args.covered else []
        understood = [c.strip() for c in args.understood.split(",") if c.strip()] if args.understood else []
        missed: list = []
        if args.missed:
            try:
                missed = json.loads(args.missed)
            except json.JSONDecodeError:
                missed = [c.strip() for c in args.missed.split(",") if c.strip()]
        kg.log_doc_progress(
            doc_path=args.doc,
            doc_type=args.doc_type,
            covered=covered,
            understood=understood,
            missed=missed,
            coverage_pct=args.coverage_pct,
            total_concepts=args.total_concepts,
        )
        print(
            f"Logged doc progress: {args.doc} | "
            f"{args.coverage_pct:.0f}% coverage | "
            f"{len(understood)} understood | {len(missed)} missed"
        )

    # ── Redesign Phase: new command handlers ──

    elif args.command == "concept_review_queue":
        data = kg.concept_review_queue_srs(n=args.n, domain=args.domain)
        _print_counted("due_concepts", data)

    elif args.command == "log_session_narrative":
        topics = [t.strip() for t in args.topics.split(",") if t.strip()]
        teaching_failures = []
        if args.teaching_failures:
            try:
                teaching_failures = json.loads(args.teaching_failures)
            except json.JSONDecodeError:
                print("Warning: --teaching-failures must be valid JSON, ignoring", file=sys.stderr)
        teaching_successes = []
        if args.teaching_successes:
            try:
                teaching_successes = json.loads(args.teaching_successes)
            except json.JSONDecodeError:
                teaching_successes = [s.strip() for s in args.teaching_successes.split("|") if s.strip()]
        key_confusions = []
        if args.key_confusions:
            try:
                key_confusions = json.loads(args.key_confusions)
            except json.JSONDecodeError:
                print("Warning: --key-confusions must be valid JSON, ignoring", file=sys.stderr)
        depth_profile = {}
        if args.depth_profile:
            try:
                depth_profile = json.loads(args.depth_profile)
            except json.JSONDecodeError:
                print("Warning: --depth-profile must be valid JSON, ignoring", file=sys.stderr)
        nid = kg.log_session_narrative(
            skill=args.skill,
            topics=topics,
            summary=args.summary,
            teaching_successes=teaching_successes,
            teaching_failures=teaching_failures,
            next_session_strategy=args.next_session_strategy,
            key_confusions=key_confusions,
            depth_profile=depth_profile,
            duration_turns=args.duration_turns,
            session_success_rate=getattr(args, "session_success_rate", None),
        )
        print(f"Logged session narrative (id={nid}) for skill='{args.skill}', {len(topics)} topic(s)")

    elif args.command == "last_session_narrative":
        data = kg.get_last_session_narrative(skill=args.skill, topic=args.topic)
        if data:
            # Strip internal DB fields — only emit actionable teaching fields
            _INTERNAL = {
                "narrative_id", "duration_turns", "linked_signal_ids",
                "session_success_rate", "strategy_outcome", "topic_fingerprint",
                "depth_profile_json", "teaching_successes",
            }
            _print_json({k: v for k, v in data.items() if k not in _INTERNAL})
        else:
            _print_json({"status": "none_found"})

    elif args.command == "blocking_gaps":
        data = kg.get_blocking_gaps(args.topic)
        _print_counted("blocking_gaps", data)

    elif args.command == "concept_chain":
        data = kg.concept_chain(args.concept, topic_name=args.topic)
        _print_json(data)

    elif args.command == "add_concept_relationship":
        kg.add_concept_relationship(
            concept_a=args.concept_a,
            concept_b=args.concept_b,
            relationship=args.relationship,
            topic_a=args.topic_a,
            topic_b=args.topic_b,
            strength=args.strength,
            notes=args.notes,
            source="manual",
        )
        print(f"Added relationship: '{args.concept_a}' {args.relationship} '{args.concept_b}'")

    elif args.command == "topic_specificity_check":
        data = kg.validate_topic_specificity(args.topic_name)
        _print_json(data)

    elif args.command == "fine_grained_gaps":
        data = kg.fine_grained_gaps(top=args.top, domain=args.domain)
        _print_counted("gaps", data)

    elif args.command == "migrate_confusion_matrix":
        result = kg.migrate_confusion_matrix()
        print(f"Migration complete: {result.get('migrated', 0)} pairs migrated, "
              f"{result.get('skipped', 0)} skipped (already present)")
        if result.get("error"):
            print(f"Error: {result['error']}", file=sys.stderr)

    # ── Iteration 2: Prerequisite seeding ──
    elif args.command == "seed_prerequisites":
        result = kg.seed_prerequisites_from_cooccurrence()
        _print_json(result)

    # ── Iteration 3: ZPD + learning velocity ──
    elif args.command == "difficulty_target":
        data = kg.recommend_difficulty_target()
        _print_json(data)

    elif args.command == "study_plan":
        data = kg.study_plan(hours=args.hours, rotation=args.rotation, focus=args.focus)
        _print_json(data)

    elif args.command == "add_concept_alias":
        data = kg.add_concept_alias(
            alias=args.alias,
            canonical_concept=args.canonical_concept,
            topic_name=args.topic,
            source=args.source,
        )
        _print_json(data)

    elif args.command == "resolve_concept":
        topic_id = None
        if args.topic:
            topic_id = kg._upsert_topic(kg._normalize_topic(args.topic), args.topic.strip())
            if topic_id < 0:
                topic_id = None
        data = {
            "concept": args.concept,
            "topic": args.topic,
            "resolved": kg._resolve_concept_text(args.concept, topic_id),
            "topic_id": topic_id,
        }
        _print_json(data)

    elif args.command == "learning_velocity":
        data = kg.learning_velocity(domain=args.domain, n_sessions=args.n)
        _print_json(data)

    # ── Iteration 4: Blind spot detection ──
    elif args.command == "unknown_unknowns":
        data = kg.detect_unknown_unknowns(query=args.topic, n=args.n)
        _print_counted("unknown_unknowns", data)

    elif args.command == "misconception_clusters":
        data = kg.misconception_clusters()
        _print_counted("clusters", data)

    elif args.command == "seed_topic_adjacency":
        result = kg.auto_seed_topic_adjacency()
        _print_json(result)

    elif args.command == "backfill_topic_fingerprints":
        result = kg.backfill_topic_fingerprints()
        _print_json(result)

    # ── Obsidian Redesign commands ──

    elif args.command == "generate_error_atlas":
        data = kg.generate_error_atlas()
        _print_json(data)

    elif args.command == "export_concept_stubs":
        data = kg.export_concept_stubs(only_studied=args.only_studied)
        _print_json(data)

    elif args.command == "acgme_readiness":
        data = kg.acgme_readiness(pgy=args.pgy)
        _print_json(data)

    # ── Episodic Memory commands ──

    elif args.command == "log_answer":
        data = kg.log_answer(
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
        _print_json(data)

    elif args.command == "log_exchange":
        xid = kg.log_exchange(
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
            teaching_approach=args.teaching_approach,
            retrieval_sources=args.retrieval_sources,
            breakthrough=args.breakthrough,
            insight_text=args.insight,
            signal_event_id=args.signal_event_id,
            domain=args.domain,
            depth=args.depth,
        )
        label = {0: "incorrect", 1: "partial", 2: "correct"}.get(args.correct, "?")
        print(f"Logged exchange #{xid}: [{label}] concept='{args.concept}' (turn {args.turn})")

    elif args.command == "exchange_history":
        data = kg.exchange_history(
            topic_name=args.topic,
            concept_text=args.concept,
            error_type=args.error_type,
            answer_correct=args.correct,
            skill=args.skill,
            days_back=args.days,
            top=args.top,
            breakthrough_only=args.breakthrough,
        )
        _print_counted("exchanges", data)

    elif args.command == "recall":
        correct_val = args.correct
        if args.errors_only:
            correct_val = 0

        recall_kwargs = dict(
            query=args.query or "",
            topic_name=args.topic,
            domain=args.domain,
            error_type=args.error_type,
            answer_correct=correct_val,
            skill=args.skill,
            days_back=args.days,
            max_results=args.max_results,
            use_semantic=not args.sqlite_only,
        )
        if args.compact:
            data = kg.recall_episodes_compact(**recall_kwargs)
        else:
            data = kg.recall_episodes(**recall_kwargs)

        output = json.dumps(data, indent=2, default=str)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"Recalled {len(data.get('exchanges', []))} exchange(s), "
                  f"{len(data.get('episode_summaries', []))} summary(ies) -> {args.output}")
        else:
            print(output)

    elif args.command == "teaching_effectiveness":
        data = kg.teaching_effectiveness(
            domain=args.domain,
            days_back=args.days,
        )
        _print_json(data)

    elif args.command == "concept_evolution":
        data = kg.concept_evolution_history(
            concept_text=args.concept,
            topic_name=args.topic,
            days_back=args.days,
            limit=args.limit,
        )
        _print_counted("evolution", data)

    elif args.command == "derive_session_confusions":
        data = kg.derive_session_confusions(
            session_ts=args.session_ts,
            skill=args.skill,
            hours_back=args.hours,
        )
        _print_counted("confusions", data)

    elif args.command == "domain_error_profile":
        data = kg.domain_error_profile(domain=args.domain, days_back=args.days)
        _print_json(data)


def _build_parser() -> argparse.ArgumentParser:
    """Build the knowledge-graph CLI parser."""
    parser = argparse.ArgumentParser(
        description="Knowledge Graph — learner topic mastery tracker",
    )
    subparsers = parser.add_subparsers(dest="command")

    # status
    subparsers.add_parser("status", help="Show knowledge graph summary")

    # topic_detail
    p_td = subparsers.add_parser("topic_detail", help="Show detail for a single topic")
    p_td.add_argument("topic", type=str, help="Topic name to look up")

    # log_event
    p_le = subparsers.add_parser("log_event", help="Log a signal event")
    p_le.add_argument("--topic", required=True, help="Topic name")
    p_le.add_argument("--source", required=True, help="Signal source (rag, bootcamp, anki, intraop, manual)")
    p_le.add_argument("--signal-type", required=True, help="Signal type")
    p_le.add_argument("--depth", type=int, default=1, help="Depth at event (0-4)")
    p_le.add_argument("--category", default="", help="Topic category")

    # log_bootcamp
    p_lb = subparsers.add_parser("log_bootcamp", help="Log bootcamp session results")
    p_lb.add_argument("--topics", required=True, help="Comma-separated topics covered")
    p_lb.add_argument("--weaknesses", default="", help="Comma-separated weaknesses identified")
    p_lb.add_argument("--module", default="", help="Bootcamp module name")
    p_lb.add_argument("--outcome", default="partial", help="Outcome: pass, partial, fail")
    p_lb.add_argument("--calibration", default="", help='JSON list of calibration signals: [{"concept":"...","response_confidence":"high|low","correct":true|false}]')

    # log_study_session (agent-level post-interaction signal — per-concept mastery)
    p_ls = subparsers.add_parser("log_study", help="Log per-concept learning signal (what was understood vs. missed)")
    p_ls.add_argument("--topics", required=True, help="Comma-separated topic names covered")
    p_ls.add_argument("--understood", default="", help="Comma-separated concepts the user demonstrated understanding of")
    p_ls.add_argument("--gaps", default="", help="Comma-separated concepts the user missed, got wrong, or was confused by")
    p_ls.add_argument("--gap-details", default="", help="JSON list of rich gap entries: [{\"concept\":\"...\",\"error_type\":\"...\",\"misconception\":\"...\",\"remediation\":\"...\"}]")
    p_ls.add_argument("--depth", type=int, default=1, help="Depth of material (1=surface, 2=mechanistic, 3=decision-making)")
    p_ls.add_argument("--source", default="rag", help="Capability source: rag, bootcamp, intraop")

    # log_learning_pattern (meta-cognitive pattern)
    p_lp = subparsers.add_parser("log_pattern", help="Log a meta-cognitive learning pattern")
    p_lp.add_argument("--type", required=True, dest="pattern_type", help="Pattern type: strong_mechanistic_learner, cross_contamination_prone, numerical_recall_weak, visual_spatial_strength, application_transfer_gap")
    p_lp.add_argument("--description", required=True, help="Human-readable pattern description")
    p_lp.add_argument("--evidence", default="", help="Supporting observation from this session")

    # add_topic
    p_at = subparsers.add_parser("add_topic", help="Add or update a topic")
    p_at.add_argument("--name", required=True, help="Topic name")
    p_at.add_argument("--category", default="", help="Topic category")
    p_at.add_argument("--source", default="attending-directive", help="Source for curriculum entry")
    p_at.add_argument("--priority", type=int, default=None, help="Curriculum priority (1=core, 2=important, 3=advanced)")

    # backfill
    p_bf = subparsers.add_parser("backfill", help="Backfill from telemetry log")
    p_bf.add_argument("--telemetry", required=True, help="Path to search_telemetry.jsonl")

    # load_curriculum
    load_parser = subparsers.add_parser("load_curriculum", help="Load curriculum from JSON skeleton")
    load_parser.add_argument("--path", default=str(BASE_DIR / "data" / "curriculum_skeleton.json"))

    # gaps / recommendations
    gaps_parser = subparsers.add_parser("gaps", help="Show study gap recommendations")
    gaps_parser.add_argument("--top", type=int, default=10)
    gaps_parser.add_argument("--rotation", default=None)

    # apply_decay (manual trigger)
    subparsers.add_parser("apply_decay", help="Apply forgetting-curve decay to all topics")

    # sync_anki
    sync_anki_parser = subparsers.add_parser("sync_anki", help="Sync Anki review data into knowledge graph")
    sync_anki_parser.add_argument("--url", default="http://localhost:8765")

    # dashboard (JSON for agent display)
    subparsers.add_parser("dashboard", help="Domain progress dashboard (JSON output)")

    # topics (filtered list, JSON for agent display)
    topics_parser = subparsers.add_parser("topics", help="Filtered topic list (JSON output)")
    topics_parser.add_argument("--domain", default=None, help="Filter by domain (e.g. 'Vascular')")
    topics_parser.add_argument("--min-confidence", type=float, default=None)
    topics_parser.add_argument("--max-confidence", type=float, default=None)
    topics_parser.add_argument("--depth", type=int, default=None)
    topics_parser.add_argument("--sort", default="confidence", choices=["confidence", "confidence_asc", "encounters", "recent", "alpha"])
    topics_parser.add_argument("--only-studied", action="store_true")
    topics_parser.add_argument("--limit", type=int, default=50)

    # activity (recent signal events, JSON for agent display)
    activity_parser = subparsers.add_parser("activity", help="Recent activity feed (JSON output)")
    activity_parser.add_argument("--n", type=int, default=30)

    # review_queue (spaced verification — concepts due for re-testing)
    rq_parser = subparsers.add_parser("review_queue", help="Concepts due for spaced verification (JSON output)")
    rq_parser.add_argument("--n", type=int, default=10, help="Max concepts to return")
    rq_parser.add_argument("--domain", default=None, help="Filter by curriculum domain")

    # context (prefrontal cortex — learner-aware pre-flight check)
    context_parser = subparsers.add_parser("context", help="Learner context for a query (JSON output)")
    context_parser.add_argument("query", help="The user's query to contextualize")
    context_parser.add_argument("--output", default=None, metavar="PATH",
                                help="Write JSON output to this file path in addition to stdout")

    # milestone_report
    subparsers.add_parser("milestone_report", help="ACGME milestone competency dashboard (JSON output)")

    # transfer_candidates
    tc_parser = subparsers.add_parser("transfer_candidates", help="Concepts ready for cross-context transfer validation (JSON)")
    tc_parser.add_argument("--n", type=int, default=5, help="Max candidates to return")

    # log_transfer
    lt_parser = subparsers.add_parser("log_transfer", help="Log outcome of a transfer validation attempt")
    lt_parser.add_argument("--concept", required=True, help="Concept text that was tested")
    lt_parser.add_argument("--topic", required=True, help="Original topic the concept belongs to")
    lt_parser.add_argument("--context", required=True, help="New clinical context where transfer was tested")
    lt_parser.add_argument("--success", action="store_true", help="Set if the learner succeeded")

    # cognitive_patterns (Refinement #2 — process-level error detection)
    subparsers.add_parser("cognitive_patterns", help="Detect recurring cognitive error types across topics (JSON)")

    # calibration_profile (Refinement #1 — confidence calibration)
    subparsers.add_parser("calibration_profile", help="Compute confidence calibration profile from bootcamp data (JSON)")

    # confusable_pairs (Refinement #3 — proactive discrimination)
    cp_parser = subparsers.add_parser("confusable_pairs", help="Query confusable concept pairs from confusion matrix (JSON)")
    cp_parser.add_argument("--topic", default="", help="Filter pairs by topic (substring match)")

    # doc_status — read document study state
    p_ds = subparsers.add_parser("doc_status", help="Get study status for a Study Material document (JSON output)")
    p_ds.add_argument("doc_path", type=str, help="Vault-relative path, e.g. 'Study Material/vasospasm_20260325.md'")

    # ── Redesign Phase: new subcommands ──

    # concept_review_queue — SRS-scheduled concepts due for review
    crq_parser = subparsers.add_parser("concept_review_queue",
        help="Concepts due for SM-2 spaced review (JSON output)")
    crq_parser.add_argument("--n", type=int, default=10, help="Max concepts to return")
    crq_parser.add_argument("--domain", default=None, help="Filter by curriculum domain")

    # log_session_narrative — persist teaching narrative at session end
    p_sn = subparsers.add_parser("log_session_narrative",
        help="Persist a session-level teaching narrative with next-session strategy")
    p_sn.add_argument("--skill", required=True, help="Skill that produced this session")
    p_sn.add_argument("--topics", required=True,
        help="Comma-separated topic names covered")
    p_sn.add_argument("--summary", default="", help="1-2 sentence session recap")
    p_sn.add_argument("--teaching-failures", default="",
        help='JSON list: [{"concept":"...","attempted":"...","why_failed":"..."}]')
    p_sn.add_argument("--teaching-successes", default="",
        help='JSON list of strings describing what worked')
    p_sn.add_argument("--strategy", default="", dest="next_session_strategy",
        help="Forward directive for the NEXT session on these topics")
    p_sn.add_argument("--key-confusions", default="",
        help='JSON list: [{"concept_a":"...","concept_b":"...","disambiguation_axis":"..."}]')
    p_sn.add_argument("--depth-profile", default="",
        help='JSON dict: {"topic": depth_achieved}')
    p_sn.add_argument("--turns", type=int, default=0, dest="duration_turns",
        help="Number of interaction turns in session")
    p_sn.add_argument("--session-success-rate", type=float, default=None, dest="session_success_rate",
        help="Session success rate 0.0–1.0 (understood / total concepts). Used for ZPD tracking.")

    # last_session_narrative — retrieve most recent session narrative
    p_lsn = subparsers.add_parser("last_session_narrative",
        help="Retrieve most recent session narrative, optionally filtered (JSON output)")
    p_lsn.add_argument("--skill", default=None, help="Filter by skill")
    p_lsn.add_argument("--topic", default=None, help="Filter by topic (substring)")

    # blocking_gaps — gaps with prerequisite chains
    p_bg = subparsers.add_parser("blocking_gaps",
        help="Show gaps with unmet prerequisite concepts (JSON output)")
    p_bg.add_argument("--topic", required=True, help="Topic name to check")

    # concept_chain — prerequisite + extension chain for a concept
    p_cc = subparsers.add_parser("concept_chain",
        help="Show prerequisite and extension chain for a concept (JSON output)")
    p_cc.add_argument("--concept", required=True, help="Concept text to look up")
    p_cc.add_argument("--topic", default=None, help="Topic context (optional)")

    # add_concept_relationship — add a relationship between two concepts
    p_acr = subparsers.add_parser("add_concept_relationship",
        help="Add a relationship between two concepts (prerequisite, confusable, etc.)")
    p_acr.add_argument("--a", required=True, dest="concept_a", help="First concept")
    p_acr.add_argument("--b", required=True, dest="concept_b", help="Second concept")
    p_acr.add_argument("--type", required=True, dest="relationship",
        choices=["prerequisite_of", "confusable_with", "extends", "differentiates_from"],
        help="Relationship type")
    p_acr.add_argument("--topic-a", default="", help="Topic for concept A (optional)")
    p_acr.add_argument("--topic-b", default="", help="Topic for concept B (optional)")
    p_acr.add_argument("--notes", default="", help="Disambiguation axis or notes")
    p_acr.add_argument("--strength", type=float, default=0.5, help="Relationship strength 0-1")

    # topic_specificity_check — validate topic name granularity
    p_tsc = subparsers.add_parser("topic_specificity_check",
        help="Validate topic name specificity (JSON output)")
    p_tsc.add_argument("topic_name", type=str, help="Topic name to check")

    # fine_grained_gaps — concept-level gaps with root_cause + error_process
    p_fgg = subparsers.add_parser("fine_grained_gaps",
        help="Concept-level gaps with root_cause and error_process (JSON output)")
    p_fgg.add_argument("--top", type=int, default=10, help="Max gaps to return")
    p_fgg.add_argument("--domain", default=None, help="Filter by domain")

    # migrate_confusion_matrix — one-time migration from JSON to DB
    subparsers.add_parser("migrate_confusion_matrix",
        help="Migrate confusion_matrix.json into concept_relationships table (idempotent)")

    # ── Iteration 2: Prerequisite seeding ──
    subparsers.add_parser("seed_prerequisites",
        help="Auto-seed prerequisite + confusable relationships from gap co-occurrence (JSON output)")

    # ── Iteration 3: ZPD + learning velocity ──
    subparsers.add_parser("difficulty_target",
        help="ZPD-based difficulty recommendation from recent session success rates (JSON output)")

    p_sp = subparsers.add_parser("study_plan",
        help="Integrated memory-driven study plan from SRS, gaps, calibration, and transfer candidates (JSON output)")
    p_sp.add_argument("--hours", type=float, default=1.0,
        help="Study time budget in hours (default 1.0)")
    p_sp.add_argument("--rotation", default=None,
        help="Optional rotation/domain filter")
    p_sp.add_argument("--focus", default=None,
        help="Optional topic/domain focus override")

    p_alias = subparsers.add_parser("add_concept_alias",
        help="Add/update a concept alias mapping for stable concept identity (JSON output)")
    p_alias.add_argument("--alias", required=True, help="Alias text")
    p_alias.add_argument("--canonical", required=True, dest="canonical_concept", help="Canonical concept text")
    p_alias.add_argument("--topic", default="", help="Optional topic context")
    p_alias.add_argument("--source", default="manual", help="Source of alias mapping")

    p_resolve = subparsers.add_parser("resolve_concept",
        help="Resolve a concept alias in optional topic context (JSON output)")
    p_resolve.add_argument("concept", help="Concept or alias text")
    p_resolve.add_argument("--topic", default="", help="Optional topic context")

    p_lv = subparsers.add_parser("learning_velocity",
        help="Per-domain confidence change rate over recent sessions (JSON output)")
    p_lv.add_argument("--domain", default=None, help="Filter by domain")
    p_lv.add_argument("--n", type=int, default=10, help="Number of sessions to analyze")

    # ── Iteration 4: Blind spot detection ──
    p_uu = subparsers.add_parser("unknown_unknowns",
        help="Adjacent curriculum topics never studied (blind spot detection, JSON output)")
    p_uu.add_argument("--topic", required=True, help="Topic or query to find blind spots adjacent to")
    p_uu.add_argument("--n", type=int, default=5, help="Max results")

    subparsers.add_parser("misconception_clusters",
        help="Group root_cause descriptions by cognitive theme (JSON output)")

    subparsers.add_parser("seed_topic_adjacency",
        help="Seed topic_adjacency table from curriculum milestone groupings (idempotent)")

    subparsers.add_parser("backfill_topic_fingerprints",
        help="Backfill topic_fingerprint for existing session_narratives (Round 3, idempotent)")

    # ── Obsidian Redesign: Error Atlas, Concept Stubs, ACGME Readiness ──

    subparsers.add_parser("generate_error_atlas",
        help="Export confusable pairs for Error Atlas vault generation (JSON output)")

    p_ecs = subparsers.add_parser("export_concept_stubs",
        help="Export curriculum topics for Obsidian concept stub generation (JSON output)")
    p_ecs.add_argument("--only-studied", action="store_true",
        help="Return only topics with encounter_count > 0")

    p_ar = subparsers.add_parser("acgme_readiness",
        help="ACGME readiness data for current PGY year (JSON output)")
    p_ar.add_argument("--pgy", type=int, default=None,
        help="PGY year to filter to (default: reads data/pgy_config.json, falls back to 1)")

    # log_doc_progress — upsert document study progress
    p_ldp = subparsers.add_parser("log_doc_progress", help="Upsert document study progress (heartbeat + session-end)")
    p_ldp.add_argument("--doc", required=True, metavar="DOC_PATH",
                        help="Vault-relative path to the Study Material document")
    p_ldp.add_argument("--doc-type", default="unknown",
                        help="Source type: report, operative-guide, study-material, other")
    p_ldp.add_argument("--covered", default="",
                        help="Comma-separated concept/question IDs covered this session")
    p_ldp.add_argument("--understood", default="",
                        help="Comma-separated concept/question IDs confirmed correct")
    p_ldp.add_argument("--missed", default="",
                        help='JSON list: [{"concept":"...","error_type":"...","misconception":"..."}] or comma-separated strings')
    p_ldp.add_argument("--coverage-pct", type=float, default=0.0, dest="coverage_pct",
                        help="Cumulative coverage percentage (0–100)")
    p_ldp.add_argument("--total-concepts", type=int, default=0, dest="total_concepts",
                        help="Total concepts/questions in the document")

    # ── Episodic Memory commands ──
    p_lx = subparsers.add_parser("log_exchange", help="Log a learning exchange (question + answer + correction)")
    p_lx.add_argument("--session-ts", required=True, dest="session_ts",
                       help="ISO session timestamp (shared across all exchanges in a session)")
    p_lx.add_argument("--turn", required=True, type=int, help="Turn number within session (1-indexed)")
    p_lx.add_argument("--skill", required=True, help="Skill name: study-session, rag-workflow, intern-bootcamp, ad-hoc")
    p_lx.add_argument("--topic", required=True, help="Topic name")
    p_lx.add_argument("--concept", required=True, help="Specific concept tested")
    p_lx.add_argument("--question", required=True, help="The question asked (verbatim)")
    p_lx.add_argument("--answer", required=True, help="The user's answer (verbatim or close paraphrase)")
    p_lx.add_argument("--correct", required=True, type=int, choices=[0, 1, 2],
                       help="0=incorrect, 1=partial, 2=correct")
    p_lx.add_argument("--correction", default="", help="Agent's correction/explanation (empty if correct)")
    p_lx.add_argument("--error-type", default="", dest="error_type",
                       help="Error classification: numerical_recall, conceptual_confusion, etc.")
    p_lx.add_argument("--misconception", default="", help="The specific wrong belief exhibited")
    p_lx.add_argument("--root-cause", default="", dest="root_cause", help="Why the error occurred")
    p_lx.add_argument("--teaching-approach", default="", dest="teaching_approach",
                       help="Teaching approach used: mechanism-first, classification-first, case-based, etc.")
    p_lx.add_argument("--retrieval-sources", default="", dest="retrieval_sources",
                       help="Textbook sources shown (book: chapter/heading)")
    p_lx.add_argument("--signal-event-id", type=int, default=None, dest="signal_event_id",
                       help="Optional linked signal_events.event_id")
    p_lx.add_argument("--breakthrough", action="store_true", help="Mark as an aha moment")
    p_lx.add_argument("--insight", default="", help="What clicked (1 sentence)")
    p_lx.add_argument("--depth", type=int, default=1, help="Depth of material (1=surface, 2=mechanism, 3=decision)")
    p_lx.add_argument("--domain", default="", help="ACGME domain")

    p_la = subparsers.add_parser("log_answer",
        help="Atomically log active answer signal + exchange + concept mastery")
    p_la.add_argument("--session-ts", required=True, dest="session_ts",
                      help="ISO session timestamp shared across all answers in a session")
    p_la.add_argument("--turn", required=True, type=int, help="Turn number within session")
    p_la.add_argument("--skill", required=True, help="Skill name")
    p_la.add_argument("--topic", required=True, help="Topic name")
    p_la.add_argument("--concept", required=True, help="Specific concept tested")
    p_la.add_argument("--question", required=True, help="The question asked")
    p_la.add_argument("--answer", required=True, help="The user's answer")
    p_la.add_argument("--correct", required=True, type=int, choices=[0, 1, 2],
                      help="0=incorrect, 1=partial, 2=correct")
    p_la.add_argument("--correction", default="", help="Correction/explanation if not fully correct")
    p_la.add_argument("--error-type", default="", dest="error_type", help="Error classification")
    p_la.add_argument("--misconception", default="", help="Specific wrong belief")
    p_la.add_argument("--root-cause", default="", dest="root_cause", help="Why the error occurred")
    p_la.add_argument("--remediation", default="", help="What should address the gap")
    p_la.add_argument("--teaching-approach", default="", dest="teaching_approach", help="Teaching approach used")
    p_la.add_argument("--retrieval-sources", default="", dest="retrieval_sources", help="Textbook sources shown")
    p_la.add_argument("--breakthrough", action="store_true", help="Mark as an aha moment")
    p_la.add_argument("--insight", default="", help="What clicked")
    p_la.add_argument("--depth", type=int, default=1, help="Depth of material")
    p_la.add_argument("--domain", default="", help="ACGME domain")
    p_la.add_argument("--response-confidence", default="", dest="response_confidence",
                      choices=["", "high", "low"], help="Silent confidence tag from language cues")

    p_xh = subparsers.add_parser("exchange_history", help="Query past learning exchanges with structured filters (JSON)")
    p_xh.add_argument("--topic", default=None, help="Filter by topic (substring match)")
    p_xh.add_argument("--concept", default=None, help="Filter by concept (substring match)")
    p_xh.add_argument("--error-type", default=None, dest="error_type", help="Exact error type filter")
    p_xh.add_argument("--correct", default=None, type=int, choices=[0, 1, 2],
                       help="Filter by correctness: 0=incorrect, 1=partial, 2=correct")
    p_xh.add_argument("--skill", default=None, help="Filter by skill name")
    p_xh.add_argument("--days", type=int, default=90, help="Lookback window in days (default 90)")
    p_xh.add_argument("--top", type=int, default=20, help="Max results (default 20)")
    p_xh.add_argument("--breakthrough", action="store_true", help="Only breakthroughs")

    # recall — hybrid structured + keyword retrieval of past episodes
    p_recall = subparsers.add_parser("recall",
        help="Recall relevant past learning exchanges (hybrid structured + keyword search, JSON)")
    p_recall.add_argument("query", nargs="?", default="",
        help="Free-text query for keyword matching across exchange content")
    p_recall.add_argument("--topic", default=None, help="Filter by topic (substring match)")
    p_recall.add_argument("--domain", default=None, help="Filter by domain")
    p_recall.add_argument("--error-type", default=None, dest="error_type",
        help="Filter by error type")
    p_recall.add_argument("--correct", default=None, type=int, choices=[0, 1, 2],
        help="Filter by correctness")
    p_recall.add_argument("--skill", default=None, help="Filter by skill name")
    p_recall.add_argument("--errors-only", action="store_true", dest="errors_only",
        help="Shorthand for --correct 0")
    p_recall.add_argument("--days", type=int, default=90, help="Lookback window (default 90)")
    p_recall.add_argument("--max", type=int, default=10, dest="max_results",
        help="Max results (default 10)")
    p_recall.add_argument("--output", default="", help="Write JSON to file instead of stdout")
    p_recall.add_argument("--compact", action="store_true",
                          help="Return compact summaries instead of full text")
    p_recall.add_argument("--sqlite-only", action="store_true",
                          help="Skip LanceDB semantic search for fast/offline recall")

    # teaching_effectiveness — analyze which approaches work
    p_te = subparsers.add_parser("teaching_effectiveness",
        help="Analyze teaching approach effectiveness (JSON)")
    p_te.add_argument("--domain", default=None, help="Filter by domain")
    p_te.add_argument("--days", type=int, default=90, help="Lookback window (default 90)")

    # concept_evolution — show concept understanding evolution history
    p_evo = subparsers.add_parser("concept_evolution",
        help="Show concept understanding evolution history (JSON)")
    p_evo.add_argument("--concept", default=None, help="Filter by concept text")
    p_evo.add_argument("--topic", default=None, help="Filter by topic name")
    p_evo.add_argument("--days", type=int, default=180, help="Lookback days (default 180)")
    p_evo.add_argument("--limit", type=int, default=30, help="Max results (default 30)")

    p_dsc = subparsers.add_parser("derive_session_confusions",
        help="Auto-derive key_confusions pairs from recent learning_exchanges (JSON)")
    p_dsc.add_argument("--session-ts", default=None,
        help="ISO timestamp — use as session start cutoff instead of --hours")
    p_dsc.add_argument("--skill", default=None, help="Filter to a specific skill")
    p_dsc.add_argument("--hours", type=int, default=4,
        help="Hours to look back when --session-ts not given (default 4)")

    p_dep = subparsers.add_parser("domain_error_profile",
        help="Aggregate error patterns for a clinical domain (JSON)")
    p_dep.add_argument("--domain", required=True, help="Domain slug (vascular, spine, tumor, etc.)")
    p_dep.add_argument("--days", type=int, default=90, help="Lookback days (default 90)")

    return parser

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    kg = KnowledgeGraph()

    try:
        _dispatch_command(args, kg)
    finally:
        kg.close()



if __name__ == "__main__":
    main()
