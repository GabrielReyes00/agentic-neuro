#!/usr/bin/env python3
"""Hidden tutor control strategy for learning sessions.

The output is designed for agent harnesses, not learner-facing display. It
turns the adaptive learner model into a concise control loop: what cognitive
operation the next question should perform, how to respond after the answer,
and what evidence is required before claiming mastery.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from kg_constants import DATA_DIR
from learner_model import estimate_mastery, next_item
from teaching_recommender import recommend_approach

DEFAULT_DB_PATH = DATA_DIR / "knowledge_graph.db"

SESSION_CONTROL_LOOP = [
    "diagnose current learner state",
    "choose one cognitive operation",
    "ask one question with no hint or answer context",
    "grade the committed answer",
    "decide advance, lateral transfer, remediate, or consolidate",
    "update the hidden session plan",
]

MASTERY_LADDER = [
    {"rung": 1, "name": "recognition", "evidence": "identifies the entity or syndrome"},
    {"rung": 2, "name": "definition_or_fact", "evidence": "recalls the core fact, number, or classification"},
    {"rung": 3, "name": "mechanism", "evidence": "explains why the fact is true"},
    {"rung": 4, "name": "discriminator", "evidence": "separates close confusers on the decisive axis"},
    {"rung": 5, "name": "management_consequence", "evidence": "states what changes management"},
    {"rung": 6, "name": "edge_case_or_contraindication", "evidence": "names what would make the usual plan unsafe"},
    {"rung": 7, "name": "transfer_case", "evidence": "applies the concept in a new clinical or operative context"},
    {"rung": 8, "name": "oral_board_defense", "evidence": "defends a plan and alternatives under challenge"},
    {"rung": 9, "name": "delayed_retention", "evidence": "passes a later spaced check"},
]

QUESTION_JOBS: dict[str, str] = {
    "calibrate": "diagnostic_calibration",
    "repair_prerequisite": "repair_prerequisite",
    "force_discrimination": "separate_confusers",
    "raise_fidelity": "test_management_consequence",
    "transfer": "transfer_to_case",
    "consolidate": "verify_retention",
    "close_loop": "mastery_audit",
}

DOMAIN_PLAYBOOKS: dict[str, list[str]] = {
    "vascular": [
        "vascular anatomy and territory",
        "natural history or rupture/ischemia risk",
        "treatment selection and contraindications",
        "peri-procedural complication rescue",
        "surveillance and delayed deterioration",
    ],
    "spine": [
        "localization and syndrome",
        "stability and neurologic urgency",
        "imaging discriminator",
        "operative indication and approach risk",
        "postoperative complication rescue",
    ],
    "tumor": [
        "presentation and localization",
        "imaging differential",
        "tissue or molecular diagnosis",
        "treatment sequence",
        "recurrence or adjuvant decision",
    ],
    "icu": [
        "physiology equation or threshold",
        "immediate orders",
        "monitoring target",
        "failure-to-rescue trigger",
        "handoff and escalation language",
    ],
    "general": [
        "illness script",
        "key discriminator",
        "management consequence",
        "danger zone",
        "transfer scenario",
    ],
}

TRANSFER_CONTEXTS = [
    "ED consult",
    "ICU deterioration",
    "OR or procedure complication",
    "post-op floor page",
    "oral-board defense",
    "imaging read",
]

CLINICAL_DANGER_KEYWORDS = (
    "herniation",
    "rupture",
    "vasospasm",
    "cauda",
    "cord compression",
    "epidural",
    "subdural",
    "hydrocephalus",
    "icp",
    "cpp",
    "airway",
    "anticoag",
    "infection",
    "sepsis",
)


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DEFAULT_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _infer_domain(text: str) -> str:
    haystack = (text or "").lower()
    if any(w in haystack for w in ("aneurysm", "sah", "vasospasm", "avm", "dural av", "stroke", "mca", "aca", "pica")):
        return "vascular"
    if any(w in haystack for w in ("spine", "cervical", "lumbar", "thoracic", "cauda", "cord", "myelopathy")):
        return "spine"
    if any(w in haystack for w in ("tumor", "glioma", "meningioma", "pituitary", "gbm", "metast")):
        return "tumor"
    if any(w in haystack for w in ("icp", "cpp", "evd", "icu", "osmotherapy", "herniation", "hydrocephalus")):
        return "icu"
    return "general"


def _current_rung(mastery_prob: float, transfer_state: str = "") -> int:
    if mastery_prob < 0.15:
        return 1
    if mastery_prob < 0.3:
        return 2
    if mastery_prob < 0.5:
        return 3
    if mastery_prob < 0.65:
        return 4
    if transfer_state in ("untested", "fact_recalled", "anki_reviewed", ""):
        return 6
    if mastery_prob < 0.85:
        return 7
    return 8


def _confusable_pair(conn: sqlite3.Connection, concept: str, query: str) -> dict[str, Any] | None:
    target = (concept or query or "").strip().lower()
    if not target:
        return None
    row = conn.execute(
        """SELECT *
           FROM concept_relationships
           WHERE relationship = 'confusable_with'
             AND (LOWER(concept_a) = ? OR LOWER(concept_b) = ?
                  OR LOWER(?) LIKE '%' || LOWER(concept_a) || '%'
                  OR LOWER(?) LIKE '%' || LOWER(concept_b) || '%')
           ORDER BY strength DESC, created_ts DESC
           LIMIT 1""",
        (target, target, target, target),
    ).fetchone()
    return dict(row) if row else None


def _transfer_state(conn: sqlite3.Connection, topic: str, concept: str) -> str:
    row = conn.execute(
        """SELECT lcs.transfer_state
           FROM learner_concept_state lcs
           LEFT JOIN topics t ON t.topic_id = lcs.topic_id
           WHERE (? = '' OR LOWER(lcs.concept_text) = LOWER(?))
             AND (? = '' OR LOWER(t.display_name) LIKE ? OR LOWER(t.canonical_name) LIKE ?)
           ORDER BY lcs.last_updated DESC
           LIMIT 1""",
        (concept, concept, topic, f"%{topic.lower()}%", f"%{topic.lower()}%"),
    ).fetchone()
    return str(row["transfer_state"] or "") if row else ""


def _danger_score(text: str) -> float:
    haystack = (text or "").lower()
    hits = sum(1 for kw in CLINICAL_DANGER_KEYWORDS if kw in haystack)
    return min(1.0, hits * 0.2)


def _concept_bottlenecks(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    rows = conn.execute(
        """SELECT cr.concept_a AS concept,
                  cr.topic_a AS topic,
                  COUNT(*) AS downstream_count,
                  AVG(cr.strength) AS mean_strength,
                  AVG(COALESCE(lcs.mastery_prob, 0.25)) AS mastery_prob,
                  GROUP_CONCAT(DISTINCT cr.concept_b) AS unlocks
           FROM concept_relationships cr
           LEFT JOIN learner_concept_state lcs
             ON LOWER(lcs.concept_text) = LOWER(cr.concept_a)
           WHERE cr.relationship = 'prerequisite_of'
           GROUP BY LOWER(cr.concept_a)
           ORDER BY downstream_count DESC, mean_strength DESC
           LIMIT 50"""
    ).fetchall()
    bottlenecks: list[dict[str, Any]] = []
    for row in rows:
        concept = row["concept"] or ""
        unlocks = [u for u in str(row["unlocks"] or "").split(",") if u][:8]
        relevance = 0.25 if q and (q in concept.lower() or any(q in u.lower() for u in unlocks)) else 0.0
        mastery = float(row["mastery_prob"] or 0.25)
        downstream = int(row["downstream_count"] or 0)
        danger = _danger_score(" ".join([concept, " ".join(unlocks), row["topic"] or ""]))
        score = min(1.0, downstream * 0.12 + (1.0 - mastery) * 0.35 + danger * 0.25 + relevance)
        bottlenecks.append({
            "concept": concept,
            "topic": row["topic"] or "",
            "downstream_count": downstream,
            "unlocks": unlocks,
            "mastery_prob": round(mastery, 4),
            "danger_score": round(danger, 4),
            "yield_score": round(score, 4),
            "recommended_probe": (
                f"Before downstream teaching, test the bottleneck: {concept}. "
                f"Ask how it changes {unlocks[0] if unlocks else 'the next management step'}."
            ),
        })
    bottlenecks.sort(key=lambda b: b["yield_score"], reverse=True)
    return bottlenecks[:limit]


def _learning_yield_targets(
    conn: sqlite3.Connection,
    *,
    query: str,
    next_items: dict[str, Any],
    bottlenecks: list[dict[str, Any]],
    limit: int = 6,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for item in next_items.get("items", []):
        concept = item.get("concept") or ""
        if not concept:
            continue
        score = float(item.get("score") or 0.0) * 0.45
        score += (1.0 - float(item.get("mastery_prob") or 0.35)) * 0.25
        score += _danger_score(" ".join([concept, item.get("topic", ""), query])) * 0.2
        candidates[concept.lower()] = {
            "concept": concept,
            "topic": item.get("topic", ""),
            "yield_score": round(min(1.0, score), 4),
            "reason": "ZPD candidate with learner-model uncertainty",
            "question_job": "transfer_to_case" if float(item.get("mastery_prob") or 0.0) >= 0.6 else "validate_mechanism",
        }
    for bottleneck in bottlenecks:
        concept = bottleneck["concept"]
        key = concept.lower()
        score = float(bottleneck.get("yield_score") or 0.0)
        if key in candidates:
            candidates[key]["yield_score"] = round(min(1.0, candidates[key]["yield_score"] + score * 0.35), 4)
            candidates[key]["reason"] += "; also a downstream bottleneck"
            candidates[key]["question_job"] = "repair_prerequisite"
        else:
            candidates[key] = {
                "concept": concept,
                "topic": bottleneck.get("topic", ""),
                "yield_score": round(score, 4),
                "reason": f"bottleneck unlocking {bottleneck.get('downstream_count', 0)} downstream concept(s)",
                "question_job": "repair_prerequisite",
            }
    rows = conn.execute(
        """SELECT le.concept_text, t.display_name AS topic,
                  COUNT(*) AS misses,
                  MAX(le.session_ts) AS last_missed
           FROM learning_exchanges le
           LEFT JOIN topics t ON t.topic_id = le.topic_id
           WHERE le.answer_correct < 2
           GROUP BY LOWER(le.concept_text)
           ORDER BY misses DESC, last_missed DESC
           LIMIT 20"""
    ).fetchall()
    for row in rows:
        concept = row["concept_text"] or ""
        key = concept.lower()
        score = min(1.0, 0.35 + int(row["misses"] or 0) * 0.08 + _danger_score(concept) * 0.25)
        if key in candidates:
            candidates[key]["yield_score"] = round(min(1.0, candidates[key]["yield_score"] + score * 0.25), 4)
            candidates[key]["reason"] += "; recurrent miss"
        else:
            candidates[key] = {
                "concept": concept,
                "topic": row["topic"] or "",
                "yield_score": round(score, 4),
                "reason": f"recurrent miss ({row['misses']}x)",
                "question_job": "expose_misconception",
            }
    ranked = sorted(candidates.values(), key=lambda c: c["yield_score"], reverse=True)
    return ranked[:limit]


def _transfer_matrix(conn: sqlite3.Connection, concept: str, topic: str) -> dict[str, Any]:
    state = _transfer_state(conn, topic, concept)
    demonstrated: set[str] = set()
    if state in ("applied_to_vignette", "applied_under_time_pressure", "applied_to_real_case", "operative_schema_integrated"):
        demonstrated.add("oral-board defense" if state == "applied_to_vignette" else "")
        demonstrated.add("ICU deterioration" if state == "applied_under_time_pressure" else "")
        demonstrated.add("ED consult" if state == "applied_to_real_case" else "")
        demonstrated.add("OR or procedure complication" if state == "operative_schema_integrated" else "")
    rows = conn.execute(
        """SELECT content_text, payload_json
           FROM memory_events
           WHERE event_type IN ('transfer_validation', 'case_memory')
             AND LOWER(concept_text) = LOWER(?)
           ORDER BY event_ts DESC
           LIMIT 20""",
        (concept,),
    ).fetchall()
    blob = " ".join((row["content_text"] or "") + " " + (row["payload_json"] or "") for row in rows).lower()
    for ctx in TRANSFER_CONTEXTS:
        if ctx.lower().split()[0] in blob or ctx.lower() in blob:
            demonstrated.add(ctx)
    cells = []
    for ctx in TRANSFER_CONTEXTS:
        status = "demonstrated" if ctx in demonstrated else "untested"
        cells.append({
            "context": ctx,
            "status": status,
            "prompt": f"Apply {concept or 'the target concept'} in a {ctx.lower()} scenario.",
        })
    gaps = [c for c in cells if c["status"] == "untested"]
    return {
        "concept": concept,
        "current_transfer_state": state or "untested",
        "contexts": cells,
        "next_transfer_gap": gaps[0] if gaps else {},
    }


def _error_recurrence_fingerprints(conn: sqlite3.Connection, limit: int = 5) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT COALESCE(NULLIF(error_type, ''), 'unknown') AS fingerprint,
                  COUNT(*) AS n,
                  GROUP_CONCAT(DISTINCT concept_text) AS concepts,
                  MAX(session_ts) AS last_seen
           FROM learning_exchanges
           WHERE answer_correct < 2
           GROUP BY COALESCE(NULLIF(error_type, ''), 'unknown')
           ORDER BY n DESC, last_seen DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    advice = {
        "threshold_anchor_error": "force threshold -> action sequence, not isolated number recall",
        "sequence_of_management_error": "ask for ordered management with escalation triggers",
        "anatomy_boundary_error": "draw or verbalize boundaries before clinical application",
        "vascular_territory_confusion": "force territory/perforator discrimination",
        "imaging_sign_misread": "ask for search pattern before naming the read",
        "complication_rescue_gap": "use deterioration and rescue prompts",
        "conceptual_confusion": "use forced discrimination on one axis",
        "numerical_recall": "use threshold drill followed by management consequence",
    }
    return [
        {
            "fingerprint": row["fingerprint"],
            "count": int(row["n"] or 0),
            "concepts": [c for c in str(row["concepts"] or "").split(",") if c][:6],
            "last_seen": row["last_seen"],
            "teaching_implication": advice.get(row["fingerprint"], "expose the process error, then retest in a new context"),
        }
        for row in rows
    ]


def _compression_schema(concept: str, domain: str) -> dict[str, Any]:
    target = concept or "the topic"
    return {
        "one_breath": f"Give the one-breath schema for {target}.",
        "algorithm": f"State the shortest safe algorithm for {target}.",
        "danger_statement": f"What is the one danger rule that prevents harm in {target}?",
        "discriminator": f"What single feature most cleanly separates {target} from its closest mimic?",
        "rescue_move": f"If {target} goes badly in {domain}, what is the first rescue move?",
    }


def _chief_challenges(concept: str, domain: str) -> list[str]:
    target = concept or "this plan"
    base = [
        f"Your chief disagrees with your plan for {target}. Defend it in two sentences.",
        f"The patient worsens after your first step for {target}. What now?",
        f"Radiology reads it differently. What finding settles the disagreement?",
        f"What would make your current plan unsafe?",
    ]
    if domain == "vascular":
        base.append("You are worried about rupture or vasospasm. What changes disposition and monitoring?")
    elif domain == "spine":
        base.append("What finding converts this from outpatient workup to urgent decompression?")
    elif domain == "icu":
        base.append("Give exact orders, monitoring target, and when you call the chief.")
    elif domain == "tumor":
        base.append("Defend observation versus tissue diagnosis versus resection.")
    return base[:5]


def _anti_illusion_checks(concept: str, question_job: str, domain: str) -> list[str]:
    target = concept or "this concept"
    checks = [
        f"Change one variable: when would the usual rule for {target} mislead you?",
        f"What is the contraindication or exception to the standard answer for {target}?",
    ]
    if question_job in ("test_threshold", "test_management_consequence") or domain == "icu":
        checks.append(f"Do not just quote the threshold for {target}; state the action sequence it triggers.")
    if question_job == "separate_confusers":
        checks.append(f"Name the one feature that rules in the mimic and rules out {target}.")
    if domain == "vascular":
        checks.append("What vascular territory or collateral assumption could make this answer wrong?")
    return checks[:4]


def _intern_reality_prompts(concept: str, domain: str) -> dict[str, str]:
    target = concept or "this problem"
    return {
        "orders": f"What exact orders would you place first for {target}?",
        "monitoring": f"What are you monitoring, and what value changes your plan?",
        "call": f"Who needs to know now: chief, attending, ICU, anesthesia, radiology, or OR?",
        "disposition": f"What finding changes floor vs ICU vs OR/angiography disposition?",
        "chief_phrase": f"Give the one-line chief update for {target}.",
    }


def _living_mastery_map(
    *,
    bottlenecks: list[dict[str, Any]],
    yield_targets: list[dict[str, Any]],
    transfer_matrix: dict[str, Any],
    fingerprints: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "bottleneck_targets": bottlenecks[:3],
        "highest_yield_next_questions": yield_targets[:3],
        "transfer_gaps": [c for c in transfer_matrix.get("contexts", []) if c.get("status") == "untested"][:3],
        "recurring_error_processes": fingerprints[:3],
        "dashboard_directive": (
            "When writing review artifacts or dashboard notes, separate bottlenecks, recall-only mastery, "
            "transfer gaps, and recurring error fingerprints."
        ),
    }


def _choose_control_state(
    *,
    mastery_prob: float,
    difficulty_band: str,
    transfer_state: str,
    has_confuser: bool,
    proactive_probe: bool,
) -> str:
    if proactive_probe or difficulty_band in ("cold_start", "remediate") or mastery_prob < 0.3:
        return "repair_prerequisite"
    if has_confuser:
        return "force_discrimination"
    if mastery_prob >= 0.65 and transfer_state in ("", "untested", "fact_recalled", "anki_reviewed"):
        return "transfer"
    if mastery_prob >= 0.8:
        return "consolidate"
    if mastery_prob >= 0.55:
        return "raise_fidelity"
    return "calibrate"


def build_tutor_strategy(
    conn: sqlite3.Connection,
    *,
    query: str,
    topic: str = "",
    concept: str = "",
    skill: str = "",
    proactive_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_topic = topic or query
    mastery = estimate_mastery(conn, topic=effective_topic, concept=concept)
    next_items = next_item(conn, mode="zpd", topic=effective_topic, limit=5)
    primary_item = (next_items.get("items") or [{}])[0]
    effective_concept = concept or primary_item.get("concept") or query
    transfer_state = _transfer_state(conn, effective_topic, effective_concept)
    confuser = _confusable_pair(conn, effective_concept, query)
    probe_active = bool(proactive_probe and proactive_probe.get("status") == "popped")
    mastery_prob = float(mastery.get("mastery_prob") or primary_item.get("mastery_prob") or 0.35)
    band = str(mastery.get("difficulty_band") or primary_item.get("difficulty_band") or "zpd")
    control_state = _choose_control_state(
        mastery_prob=mastery_prob,
        difficulty_band=band,
        transfer_state=transfer_state,
        has_confuser=bool(confuser),
        proactive_probe=probe_active,
    )
    question_job = QUESTION_JOBS[control_state]
    rung = _current_rung(mastery_prob, transfer_state)
    next_rung = min(9, rung + 1)
    domain = _infer_domain(" ".join([effective_topic, effective_concept, query]))
    bottlenecks = _concept_bottlenecks(conn, query)
    yield_targets = _learning_yield_targets(
        conn,
        query=query,
        next_items=next_items,
        bottlenecks=bottlenecks,
    )
    transfer_matrix = _transfer_matrix(conn, effective_concept, effective_topic)
    fingerprints = _error_recurrence_fingerprints(conn)
    approach = recommend_approach(
        conn,
        concept_text=effective_concept,
        error_type="conceptual_confusion" if confuser else "",
        difficulty_band=band,
    )

    if approach.get("sparse"):
        style_policy = {
            "mode": "explore",
            "directive": "Vary teaching approach after misses and log the exact move; do not overcommit to the sparse recommendation.",
            "cycle": ["forced_discrimination", "pathophys_derivation", "clinical_vignette_transfer"],
        }
    else:
        style_policy = {
            "mode": "exploit",
            "directive": "Use the recommended approach unless safety or the user's requested source requires a more specific move.",
            "cycle": [approach.get("approach")],
        }

    return {
        "ok": True,
        "query": query,
        "skill": skill,
        "control_loop": SESSION_CONTROL_LOOP,
        "control_state": control_state,
        "question_job": question_job,
        "next_action": {
            "ask": question_job,
            "after_correct": "advance one mastery rung; if shallow, escalate to contraindication, threshold, rescue, or defense",
            "after_partial": "give minimum effective explanation, then one targeted repair probe",
            "after_incorrect": "stop unsafe trajectory, repair the smallest missing link, then near-transfer retest",
        },
        "mastery_ladder": {
            "current_rung": MASTERY_LADDER[rung - 1],
            "next_rung": MASTERY_LADDER[next_rung - 1],
            "full_ladder": MASTERY_LADDER,
        },
        "minimum_effective_explanation": [
            "one correction",
            "one reason it changes management or safety",
            "one near-transfer retest",
        ],
        "teaching_style_policy": style_policy,
        "mastery_claim_audit": {
            "claim_mastery_only_if": [
                "direct recall or mechanism is correct without hints",
                "clinical or operative transfer is correct",
                "no active dangerous misconception remains",
            ],
            "prefer_delayed_retention": True,
        },
        "domain_playbook": {
            "domain": domain,
            "sequence": DOMAIN_PLAYBOOKS[domain],
        },
        "learning_yield_optimizer": {
            "directive": "Choose the highest learning-return question per minute when the user has not specified a source order.",
            "targets": yield_targets,
        },
        "concept_bottlenecks": {
            "directive": "Test bottlenecks before downstream teaching when they are prerequisite, dangerous, or high-connectivity.",
            "targets": bottlenecks,
        },
        "cross_context_transfer_matrix": transfer_matrix,
        "error_recurrence_fingerprints": fingerprints,
        "compression_card": _compression_schema(effective_concept, domain),
        "pre_mortem": {
            "prompt": f"Before the explanation, ask: what are two ways {effective_concept or 'this problem'} could hurt the patient or the operation?",
            "use_when": "before broad teaching, case transfer, or management explanation",
        },
        "anti_illusion_checks": _anti_illusion_checks(effective_concept, question_job, domain),
        "intern_reality": _intern_reality_prompts(effective_concept, domain),
        "chief_challenges": _chief_challenges(effective_concept, domain),
        "living_mastery_map": _living_mastery_map(
            bottlenecks=bottlenecks,
            yield_targets=yield_targets,
            transfer_matrix=transfer_matrix,
            fingerprints=fingerprints,
        ),
        "adaptive_inputs": {
            "mastery": mastery,
            "next_items": next_items.get("items", []),
            "recommended_approach": approach,
            "confusable_pair": confuser or {},
            "proactive_probe": proactive_probe or {},
        },
    }


def _load_probe(path: str | Path) -> dict[str, Any]:
    try:
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _main() -> int:
    parser = argparse.ArgumentParser(description="Build hidden tutor strategy")
    parser.add_argument("query")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--topic", default="")
    parser.add_argument("--concept", default="")
    parser.add_argument("--skill", default="")
    parser.add_argument("--probe-json", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    conn = connect(args.db)
    try:
        data = build_tutor_strategy(
            conn,
            query=args.query,
            topic=args.topic,
            concept=args.concept,
            skill=args.skill,
            proactive_probe=_load_probe(args.probe_json) if args.probe_json else {},
        )
        text = json.dumps(data, indent=2)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        print(text)
        return 0 if data.get("ok") else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(_main())
