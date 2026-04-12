#!/usr/bin/env python3
"""Deterministic Universal Post-Session Hook with hard verification.

This script executes the shared post-session pipeline and emits a structured
verification report so command skills can surface exactly what passed or failed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from knowledge_graph import KnowledgeGraph
import vault_kg_sync
import vault_canvas_builder


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VAULT_ROOT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
VAULT_ROOT = DEFAULT_VAULT_ROOT
DASHBOARD_PATH = DEFAULT_VAULT_ROOT / "Dashboard.md"
ACGME_PATH = DEFAULT_VAULT_ROOT / "ACGME Readiness.md"
CONCEPTS_DIR = DEFAULT_VAULT_ROOT / "Concepts"

PROTECTED_CONCEPTS = {
    "Neurosurgery Consult Checklists by Pathology.md",
    "Neurosurgery Consult Workflow.md",
    "Peripheral Nerve Injury Classifications (Seddon & Sunderland).md",
}

DEPTH_LABEL_MAP = {
    0: "not_studied",
    1: "surface",
    2: "mechanistic",
    3: "applied",
}

PRIORITY_LABEL_MAP = {
    1: "core",
    2: "important",
    3: "advanced",
}


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_date_label(ts: str) -> str:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return f"{dt.strftime('%b')} {dt.day}, {dt.year}"
        except ValueError:
            continue
    return "Unknown"


def _safe_text(value: str) -> str:
    return (value or "").replace("|", "\\|").strip()


def _title_case(text: str) -> str:
    return " ".join(word.capitalize() for word in (text or "").strip().split())


def _depth_label(depth: int) -> str:
    return DEPTH_LABEL_MAP.get(depth, f"depth-{depth}")


def _priority_label(priority: int) -> str:
    return PRIORITY_LABEL_MAP.get(priority, "core")


# Concept file composition lives in src/vault_kg_sync.py. This hook invokes
# sync_studied_concepts() which handles all rendering of the Learning State
# Dataview block, relationship edge sections, and Encounter History ledger.


def _progress_bar(percent: float) -> str:
    filled = max(0, min(10, int(percent // 10)))
    return ("█" * filled) + ("░" * (10 - filled))


def _collect_vault_assets() -> dict[str, dict[str, Any]]:
    sections = {
        "Reports": VAULT_ROOT / "Reports",
        "Operative Guides": VAULT_ROOT / "Operative Guides",
        "Study Material": VAULT_ROOT / "Study Material",
        "Concepts": VAULT_ROOT / "Concepts",
    }
    assets: dict[str, dict[str, Any]] = {}

    for label, directory in sections.items():
        files = sorted(directory.glob("*.md")) if directory.exists() else []
        filtered = [f for f in files if f.name != "INDEX.md"]
        preview = filtered[:5]

        links = []
        for path in preview:
            stem = path.stem
            link_base = directory.name
            display = stem.replace("_", " ")
            links.append(f"[[{link_base}/{stem}|{display}]]")

        assets[label] = {
            "count": len(filtered),
            "links": links,
        }

    return assets


def _domain_milestones(kg: KnowledgeGraph) -> dict[str, str]:
    rows = kg.conn.execute(
        """
        SELECT domain, MIN(acgme_milestone) AS acgme_milestone
        FROM curriculum_topics
        GROUP BY domain
        """
    ).fetchall()
    return {row["domain"]: (row["acgme_milestone"] or "-") for row in rows}


def _compute_priority_gaps(kg: KnowledgeGraph, n: int) -> list[dict[str, Any]]:
    """Compute priority gaps without re-running apply_decay."""
    curriculum_rows = kg.conn.execute("SELECT * FROM curriculum_topics").fetchall()
    if not curriculum_rows:
        return []

    priority_weight = {1: 3.0, 2: 2.0, 3: 1.0}
    now = _utc_now()
    thirty_days_ago = (now.replace(microsecond=0) - timedelta(days=30)).isoformat()
    results: list[dict[str, Any]] = []

    for crow in curriculum_rows:
        c = dict(crow)
        canonical = KnowledgeGraph._normalize_topic(c.get("topic_name", ""))
        learner = kg._find_topic(canonical) if canonical else None
        priority = c.get("priority", 2)
        weight = priority_weight.get(priority, 1.0)

        if learner is None:
            base = 0.8
            gap_type = "never_encountered"
            error_count = 0
        else:
            confidence_gap = 1.0 - float(learner.get("confidence", 0.0) or 0.0)
            depth_penalty = max(0, 3 - int(learner.get("depth", 0) or 0)) * 0.1
            err_row = kg.conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM signal_events
                WHERE topic_id = ?
                  AND signal_type IN ('incorrect_recall', 'weakness_identified')
                  AND timestamp > ?
                """,
                (learner["topic_id"], thirty_days_ago),
            ).fetchone()
            error_count = int(err_row["cnt"] if err_row else 0)
            error_penalty = min(0.3, error_count * 0.1)
            base = confidence_gap + depth_penalty + error_penalty

            if error_count >= 3:
                gap_type = "error_cluster"
            elif float(learner.get("confidence", 0.0) or 0.0) < 0.3 and int(learner.get("encounter_count", 0) or 0) > 0:
                gap_type = "decaying"
            elif int(learner.get("depth", 0) or 0) <= 1 and priority == 1:
                gap_type = "shallow"
            else:
                gap_type = "general_gap"

        results.append(
            {
                "curriculum_topic": c,
                "learner_topic": dict(learner) if learner else None,
                "gap_score": round(base * weight, 4),
                "gap_type": gap_type,
                "error_count": error_count,
            }
        )

    results.sort(key=lambda r: r["gap_score"], reverse=True)
    return results[:n]


def _render_dashboard(
    *,
    dashboard_data: dict[str, Any],
    recs: list[dict[str, Any]],
    review_queue: list[dict[str, Any]],
    activity_feed: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    calibration: dict[str, Any],
    skill: str,
    topics: str,
    vault_writes: str,
    next_priority_override: str,
    milestone_map: dict[str, str],
) -> str:
    domains = dashboard_data.get("domains", [])
    sorted_domains = sorted(domains, key=lambda d: float(d.get("coverage_pct", 0.0)), reverse=True)

    total_curriculum = sum(int(d.get("total", 0) or 0) for d in domains)
    touched = sum(int(d.get("encountered", 0) or 0) for d in domains)
    coverage = round((100.0 * touched / total_curriculum), 1) if total_curriculum else 0.0
    events_logged = int(dashboard_data.get("total_events", 0) or 0)

    recent = activity_feed[:10]
    last_session = _safe_date_label(recent[0]["timestamp"]) if recent else "Unknown"

    gap_domain = recs[0]["curriculum_topic"].get("domain", "General") if recs else "General"
    gap_topic = recs[0]["curriculum_topic"].get("display_name", "No major gap identified") if recs else "No major gap identified"
    next_priority = next_priority_override or gap_topic

    assets = _collect_vault_assets()
    reports_asset = assets["Reports"]
    guides_asset = assets["Operative Guides"]
    study_asset = assets["Study Material"]
    concepts_asset = assets["Concepts"]

    lines: list[str] = []
    lines.append("---")
    lines.append(f"updated: {_utc_now().date().isoformat()}")
    lines.append("---")
    lines.append("")
    lines.append("> [!abstract] Overview")
    lines.append(
        f"> **Curriculum coverage**: {coverage}% — {touched} of {total_curriculum} topics touched | "
        f"**Events logged**: {events_logged} | **Last session**: {last_session}"
    )
    lines.append("")
    lines.append("> [!info] Live Dashboard")
    lines.append("> The Study Queue sections below are live Dataview queries that read `mastery::`, `next_due::`, and `error_type::` inline fields from every Concept file. Install the **Dataview** community plugin for them to render. Aggregate sections (curriculum progress, recent activity, vault assets, last session) are regenerated by the post-session hook.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Curriculum Progress")
    lines.append("")
    lines.append("Coverage is measured against the ACGME curriculum. A topic is \"touched\" only when a study signal is logged against a curriculum-mapped entry.")
    lines.append("")
    lines.append("| Domain | Milestone | Touched | Coverage | Progress |")
    lines.append("|--------|-----------|---------|----------|----------|")
    for d in sorted_domains:
        domain_name = d.get("domain", "Unknown")
        milestone = milestone_map.get(domain_name, "-")
        encountered = int(d.get("encountered", 0) or 0)
        total = int(d.get("total", 0) or 0)
        coverage_pct = float(d.get("coverage_pct", 0.0) or 0.0)
        lines.append(
            f"| {_safe_text(domain_name)} | {_safe_text(milestone)} | {encountered} / {total} | {coverage_pct:.1f}% | {_progress_bar(coverage_pct)} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Study Queue")
    lines.append("")
    lines.append("> [!tip] This Week")
    lines.append(
        f"> Highest leverage domain is **{_safe_text(gap_domain)}**. Start with **{_safe_text(gap_topic)}**, "
        "then validate one overdue concept from the concept review queue."
    )
    lines.append("")
    lines.append("### Concepts Due for Review")
    lines.append("")
    lines.append("Live query — pulls from `next_due` inline field on every studied Concept file. Edit filters directly in this block.")
    lines.append("")
    lines.append("```dataview")
    lines.append("TABLE WITHOUT ID")
    lines.append('  file.link         AS "Concept",')
    lines.append('  mastery           AS "Mastery",')
    lines.append('  next_due          AS "Due",')
    lines.append('  error_type        AS "Error",')
    lines.append('  domain            AS "Domain"')
    lines.append('FROM "Concepts"')
    lines.append("WHERE next_due != null AND next_due != \"~\" AND status != \"not_studied\"")
    lines.append("SORT next_due ASC")
    lines.append("LIMIT 15")
    lines.append("```")
    lines.append("")
    lines.append("### Shallow Core Concepts (Priority Gaps)")
    lines.append("")
    lines.append("Core (priority=core) curriculum concepts with `mastery < 0.3`. Fully dynamic — regenerates whenever a concept's mastery changes.")
    lines.append("")
    lines.append("```dataview")
    lines.append("TABLE WITHOUT ID")
    lines.append('  file.link         AS "Concept",')
    lines.append('  domain            AS "Domain",')
    lines.append('  acgme_milestone   AS "ACGME",')
    lines.append('  mastery           AS "Mastery",')
    lines.append('  encounters        AS "Encounters"')
    lines.append('FROM "Concepts"')
    lines.append('WHERE priority = "core" AND mastery < 0.3 AND status != "not_studied"')
    lines.append("SORT mastery ASC")
    lines.append("LIMIT 15")
    lines.append("```")
    lines.append("")
    lines.append("### High-Risk Concepts (Errors + Low Mastery)")
    lines.append("")
    lines.append("Concepts with a recent error type recorded AND `mastery < 0.5`. These are the misconception clusters most worth drilling.")
    lines.append("")
    lines.append("```dataview")
    lines.append("TABLE WITHOUT ID")
    lines.append('  file.link     AS "Concept",')
    lines.append('  error_type    AS "Error Type",')
    lines.append('  mastery       AS "Mastery",')
    lines.append('  blocking_gaps AS "Blockers",')
    lines.append('  last_tested   AS "Last Tested"')
    lines.append('FROM "Concepts"')
    lines.append('WHERE error_type != null AND error_type != "~" AND mastery < 0.5')
    lines.append("SORT mastery ASC")
    lines.append("LIMIT 15")
    lines.append("```")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Recent Activity")
    lines.append("")
    lines.append("| Date | Source | Activity |")
    lines.append("|------|--------|----------|")
    for row in recent:
        date_label = _safe_date_label(row.get("timestamp", ""))
        source = row.get("source", "unknown")
        signal = row.get("signal", row.get("signal_type", "activity"))
        topic = row.get("topic", "")
        activity = f"{signal} — {topic}".strip(" —")
        lines.append(f"| {date_label} | {_safe_text(source)} | {_safe_text(activity)} |")
    if not recent:
        lines.append("| No data yet | - | Complete a study session to populate. |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Patterns & Calibration")
    lines.append("")
    if patterns or calibration:
        lines.append("> [!note] Calibration Snapshot")
        if patterns:
            top_patterns = ", ".join(p.get("error_type", "unknown") for p in patterns[:3])
            lines.append(f"> Recurring error patterns: {top_patterns}.")
        else:
            lines.append("> No recurring cognitive pattern clusters yet.")

        total_signals = calibration.get("total_signals", 0)
        score = calibration.get("calibration_score")
        if total_signals:
            score_text = f"{score:.2f}" if isinstance(score, (int, float)) else "n/a"
            lines.append(f"> Calibration signals: {total_signals} | calibration score: {score_text}.")
        else:
            lines.append("> No calibration data yet — complete an `/intern-bootcamp` session to populate.")
    else:
        lines.append("> [!note] No calibration data yet")
        lines.append("> Complete an `/intern-bootcamp` session to build your confidence calibration profile.")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Vault Assets")
    lines.append("")
    lines.append("> [!example] Notes in this vault")
    lines.append(
        f"> **Reports** ({reports_asset['count']}): "
        + (", ".join(reports_asset["links"]) if reports_asset["links"] else "None yet")
    )
    lines.append(
        f"> **Operative Guides** ({guides_asset['count']}): "
        + (", ".join(guides_asset["links"]) if guides_asset["links"] else "None yet — use `/intraoperative-guide` to generate one")
    )
    lines.append(
        f"> **Study Material** ({study_asset['count']}): "
        + (", ".join(study_asset["links"]) if study_asset["links"] else "None yet")
    )
    lines.append(
        f"> **Concepts** ({concepts_asset['count']}): "
        + (", ".join(concepts_asset["links"]) if concepts_asset["links"] else "None yet")
    )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## ACGME Milestone Canvases")
    lines.append("")
    lines.append("> [!map] Knowledge Graph Topology")
    lines.append("> One Obsidian Canvas per ACGME milestone. Nodes are curriculum concepts, colored by mastery (red=not studied, orange=surface, yellow=mechanistic, green=mastered). Edges are prerequisite and confusable-pair relationships drawn from the knowledge graph.")
    lines.append(">")
    lines.append("> Open the index: [[ACGME Canvases/INDEX|ACGME Canvases Index]]")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## What Changed (Last Session)")
    lines.append("")
    lines.append(f"> [!info] Last session — {_utc_now().date().isoformat()}")
    lines.append(f"> **Skill**: {_safe_text(skill)}")
    lines.append(f"> **Topics Touched**: {_safe_text(topics or 'not provided')}")
    lines.append(f"> **Vault Writes**: {_safe_text(vault_writes or 'not provided')}")
    lines.append(f"> **Next Priority**: {_safe_text(next_priority)}")
    lines.append("")

    return "\n".join(lines)


def _verify_file_written(path: Path, started_at: datetime) -> tuple[bool, str]:
    if not path.exists():
        return False, f"{path} was not created."
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    if modified_at < started_at:
        return False, f"{path} was not updated in this run."
    return True, f"{path} updated at {modified_at.isoformat()}."


def main() -> int:
    parser = argparse.ArgumentParser(description="Run universal post-session hook with hard verification.")
    parser.add_argument("--skill", required=True, help="Skill name, e.g. generate-report")
    parser.add_argument("--topics", default="", help="Comma-separated topic list")
    parser.add_argument("--vault-writes", default="", help="Comma-separated files updated during session")
    parser.add_argument("--next-priority", default="", help="Override next-priority text for dashboard")
    parser.add_argument("--report-out", default="/tmp/post_session_hook_report.json", help="Verification report output path")
    parser.add_argument("--vault-root", default=str(DEFAULT_VAULT_ROOT), help="Vault root path for Dashboard/ACGME/Concepts writes")
    parser.add_argument("--gaps-top", type=int, default=8, help="Number of priority gaps to render")
    parser.add_argument("--review-n", type=int, default=20, help="Concept review queue size to load")
    parser.add_argument("--activity-n", type=int, default=12, help="Activity rows to load")
    parser.add_argument("--pgy", type=int, default=None, help="Optional PGY override for ACGME export")
    args = parser.parse_args()

    global VAULT_ROOT, DASHBOARD_PATH, ACGME_PATH, CONCEPTS_DIR
    VAULT_ROOT = Path(args.vault_root).expanduser()
    DASHBOARD_PATH = VAULT_ROOT / "Dashboard.md"
    ACGME_PATH = VAULT_ROOT / "ACGME Readiness.md"
    CONCEPTS_DIR = VAULT_ROOT / "Concepts"

    started_at = _utc_now()
    steps: list[StepResult] = []
    metrics: dict[str, Any] = {}

    kg = KnowledgeGraph()

    try:
        kg.apply_decay()
        steps.append(StepResult("apply_decay", True, "Decay applied to topic confidences."))
    except Exception as exc:
        steps.append(StepResult("apply_decay", False, f"apply_decay failed: {exc}"))

    dashboard_data: dict[str, Any] = {}
    recs: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    activity_feed: list[dict[str, Any]] = []
    patterns: list[dict[str, Any]] = []
    calibration: dict[str, Any] = {}
    milestones: dict[str, str] = {}

    try:
        dashboard_data = kg.dashboard()
        recs = _compute_priority_gaps(kg, args.gaps_top)
        review_queue = kg.get_review_queue(n=args.review_n)
        activity_feed = kg.activity_feed(n=args.activity_n)
        patterns = kg.detect_cognitive_patterns()
        calibration = kg.compute_calibration_profile()
        milestones = _domain_milestones(kg)
        steps.append(StepResult("collect_dashboard_inputs", True, "Loaded dashboard, gap, review queue, activity, pattern, and calibration data."))
        metrics["gap_count"] = len(recs)
        metrics["review_queue_count"] = len(review_queue)
        metrics["activity_rows"] = len(activity_feed)
    except Exception as exc:
        steps.append(StepResult("collect_dashboard_inputs", False, f"Failed collecting dashboard inputs: {exc}"))

    try:
        dashboard_text = _render_dashboard(
            dashboard_data=dashboard_data,
            recs=recs,
            review_queue=review_queue,
            activity_feed=activity_feed,
            patterns=patterns,
            calibration=calibration,
            skill=args.skill,
            topics=args.topics,
            vault_writes=args.vault_writes,
            next_priority_override=args.next_priority,
            milestone_map=milestones,
        )
        DASHBOARD_PATH.parent.mkdir(parents=True, exist_ok=True)
        DASHBOARD_PATH.write_text(dashboard_text, encoding="utf-8")
        ok, detail = _verify_file_written(DASHBOARD_PATH, started_at)
        if ok and f"updated: {_utc_now().date().isoformat()}" not in dashboard_text:
            ok = False
            detail = "Dashboard updated, but updated date was not set to today."
        steps.append(StepResult("write_dashboard", ok, detail))
    except Exception as exc:
        steps.append(StepResult("write_dashboard", False, f"Failed writing dashboard: {exc}"))

    acgme_tmp = Path("/tmp/acgme_data.json")
    try:
        acgme_data = kg.acgme_readiness(pgy=args.pgy)
        acgme_tmp.write_text(json.dumps(acgme_data, indent=2, default=str), encoding="utf-8")
        result = subprocess.run(
            [
                "python3",
                "scripts/write_acgme_readiness.py",
                "--json",
                str(acgme_tmp),
                "--output",
                str(ACGME_PATH),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            steps.append(StepResult("write_acgme_readiness", False, f"write_acgme_readiness.py failed: {result.stderr.strip()[:400]}"))
        else:
            ok, detail = _verify_file_written(ACGME_PATH, started_at)
            steps.append(StepResult("write_acgme_readiness", ok, detail))
    except Exception as exc:
        steps.append(StepResult("write_acgme_readiness", False, f"Failed generating ACGME readiness: {exc}"))

    try:
        sync_result = vault_kg_sync.sync_studied_concepts(
            kg,
            CONCEPTS_DIR,
            protected=PROTECTED_CONCEPTS,
        )
        concept_written = int(sync_result.get("written", 0))
        concept_skipped = int(sync_result.get("skipped_protected", 0))
        metrics["concept_stubs_written"] = concept_written
        metrics["concept_stubs_skipped_protected"] = concept_skipped
        steps.append(
            StepResult(
                "update_studied_concept_stubs",
                True,
                f"Synced {concept_written} studied concept files via vault_kg_sync "
                f"(skipped protected: {concept_skipped}). Each file now carries Dataview "
                "inline fields, KG relationship sections, and Encounter History ledger.",
            )
        )
    except Exception as exc:
        steps.append(StepResult("update_studied_concept_stubs", False, f"Failed vault_kg_sync: {exc}"))

    # ── ACGME milestone canvases ─────────────────────────────────────────
    try:
        canvas_result = vault_canvas_builder.sync_canvases(kg, VAULT_ROOT)
        metrics["canvases_written"] = canvas_result.get("canvases_written", 0)
        metrics["canvas_nodes"] = canvas_result.get("total_nodes", 0)
        metrics["canvas_edges"] = canvas_result.get("total_edges", 0)
        steps.append(
            StepResult(
                "sync_acgme_canvases",
                True,
                f"Regenerated {canvas_result.get('canvases_written', 0)} ACGME milestone canvases "
                f"({canvas_result.get('total_nodes', 0)} nodes, {canvas_result.get('total_edges', 0)} edges).",
            )
        )
    except Exception as exc:
        steps.append(StepResult("sync_acgme_canvases", False, f"sync_canvases failed: {exc}", required=False))

    try:
        if acgme_tmp.exists():
            acgme_tmp.unlink()
        steps.append(StepResult("cleanup_tmp", True, "Temporary post-session files cleaned."))
    except Exception as exc:
        steps.append(StepResult("cleanup_tmp", False, f"Failed tmp cleanup: {exc}", required=False))

    # Commit and push all vault changes to GitHub
    sync_script = PROJECT_ROOT / "scripts" / "sync_vault.sh"
    try:
        sync_result = subprocess.run(
            ["bash", str(sync_script)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if sync_result.returncode != 0:
            steps.append(StepResult("sync_vault", False, f"sync_vault.sh failed: {sync_result.stderr.strip()[:300]}", required=False))
        else:
            steps.append(StepResult("sync_vault", True, "Vault changes committed and pushed.", required=False))
    except Exception as exc:
        steps.append(StepResult("sync_vault", False, f"sync_vault.sh error: {exc}", required=False))

    failures = [s for s in steps if s.required and not s.ok]
    overall_ok = len(failures) == 0

    report = {
        "ok": overall_ok,
        "skill": args.skill,
        "generated_at": _utc_now().isoformat(),
        "steps": [asdict(s) for s in steps],
        "metrics": metrics,
    }

    report_path = Path(args.report_out)
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception as exc:
        steps.append(StepResult("write_report", False, f"Failed writing report_out: {exc}"))
        overall_ok = False

    print(json.dumps(report, indent=2))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
