"""ACGME readiness overlay for global memory-driven review."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

OPEN_GAP_STATES = frozenset({"missed", "partially_repaired", "regressed"})


def _acgme_title_pgy() -> dict[str, int]:
    """Map each ACGME catalog topic title to its target PGY level."""
    try:
        from concept_inventory import ACGME_PATH  # noqa: PLC0415

        catalog = json.loads(ACGME_PATH.read_text())
    except (OSError, ValueError, ImportError):
        return {}
    out: dict[str, int] = {}
    for milestone in (catalog.get("milestones") or {}).values():
        for topic in milestone.get("topics", []) or []:
            title = str(topic.get("title", ""))
            if not title:
                continue
            try:
                out[title] = int(topic.get("pgy_target", 1))
            except (TypeError, ValueError):
                continue
    return out


def _exposure_status(attempts: int, success_rate: float, open_gaps: int) -> str:
    if attempts == 0:
        return "unexposed"
    if attempts == 1 or success_rate < 0.6 or open_gaps > 0:
        return "exposed_superficial"
    return "exposed_deep"


def aggregate_learner_concept_stats(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Per-learner-concept assessed stats (fan-out safe), only concepts ever attempted.

    Attempts and open gaps are aggregated in separate pre-aggregated subqueries so
    the two one-to-many joins never multiply against each other (a claim_results x
    claim_state cartesian would inflate every count by the number of claim_state
    rows). The quick-answer exclusion lives inside the attempts subquery's WHERE so
    it actually drops those rows instead of merely nulling the exchange join. The
    learner display name and explicit binding are kept so the readiness overlay can
    lexically project concepts that carry assessed history but no explicit binding.
    """
    rows = conn.execute(
        """SELECT c.id, c.display_name,
                  COALESCE(c.inventory_concept_id, '') AS inventory_concept_id,
                  att.attempts AS attempts,
                  COALESCE(att.successes, 0) AS successes,
                  COALESCE(gap.open_gaps, 0) AS open_gaps
             FROM concepts c
             JOIN (
                 SELECT cr.concept_id,
                        COUNT(*) AS attempts,
                        SUM(CASE WHEN cr.score >= 2 THEN 1 ELSE 0 END) AS successes
                   FROM claim_results cr
                   LEFT JOIN exchanges ex ON ex.id = cr.exchange_id
                  WHERE COALESCE(ex.skill, '') != 'quick-answer'
                  GROUP BY cr.concept_id
             ) att ON att.concept_id = c.id
             LEFT JOIN (
                 SELECT concept_id, COUNT(*) AS open_gaps
                   FROM claim_state
                  WHERE origin = 'assessed'
                    AND state IN ('missed','partially_repaired','regressed')
                  GROUP BY concept_id
             ) gap ON gap.concept_id = c.id
            WHERE att.attempts > 0"""
    ).fetchall()
    return [
        {
            "display_name": str(r["display_name"] or ""),
            "inventory_concept_id": str(r["inventory_concept_id"] or ""),
            "attempts": int(r["attempts"] or 0),
            "successes": int(r["successes"] or 0),
            "open_gaps": int(r["open_gaps"] or 0),
        }
        for r in rows
    ]


def project_learner_history_onto_inventory(
    conn: sqlite3.Connection,
    inv: sqlite3.Connection,
) -> tuple[dict[str, dict[str, Any]], int, int]:
    """Per-inventory-id learner stats from explicit bindings plus lexical projection.

    Explicit `inventory_concept_id` bindings are authoritative. Learner concepts
    that carry assessed history but no explicit binding (the common case until the
    agent starts passing --inventory-concept-id) are lexically projected onto the
    inventory so the readiness overlay reflects real study history immediately
    instead of reporting everything as a blind spot.
    """
    from concept_inventory import LEARNER_MATCH_THRESHOLD, _lexical_score, _tokens  # noqa: PLC0415

    inv_tokens: dict[str, frozenset[str]] = {}
    for r in inv.execute("SELECT id, name FROM concepts"):
        inv_tokens[str(r["id"])] = _tokens(r["name"])
    for r in inv.execute("SELECT concept_id, alias FROM aliases"):
        cid = str(r["concept_id"])
        if cid in inv_tokens:
            inv_tokens[cid] = inv_tokens[cid] | _tokens(r["alias"])

    raw: dict[str, list[int]] = {}
    explicit_ids: set[str] = set()
    projected = 0
    for cs in aggregate_learner_concept_stats(conn):
        inv_id = cs["inventory_concept_id"]
        if inv_id:
            explicit_ids.add(inv_id)
        else:
            lt = _tokens(cs["display_name"])
            best: tuple[float, str] | None = None
            for iid, toks in inv_tokens.items():
                score = _lexical_score(lt, toks)
                if best is None or score > best[0] or (score == best[0] and iid < best[1]):
                    best = (score, iid)
            if not best or best[0] < LEARNER_MATCH_THRESHOLD:
                continue
            inv_id = best[1]
            projected += 1
        acc = raw.setdefault(inv_id, [0, 0, 0])
        acc[0] += cs["attempts"]
        acc[1] += cs["successes"]
        acc[2] += cs["open_gaps"]
    learner_by_inv = {
        iid: {
            "attempts": a,
            "success_rate": round(s / max(1, a), 3),
            "open_gaps": g,
        }
        for iid, (a, s, g) in raw.items()
    }
    return learner_by_inv, len(explicit_ids), projected


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

    inv = _open_inventory()
    try:
        learner_by_inv, explicit_bindings, lexically_projected = project_learner_history_onto_inventory(
            conn, inv
        )
        # One row per concept. A LEFT JOIN to acgme_links would fan out concepts
        # that carry multiple milestone links, double-counting them in the domain
        # totals; aggregate one representative link per concept instead.
        inv_rows = inv.execute("SELECT id, name, domain, tier FROM concepts").fetchall()
        acgme_by_concept: dict[str, tuple[str, str]] = {}
        for r in inv.execute(
            "SELECT concept_id, milestone, acgme_title FROM acgme_links ORDER BY concept_id, acgme_title"
        ):
            acgme_by_concept.setdefault(str(r["concept_id"]), (str(r["milestone"] or ""), str(r["acgme_title"] or "")))
    finally:
        inv.close()

    catalog_topics_total = sum(1 for _ in _load_curriculum_catalog())
    title_pgy = _acgme_title_pgy()
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
        milestone, acgme_title = acgme_by_concept.get(inv_id, ("", ""))
        # Scope blind spots to what a learner at this PGY level is expected to know
        # (topics whose target PGY is at or below the requested lens). Topics without
        # a known PGY target are kept rather than silently dropped.
        topic_pgy = title_pgy.get(acgme_title)
        pgy_relevant = topic_pgy is None or topic_pgy <= pgy_target
        if exposure == "unexposed" and acgme_title and pgy_relevant and len(blind_spots) < spot_limit:
            blind_spots.append({
                "inventory_concept_id": inv_id,
                "concept": str(row["name"]),
                "domain": domain,
                "milestone": milestone,
                "acgme_title": acgme_title,
                "pgy_target": topic_pgy,
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
        "pgy_target": pgy_target,
        "curriculum_catalog_topics": catalog_topics_total,
        "inventory_concepts_with_learner_history": len(learner_by_inv),
        "explicit_inventory_bindings": explicit_bindings,
        "lexically_projected_concepts": lexically_projected,
        "domain_gaps": domain_gaps,
        "top_blind_spots": blind_spots,
        "teaching_note": (
            "Use domain_gaps and top_blind_spots to choose the next global review focus. "
            "Exposure blends explicit inventory bindings with a lexical projection of "
            "assessed history; it is a readiness estimate, not a session handoff from prior topics."
        ),
    }
