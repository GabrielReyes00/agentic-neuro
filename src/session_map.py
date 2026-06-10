"""Session-scoped inventory knowledge map: create, patch, policy, and lifecycle.

The live map is the single source of truth during a study-review session.
Startup builds it from the concept inventory; each log-answer patches nodes
incrementally; end-session deletes the file.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
SESSIONS_DIR = BASE_DIR / "data" / "Sessions"

LEARNER_MATCH_THRESHOLD = 0.5
STABLE_BINDING_COUNT = 2

OPEN_GAP_STATES = frozenset({"missed", "partially_repaired", "regressed"})
MISCONCEPTION_GAP_TYPES = frozenset({"conceptual_confusion", "cross_contamination"})
STATE_SEVERITY = {
    "missed": 0,
    "partially_repaired": 1,
    "regressed": 2,
    "repaired_same_session": 3,
    "passed": 4,
    "untested": 99,
}

_STOPWORDS = frozenset({
    "of", "the", "in", "and", "or", "vs", "for", "a", "an", "to", "with", "on",
    "by", "at", "from", "into", "after", "before", "their", "its",
})


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 1)


def _lexical_score(query_tokens: frozenset[str], candidate_tokens: frozenset[str]) -> float:
    if not query_tokens or not candidate_tokens:
        return 0.0
    overlap = query_tokens & candidate_tokens
    if not overlap:
        return 0.0
    jaccard = len(overlap) / len(query_tokens | candidate_tokens)
    containment = len(overlap) / min(len(query_tokens), len(candidate_tokens))
    return max(jaccard, 0.85 * containment)


def _sanitize_session_id(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", session_id)


def session_map_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"knowledge_map_{_sanitize_session_id(session_id)}.json"


def _empty_session_stats() -> dict[str, int]:
    return {
        "newly_exposed": 0,
        "reviewed": 0,
        "improved": 0,
        "regressed": 0,
        "repaired": 0,
        "probed": 0,
    }


def create_from_projection(
    projection: dict[str, Any],
    *,
    session_id: str,
    profile: str,
    doc_path: str = "",
    learner_topics: list[str] | None = None,
) -> dict[str, Any]:
    """Build a session map document from a map-learner projection."""
    knowledge_map = list(projection.get("knowledge_map") or [])
    for entry in knowledge_map:
        entry.setdefault("binding_source", "startup_projection")
        entry.setdefault("session_probed", False)
        entry.setdefault("artifact_native", bool(doc_path and profile == "doc"))
        entry.setdefault("stuck_probe_count", 0)
        entry.setdefault("last_miss_cognitive_op", "")
    return {
        "version": 1,
        "session_id": session_id,
        "profile": profile,
        "doc_path": doc_path,
        "learner_topics": list(learner_topics or []),
        "scope": projection.get("scope", {}),
        "edges": projection.get("edges", []),
        "knowledge_map": knowledge_map,
        "unmatched_learner_concepts": list(projection.get("unmatched_learner_concepts") or []),
        "session_stats": _empty_session_stats(),
        "teaching_priority": "artifact_primary" if profile == "doc" and doc_path else "map_primary",
    }


def write(session_id: str, data: dict[str, Any]) -> None:
    path = session_map_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["session_id"] = session_id
    path.write_text(_json_dumps(data), encoding="utf-8")


def load(session_id: str) -> dict[str, Any] | None:
    path = session_map_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def delete(session_id: str) -> bool:
    path = session_map_path(session_id)
    if path.exists():
        path.unlink()
        return True
    return False


def _node_index(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(entry["concept_id"]): entry
        for entry in data.get("knowledge_map", [])
        if isinstance(entry, dict) and entry.get("concept_id")
    }


def lexical_match_inventory_id(concept_text: str, data: dict[str, Any]) -> tuple[str | None, float]:
    """Match free-text concept label to a scoped inventory node."""
    query_tokens = _tokens(concept_text)
    if not query_tokens:
        return None, 0.0
    best_score = 0.0
    best_id: str | None = None
    for entry in data.get("knowledge_map", []):
        if not isinstance(entry, dict):
            continue
        node_tokens = _tokens(str(entry.get("concept", "")))
        score = _lexical_score(query_tokens, node_tokens)
        cid = str(entry.get("concept_id", ""))
        if score > best_score or (score == best_score and cid and (best_id is None or cid < best_id)):
            best_score = score
            best_id = cid
    if best_score >= LEARNER_MATCH_THRESHOLD and best_id:
        return best_id, best_score
    return None, best_score


def resolve_inventory_id(
    *,
    inventory_concept_id: str,
    concept_text: str,
    data: dict[str, Any],
) -> tuple[str | None, str, float]:
    """Resolve inventory concept id: explicit id, else lexical provisional match."""
    nodes = _node_index(data)
    if inventory_concept_id and inventory_concept_id in nodes:
        return inventory_concept_id, "bound", 1.0
    matched, score = lexical_match_inventory_id(concept_text, data)
    if matched:
        return matched, "provisional", score
    return None, "unbound", score


def _exposure_from_counts(attempts: int, successes: int, avg_stability: float) -> str:
    success_rate = successes / attempts if attempts else 0.0
    if attempts == 0:
        return "unexposed"
    if attempts == 1 or avg_stability < 2.0 or success_rate < 0.6:
        return "exposed_superficial"
    return "exposed_deep"


def _knowledge_state_for_score(correct: int, previous: str | None) -> str:
    if correct == 2:
        if previous in OPEN_GAP_STATES:
            return "repaired_same_session"
        return "passed"
    if correct == 1:
        return "partially_repaired"
    return "missed"


def _session_delta(
    *,
    prior_exposure: str,
    new_exposure: str,
    prior_state: str,
    new_state: str,
    correct: int,
) -> str:
    if prior_exposure == "unexposed":
        return "newly_exposed"
    if correct == 2 and prior_state in OPEN_GAP_STATES:
        return "repaired"
    if correct == 2 and prior_exposure == "exposed_superficial" and new_exposure == "exposed_deep":
        return "improved"
    if correct < 2 and prior_state in {"passed", "repaired_same_session"}:
        return "regressed"
    if prior_exposure != "unexposed":
        return "reviewed"
    return "probed"


def patch_after_log(
    data: dict[str, Any],
    *,
    inventory_concept_id: str,
    concept_text: str,
    correct: int,
    exchange_id: int,
    coverage_role: str = "",
    learner_concept_id: int | None = None,
    cognitive_op: str = "",
) -> tuple[dict[str, Any], str]:
    """Incrementally update one knowledge-map node after an assessed exchange."""
    inv_id, binding_tier, match_score = resolve_inventory_id(
        inventory_concept_id=inventory_concept_id,
        concept_text=concept_text,
        data=data,
    )
    stats = data.setdefault("session_stats", _empty_session_stats())
    if not inv_id:
        unmatched = data.setdefault("unmatched_learner_concepts", [])
        unmatched.append({
            "concept": concept_text,
            "learner_concept_id": learner_concept_id,
            "exchange_id": exchange_id,
            "binding_tier": "unbound",
            "match_score": round(match_score, 3),
        })
        stats["probed"] = stats.get("probed", 0) + 1
        return data, "unbound"

    nodes = _node_index(data)
    entry = nodes[inv_id]
    prior_exposure = str(entry.get("exposure_status", "unexposed"))
    prior_state = str(entry.get("knowledge_state", "untested"))

    attempts = int(entry.get("attempts_count", 0)) + 1
    successes = int(entry.get("sqlite_success_rate", 0) * int(entry.get("attempts_count", 0)))
    if correct >= 2:
        successes += 1
    success_rate = round(successes / attempts, 3) if attempts else 0.0
    avg_stability = float(entry.get("avg_stability", 1.0))
    if correct >= 2:
        avg_stability = min(4.0, avg_stability + 0.5)
    elif correct == 0:
        avg_stability = max(0.5, avg_stability - 0.5)

    new_state = _knowledge_state_for_score(correct, prior_state if prior_state != "untested" else None)
    new_exposure = _exposure_from_counts(attempts, successes, avg_stability)
    delta = _session_delta(
        prior_exposure=prior_exposure,
        new_exposure=new_exposure,
        prior_state=prior_state,
        new_state=new_state,
        correct=correct,
    )

    stuck_probe_count = int(entry.get("stuck_probe_count", 0) or 0)
    if correct >= 2:
        stuck_probe_count = 0
    elif delta in {"reviewed", "regressed"} or new_state in OPEN_GAP_STATES:
        stuck_probe_count += 1

    entry.update({
        "exposure_status": new_exposure,
        "knowledge_state": new_state,
        "attempts_count": attempts,
        "sqlite_success_rate": success_rate,
        "avg_stability": avg_stability,
        "session_probed": True,
        "last_exchange_id": exchange_id,
        "last_session_delta": delta,
        "binding_source": "explicit" if inventory_concept_id else "lexical_backfill",
        "binding_tier": binding_tier,
        "match_score": round(match_score, 3),
        "active_misconception": correct == 0 and bool(entry.get("active_misconception")),
        "stuck_probe_count": stuck_probe_count,
        "last_cognitive_op": cognitive_op or entry.get("last_cognitive_op", ""),
    })
    if correct < 2 and cognitive_op:
        entry["last_miss_cognitive_op"] = cognitive_op
    if coverage_role == "primary_doc":
        entry["artifact_native"] = True
    if learner_concept_id is not None:
        matched = list(entry.get("matched_learner_concepts") or [])
        if not any(m.get("learner_concept_id") == learner_concept_id for m in matched if isinstance(m, dict)):
            matched.append({
                "learner_concept_id": learner_concept_id,
                "name": concept_text,
                "match_score": round(match_score, 3),
                "binding_source": entry["binding_source"],
            })
        entry["matched_learner_concepts"] = matched

    stat_key = {
        "newly_exposed": "newly_exposed",
        "reviewed": "reviewed",
        "improved": "improved",
        "regressed": "regressed",
        "repaired": "repaired",
    }.get(delta)
    if stat_key:
        stats[stat_key] = stats.get(stat_key, 0) + 1
    stats["probed"] = stats.get("probed", 0) + 1
    return data, delta


def session_progress(data: dict[str, Any]) -> dict[str, int]:
    stats = data.get("session_stats", {})
    if not isinstance(stats, dict):
        return _empty_session_stats()
    return {k: int(stats.get(k, 0)) for k in _empty_session_stats()}


def apply_artifact_priority(
    plan: dict[str, Any],
    knowledge_map: list[dict[str, Any]],
    *,
    profile: str,
    doc_path: str,
) -> dict[str, Any]:
    """Doc-anchored sessions: artifact content leads; map supplies context."""
    if profile != "doc" or not doc_path or not isinstance(plan, dict):
        return plan
    plan = dict(plan)
    artifact_native: list[str] = []
    map_context: list[str] = []
    for entry in knowledge_map:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("concept", ""))
        if not name:
            continue
        if entry.get("artifact_native") or entry.get("role") == "entry":
            artifact_native.append(name)
        elif entry.get("exposure_status") == "unexposed":
            map_context.append(name)
        else:
            artifact_native.append(name)
    targets = plan.get("target_concepts")
    if isinstance(targets, list):
        artifact_set = {n.lower() for n in artifact_native}
        ordered = [t for t in targets if str(t).lower() in artifact_set]
        ordered.extend(t for t in targets if str(t).lower() not in artifact_set)
        plan["target_concepts"] = ordered
    directives = list(plan.get("pedagogical_directives") or [])
    artifact_rule = (
        "Artifact Priority: teach from the requested document first. "
        "Use map-only unexposed concepts only at phase boundaries, for prerequisite gaps, "
        "misconception repair, or transfer after artifact material is substantially covered."
    )
    if artifact_rule not in directives:
        directives.insert(0, artifact_rule)
    plan["pedagogical_directives"] = directives
    plan["teaching_priority"] = "artifact_primary"
    plan["artifact_native_targets"] = artifact_native[:25]
    plan["map_context_targets"] = map_context[:15]
    return plan


def compute_policy_from_session(
    data: dict[str, Any],
    conn: sqlite3.Connection,
    *,
    topic_id: int,
    topic_slug: str,
) -> dict[str, Any]:
    from cognitive_ops import weak_operations_from_map  # noqa: PLC0415
    from mastery_intelligence import (  # noqa: PLC0415
        binding_quality_summary,
        orient_skip_metadata,
        stuck_escalation_targets,
    )
    from study_memory import (  # noqa: PLC0415
        _compute_teaching_policy,
        _due_claims_for_summary,
        shadow_rule_signals_for_summary,
        TARGET_CONCEPTS_COMPACT_CAP,
    )

    knowledge_map = list(data.get("knowledge_map") or [])
    if not knowledge_map:
        return {}
    due = _due_claims_for_summary(conn, topic_id=topic_id, limit=8)
    concept_ids = [
        int(m["learner_concept_id"])
        for entry in knowledge_map
        for m in (entry.get("matched_learner_concepts") or [])
        if isinstance(m, dict) and m.get("learner_concept_id") is not None
    ]
    shadows = shadow_rule_signals_for_summary(conn, relevant_concept_ids=concept_ids, limit=4)
    plan = _compute_teaching_policy(
        knowledge_map,
        due_claims=due,
        shadow_rule_signals=shadows,
        stuck_escalations=stuck_escalation_targets(knowledge_map),
        orient_skip=orient_skip_metadata(knowledge_map),
    )
    weak_ops = weak_operations_from_map(knowledge_map)
    if weak_ops:
        decision_inputs = dict(plan.get("decision_inputs") or {})
        decision_inputs["weak_operations"] = weak_ops
        plan["decision_inputs"] = decision_inputs
    binding_quality = binding_quality_summary(knowledge_map)
    if any(binding_quality.values()):
        decision_inputs = dict(plan.get("decision_inputs") or {})
        decision_inputs["binding_quality"] = binding_quality
        plan["decision_inputs"] = decision_inputs
    plan = apply_artifact_priority(
        plan,
        knowledge_map,
        profile=str(data.get("profile", "")),
        doc_path=str(data.get("doc_path", "")),
    )
    if isinstance(plan.get("target_concepts"), list) and len(plan["target_concepts"]) > TARGET_CONCEPTS_COMPACT_CAP:
        targets = list(plan["target_concepts"])
        plan = dict(plan)
        plan["target_concepts"] = targets[:TARGET_CONCEPTS_COMPACT_CAP]
        plan["target_concepts_omitted"] = len(targets) - TARGET_CONCEPTS_COMPACT_CAP
    return plan


def bootstrap_session_map(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    topic: str,
    doc_path: str = "",
    skill: str = "",
) -> dict[str, Any] | None:
    """Create session map on first log-answer when startup did not write one."""
    existing = load(session_id)
    if existing:
        return existing
    try:
        from concept_inventory import _open_inventory, map_learner  # noqa: PLC0415
    except ImportError:
        return None
    inv = _open_inventory()
    try:
        profile = "doc" if doc_path else "memory"
        query = doc_path or topic
        from study_memory import DB_PATH  # noqa: PLC0415
        projection = map_learner(
            inventory_conn=inv,
            memory_db=DB_PATH,
            learner_topics=[topic] if topic else [],
            query=query,
            budget=80,
        )
        if not projection.get("ok"):
            return None
        data = create_from_projection(
            projection,
            session_id=session_id,
            profile=profile,
            doc_path=doc_path,
            learner_topics=[topic] if topic else [],
        )
        write(session_id, data)
        return data
    except Exception as exc:
        print(f"WARN session_map_bootstrap_failed: {exc}", file=sys.stderr)
        return None
    finally:
        inv.close()


def build_inventory_projection(
    *,
    topic: str,
    doc_path: str = "",
    memory_db: Path | None = None,
) -> dict[str, Any] | None:
    """Run map-learner for startup-recall integration."""
    try:
        from concept_inventory import _open_inventory, map_learner  # noqa: PLC0415
    except ImportError:
        return None
    inv = _open_inventory()
    try:
        query = doc_path or topic
        learner_topics = [topic] if topic else []
        db_path = memory_db or (BASE_DIR / "data" / "study_memory.db")
        projection = map_learner(
            inventory_conn=inv,
            memory_db=db_path,
            learner_topics=learner_topics,
            query=query,
            budget=80,
        )
        if not projection.get("ok"):
            return None
        return projection
    except Exception as exc:
        print(f"WARN inventory_projection_failed: {exc}", file=sys.stderr)
        return None
    finally:
        inv.close()


def promote_inventory_binding(
    conn: sqlite3.Connection,
    *,
    learner_concept_id: int,
    inventory_concept_id: str,
) -> None:
    """Backfill stable inventory binding onto learner concept rows."""
    if not inventory_concept_id:
        return
    count = conn.execute(
        """SELECT COUNT(*) FROM claim_results
           WHERE concept_id = ? AND inventory_concept_id = ?""",
        (learner_concept_id, inventory_concept_id),
    ).fetchone()[0]
    row = conn.execute(
        "SELECT inventory_concept_id FROM concepts WHERE id = ?",
        (learner_concept_id,),
    ).fetchone()
    existing = row["inventory_concept_id"] if row else None
    if existing and existing == inventory_concept_id:
        conn.execute(
            """UPDATE concepts
               SET binding_match_count = MAX(COALESCE(binding_match_count, 0), ?)
               WHERE id = ?""",
            (count, learner_concept_id),
        )
        return
    if count >= STABLE_BINDING_COUNT or (count >= 1 and not existing):
        conn.execute(
            """UPDATE concepts
               SET inventory_concept_id = ?,
                   binding_match_count = MAX(COALESCE(binding_match_count, 0), ?)
               WHERE id = ?""",
            (inventory_concept_id, count, learner_concept_id),
        )
    else:
        conn.execute(
            """UPDATE concepts
               SET binding_match_count = MAX(COALESCE(binding_match_count, 0), ?)
               WHERE id = ?""",
            (count, learner_concept_id),
        )
