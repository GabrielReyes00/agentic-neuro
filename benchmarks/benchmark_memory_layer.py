#!/usr/bin/env python3
"""Behavioral benchmark for the claim-centered learner-memory layer.

The benchmark uses temporary databases for synthetic longitudinal scenarios and
copies the live database before measuring a real startup packet. It never writes
to ``data/study_memory.db``.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import inspect
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_BENCH_RUNTIME = tempfile.TemporaryDirectory(prefix="agentic-neuro-memory-benchmark-")
os.environ["NEURO_EPHEMERAL_DIR"] = str(Path(_BENCH_RUNTIME.name) / "runtime")
os.environ["NEURO_STUDY_MAP_DIR"] = str(
    Path(_BENCH_RUNTIME.name) / "runtime" / "study_maps"
)
sys.path.insert(0, str(ROOT / "src"))

import concept_inventory  # noqa: E402
import study_memory  # noqa: E402


def _assessment(
    conn: sqlite3.Connection,
    *,
    session: str,
    topic: str,
    concept: str,
    inventory_id: str,
    tested_claim: str,
    score: int,
    marker: str,
    operation: str = "discrimination",
    teaching_intent: str = "new_material",
    match_claim_state_id: int | None = None,
    force_new_claim: bool = False,
    **extra: object,
) -> int:
    kwargs: dict[str, object] = {
        "session_id": session,
        "topic": topic,
        "concept": concept,
        "question": f"Question testing {tested_claim}",
        "answer": f"Learner answer {marker}",
        "correct": score,
        "tested_claim": tested_claim,
        "learner_claim": f"Learner committed to {marker}",
        "missing_edge": f"missing_{marker}" if score < 2 else "",
        "corrected_rule": f"corrected_{marker}" if score < 2 else "",
        "clinical_consequence": f"consequence_{marker}",
        "retest_prompt_shape": f"retest_{marker}",
        "misconception": f"misconception_{marker}" if score < 2 else "",
        "error_type": "conceptual_confusion" if score < 2 else "",
        "learning_operation": operation,
        "teaching_intent": teaching_intent,
        "expected_answer_edge": f"edge_{marker}",
        "answer_mode": "unaided",
        "confidence_observed": "high" if score < 2 else "fluent",
        "teaching_move": "contrastive_drill",
        "agent_priority": "high" if score < 2 else "low",
        "match_claim_state_id": match_claim_state_id,
        "force_new_claim": force_new_claim,
        "inventory_concept_id": inventory_id,
        "skill": "benchmark",
        "ts": session,
    }
    parameters = inspect.signature(study_memory.log_answer).parameters
    kwargs.update({key: value for key, value in extra.items() if key in parameters})
    with contextlib.redirect_stdout(io.StringIO()):
        return study_memory.log_answer(conn, **kwargs)  # type: ignore[arg-type]


def _new_db(path: Path) -> sqlite3.Connection:
    return study_memory._get_db(path)


def _claim_trace_precision() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        conn = _new_db(Path(tmp) / "memory.db")
        try:
            _assessment(
                conn,
                session="2026-01-01T00:00:00+00:00",
                topic="benchmark-evd",
                concept="EVD management",
                inventory_id="ncc.monitoring.evd-management",
                tested_claim="Lowering the drainage height increases CSF diversion",
                score=0,
                marker="drain_height_direction",
                force_new_claim=True,
            )
            _assessment(
                conn,
                session="2026-01-02T00:00:00+00:00",
                topic="benchmark-evd",
                concept="EVD management",
                inventory_id="ncc.monitoring.evd-management",
                tested_claim="A flat EVD waveform makes the displayed ICP unreliable",
                score=0,
                marker="flat_waveform_reliability",
                force_new_claim=True,
            )
            payload = json.loads(
                study_memory.retrieval_summary(
                    conn,
                    topic="benchmark-evd",
                    limit=8,
                    include_curated=True,
                    include_model=True,
                )
            )
            cards = payload["planning_brief"]["open_first"]
            exact = 0
            details = []
            for card in cards:
                summary = str(card.get("summary") or "")
                expected = (
                    "drain_height_direction"
                    if "drain_height_direction" in summary or "drainage height" in summary
                    else "flat_waveform_reliability"
                )
                other = (
                    "flat_waveform_reliability"
                    if expected == "drain_height_direction"
                    else "drain_height_direction"
                )
                trace = card.get("memory_trace")
                if isinstance(trace, dict):
                    trace_text = json.dumps(trace, sort_keys=True)
                else:
                    trace_text = json.dumps(card.get("historical_misconceptions") or [], sort_keys=True)
                passed = expected in trace_text and other not in trace_text
                exact += int(passed)
                details.append({"claim_state_id": card.get("claim_state_id"), "exact": passed})
            return {
                "score": round(exact / max(1, len(cards)), 3),
                "cards": len(cards),
                "details": details,
            }
        finally:
            conn.close()


def _cross_topic_canonical_recall() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "memory.db"
        conn = _new_db(db_path)
        try:
            inventory_id = "vasc.sah.hunt-hess"
            _assessment(
                conn,
                session="2026-01-01T00:00:00+00:00",
                topic="benchmark-context-a",
                concept="Hunt-Hess clinical grading",
                inventory_id=inventory_id,
                tested_claim="Drowsiness is sufficient for Hunt-Hess grade III",
                score=0,
                marker="drowsiness_threshold",
            )
            _assessment(
                conn,
                session="2026-01-02T00:00:00+00:00",
                topic="benchmark-context-b",
                concept="Hunt-Hess clinical grading",
                inventory_id=inventory_id,
                tested_claim="Hunt-Hess is a clinical rather than CT blood-burden scale",
                score=2,
                marker="clinical_vs_imaging",
            )
            inv = concept_inventory._open_inventory()
            try:
                projection = concept_inventory.map_learner(
                    inventory_conn=inv,
                    memory_db=db_path,
                    learner_topics=["benchmark-context-b"],
                    query="Hunt-Hess clinical grading",
                    budget=40,
                )
            finally:
                inv.close()
            node = next(
                item for item in projection["knowledge_map"]
                if item["concept_id"] == inventory_id
            )
            passed = int(node["attempts_count"]) == 2 and bool(node["active_misconception"])
            return {
                "score": 1.0 if passed else 0.0,
                "attempts_recalled": int(node["attempts_count"]),
                "active_misconception": bool(node["active_misconception"]),
                "matched_contexts": len(node.get("matched_learner_concepts") or []),
            }
        finally:
            conn.close()


def _cross_domain_query_coverage() -> dict[str, Any]:
    inv = concept_inventory._open_inventory()
    try:
        scoped = concept_inventory.scope_subgraph(
            inv,
            query="CPP targets across TBI and spinal cord injury",
            budget=80,
        )
    finally:
        inv.close()
    expected = {
        "tra.severe-tbi.cpp-targets",
        "spi.sci.map-goals",
    }
    present = {str(node["id"]) for node in scoped.get("nodes", [])} & expected
    return {
        "score": round(len(present) / len(expected), 3),
        "expected": sorted(expected),
        "present": sorted(present),
        "anchored_topics": scoped.get("scope", {}).get("anchored_topics", []),
    }


def _mastery_depth_calibration() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "memory.db"
        conn = _new_db(db_path)
        try:
            inventory_id = "tra.severe-tbi.cpp-targets"
            _assessment(
                conn,
                session="2026-01-01T00:00:00+00:00",
                topic="benchmark-tbi",
                concept="CPP targets",
                inventory_id=inventory_id,
                tested_claim="Apply CPP targets when ICP rises despite a stable MAP",
                score=2,
                marker="transfer_frame_one",
                operation="transfer",
                teaching_intent="transfer_check",
            )

            def depth() -> str:
                inv = concept_inventory._open_inventory()
                try:
                    projection = concept_inventory.map_learner(
                        inventory_conn=inv,
                        memory_db=db_path,
                        learner_topics=["benchmark-tbi"],
                        query="CPP targets in severe TBI",
                        budget=40,
                    )
                finally:
                    inv.close()
                node = next(
                    item for item in projection["knowledge_map"]
                    if item["concept_id"] == inventory_id
                )
                return str(node["mastery_depth"])

            after_one = depth()
            state_id = int(conn.execute(
                "SELECT id FROM claim_state ORDER BY id DESC LIMIT 1"
            ).fetchone()[0])
            _assessment(
                conn,
                session="2026-01-10T00:00:00+00:00",
                topic="benchmark-tbi",
                concept="CPP targets",
                inventory_id=inventory_id,
                tested_claim="Apply CPP targets when autoregulation is impaired",
                score=2,
                marker="transfer_frame_two",
                operation="transfer",
                teaching_intent="transfer_check",
                match_claim_state_id=state_id,
            )
            after_two = depth()
            passed = after_one != "transfer_ready" and after_two == "transfer_ready"
            return {
                "score": 1.0 if passed else 0.0,
                "after_one_transfer": after_one,
                "after_two_cross_session_transfers": after_two,
            }
        finally:
            conn.close()


def _longitudinal_state_machine() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        conn = _new_db(Path(tmp) / "memory.db")
        try:
            common = {
                "topic": "benchmark-sah",
                "concept": "Hunt-Hess clinical grading",
                "inventory_id": "vasc.sah.hunt-hess",
                "tested_claim": "Drowsiness is sufficient for Hunt-Hess grade III",
            }
            _assessment(
                conn,
                session="2026-01-01T00:00:00+00:00",
                score=0,
                marker="initial_miss",
                **common,
            )
            state_id = int(conn.execute("SELECT id FROM claim_state").fetchone()[0])
            _assessment(
                conn,
                session="2026-01-01T00:10:00+00:00",
                score=2,
                marker="immediate_repair",
                teaching_intent="repair_after_miss",
                match_claim_state_id=state_id,
                **common,
            )
            _assessment(
                conn,
                session="2026-01-08T00:00:00+00:00",
                score=2,
                marker="retention_pass",
                teaching_intent="retention_check",
                match_claim_state_id=state_id,
                **common,
            )
            _assessment(
                conn,
                session="2026-01-20T00:00:00+00:00",
                score=2,
                marker="transfer_pass",
                teaching_intent="transfer_check",
                match_claim_state_id=state_id,
                **common,
            )
            state = conn.execute(
                "SELECT state FROM claim_state WHERE id = ?", (state_id,)
            ).fetchone()[0]
            episode = conn.execute(
                "SELECT status FROM repair_episodes WHERE claim_state_id = ? ORDER BY id DESC LIMIT 1",
                (state_id,),
            ).fetchone()[0]
            card = conn.execute(
                "SELECT card_type FROM retrieval_cards WHERE claim_state_id = ? AND status = 'active'",
                (state_id,),
            ).fetchone()[0]
            passed = state == "durable" and episode == "transferred" and card == "scaffold"
            return {
                "score": 1.0 if passed else 0.0,
                "claim_state": state,
                "repair_episode": episode,
                "active_card": card,
            }
        finally:
            conn.close()


def _capture_schema_fidelity() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        conn = _new_db(Path(tmp) / "memory.db")
        try:
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(claim_results)")
            }
            expected = {
                "demonstrated_edge",
                "misconception_text",
                "teaching_intervention",
            }
            present = columns & expected
            return {
                "score": round(len(present) / len(expected), 3),
                "expected": sorted(expected),
                "present": sorted(present),
            }
        finally:
            conn.close()


def _identity_audit_precision() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        conn = _new_db(Path(tmp) / "memory.db")
        try:
            _assessment(
                conn,
                session="2026-01-01T00:00:00+00:00",
                topic="benchmark-identity",
                concept="EVD management",
                inventory_id="ncc.monitoring.evd-management",
                tested_claim="Lowering drain height increases diversion",
                score=0,
                marker="distinct_height",
                force_new_claim=True,
            )
            _assessment(
                conn,
                session="2026-01-02T00:00:00+00:00",
                topic="benchmark-identity",
                concept="EVD management",
                inventory_id="ncc.monitoring.evd-management",
                tested_claim="A flat waveform makes ICP unreliable",
                score=0,
                marker="distinct_waveform",
                force_new_claim=True,
            )
            _assessment(
                conn,
                session="2026-01-03T00:00:00+00:00",
                topic="benchmark-identity",
                concept="EVD management",
                inventory_id="ncc.monitoring.evd-management",
                tested_claim="Lowering the EVD drain height increases diversion",
                score=0,
                marker="height_paraphrase",
                force_new_claim=True,
            )
            audit = study_memory.identity_audit(conn)
            candidates = audit.get("duplicate_claim_state_candidates", [])
            falsely_flagged = any(
                "flat waveform" in " ".join(item.get("claims") or []).lower()
                for item in candidates
                if isinstance(item, dict)
            )
            true_duplicate_found = any(
                "drain height" in " ".join(item.get("claims") or []).lower()
                and "flat waveform" not in " ".join(item.get("claims") or []).lower()
                for item in candidates
                if isinstance(item, dict)
            )
            return {
                "score": 1.0 if true_duplicate_found and not falsely_flagged else 0.0,
                "distinct_claims_flagged": falsely_flagged,
                "true_duplicate_found": true_duplicate_found,
                "candidate_count": len(candidates),
            }
        finally:
            conn.close()


def _live_startup_packet(db_path: Path, repeat: int) -> dict[str, Any]:
    if not db_path.exists():
        return {"status": "skipped", "reason": f"missing {db_path}"}
    sizes: list[int] = []
    latencies: list[float] = []
    high_signal_counts: list[int] = []
    drilldown_discoverable = False
    with tempfile.TemporaryDirectory() as tmp:
        copied = Path(tmp) / "study_memory.db"
        shutil.copy2(db_path, copied)
        conn = _new_db(copied)
        try:
            for idx in range(max(1, repeat)):
                started = time.perf_counter()
                raw = study_memory.startup_recall(
                    conn,
                    topic="EVD management in ICU",
                    profile="memory",
                    session_id="",
                )
                latencies.append((time.perf_counter() - started) * 1000)
                sizes.append(len(raw.encode("utf-8")))
                payload = json.loads(raw)
                brief = payload.get("planning_brief", {})
                high_signal_counts.append(
                    len(brief.get("open_first") or [])
                    + len(brief.get("recent_repairs") or [])
                )
                guidance = payload.get("retrieval_guidance") or {}
                drilldown_discoverable = (
                    isinstance(guidance, dict)
                    and "node-recall" in str(guidance.get("drilldown") or "")
                    and bool(guidance.get("full_policy_computed_before_compaction"))
                )
        finally:
            conn.close()
    return {
        "status": "ok",
        "serialized_bytes": sizes[-1],
        "latency_ms": {
            "median": round(sorted(latencies)[len(latencies) // 2], 2),
            "min": round(min(latencies), 2),
            "max": round(max(latencies), 2),
        },
        "high_signal_cards": high_signal_counts[-1],
        "drilldown_discoverable": drilldown_discoverable,
    }


def _new_topic_orientation() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        conn = _new_db(Path(tmp) / "memory.db")
        try:
            payload = json.loads(
                study_memory.startup_recall(
                    conn,
                    topic="novel molecular biology of diffuse midline glioma",
                    profile="memory",
                )
            )
            startup = payload.get("startup_recall") or {}
            brief = payload.get("planning_brief") or {}
            orientation = brief.get("new_topic_orientation") or {}
            passed = (
                startup.get("ready_to_teach") is True
                and startup.get("routing_required") is False
                and orientation.get("status") == "new_topic_no_learner_history"
                and bool(brief.get("knowledge_map"))
            )
            return {
                "score": 1.0 if passed else 0.0,
                "ready_to_teach": bool(startup.get("ready_to_teach")),
                "routing_required": bool(startup.get("routing_required")),
                "orientation_status": orientation.get("status"),
                "knowledge_map_nodes": len(brief.get("knowledge_map") or []),
            }
        finally:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live-db",
        type=Path,
        default=ROOT / "data" / "study_memory.db",
        help="Live database to copy for packet-size and latency measurement.",
    )
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    cases = {
        "claim_trace_precision": _claim_trace_precision(),
        "cross_topic_canonical_recall": _cross_topic_canonical_recall(),
        "cross_domain_query_coverage": _cross_domain_query_coverage(),
        "mastery_depth_calibration": _mastery_depth_calibration(),
        "longitudinal_state_machine": _longitudinal_state_machine(),
        "capture_schema_fidelity": _capture_schema_fidelity(),
        "identity_audit_precision": _identity_audit_precision(),
        "new_topic_orientation": _new_topic_orientation(),
    }
    live_packet = _live_startup_packet(args.live_db, args.repeat)
    if live_packet.get("status") == "ok":
        size = int(live_packet.get("serialized_bytes", 0) or 0)
        latency = float((live_packet.get("latency_ms") or {}).get("median", 0) or 0)
        discoverable = bool(live_packet.get("drilldown_discoverable"))
        cases["startup_packet_efficiency"] = {
            "score": 1.0 if size <= 45_000 and latency <= 500 and discoverable else 0.0,
            "serialized_bytes": size,
            "target_max_bytes": 45_000,
            "median_latency_ms": latency,
            "target_max_latency_ms": 500,
            "drilldown_discoverable": discoverable,
        }
    quality_scores = [float(case["score"]) for case in cases.values()]
    report = {
        "schema": "memory_benchmark_v1",
        "quality": {
            "case_count": len(cases),
            "mean_score": round(sum(quality_scores) / len(quality_scores), 4),
            "passed": sum(score == 1.0 for score in quality_scores),
        },
        "cases": cases,
        "live_startup_packet": live_packet,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
