"""ACGME readiness overlay for global memory-driven review."""

from __future__ import annotations

import sqlite3
from typing import Any

OPEN_GAP_STATES = frozenset({"missed", "partially_repaired", "regressed"})


def _exposure_status(attempts: int, success_rate: float, open_gaps: int) -> str:
    if attempts == 0:
        return "unexposed"
    if attempts == 1 or success_rate < 0.6 or open_gaps > 0:
        return "exposed_superficial"
    return "exposed_deep"


def build_acgme_readiness_overlay(
    conn: sqlite3.Connection,
    *,
    pgy_target: int = 1,
    domain_limit: int = 6,
    spot_limit: int = 8,
) -> dict[str, Any]:
    """Lean PGY-scoped readiness from learner inventory bindings + ACGME links."""
    try:
        from concept_inventory import _open_inventory  # noqa: PLC0415
        from study_memory import _load_curriculum_catalog  # noqa: PLC0415
    except ImportError:
        return {"status": "unavailable", "reason": "inventory_or_curriculum_unavailable"}

    learner_rows = conn.execute(
        """SELECT c.inventory_concept_id,
                  COUNT(cr.id) AS attempts,
                  SUM(CASE WHEN cr.score >= 2 THEN 1 ELSE 0 END) AS successes,
                  SUM(CASE WHEN cs.state IN ('missed','partially_repaired','regressed') THEN 1 ELSE 0 END) AS open_gaps
             FROM concepts c
             LEFT JOIN claim_results cr ON cr.concept_id = c.id
             LEFT JOIN exchanges ex ON ex.id = cr.exchange_id AND COALESCE(ex.skill, '') != 'quick-answer'
             LEFT JOIN claim_state cs ON cs.concept_id = c.id AND cs.origin = 'assessed'
            WHERE COALESCE(c.inventory_concept_id, '') != ''
            GROUP BY c.inventory_concept_id"""
    ).fetchall()
    learner_by_inv = {
        str(row["inventory_concept_id"]): {
            "attempts": int(row["attempts"] or 0),
            "success_rate": round(int(row["successes"] or 0) / max(1, int(row["attempts"] or 0)), 3),
            "open_gaps": int(row["open_gaps"] or 0),
        }
        for row in learner_rows
    }

    inv = _open_inventory()
    try:
        inv_rows = inv.execute(
            """SELECT c.id, c.name, c.domain, c.tier,
                      al.milestone, al.acgme_title
                 FROM concepts c
                 LEFT JOIN acgme_links al ON al.concept_id = c.id"""
        ).fetchall()
    finally:
        inv.close()

    pgy_topics = {
        title
        for title, _domain, _tokens in _load_curriculum_catalog()
    }
    domain_stats: dict[str, dict[str, Any]] = {}
    blind_spots: list[dict[str, str]] = []
    for row in inv_rows:
        inv_id = str(row["id"])
        domain = str(row["domain"] or "general")
        learner = learner_by_inv.get(inv_id, {"attempts": 0, "success_rate": 0.0, "open_gaps": 0})
        exposure = _exposure_status(
            int(learner["attempts"]),
            float(learner["success_rate"]),
            int(learner["open_gaps"]),
        )
        bucket = domain_stats.setdefault(domain, {
            "domain": domain,
            "inventory_total": 0,
            "unexposed": 0,
            "superficial_or_stuck": 0,
            "deep": 0,
            "priority_inventory_ids": [],
        })
        bucket["inventory_total"] += 1
        if exposure == "unexposed":
            bucket["unexposed"] += 1
        elif exposure == "exposed_superficial":
            bucket["superficial_or_stuck"] += 1
        else:
            bucket["deep"] += 1
        if exposure != "exposed_deep" and len(bucket["priority_inventory_ids"]) < 3:
            bucket["priority_inventory_ids"].append(inv_id)
        milestone = str(row["milestone"] or "")
        acgme_title = str(row["acgme_title"] or "")
        if exposure == "unexposed" and acgme_title and len(blind_spots) < spot_limit:
            blind_spots.append({
                "inventory_concept_id": inv_id,
                "concept": str(row["name"]),
                "domain": domain,
                "milestone": milestone,
                "acgme_title": acgme_title,
            })

    domain_gaps = sorted(
        domain_stats.values(),
        key=lambda item: (
            -(int(item["superficial_or_stuck"]) + int(item["unexposed"])),
            -int(item["unexposed"]),
            str(item["domain"]),
        ),
    )[:domain_limit]

    return {
        "status": "ok",
        "pgy_lens": pgy_target,
        "catalog_topics_seen": len(pgy_topics),
        "learner_inventory_bindings": len(learner_by_inv),
        "domain_gaps": domain_gaps,
        "top_blind_spots": blind_spots,
        "teaching_note": (
            "Use domain_gaps and top_blind_spots to choose the next global review focus. "
            "This overlay is PGY-scoped readiness, not a session handoff from prior topics."
        ),
    }
