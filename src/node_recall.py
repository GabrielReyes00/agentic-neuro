"""Inventory-node drilldown and knowledge-map enrichment for study-review."""

from __future__ import annotations

import sqlite3
from typing import Any

ORIENT_MENU_CAP = 12
LEARNER_SURFACE_CLAIM_CAP = 2
STUCK_EXPOSURE = frozenset({"exposed_superficial"})
STUCK_STATES = frozenset({"missed", "partially_repaired", "regressed", "untested"})


def learner_surface_for_concept(conn: sqlite3.Connection, learner_concept_id: int) -> dict[str, Any]:
    """Compact high-signal learner evidence for one SQLite concept row."""
    from study_memory import (  # noqa: PLC0415
        OPEN_GAP_STATES,
        _active_prereq_gaps,
        _claim_state_repair_stats,
        _claim_memory_trace,
        _compact_text,
        _concept_relations,
    )

    row = conn.execute(
        "SELECT id, display_name, inventory_concept_id FROM concepts WHERE id = ?",
        (learner_concept_id,),
    ).fetchone()
    if not row:
        return {}
    states = conn.execute(
        """SELECT id, state, priority, claim_text, gap_type
           FROM claim_state
           WHERE concept_id = ? AND origin = 'assessed'
           ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                    CASE state WHEN 'missed' THEN 0 WHEN 'regressed' THEN 1 WHEN 'partially_repaired' THEN 2 ELSE 3 END
           LIMIT ?""",
        (learner_concept_id, LEARNER_SURFACE_CLAIM_CAP + 2),
    ).fetchall()
    open_claims = [
        {
            "claim_state_id": int(s["id"]),
            "state": s["state"],
            "priority": s["priority"],
            "claim_text": _compact_text(str(s["claim_text"]), 120),
            "gap_type": s["gap_type"] or "",
        }
        for s in states
        if s["state"] in OPEN_GAP_STATES
    ][:LEARNER_SURFACE_CLAIM_CAP]
    top_gap = open_claims[0]["claim_text"] if open_claims else ""
    primary_state_id = int(open_claims[0]["claim_state_id"]) if open_claims else None
    memory_trace = (
        _claim_memory_trace(conn, primary_state_id, history_limit=5)
        if primary_state_id is not None
        else {}
    )
    last_misc = str(memory_trace.get("misconception") or "")
    relations = _concept_relations(conn, learner_concept_id)
    repair_stats = (
        _claim_state_repair_stats(conn, int(open_claims[0]["claim_state_id"]))
        if open_claims
        else {"failures": 0, "repairs": 0}
    )
    return {
        "learner_concept_id": learner_concept_id,
        "display_name": row["display_name"],
        "inventory_concept_id": row["inventory_concept_id"] or "",
        "open_claims": len(open_claims),
        "top_gap": _compact_text(top_gap, 100),
        "last_misconception_verbatim": _compact_text(last_misc, 120),
        "memory_trace": memory_trace,
        "prerequisites": (relations.get("prerequisites") or [])[:3],
        "active_prerequisite_gaps": _active_prereq_gaps(conn, learner_concept_id)[:2],
        "semantic_competitors": (relations.get("semantic_competitors") or [])[:2],
        "repair_velocity": repair_stats,
        "open_claim_details": open_claims,
    }


def enrich_knowledge_map_learner_surfaces(
    conn: sqlite3.Connection,
    knowledge_map: list[dict[str, Any]],
) -> None:
    """Attach compact learner_surface to inventory nodes with matched learner concepts."""
    for entry in knowledge_map:
        if not isinstance(entry, dict):
            continue
        matched = entry.get("matched_learner_concepts") or []
        if not matched:
            continue
        surfaces: list[dict[str, Any]] = []
        for m in matched[:2]:
            if not isinstance(m, dict) or m.get("learner_concept_id") is None:
                continue
            surface = learner_surface_for_concept(conn, int(m["learner_concept_id"]))
            if surface:
                surfaces.append(surface)
        if surfaces:
            entry["learner_surface"] = surfaces[0] if len(surfaces) == 1 else surfaces
            primary = surfaces[0]
            if primary.get("open_claims"):
                entry["open_claims"] = primary["open_claims"]
            if primary.get("top_gap"):
                entry["top_gap"] = primary["top_gap"]
            if primary.get("last_misconception_verbatim"):
                entry["last_misconception_verbatim"] = primary["last_misconception_verbatim"]


def build_orient_menu(
    knowledge_map: list[dict[str, Any]],
    *,
    cap: int = ORIENT_MENU_CAP,
) -> list[dict[str, str]]:
    """Capped unexposed entry nodes for ORIENT phase choice menus."""
    from concept_inventory import TIER_ORDER  # noqa: PLC0415

    candidates = [
        entry
        for entry in knowledge_map
        if isinstance(entry, dict)
        and entry.get("exposure_status") == "unexposed"
        and entry.get("role", "entry") == "entry"
    ]
    candidates.sort(
        key=lambda e: (
            TIER_ORDER.get(str(e.get("tier", "core")), 1),
            str(e.get("concept", "")),
        )
    )
    menu: list[dict[str, str]] = []
    for entry in candidates[:cap]:
        menu.append({
            "concept_id": str(entry.get("concept_id", "")),
            "concept": str(entry.get("concept", "")),
            "tier": str(entry.get("tier", "")),
            "type": str(entry.get("type", "")),
        })
    return menu


def session_handoff_from_map(session_map: dict[str, Any]) -> dict[str, Any]:
    """Structured inventory-ID handoff skeleton from the live session map."""
    priority: list[str] = []
    improved: list[str] = []
    reviewed: list[str] = []
    unbound: list[str] = []
    for entry in session_map.get("knowledge_map") or []:
        if not isinstance(entry, dict):
            continue
        inv_id = str(entry.get("concept_id", ""))
        if not inv_id:
            continue
        delta = str(entry.get("last_session_delta", ""))
        exposure = str(entry.get("exposure_status", ""))
        state = str(entry.get("knowledge_state", ""))
        if delta == "improved":
            improved.append(inv_id)
        elif delta in {"reviewed", "repaired", "newly_exposed"}:
            reviewed.append(inv_id)
        if (
            entry.get("session_probed")
            and (exposure in STUCK_EXPOSURE or state in STUCK_STATES)
            and delta not in {"improved", "repaired"}
        ):
            priority.append(inv_id)
    for item in session_map.get("unmatched_learner_concepts") or []:
        if isinstance(item, dict) and item.get("concept"):
            unbound.append(str(item["concept"]))
    stats = session_map.get("session_stats") or {}
    return {
        "priority_inventory_ids": priority[:8],
        "improved_inventory_ids": improved[:8],
        "reviewed_inventory_ids": reviewed[:8],
        "unbound_concepts": unbound[:5],
        "session_progress": {k: int(stats.get(k, 0)) for k in (
            "newly_exposed", "reviewed", "improved", "regressed", "repaired", "probed"
        )},
    }


def node_recall(
    conn: sqlite3.Connection,
    *,
    inventory_concept_id: str,
    topic: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """Point-of-need drilldown for one inventory concept node."""
    from concept_inventory import _open_inventory  # noqa: PLC0415
    from session_map import load as load_session_map  # noqa: PLC0415
    from study_memory import (  # noqa: PLC0415
        _due_claims_for_summary,
        resolve_topic,
        shadow_rule_signals_for_summary,
    )

    inv = _open_inventory()
    try:
        row = inv.execute(
            """SELECT c.id, c.name, c.topic_id, c.domain, c.type, c.tier, c.blurb, t.name AS topic_name
               FROM concepts c JOIN topics t ON t.id = c.topic_id WHERE c.id = ?""",
            (inventory_concept_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": f"unknown inventory concept id: {inventory_concept_id}"}
        inventory_node = {
            "concept_id": row["id"],
            "concept": row["name"],
            "topic_id": row["topic_id"],
            "domain": row["domain"],
            "type": row["type"],
            "tier": row["tier"],
            "blurb": row["blurb"],
            "topic_name": row["topic_name"],
        }
        edges = {
            "prereq": [],
            "discriminator": [],
            "related": [],
        }
        for edge_type in edges:
            rows = inv.execute(
                """SELECT e.dst, c.name FROM edges e
                   JOIN concepts c ON c.id = e.dst
                   WHERE e.src = ? AND e.edge_type = ? LIMIT 6""",
                (inventory_concept_id, edge_type),
            ).fetchall()
            edges[edge_type] = [{"concept_id": r["dst"], "concept": r["name"]} for r in rows]
    finally:
        inv.close()

    learner_concept_ids: list[int] = []
    session_entry: dict[str, Any] | None = None
    if session_id:
        smap = load_session_map(session_id)
        if smap:
            for entry in smap.get("knowledge_map") or []:
                if isinstance(entry, dict) and entry.get("concept_id") == inventory_concept_id:
                    session_entry = entry
                    break
    if session_entry:
        for m in session_entry.get("matched_learner_concepts") or []:
            if isinstance(m, dict) and m.get("learner_concept_id") is not None:
                learner_concept_ids.append(int(m["learner_concept_id"]))
    if not learner_concept_ids:
        rows = conn.execute(
            "SELECT id FROM concepts WHERE inventory_concept_id = ?",
            (inventory_concept_id,),
        ).fetchall()
        learner_concept_ids = [int(r["id"]) for r in rows]
    if not learner_concept_ids and topic:
        try:
            res = resolve_topic(conn, topic)
            topic_row = conn.execute("SELECT id FROM topics WHERE canonical_slug = ?", (res.slug,)).fetchone()
            if topic_row:
                rows = conn.execute(
                    """SELECT c.id FROM concepts c
                       WHERE c.topic_id = ? AND (
                         c.inventory_concept_id = ?
                         OR lower(c.display_name) = lower(?)
                       )""",
                    (int(topic_row["id"]), inventory_concept_id, inventory_node["concept"]),
                ).fetchall()
                learner_concept_ids = [int(r["id"]) for r in rows]
        except Exception as exc:  # noqa: BLE001 - optional fallback lookup, but observe the loss
            print(f"WARN node_recall_topic_lookup_failed topic={topic}: {exc}", file=sys.stderr)

    surfaces = [learner_surface_for_concept(conn, cid) for cid in learner_concept_ids[:3]]
    shadows = shadow_rule_signals_for_summary(conn, relevant_concept_ids=learner_concept_ids, limit=4)
    due: list[dict[str, Any]] = []
    if topic:
        try:
            res = resolve_topic(conn, topic)
            topic_row = conn.execute("SELECT id FROM topics WHERE canonical_slug = ?", (res.slug,)).fetchone()
            if topic_row:
                due_all = _due_claims_for_summary(conn, topic_id=int(topic_row["id"]), limit=12)
                surface_names = {str(s.get("display_name", "")).lower() for s in surfaces if s}
                due = [
                    item for item in due_all
                    if isinstance(item, dict)
                    and str(item.get("concept", "")).lower() in surface_names
                ]
        except Exception as exc:  # noqa: BLE001 - optional signal, but observe the loss
            print(f"WARN node_recall_due_claims_failed topic={topic}: {exc}", file=sys.stderr)

    return {
        "ok": True,
        "inventory_node": inventory_node,
        "inventory_edges": edges,
        "session_entry": session_entry,
        "learner_surfaces": [s for s in surfaces if s],
        "shadow_rules": shadows,
        "due_claims": due[:4],
        "teaching_hint": (
            "Use learner_surfaces and shadow_rules to design the next probe; "
            "do not narrate this payload to the learner."
        ),
    }
