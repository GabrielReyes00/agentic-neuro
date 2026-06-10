"""Lean cognitive-operation tagging for assessed learning exchanges."""

from __future__ import annotations

import re

VALID_COGNITIVE_OPS = frozenset({
    "discrimination",
    "quantification",
    "sequencing",
    "mechanism",
    "transfer",
})

COGNITIVE_OP_RETEST_HINTS: dict[str, str] = {
    "discrimination": "Retest with a changed vignette that swaps the confusable finding or forces a single decisive discriminator.",
    "quantification": "Retest with a new number, threshold, dose, or time window that changes the management branch.",
    "sequencing": "Retest with higher acuity and ask for the first move, next move, and escalation trigger in order.",
    "mechanism": "Retest by asking why the anatomy/pathophysiology produces the finding, then apply it in a nearby case.",
    "transfer": "Retest under changed surface features, incomplete data, or a different clinical setting while holding the core principle fixed.",
}

_STOPWORDS = frozenset({
    "of", "the", "in", "and", "or", "vs", "for", "a", "an", "to", "with", "on",
    "by", "at", "from", "into", "after", "before", "their", "its",
})


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def classify_cognitive_op(*, concept: str = "", question: str = "", explicit: str = "") -> str:
    """Classify the probed cognitive operation; explicit agent value wins."""
    if explicit:
        op = _normalize(explicit).replace(" ", "_").replace("-", "_")
        if op in VALID_COGNITIVE_OPS:
            return op
    hay = _normalize(f"{concept} {question}")
    if any(x in hay for x in ("what map", "dose", "target", "threshold", "how fast", "mg", "mmhg", "mcg", "grade", "cutoff")):
        return "quantification"
    if any(x in hay for x in ("for each", "distinguish", " vs ", "same sbp", "different", "contrast", "mimic", "confus")):
        return "discrimination"
    if any(x in hay for x in ("first", "sequence", "next 5 minutes", "order", "before", "after which")):
        return "sequencing"
    if any(x in hay for x in ("why", "equation", "physiologic", "mechanism", "because", "pathophys")):
        return "mechanism"
    return "transfer"


def retest_hint_for_op(cognitive_op: str) -> str:
    return COGNITIVE_OP_RETEST_HINTS.get(cognitive_op, COGNITIVE_OP_RETEST_HINTS["transfer"])


def probe_feedback(*, cognitive_op: str, score: int, inventory_concept_id: str = "") -> dict[str, str]:
    """Compact per-turn feedback for policy=; omitted on clean passes when score=2."""
    if score >= 2:
        return {}
    payload = {
        "cognitive_op": cognitive_op,
        "outcome": "partial" if score == 1 else "miss",
        "retest_hint": retest_hint_for_op(cognitive_op),
    }
    if inventory_concept_id:
        payload["inventory_concept_id"] = inventory_concept_id
    return payload


def weak_operations_from_map(
    knowledge_map: list[dict[str, object]],
    *,
    cap: int = 2,
) -> list[dict[str, str]]:
    """Session-local weak cognitive ops from recent misses on the live map."""
    tallies: dict[str, dict[str, int]] = {}
    for entry in knowledge_map:
        if not isinstance(entry, dict):
            continue
        op = str(entry.get("last_miss_cognitive_op") or "").strip()
        if not op:
            continue
        inv_id = str(entry.get("concept_id") or "")
        bucket = tallies.setdefault(op, {"misses": 0, "inventory_id": inv_id})
        bucket["misses"] += 1
        if inv_id and not bucket.get("inventory_id"):
            bucket["inventory_id"] = inv_id
    ranked = sorted(tallies.items(), key=lambda item: (-item[1]["misses"], item[0]))
    out: list[dict[str, str]] = []
    for op, stats in ranked[:cap]:
        item = {"operation": op, "misses": str(stats["misses"])}
        if stats.get("inventory_id"):
            item["inventory_concept_id"] = str(stats["inventory_id"])
        item["retest_hint"] = retest_hint_for_op(op)
        out.append(item)
    return out
