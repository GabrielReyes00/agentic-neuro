"""Session-local mastery intelligence: orient skip, stuck escalation, escalation inheritance."""

from __future__ import annotations

import re
from typing import Any

STUCK_PROBE_THRESHOLD = 2
OPEN_GAP_STATES = frozenset({"missed", "partially_repaired", "regressed"})


def parse_escalation_clause(content: str) -> str:
    """Extract an Escalation: clause from curated summary content."""
    text = str(content or "")
    match = re.search(r"(?i)escalation\s*:\s*(.+?)(?:\n|$)", text)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def escalation_directives_for_summary(
    conn,
    *,
    relevant_concept_ids: list[int] | None = None,
    limit: int = 3,
) -> list[dict[str, str]]:
    """Active curated summaries with explicit escalation clauses."""
    where = "WHERE ms.status = 'active'"
    params: list[object] = []
    if relevant_concept_ids:
        placeholders = ",".join("?" * len(relevant_concept_ids))
        where += f" AND (ms.concept_id IN ({placeholders}) OR COALESCE(ms.inventory_concept_id, '') != '')"
        params.extend(relevant_concept_ids)
    rows = conn.execute(
        f"""SELECT ms.id, ms.content, ms.inventory_concept_id, ms.concept_id,
                   c.display_name AS concept, c.inventory_concept_id AS concept_inventory_id
              FROM memory_summaries ms
              LEFT JOIN concepts c ON c.id = ms.concept_id
              {where}
             ORDER BY ms.importance_score DESC, ms.generated_at DESC
             LIMIT ?""",
        [*params, max(limit * 4, limit)],
    ).fetchall()
    out: list[dict[str, str]] = []
    for row in rows:
        directive = parse_escalation_clause(str(row["content"] or ""))
        if not directive:
            continue
        inv_id = str(row["inventory_concept_id"] or row["concept_inventory_id"] or "").strip()
        out.append({
            "summary_id": str(int(row["id"])),
            "inventory_concept_id": inv_id,
            "concept": str(row["concept"] or ""),
            "escalation_directive": directive,
        })
        if len(out) >= limit:
            break
    return out


def attach_escalation_directives(
    knowledge_map: list[dict[str, Any]],
    directives: list[dict[str, str]],
) -> None:
    """Attach escalation directives to matching inventory nodes."""
    by_inv = {
        str(item["inventory_concept_id"]): item["escalation_directive"]
        for item in directives
        if item.get("inventory_concept_id")
    }
    for entry in knowledge_map:
        if not isinstance(entry, dict):
            continue
        inv_id = str(entry.get("concept_id") or "")
        if inv_id in by_inv:
            entry["escalation_directive"] = by_inv[inv_id]


def orient_entry_nodes(knowledge_map: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        entry for entry in knowledge_map
        if isinstance(entry, dict) and str(entry.get("role", "entry")) == "entry"
    ]


# A topic with a substantial existing schema (most entries already exposed) has no
# "fog to clear": a minority of unexposed entries should not force full ORIENT when
# the learner has clearly engaged the topic. They are deepened/introduced within
# DEEPEN instead. ORIENT still fires for predominantly-new topics.
ORIENT_SKIP_EXPOSED_FRACTION = 0.6
ORIENT_SKIP_MIN_EXPOSED = 3
# A substantial body of partially-learned concepts is a schema worth DEEPENing even
# when the scope is broad and unexposed neighbors dominate by count. This keeps the
# ORIENT/DEEPEN decision robust to scope breadth (a focal study area inside a broadly
# anchored topic should DEEPEN the gaps, not re-orient the whole topic).
ORIENT_SKIP_MIN_DEEPENABLE = 4


def _orient_skip_reason(knowledge_map: list[dict[str, Any]]) -> str:
    entries = orient_entry_nodes(knowledge_map)
    if not entries:
        return ""
    exposed = [e for e in entries if str(e.get("exposure_status", "unexposed")) != "unexposed"]
    if len(exposed) == len(entries):
        return "all_entry_nodes_have_prior_exposure"
    if len(exposed) >= ORIENT_SKIP_MIN_EXPOSED and len(exposed) / len(entries) >= ORIENT_SKIP_EXPOSED_FRACTION:
        return "predominant_prior_exposure"
    deepenable = [
        e for e in exposed
        if str(e.get("exposure_status")) == "exposed_superficial"
        or str(e.get("knowledge_state", "")) in OPEN_GAP_STATES
    ]
    if len(deepenable) >= ORIENT_SKIP_MIN_DEEPENABLE:
        return "substantial_deepenable_core"
    return ""


def should_skip_orient(knowledge_map: list[dict[str, Any]]) -> bool:
    """Skip ORIENT when the learner already holds a schema for the topic.

    True when every entry node is exposed, OR when exposed entries predominate
    (>= 60% and >= 3), so a couple of unexposed entries do not force a learner who
    has clearly engaged the topic back into superficial fog-clearing.
    """
    return bool(_orient_skip_reason(knowledge_map))


def orient_skip_metadata(knowledge_map: list[dict[str, Any]]) -> dict[str, Any]:
    entries = orient_entry_nodes(knowledge_map)
    deep_entries = [
        str(entry.get("concept_id", ""))
        for entry in entries
        if str(entry.get("exposure_status", "unexposed")) != "unexposed"
    ]
    reason = _orient_skip_reason(knowledge_map)
    return {
        "skipped": bool(reason),
        "entry_nodes_total": len(entries),
        "entry_nodes_prior_deep": len(deep_entries),
        "reason": reason,
    }


def effective_unexposed_for_orient(knowledge_map: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entry-role nodes still needing landscape orientation."""
    return [
        entry for entry in orient_entry_nodes(knowledge_map)
        if str(entry.get("exposure_status", "unexposed")) == "unexposed"
    ]


def stuck_escalation_targets(
    knowledge_map: list[dict[str, Any]],
    *,
    cap: int = 4,
) -> list[dict[str, str]]:
    """Session-local stuck nodes that deserve an escalate interrupt."""
    targets: list[tuple[int, dict[str, str]]] = []
    for entry in knowledge_map:
        if not isinstance(entry, dict) or not entry.get("session_probed"):
            continue
        stuck_count = int(entry.get("stuck_probe_count", 0) or 0)
        exposure = str(entry.get("exposure_status", ""))
        state = str(entry.get("knowledge_state", ""))
        delta = str(entry.get("last_session_delta", ""))
        if stuck_count < STUCK_PROBE_THRESHOLD:
            continue
        if delta in {"improved", "repaired"}:
            continue
        if exposure != "exposed_superficial" and state not in OPEN_GAP_STATES:
            continue
        inv_id = str(entry.get("concept_id", ""))
        if not inv_id:
            continue
        targets.append((stuck_count, {
            "inventory_concept_id": inv_id,
            "concept": str(entry.get("concept", "")),
            "stuck_probe_count": str(stuck_count),
            "last_miss_cognitive_op": str(entry.get("last_miss_cognitive_op") or ""),
        }))
    targets.sort(key=lambda item: (-item[0], item[1]["inventory_concept_id"]))
    return [item for _score, item in targets[:cap]]


def mark_inventory_binding_tiers(
    conn,
    knowledge_map: list[dict[str, Any]],
) -> None:
    """Promote stable learner↔inventory bindings onto session map nodes."""
    from session_map import STABLE_BINDING_COUNT  # noqa: PLC0415

    for entry in knowledge_map:
        if not isinstance(entry, dict):
            continue
        matched = entry.get("matched_learner_concepts") or []
        if not matched:
            continue
        best_tier = str(entry.get("binding_tier", ""))
        for m in matched[:2]:
            if not isinstance(m, dict) or m.get("learner_concept_id") is None:
                continue
            row = conn.execute(
                """SELECT inventory_concept_id, COALESCE(binding_match_count, 0) AS binding_match_count
                     FROM concepts WHERE id = ?""",
                (int(m["learner_concept_id"]),),
            ).fetchone()
            if not row:
                continue
            inv_id = str(row["inventory_concept_id"] or "")
            count = int(row["binding_match_count"] or 0)
            if inv_id and inv_id == str(entry.get("concept_id", "")):
                if count >= STABLE_BINDING_COUNT:
                    best_tier = "bound"
                elif count >= 1:
                    best_tier = "provisional"
        if best_tier:
            entry["binding_tier"] = best_tier


def binding_quality_summary(knowledge_map: list[dict[str, Any]]) -> dict[str, int]:
    stable = provisional = unbound = 0
    for entry in knowledge_map:
        if not isinstance(entry, dict):
            continue
        tier = str(entry.get("binding_tier", ""))
        if tier == "bound":
            stable += 1
        elif tier == "provisional":
            provisional += 1
        else:
            unbound += 1
    return {"stable": stable, "provisional": provisional, "unbound": unbound}
