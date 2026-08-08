"""Lean cognitive-operation tagging for assessed learning exchanges."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

VALID_COGNITIVE_OPS = frozenset({
    "recall",
    "discrimination",
    "quantification",
    "sequencing",
    "mechanism",
    "transfer",
})

# Transfer breadth demonstrated twice in one sitting is not delayed transfer.
# Seven days is a conservative operational calibration boundary, not a fitted
# learner-specific forgetting model; the raw evidence span remains visible.
TRANSFER_REPLICATION_MIN_DAYS = 7.0

COGNITIVE_OP_RETEST_HINTS: dict[str, str] = {
    "recall": "Retest the same atomic fact in a clinically meaningful frame, then ask what it changes.",
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
    if any(x in hay for x in (
        "how would", "what changes if", "if instead", "changed frame", "changed setting",
        "different setting", "new scenario", "apply this", "generalize", "transfer",
    )):
        return "transfer"
    if any(x in hay for x in ("for each", "distinguish", " vs ", "same sbp", "different", "contrast", "mimic", "confus")):
        return "discrimination"
    if any(x in hay for x in ("first", "sequence", "next 5 minutes", "order", "before", "after which")):
        return "sequencing"
    if any(x in hay for x in (
        "why", "how does", "what explains", "equation", "physiologic", "mechanism",
        "because", "causes", "leads to", "produces", "pathophys", "biomechan",
    )):
        return "mechanism"
    # Flat or ambiguous prompts are recall until the question itself demonstrates
    # a higher-order operation. Defaulting to transfer overstates mastery.
    return "recall"


def trusted_operation_from_signal(*, operation: str, agent_signal_json: str = "") -> str:
    """Return a trustworthy operation from rows written by operation-aware logging.

    Historical rows predate operation-source metadata and are deliberately treated
    as unknown: the former classifier defaulted ambiguous prompts to ``transfer``,
    so accepting those rows would falsely promote factual recall to transfer.
    """
    op = _normalize(operation).replace(" ", "_").replace("-", "_")
    if op not in VALID_COGNITIVE_OPS:
        return ""
    try:
        signal = json.loads(agent_signal_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(signal, dict):
        return ""
    source = str(signal.get("cognitive_op_source") or "")
    logged_op = _normalize(str(signal.get("cognitive_op") or "")).replace(" ", "_").replace("-", "_")
    if source not in {"explicit", "inferred"} or logged_op != op:
        return ""
    return op


def mastery_depth_from_operations(operations: object) -> str:
    """Summarize the strongest demonstrated cognitive operation for one map node."""
    if isinstance(operations, str):
        values = [operations]
    elif isinstance(operations, (list, tuple, set, frozenset)):
        values = list(operations)
    else:
        values = []
    ops = {
        _normalize(str(value)).replace(" ", "_").replace("-", "_")
        for value in values
    } & VALID_COGNITIVE_OPS
    if "transfer" in ops:
        return "transfer_ready"
    if "mechanism" in ops:
        return "causal"
    if ops & {"discrimination", "sequencing"}:
        return "relational"
    if ops:
        return "factual"
    return "unknown"


def mastery_depth_from_evidence(
    evidence: object,
    *,
    active_gap: bool = False,
) -> str:
    """Conservative mastery depth from counted, cross-session evidence.

    A single successful transfer vignette is valuable evidence, but it is not
    enough to label a learner transfer-ready. That label requires two successful
    transfer probes in at least two sessions. Lower levels still reflect the
    strongest demonstrated operation, while an active gap prevents the terminal
    transfer-ready state.
    """
    if not isinstance(evidence, dict):
        return "unknown"

    normalized: dict[str, tuple[int, int, float]] = {}
    for raw_op, raw_payload in evidence.items():
        op = _normalize(str(raw_op)).replace(" ", "_").replace("-", "_")
        if op not in VALID_COGNITIVE_OPS:
            continue
        if isinstance(raw_payload, dict):
            count = int(raw_payload.get("count", 0) or 0)
            session_count = int(raw_payload.get("session_count", 0) or 0)
            if not session_count and isinstance(raw_payload.get("session_ids"), (list, tuple, set)):
                session_count = len({str(item) for item in raw_payload["session_ids"] if str(item)})
            span_days = float(raw_payload.get("span_days", 0.0) or 0.0)
        else:
            count = int(raw_payload or 0)
            session_count = 0
            span_days = 0.0
        if count > 0:
            normalized[op] = (count, session_count, span_days)

    transfer_count, transfer_sessions, transfer_span_days = normalized.get("transfer", (0, 0, 0.0))
    if (
        transfer_count >= 2
        and transfer_sessions >= 2
        and transfer_span_days >= TRANSFER_REPLICATION_MIN_DAYS
        and not active_gap
    ):
        return "transfer_ready"
    if "mechanism" in normalized:
        return "causal"
    if transfer_count or normalized.keys() & {"discrimination", "sequencing"}:
        return "relational"
    if normalized:
        return "factual"
    return "unknown"


def _parse_evidence_ts(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def add_operation_evidence(
    evidence: dict[str, dict[str, object]],
    *,
    operation: str,
    session_id: str = "",
    observed_at: str = "",
) -> None:
    """Accumulate one successful, operation-aware probe without scoring latency."""
    op = _normalize(operation).replace(" ", "_").replace("-", "_")
    if op not in VALID_COGNITIVE_OPS:
        return
    bucket = evidence.setdefault(op, {"count": 0, "session_ids": set(), "success_timestamps": set()})
    bucket["count"] = int(bucket.get("count", 0) or 0) + 1
    sessions = bucket.setdefault("session_ids", set())
    if not isinstance(sessions, set):
        sessions = {str(item) for item in sessions if str(item)}
        bucket["session_ids"] = sessions
    if session_id:
        sessions.add(str(session_id))
    timestamps = bucket.setdefault("success_timestamps", set())
    if not isinstance(timestamps, set):
        timestamps = {str(item) for item in timestamps if _parse_evidence_ts(item)}
        bucket["success_timestamps"] = timestamps
    if observed_at and _parse_evidence_ts(observed_at):
        timestamps.add(str(observed_at))


def serialize_operation_evidence(
    evidence: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Serialize counted operation evidence with a transparent temporal span."""
    serialized: dict[str, dict[str, object]] = {}
    for operation, values in evidence.items():
        sessions = sorted({str(item) for item in values.get("session_ids", []) if str(item)})
        raw_timestamps = {
            str(item) for item in values.get("success_timestamps", []) if _parse_evidence_ts(item)
        }
        for key in ("first_success_ts", "last_success_ts"):
            value = values.get(key)
            if value and _parse_evidence_ts(value):
                raw_timestamps.add(str(value))
        parsed = sorted(
            ((_parse_evidence_ts(item), item) for item in raw_timestamps),
            key=lambda item: item[0] or datetime.min.replace(tzinfo=timezone.utc),
        )
        span_days = 0.0
        if len(parsed) >= 2 and parsed[0][0] is not None and parsed[-1][0] is not None:
            span_days = max(0.0, (parsed[-1][0] - parsed[0][0]).total_seconds() / 86_400.0)
        payload: dict[str, object] = {
            "count": int(values.get("count", 0) or 0),
            "session_count": len(sessions),
            "session_ids": sessions,
            "span_days": round(span_days, 3),
        }
        if parsed:
            payload["first_success_ts"] = parsed[0][1]
            payload["last_success_ts"] = parsed[-1][1]
        serialized[str(operation)] = payload
    return serialized


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
