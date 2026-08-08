"""Argument schema for the claim-centered learner-memory CLI."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Claim-centered study memory ledger")
    sub = parser.add_subparsers(dest="command")

    p_resolve = sub.add_parser("resolve-topic")
    p_resolve.add_argument("--topic", required=True)
    p_resolve.add_argument("--doc", default="")

    p_log = sub.add_parser("log-answer")
    p_log.add_argument("--session", required=True)
    p_log.add_argument("--topic", required=True)
    p_log.add_argument("--concept", required=True)
    p_log.add_argument("--question", required=True)
    p_log.add_argument("--answer", required=True)
    p_log.add_argument("--correct", type=int, choices=[0, 1, 2], required=True)
    p_log.add_argument("--correction", default="")
    p_log.add_argument("--error-type", default="")
    p_log.add_argument("--misconception", default="")
    p_log.add_argument("--doc", default="")
    p_log.add_argument("--skill", default="")
    p_log.add_argument("--tested-claim", default="")
    p_log.add_argument("--learner-claim", default="")
    p_log.add_argument("--demonstrated-edge", default="", help="What the learner got right in a partial answer")
    p_log.add_argument("--missing-edge", default="")
    p_log.add_argument("--corrected-rule", default="")
    p_log.add_argument("--clinical-consequence", default="")
    p_log.add_argument("--retest-prompt-shape", default="")
    p_log.add_argument("--teaching-intervention", default="", help="Compact description of the explanation, contrast, or model used after this answer")
    p_log.add_argument("--learning-operation", default="")
    p_log.add_argument("--cognitive-op", default="", help="Alias for --learning-operation: recall|discrimination|quantification|sequencing|mechanism|transfer")
    p_log.add_argument("--teaching-intent", default="")
    p_log.add_argument("--expected-answer-edge", default="")
    p_log.add_argument("--coverage-role", default="")
    p_log.add_argument("--source-section", default="")
    p_log.add_argument("--source-anchor", default="")
    p_log.add_argument("--curriculum-unit", default="")
    p_log.add_argument("--answer-mode", default="")
    p_log.add_argument("--confidence-observed", default="")
    p_log.add_argument("--teaching-move", default="")
    p_log.add_argument("--strict-telemetry", action="store_true")
    p_log.add_argument("--priority", default="", help="Agent-asserted priority: urgent|high|medium|low (overrides heuristic)")
    p_log.add_argument("--match-claim-state-id", type=int, default=None, help="Bind this answer to an existing open claim (agent-asserted recurrence)")
    p_log.add_argument("--new-claim", action="store_true", help="Force a new claim_state even if a similar one exists")
    p_log.add_argument("--repairs-claim-state-ids", default="", help="Comma-separated open claim_state ids this correct answer repairs")
    p_log.add_argument("--origin", choices=["assessed", "service"], default="assessed", help="Provenance: 'service' for service-rotation learning (isolated from formal review)")
    p_log.add_argument("--rotation", type=int, default=None, help="Rotation id this service-origin answer belongs to (defaults to the active rotation)")
    p_log.add_argument("--competency-target", default="", help="Service competency_target slug this answer advances")
    p_log.add_argument("--convention", action="store_true", help="Mark as a (service x site) local convention rather than a portable clinical gap")
    p_log.add_argument("--shift-debrief-candidate-id", type=int, default=None, help="Mark this pending shift-debrief review candidate as reviewed by the logged answer")
    p_log.add_argument(
        "--inventory-concept-id",
        default="",
        help="Canonical inventory concept id for the probed concept (required for study-review when resolvable)",
    )

    p_start_session = sub.add_parser(
        "start-session",
        help="Start study-review from a typed JSON request and return tutor_state_v1",
    )
    p_start_session.add_argument("--stdin", action="store_true", required=True)

    p_assess_turn = sub.add_parser(
        "assess-turn",
        help="Atomically persist one raw learner response and one or more typed claim assessments",
    )
    p_assess_turn.add_argument("--stdin", action="store_true", required=True)

    p_close_session = sub.add_parser(
        "close-session",
        help="Close study-review from a typed JSON request",
    )
    p_close_session.add_argument("--stdin", action="store_true", required=True)

    p_session_integrity = sub.add_parser("session-integrity")
    p_session_integrity.add_argument("--session", required=True)

    p_card_decision = sub.add_parser("record-card-decision")
    p_card_decision.add_argument("--session", required=True)
    p_card_decision.add_argument("--exchange-id", type=int, required=True)
    p_card_decision.add_argument(
        "--decision",
        choices=[
            "enqueue",
            "skip_routine_correct",
            "skip_equivalent",
            "skip_low_value",
            "skip_not_durable",
            "defer_unavailable",
        ],
        required=True,
    )
    p_card_decision.add_argument("--rationale", default="")

    p_end = sub.add_parser("end-session")
    p_end.add_argument("--session", required=True)
    p_end.add_argument("--summary", required=True)
    p_end.add_argument("--next-strategy", required=True)
    p_end.add_argument("--stats-json", default="{}")
    p_end.add_argument("--json", dest="as_json", action="store_true")

    p_summary = sub.add_parser("summary")
    p_summary.add_argument("--topic", default="")
    p_summary.add_argument("--limit", type=int, default=8)
    p_summary.add_argument("--scaffold-limit", type=int, default=2)
    p_summary.add_argument("--no-scaffolds", action="store_true")
    p_summary.add_argument("--include-global-scaffolds", action="store_true")
    p_summary.add_argument("--include-curated", action="store_true")
    p_summary.add_argument("--include-due", action="store_true")
    p_summary.add_argument("--include-model", action="store_true")
    p_summary.add_argument("--context", default="", help="Optional upcoming case/rotation/context string for relevance weighting")
    p_summary.add_argument("--brief-only", action="store_true", help="Return the synthesized planning brief plus truncation diagnostics")
    p_summary.add_argument("--lens", choices=["formal", "general", "service"], default="formal", help="formal doc/audit surface; general includes shift-debrief review candidates; service routes to service memory")
    p_summary.add_argument("--service", default="", help="Service slug for --lens service")
    p_summary.add_argument("--site", default="", help="Site slug for --lens service convention scoping")
    p_summary.add_argument("--rotation", type=int, default=None, help="Rotation id for --lens service")

    p_rotation_start = sub.add_parser("rotation-start")
    p_rotation_start.add_argument("--service", required=True)
    p_rotation_start.add_argument("--site", required=True)
    p_rotation_start.add_argument("--pgy", type=int, default=None)
    p_rotation_start.add_argument("--block", default="")

    sub.add_parser("rotation-current")
    sub.add_parser("rotation-list")

    p_rotation_end = sub.add_parser("rotation-end")
    p_rotation_end.add_argument("--rotation", type=int, required=True)

    p_rubric = sub.add_parser("service-rubric")
    p_rubric.add_argument("--service", required=True)
    p_rubric.add_argument("--seed", action="store_true", help="Seed/refresh competency targets from the ACGME catalog domain slice")
    p_rubric.add_argument("--pgy", type=int, default=None, help="Restrict seeding to targets at or below this PGY")

    p_startup = sub.add_parser("startup-recall")
    p_startup.add_argument("--topic", default="")
    p_startup.add_argument("--doc", default="")
    p_startup.add_argument("--global", dest="global_mode", action="store_true")
    p_startup.add_argument("--limit", type=int, default=None)
    p_startup.add_argument("--scaffold-limit", type=int, default=None)
    p_startup.add_argument("--include-global-scaffolds", action="store_true")
    p_startup.add_argument("--context", default="", help="Optional upcoming case/rotation/context string for relevance weighting")
    p_startup.add_argument("--lens", choices=["formal", "general", "service"], default="formal", help="formal seals out service material; general includes shift-debrief review candidates; service leads with rotation gaps")
    p_startup.add_argument("--service", default="", help="Service slug for --lens service (defaults to the active rotation)")
    p_startup.add_argument("--site", default="", help="Site slug for --lens service convention scoping")
    p_startup.add_argument("--rotation", type=int, default=None, help="Rotation id for --lens service")
    p_startup.add_argument(
        "--profile",
        choices=["auto", "tutor", "doc", "memory", "audit"],
        default="auto",
        help="tutor returns token-bounded tutor_state_v1; legacy compact and audit profiles remain available",
    )

    p_profile = sub.add_parser("learner-profile")
    p_profile.add_argument("action", choices=["get", "upsert"])
    p_profile.add_argument("--stdin", action="store_true")
    p_startup.add_argument(
        "--session",
        default="",
        help="Session id; when set, writes the live knowledge map file for per-turn patching",
    )

    p_node = sub.add_parser("node-recall")
    p_node.add_argument("--inventory-concept-id", required=True)
    p_node.add_argument("--topic", default="")
    p_node.add_argument("--session", default="")

    p_artifact_get = sub.add_parser("artifact-map-get")
    p_artifact_get.add_argument("--doc", required=True)
    p_artifact_get.add_argument("--content-hash", default="")
    p_artifact_get.add_argument("--pretty", action="store_true")

    p_artifact_upsert = sub.add_parser("artifact-map-upsert")
    p_artifact_upsert.add_argument("--doc", required=True)
    p_artifact_upsert.add_argument("--topic", default="")
    p_artifact_upsert.add_argument("--content-hash", default="")
    p_artifact_upsert.add_argument("--created-by", default="agent")
    p_artifact_upsert.add_argument("--pretty", action="store_true")
    p_artifact_src = p_artifact_upsert.add_mutually_exclusive_group(required=True)
    p_artifact_src.add_argument("--input", dest="input_path", default=None)
    p_artifact_src.add_argument("--stdin", action="store_true")

    sub.add_parser("status")
    sub.add_parser("health")
    sub.add_parser("identity-audit")
    sub.add_parser("telemetry-audit")
    sub.add_parser("curation-status")
    p_maintain = sub.add_parser("maintain")
    p_maintain.add_argument("--vacuum", action="store_true", help="Also VACUUM to reclaim free pages from deletes")
    p_kmap = sub.add_parser("knowledge-map")
    p_kmap.add_argument("--domain", default="", help="Scope to one inventory domain (e.g. vascular)")
    p_kmap.add_argument("--limit", type=int, default=20)

    p_merge_topics = sub.add_parser("merge-topics")
    p_merge_topics.add_argument("--from-topic", required=True)
    p_merge_topics.add_argument("--into-topic", required=True)
    p_merge_topics.add_argument("--apply", action="store_true")

    p_realign_concept = sub.add_parser("realign-concept")
    p_realign_concept.add_argument("--concept-id", type=int, required=True)
    p_realign_concept.add_argument("--inventory-concept-id", required=True)
    p_realign_concept.add_argument("--apply", action="store_true")
    p_realign_concept.add_argument("--allow-unknown", action="store_true",
                                   help="apply even if the inventory id is not in the canonical inventory")
    p_realign_concept.add_argument("--no-restamp-claims", action="store_true",
                                   help="move only the concept binding; leave each claim's own inventory id intact")

    p_rename_concept = sub.add_parser("rename-concept")
    p_rename_concept.add_argument("--concept-id", type=int, required=True)
    p_rename_concept.add_argument("--display-name", required=True)
    p_rename_concept.add_argument("--apply", action="store_true")

    p_recall_migrate = sub.add_parser("migrate-recall-realignment")
    p_recall_migrate.add_argument("--apply", action="store_true")

    p_ad_vte_migrate = sub.add_parser("migrate-ad-vte-separation")
    p_ad_vte_migrate.add_argument("--apply", action="store_true")

    p_shadow_check = sub.add_parser("record-shadow-check")
    p_shadow_check.add_argument("--rule-id", type=int, required=True)
    p_shadow_check.add_argument("--claim-result-id", type=int, required=True)
    p_shadow_check.add_argument("--context-label", required=True)
    p_shadow_check.add_argument("--check-type", choices=["changed_frame", "transfer"], required=True)
    p_shadow_check.add_argument("--outcome", choices=["pass", "fail"], required=True)
    p_shadow_check.add_argument("--apply", action="store_true")

    p_reference_graph = sub.add_parser("load-reference-graph")
    p_reference_graph.add_argument("--input", required=True)
    p_reference_graph.add_argument("--apply", action="store_true")

    p_candidates = sub.add_parser("curate-candidates")
    p_candidates.add_argument("--mode", choices=["compact", "detailed"], default="compact")
    p_candidates.add_argument("--topic", default="")
    p_candidates.add_argument("--recent-sessions", type=int, default=5)
    p_candidates.add_argument("--limit", type=int, default=40)

    p_apply = sub.add_parser("apply-curation")
    p_apply_src = p_apply.add_mutually_exclusive_group(required=True)
    p_apply_src.add_argument("--input", dest="input_path", default=None, help="Path to apply payload JSON file")
    p_apply_src.add_argument("--stdin", action="store_true", help="Read apply payload from stdin")

    p_bd_add = sub.add_parser("shift-debrief-candidate-add")
    p_bd_add.add_argument("--session", required=True)
    p_bd_add.add_argument("--topic", required=True)
    p_bd_add.add_argument("--concept", required=True)
    p_bd_add.add_argument("--doc", required=True)
    p_bd_add.add_argument("--prompt", required=True)
    p_bd_add.add_argument("--claim", default="")
    p_bd_add.add_argument("--provenance-tier", default="")
    p_bd_add.add_argument("--origin", choices=["assessed", "service"], default="assessed")
    p_bd_add.add_argument("--rotation", type=int, default=None)
    p_bd_add.add_argument("--convention", action="store_true")
    p_bd_add.add_argument("--detail-json", default="{}")

    p_bd_list = sub.add_parser("shift-debrief-candidate-list")
    p_bd_list.add_argument("--topic", default="")
    p_bd_list.add_argument("--status", choices=["pending", "reviewed", "dismissed"], default="pending")
    p_bd_list.add_argument("--limit", type=int, default=20)

    p_bd_mark = sub.add_parser("shift-debrief-candidate-mark")
    p_bd_mark.add_argument("--candidate-id", type=int, required=True)
    p_bd_mark.add_argument("--status", choices=["pending", "dismissed"], required=True)

    return parser
