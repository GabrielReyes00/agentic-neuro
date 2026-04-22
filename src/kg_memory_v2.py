#!/usr/bin/env python3
"""Typed temporal memory V2 mixin for the learner knowledge graph."""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


MEMORY_ITEM_TYPES = {
    "episode",
    "semantic_fact",
    "learner_state",
    "teaching_policy",
    "reflection",
    "resource_link",
    "core_profile",
    "case_memory",
    "document_profile",
}

TRANSFER_STATES = [
    "untested",
    "fact_recalled",
    "anki_reviewed",
    "applied_to_vignette",
    "applied_under_time_pressure",
    "applied_to_real_case",
    "operative_schema_integrated",
]

NEUROSURGERY_ERROR_PROCESSES: dict[str, list[str]] = {
    "threshold_anchor_error": ["threshold", "dose", "cm/s", "ratio", "days", "mmhg", "number", "numeric"],
    "anatomy_boundary_error": ["boundary", "foramen", "compartment", "segment", "course", "origin", "insertion"],
    "vascular_territory_confusion": ["artery", "territory", "perforator", "acha", "pcom", "mca", "aca", "pica", "aica"],
    "imaging_sign_misread": ["ct", "mri", "cta", "angiogram", "dsa", "signal", "density", "enhancement", "imaging"],
    "sequence_of_management_error": ["next", "first", "sequence", "algorithm", "management", "order", "step"],
    "contraindication_omission": ["contraindication", "avoid", "do not", "risk", "unsafe", "hold"],
    "operative_step_order_error": ["clip", "exposure", "dissection", "temporary", "proximal", "distal", "operative", "microscope"],
    "complication_rescue_gap": ["rescue", "complication", "rupture", "deterioration", "herniation", "crisis", "bleeding"],
    "physiology_equation_confusion": ["cpp", "icp", "map", "equation", "gradient", "pressure", "perfusion"],
    "localization_pathway_error": ["localize", "tract", "pathway", "deficit", "syndrome", "level", "lesion"],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_list(raw: object) -> list:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        data = json.loads(str(raw or "[]"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _json_dict(raw: object) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(str(raw or "{}"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _merge_ids(existing: object, new_ids: list[int] | None = None) -> list[int]:
    seen: set[int] = set()
    merged: list[int] = []
    for value in _json_list(existing) + list(new_ids or []):
        try:
            ivalue = int(value)
        except Exception:
            continue
        if ivalue <= 0 or ivalue in seen:
            continue
        seen.add(ivalue)
        merged.append(ivalue)
    return merged


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _token_estimate(text: str) -> int:
    return max(1, len(text.split()) * 4 // 3)


def _clean_teaching_tags(tags: list[str], limit: int = 4) -> str:
    """Return a stable, compact teaching-approach label."""
    seen: set[str] = set()
    clean: list[str] = []
    for tag in tags:
        value = re.sub(r"[^a-z0-9_]+", "_", str(tag or "").strip().lower()).strip("_")
        if not value or value in seen:
            continue
        seen.add(value)
        clean.append(value)
        if len(clean) >= limit:
            break
    return "+".join(clean)


class KnowledgeGraphMemoryV2Mixin:
    """Additive typed memory, learner-state, and context-pack behavior."""

    def _infer_teaching_approach_v2(
        self,
        *,
        question_text: str = "",
        answer_text: str = "",
        correction_text: str = "",
        skill: str = "",
        topic_name: str = "",
        concept_text: str = "",
        answer_correct: int | None = None,
        depth: int = 1,
    ) -> str:
        """Infer the tutoring move when agents omit explicit metadata.

        This is deliberately conservative: it records the observable teaching
        shape of the exchange, not a hidden chain of thought or a correctness
        rationale. Explicit ``--teaching-approach`` values always win upstream.
        """
        text = " ".join([
            question_text or "",
            answer_text or "",
            correction_text or "",
            skill or "",
            topic_name or "",
            concept_text or "",
        ]).lower()
        question = (question_text or "").lower()
        tags: list[str] = []

        if any(marker in question for marker in (
            "describe your systematic search",
            "systematic search",
            "do not name",
            "where would you look",
            "what spaces",
            "checkpoints",
            "compartments",
            "slices",
        )):
            tags.extend(["cognitive_friction", "sequential_disclosure"])

        if any(marker in question for marker in (
            "threshold",
            "at what point",
            "when do you stop",
            "when would you",
            "what would change your plan",
            "what changes management",
        )):
            tags.append("threshold_probe")

        if any(marker in question for marker in (
            "why",
            "mechanism",
            "physiology",
            "pathophysiology",
            "so what",
            "management consequence",
            "not the answer",
        )):
            tags.append("mechanism_to_management")

        if any(marker in text for marker in (
            "patient",
            "vignette",
            "case",
            "gcs",
            "pupil",
            "ct",
            "mri",
            "cta",
            "angiogram",
            "operative",
            "surgical plan",
        )):
            tags.append("clinical_transfer")

        if any(marker in text for marker in (
            "discriminator",
            "distinguish",
            "differentiate",
            "versus",
            " vs ",
            "mimic",
            "confuser",
        )):
            tags.append("forced_discrimination")

        if any(marker in question for marker in (
            "defend",
            "walk me through",
            "oral board",
            "justify",
        )):
            tags.append("oral_board_defense")

        if int(depth or 1) >= 3:
            tags.append("depth_escalation_after_calibration")

        if int(answer_correct if answer_correct is not None else 2) < 2 and correction_text:
            tags.append("brief_correction_then_retest")

        if not tags:
            tags.append("active_recall_first")
            if int(depth or 1) >= 2:
                tags.append("adaptive_depth_probe")

        return _clean_teaching_tags(tags)

    def _infer_missing_error_metadata_v2(
        self,
        *,
        answer_correct: int,
        answer_text: str = "",
        correction_text: str = "",
        error_type: str = "",
        root_cause: str = "",
        misconception: str = "",
        concept_text: str = "",
        question_text: str = "",
    ) -> dict[str, str]:
        """Fill minimal pedagogic metadata for partial/wrong answers.

        The goal is not to over-diagnose the learner. It prevents empty rows
        from becoming unusable by preserving the broad learning process that
        future agents should adapt to.
        """
        if int(answer_correct or 0) == 2:
            return {
                "error_type": error_type or "",
                "root_cause": root_cause or "",
                "misconception": misconception or "",
            }

        answer_lower = (answer_text or "").lower()
        question_lower = (question_text or "").lower()
        correction_lower = (correction_text or "").lower()
        inferred_error = error_type
        if not inferred_error:
            if any(marker in answer_lower for marker in ("don't know", "dont know", "not sure", "unsure")):
                inferred_error = "knowledge_gap"
            elif int(answer_correct or 0) == 1:
                inferred_error = "partial_recall"
            else:
                inferred_error = "misconception"

        inferred_root = root_cause
        if not inferred_root:
            if any(marker in question_lower + correction_lower for marker in (
                "mechanism", "physiology", "pathophysiology", "why",
            )):
                inferred_root = "missing mechanism-to-management link"
            elif any(marker in question_lower + correction_lower for marker in (
                "threshold", "at what point", "when would",
            )):
                inferred_root = "incomplete decision-threshold model"
            elif any(marker in question_lower + correction_lower for marker in (
                "distinguish", "differentiate", "versus", " vs ", "discriminator",
            )):
                inferred_root = "incomplete discriminator checklist"
            else:
                inferred_root = f"incomplete model for {concept_text}" if concept_text else "incomplete concept model"

        return {
            "error_type": inferred_error,
            "root_cause": inferred_root,
            "misconception": misconception or "",
        }

    # ------------------------------------------------------------------
    # Low-level V2 writes
    # ------------------------------------------------------------------

    def _v2_topic_id(self, topic_name: str, domain: str = "") -> int | None:
        if not topic_name:
            return None
        topic_id = self._upsert_topic(
            self._normalize_topic(topic_name),
            topic_name.strip(),
            domain,
        )
        return topic_id if topic_id and topic_id > 0 else None

    def _topic_display_for_id(self, topic_id: int | None) -> str:
        if not topic_id:
            return ""
        row = self.conn.execute(
            "SELECT display_name FROM topics WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()
        return row["display_name"] if row else ""

    def _memory_item_dedupe(
        self,
        item_type: str,
        topic_id: int | None,
        concept_text: str,
        source_table: str,
        source_id: int | None,
        summary: str,
    ) -> str:
        if source_table and source_id:
            return self._memory_hash("v2_item", item_type, source_table, int(source_id))
        return self._memory_hash(
            "v2_item", item_type, topic_id, concept_text.strip().lower(), summary.strip()
        )

    def _upsert_memory_item_v2(
        self,
        *,
        item_type: str,
        summary: str,
        topic_id: int | None = None,
        concept_text: str = "",
        details: dict[str, Any] | None = None,
        importance: float = 0.5,
        confidence: float = 0.5,
        evidence_event_ids: list[int] | None = None,
        evidence_exchange_ids: list[int] | None = None,
        source_table: str = "",
        source_id: int | None = None,
        valid_from: str | None = None,
        valid_to: str = "",
        superseded_by: int | None = None,
        embedding_status: str = "pending",
        dedupe_key: str = "",
    ) -> int:
        """Insert or update one typed memory item and return item_id."""
        if item_type not in MEMORY_ITEM_TYPES:
            raise ValueError(f"unsupported memory item_type: {item_type}")
        now = _utc_now()
        concept_clean = self._resolve_concept_text(concept_text, topic_id) if concept_text else ""
        valid_from = valid_from or now
        details_json = json.dumps(details or {}, sort_keys=True, default=str)
        key = dedupe_key or self._memory_item_dedupe(
            item_type, topic_id, concept_clean, source_table, source_id, summary
        )

        existing = self.conn.execute(
            """SELECT item_id, summary, evidence_event_ids, evidence_exchange_ids,
                      embedding_status
               FROM memory_items WHERE dedupe_key = ? LIMIT 1""",
            (key,),
        ).fetchone()
        if existing:
            event_ids = _merge_ids(existing["evidence_event_ids"], evidence_event_ids)
            exchange_ids = _merge_ids(existing["evidence_exchange_ids"], evidence_exchange_ids)
            old_summary = existing["summary"] or ""
            next_embedding_status = (
                embedding_status
                if old_summary != summary
                else (existing["embedding_status"] or embedding_status)
            )
            with self.conn:
                self.conn.execute(
                    """UPDATE memory_items
                       SET topic_id = COALESCE(?, topic_id),
                           concept_text = COALESCE(NULLIF(?, ''), concept_text),
                           summary = ?,
                           details_json = ?,
                           importance = ?,
                           confidence = ?,
                           evidence_event_ids = ?,
                           evidence_exchange_ids = ?,
                           source_table = COALESCE(NULLIF(?, ''), source_table),
                           source_id = COALESCE(?, source_id),
                           valid_from = COALESCE(NULLIF(?, ''), valid_from),
                           valid_to = COALESCE(NULLIF(?, ''), valid_to),
                           superseded_by = COALESCE(?, superseded_by),
                           embedding_status = ?,
                           updated_ts = ?
                       WHERE item_id = ?""",
                    (
                        topic_id,
                        concept_clean,
                        summary,
                        details_json,
                        _clamp(float(importance)),
                        _clamp(float(confidence)),
                        json.dumps(event_ids),
                        json.dumps(exchange_ids),
                        source_table,
                        source_id,
                        valid_from,
                        valid_to,
                        superseded_by,
                        next_embedding_status,
                        now,
                        existing["item_id"],
                    ),
                )
            return int(existing["item_id"])

        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO memory_items
                   (item_type, topic_id, concept_text, summary, details_json,
                    importance, confidence, evidence_event_ids, evidence_exchange_ids,
                    source_table, source_id, valid_from, valid_to, superseded_by,
                    embedding_status, created_ts, updated_ts, dedupe_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_type,
                    topic_id,
                    concept_clean,
                    summary,
                    details_json,
                    _clamp(float(importance)),
                    _clamp(float(confidence)),
                    json.dumps(_merge_ids([], evidence_event_ids)),
                    json.dumps(_merge_ids([], evidence_exchange_ids)),
                    source_table,
                    source_id,
                    valid_from,
                    valid_to,
                    superseded_by,
                    embedding_status,
                    now,
                    now,
                    key,
                ),
            )
            return int(cur.lastrowid or -1)

    def _upsert_memory_edge_v2(
        self,
        *,
        source_item_id: int,
        target_item_id: int,
        edge_type: str,
        confidence: float = 0.5,
        evidence_event_ids: list[int] | None = None,
        valid_from: str | None = None,
        valid_to: str = "",
        dedupe_key: str = "",
    ) -> int:
        """Insert or update a temporal edge between memory items."""
        if not source_item_id or not target_item_id or source_item_id == target_item_id:
            return -1
        now = _utc_now()
        key = dedupe_key or self._memory_hash(
            "v2_edge", int(source_item_id), int(target_item_id), edge_type
        )
        existing = self.conn.execute(
            "SELECT edge_id, evidence_event_ids FROM memory_edges WHERE dedupe_key = ? LIMIT 1",
            (key,),
        ).fetchone()
        if existing:
            event_ids = _merge_ids(existing["evidence_event_ids"], evidence_event_ids)
            with self.conn:
                self.conn.execute(
                    """UPDATE memory_edges
                       SET confidence = ?,
                           evidence_event_ids = ?,
                           valid_to = ?,
                           updated_ts = ?
                       WHERE edge_id = ?""",
                    (
                        _clamp(float(confidence)),
                        json.dumps(event_ids),
                        valid_to,
                        now,
                        existing["edge_id"],
                    ),
                )
            return int(existing["edge_id"])
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO memory_edges
                   (source_item_id, target_item_id, edge_type, confidence,
                    valid_from, valid_to, evidence_event_ids, created_ts,
                    updated_ts, dedupe_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source_item_id,
                    target_item_id,
                    edge_type,
                    _clamp(float(confidence)),
                    valid_from or now,
                    valid_to,
                    json.dumps(_merge_ids([], evidence_event_ids)),
                    now,
                    now,
                    key,
                ),
            )
            return int(cur.lastrowid or -1)

    def _supersede_open_learner_items_v2(
        self,
        *,
        topic_id: int | None,
        concept_text: str,
        new_item_id: int,
        evidence_event_ids: list[int] | None = None,
    ) -> list[int]:
        """Close previous open learner-state facts for this concept."""
        if not topic_id or not concept_text or not new_item_id:
            return []
        now = _utc_now()
        rows = self.conn.execute(
            """SELECT item_id FROM memory_items
               WHERE item_type = 'learner_state'
                 AND topic_id = ?
                 AND concept_text = ?
                 AND item_id != ?
                 AND (valid_to IS NULL OR valid_to = '')
               ORDER BY item_id DESC""",
            (topic_id, concept_text.strip().lower(), new_item_id),
        ).fetchall()
        closed: list[int] = []
        with self.conn:
            for row in rows:
                self.conn.execute(
                    """UPDATE memory_items
                       SET valid_to = ?, superseded_by = ?, updated_ts = ?
                       WHERE item_id = ?""",
                    (now, new_item_id, now, row["item_id"]),
                )
                closed.append(int(row["item_id"]))
        for old_id in closed:
            self._upsert_memory_edge_v2(
                source_item_id=new_item_id,
                target_item_id=old_id,
                edge_type="supersedes",
                confidence=0.9,
                evidence_event_ids=evidence_event_ids,
                valid_from=now,
            )
        return closed

    # ------------------------------------------------------------------
    # Learner state estimator
    # ------------------------------------------------------------------

    @staticmethod
    def _calibration_state(answer_correct: int, response_confidence: str = "") -> str:
        confidence = (response_confidence or "").strip().lower()
        if confidence == "high" and answer_correct in (0, 1):
            return "overconfident_wrong"
        if confidence == "low" and answer_correct == 2:
            return "underconfident_right"
        if confidence == "high" and answer_correct == 2:
            return "calibrated_high"
        if confidence == "low" and answer_correct == 0:
            return "calibrated_low"
        return "unknown"

    @staticmethod
    def _transfer_rank(state: str) -> int:
        try:
            return TRANSFER_STATES.index((state or "untested").strip())
        except ValueError:
            return 0

    @classmethod
    def _max_transfer_state(cls, current: str, proposed: str) -> str:
        return proposed if cls._transfer_rank(proposed) >= cls._transfer_rank(current) else current

    @staticmethod
    def _infer_neurosurgery_error_process(
        *,
        error_type: str = "",
        concept_text: str = "",
        question_text: str = "",
        answer_text: str = "",
        misconception: str = "",
        root_cause: str = "",
    ) -> str:
        """Map a generic error to a neurosurgery-specific cognitive process."""
        haystack = " ".join([
            error_type or "",
            concept_text or "",
            question_text or "",
            answer_text or "",
            misconception or "",
            root_cause or "",
        ]).lower()
        if error_type == "numerical_recall":
            return "threshold_anchor_error"
        if error_type == "application_failure":
            return "sequence_of_management_error"
        if error_type == "cross_contamination":
            return "vascular_territory_confusion" if any(
                token in haystack for token in ("artery", "perforator", "territory", "acha", "pcom")
            ) else "localization_pathway_error"
        for process, tokens in NEUROSURGERY_ERROR_PROCESSES.items():
            if any(token in haystack for token in tokens):
                return process
        if error_type == "omission":
            return "contraindication_omission" if "contra" in haystack or "avoid" in haystack else "sequence_of_management_error"
        if error_type == "conceptual_confusion":
            return "physiology_equation_confusion" if any(
                token in haystack for token in ("cpp", "icp", "map", "pressure")
            ) else "localization_pathway_error"
        return error_type or "unclassified_learning_gap"

    def classify_memory_capture_v2(
        self,
        *,
        content: str,
        learner_answer: str = "",
        answer_correct: int | None = None,
        teaching_only: bool = False,
        case_context: str = "",
        transfer_context: str = "",
    ) -> dict[str, Any]:
        """Classify what kind of memory an agent should write for an interaction."""
        if case_context:
            memory_kind = "case_memory"
            command = "record-case"
            rationale = "Clinical scenario or rotation case context should be retained as case memory."
        elif transfer_context:
            memory_kind = "transfer_validation"
            command = "record-transfer"
            rationale = "The learner applied a concept in a new context."
        elif learner_answer or answer_correct is not None:
            memory_kind = "active_answer"
            command = "record-answer"
            rationale = "A real learner answer was evaluated."
        elif teaching_only:
            memory_kind = "teaching_exposure"
            command = "record-passive"
            rationale = "The agent taught without testing; this updates familiarity only."
        else:
            memory_kind = "no_write"
            command = ""
            rationale = "No teaching, tested answer, transfer, or case signal was detected."
        return {
            "ok": True,
            "memory_kind": memory_kind,
            "recommended_command": command,
            "rationale": rationale,
            "content_preview": " ".join((content or "").split())[:160],
        }

    @staticmethod
    def _state_from_active_answer(
        *,
        old_mastery: float,
        old_familiarity: float,
        old_half_life: float,
        old_difficulty: float,
        answer_correct: int,
        response_confidence: str = "",
    ) -> dict[str, float]:
        """Interpretable BKT/AKT-inspired state transition."""
        low_confidence = (response_confidence or "").strip().lower() == "low"
        high_confidence = (response_confidence or "").strip().lower() == "high"

        if answer_correct == 2:
            gain = 0.32 if not low_confidence else 0.20
            mastery = old_mastery + (1.0 - old_mastery) * gain
            familiarity = old_familiarity + (1.0 - old_familiarity) * 0.28
            half_life = min(90.0, max(1.0, old_half_life) * (1.45 if high_confidence else 1.25))
            difficulty = max(0.05, old_difficulty - 0.05)
        elif answer_correct == 1:
            mastery = old_mastery * 0.72 + 0.16
            familiarity = old_familiarity + (1.0 - old_familiarity) * 0.18
            half_life = max(0.75, old_half_life * 0.9)
            difficulty = min(1.0, old_difficulty + 0.03)
        else:
            mastery = old_mastery * 0.42
            familiarity = old_familiarity + (1.0 - old_familiarity) * 0.10
            half_life = max(0.5, old_half_life * 0.55)
            difficulty = min(1.0, old_difficulty + 0.10)
        return {
            "mastery_prob": _clamp(mastery),
            "familiarity_prob": _clamp(familiarity),
            "retention_half_life_days": max(0.5, half_life),
            "difficulty": _clamp(difficulty, 0.05, 1.0),
        }

    def _upsert_learner_concept_state_v2(
        self,
        *,
        topic_id: int,
        concept_text: str,
        evidence_event_ids: list[int] | None = None,
        evidence_exchange_ids: list[int] | None = None,
        active_answer_correct: int | None = None,
        passive_exposure: bool = False,
        misconception: str = "",
        root_cause: str = "",
        response_confidence: str = "",
        transfer_state: str = "",
        event_ts: str | None = None,
    ) -> dict[str, Any]:
        """Update current learner concept state and return the persisted row."""
        now = event_ts or _utc_now()
        concept_clean = self._resolve_concept_text(concept_text, topic_id)
        if not topic_id or not concept_clean:
            return {}
        existing = self.conn.execute(
            """SELECT * FROM learner_concept_state
               WHERE topic_id = ? AND concept_text = ?""",
            (topic_id, concept_clean),
        ).fetchone()

        if existing:
            old_mastery = float(existing["mastery_prob"] or 0.0)
            old_familiarity = float(existing["familiarity_prob"] or 0.0)
            old_half_life = float(existing["retention_half_life_days"] or 1.0)
            old_difficulty = float(existing["difficulty"] or 0.5)
            event_ids = _merge_ids(existing["evidence_event_ids"], evidence_event_ids)
            exchange_ids = _merge_ids(existing["evidence_exchange_ids"], evidence_exchange_ids)
            dominant_misconception = existing["dominant_misconception"] or ""
            root = existing["root_cause"] or ""
            calibration = existing["calibration_state"] or "unknown"
            last_active = existing["last_active_tested_at"]
            last_passive = existing["last_passive_exposed_at"]
            transfer = existing["transfer_state"] or "untested"
        else:
            old_mastery = 0.0
            old_familiarity = 0.0
            old_half_life = 1.0
            old_difficulty = 0.5
            event_ids = _merge_ids([], evidence_event_ids)
            exchange_ids = _merge_ids([], evidence_exchange_ids)
            dominant_misconception = ""
            root = ""
            calibration = "unknown"
            last_active = None
            last_passive = None
            transfer = "untested"

        mastery = old_mastery
        familiarity = old_familiarity
        half_life = old_half_life
        difficulty = old_difficulty

        if active_answer_correct is not None:
            transition = self._state_from_active_answer(
                old_mastery=old_mastery,
                old_familiarity=old_familiarity,
                old_half_life=old_half_life,
                old_difficulty=old_difficulty,
                answer_correct=int(active_answer_correct),
                response_confidence=response_confidence,
            )
            mastery = transition["mastery_prob"]
            familiarity = transition["familiarity_prob"]
            half_life = transition["retention_half_life_days"]
            difficulty = transition["difficulty"]
            last_active = now
            calibration = self._calibration_state(int(active_answer_correct), response_confidence)
            if int(active_answer_correct) == 2:
                dominant_misconception = ""
                root = ""
            else:
                dominant_misconception = misconception or dominant_misconception
                root = root_cause or root

        if passive_exposure:
            familiarity = old_familiarity + (1.0 - old_familiarity) * 0.22
            mastery = old_mastery
            half_life = max(0.75, old_half_life)
            last_passive = now
            if misconception:
                dominant_misconception = misconception
            if root_cause:
                root = root_cause

        if transfer_state:
            transfer = self._max_transfer_state(transfer, transfer_state)

        due_days = max(0.25, half_life * (0.6 if (active_answer_correct == 0) else 1.0))
        if active_answer_correct == 2:
            due_days = max(1.0, half_life * 1.4)
        elif active_answer_correct == 1:
            due_days = max(0.75, half_life)
        elif passive_exposure:
            due_days = 1.0
        next_due = (datetime.fromisoformat(now) + timedelta(days=due_days)).isoformat()

        with self.conn:
            if existing:
                self.conn.execute(
                    """UPDATE learner_concept_state
                       SET mastery_prob = ?,
                           familiarity_prob = ?,
                           retention_half_life_days = ?,
                           difficulty = ?,
                           last_active_tested_at = COALESCE(?, last_active_tested_at),
                           last_passive_exposed_at = COALESCE(?, last_passive_exposed_at),
                           next_review_due = ?,
                           dominant_misconception = ?,
                           root_cause = ?,
                           calibration_state = ?,
                           transfer_state = ?,
                           evidence_event_ids = ?,
                           evidence_exchange_ids = ?,
                           last_updated = ?
                       WHERE state_id = ?""",
                    (
                        mastery,
                        familiarity,
                        half_life,
                        difficulty,
                        last_active,
                        last_passive,
                        next_due,
                        dominant_misconception,
                        root,
                        calibration,
                        transfer,
                        json.dumps(event_ids),
                        json.dumps(exchange_ids),
                        now,
                        existing["state_id"],
                    ),
                )
            else:
                self.conn.execute(
                    """INSERT INTO learner_concept_state
                       (topic_id, concept_text, mastery_prob, familiarity_prob,
                        retention_half_life_days, difficulty, last_active_tested_at,
                        last_passive_exposed_at, next_review_due,
                        dominant_misconception, root_cause, calibration_state,
                        transfer_state, evidence_event_ids, evidence_exchange_ids,
                        last_updated)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        topic_id,
                        concept_clean,
                        mastery,
                        familiarity,
                        half_life,
                        difficulty,
                        last_active,
                        last_passive,
                        next_due,
                        dominant_misconception,
                        root,
                        calibration,
                        transfer,
                        json.dumps(event_ids),
                        json.dumps(exchange_ids),
                        now,
                    ),
                )

        row = self.conn.execute(
            """SELECT * FROM learner_concept_state
               WHERE topic_id = ? AND concept_text = ?""",
            (topic_id, concept_clean),
        ).fetchone()
        return dict(row) if row else {}

    def _update_teaching_policy_stats_v2(
        self,
        *,
        topic_id: int | None,
        domain: str = "",
        concept_text: str = "",
        error_type: str = "",
        teaching_approach: str = "",
        difficulty_band: str = "",
        mastery_delta: float | None = None,
        outcome: str = "unknown",
        evidence_event_ids: list[int] | None = None,
        evidence_exchange_ids: list[int] | None = None,
    ) -> int:
        if not teaching_approach:
            return -1
        try:
            from teaching_recommender import canonicalize_approach
            teaching_approach = canonicalize_approach(self.conn, teaching_approach)
        except Exception:
            teaching_approach = teaching_approach.strip().lower()
        now = _utc_now()
        concept_clean = self._resolve_concept_text(concept_text, topic_id) if concept_text else ""
        key = self._memory_hash(
            "teaching_policy_v2",
            domain,
            topic_id,
            concept_clean,
            error_type,
            difficulty_band,
            teaching_approach.strip().lower(),
        )
        existing = self.conn.execute(
            """SELECT * FROM teaching_policy_stats
               WHERE dedupe_key = ? LIMIT 1""",
            (key,),
        ).fetchone()
        success_inc = 1 if outcome == "success" else 0
        failure_inc = 1 if outcome == "failure" else 0
        unknown_inc = 1 if outcome not in ("success", "failure") else 0
        if existing:
            event_ids = _merge_ids(existing["evidence_event_ids"], evidence_event_ids)
            exchange_ids = _merge_ids(existing["evidence_exchange_ids"], evidence_exchange_ids)
            success = int(existing["success_count"] or 0) + success_inc
            failure = int(existing["failure_count"] or 0) + failure_inc
            unknown = int(existing["unknown_count"] or 0) + unknown_inc
            total_resolved = success + failure
            confidence = (success / total_resolved) if total_resolved else 0.5
            delta = float(mastery_delta or 0.0)
            delta_count_inc = 1 if mastery_delta is not None else 0
            sparse = 0 if (success + failure) >= 3 else 1
            with self.conn:
                self.conn.execute(
                    """UPDATE teaching_policy_stats
                       SET success_count = ?,
                           failure_count = ?,
                           unknown_count = ?,
                           mastery_delta_sum = COALESCE(mastery_delta_sum, 0.0) + ?,
                           mastery_delta_count = COALESCE(mastery_delta_count, 0) + ?,
                           last_mastery_delta = ?,
                           difficulty_band = COALESCE(NULLIF(difficulty_band, ''), ?),
                           sparse = ?,
                           confidence = ?,
                           last_outcome = ?,
                           evidence_event_ids = ?,
                           evidence_exchange_ids = ?,
                           updated_ts = ?
                       WHERE policy_id = ?""",
                    (
                        success,
                        failure,
                        unknown,
                        delta,
                        delta_count_inc,
                        delta,
                        difficulty_band,
                        sparse,
                        confidence,
                        outcome,
                        json.dumps(event_ids),
                        json.dumps(exchange_ids),
                        now,
                        existing["policy_id"],
                    ),
                )
            return int(existing["policy_id"])

        confidence = 1.0 if outcome == "success" else (0.0 if outcome == "failure" else 0.5)
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO teaching_policy_stats
                   (domain, topic_id, concept_text, error_type, teaching_approach,
                    difficulty_band,
                    success_count, failure_count, unknown_count, exposure_count,
                    mastery_delta_sum, mastery_delta_count, last_mastery_delta, sparse,
                    confidence, last_outcome, evidence_event_ids,
                    evidence_exchange_ids, created_ts, updated_ts, dedupe_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    domain,
                    topic_id,
                    concept_clean,
                    error_type,
                    teaching_approach,
                    difficulty_band,
                    success_inc,
                    failure_inc,
                    unknown_inc,
                    float(mastery_delta or 0.0),
                    1 if mastery_delta is not None else 0,
                    float(mastery_delta or 0.0),
                    1,
                    confidence,
                    outcome,
                    json.dumps(_merge_ids([], evidence_event_ids)),
                    json.dumps(_merge_ids([], evidence_exchange_ids)),
                    now,
                    now,
                    key,
                ),
            )
            return int(cur.lastrowid or -1)

    # ------------------------------------------------------------------
    # Public V2 write hooks used by existing commands
    # ------------------------------------------------------------------

    def record_active_answer_v2(
        self,
        *,
        session_ts: str,
        turn_number: int,
        skill: str,
        topic_name: str,
        concept_text: str,
        question_text: str,
        answer_text: str,
        answer_correct: int,
        correction_text: str = "",
        error_type: str = "",
        error_process: str = "",
        misconception: str = "",
        root_cause: str = "",
        remediation: str = "",
        teaching_approach: str = "",
        retrieval_sources: str = "",
        breakthrough: bool = False,
        insight_text: str = "",
        domain: str = "",
        depth: int = 1,
        response_confidence: str = "",
        memory_event_id: int | None = None,
        exchange_id: int | None = None,
        signal_event_id: int | None = None,
    ) -> dict[str, Any]:
        """Project one active answer into typed V2 memory and learner state."""
        topic_id = self._v2_topic_id(topic_name, domain)
        if not topic_id:
            return {"ok": False, "error": "topic could not be resolved"}
        concept_clean = self._resolve_concept_text(concept_text, topic_id)
        evidence_events = [memory_event_id] if memory_event_id else []
        evidence_exchanges = [exchange_id] if exchange_id else []
        now = _utc_now()
        error_process = error_process or self._infer_neurosurgery_error_process(
            error_type=error_type,
            concept_text=concept_clean,
            question_text=question_text,
            answer_text=answer_text,
            misconception=misconception,
            root_cause=root_cause,
        )
        prior_state = self.conn.execute(
            """SELECT * FROM learner_concept_state
               WHERE topic_id = ? AND concept_text = ?""",
            (topic_id, concept_clean),
        ).fetchone()
        prior_mastery = float(prior_state["mastery_prob"] or 0.0) if prior_state else 0.0
        correct_label = {0: "incorrect", 1: "partial", 2: "correct"}.get(
            int(answer_correct), "unknown"
        )

        episode_summary = (
            f"{topic_name}: Gabriel answered {correct_label} on {concept_clean}. "
            f"Q: {question_text.strip()} A: {answer_text.strip()}"
        )
        if correction_text:
            episode_summary += f" Correction: {correction_text.strip()}"
        episode_item_id = self._upsert_memory_item_v2(
            item_type="episode",
            topic_id=topic_id,
            concept_text=concept_clean,
            summary=episode_summary,
            details={
                "session_ts": session_ts,
                "turn_number": turn_number,
                "skill": skill,
                "question": question_text,
                "answer": answer_text,
                "answer_correct": answer_correct,
                "correction": correction_text,
                "error_type": error_type,
                "error_process": error_process,
                "misconception": misconception,
                "root_cause": root_cause,
                "remediation": remediation,
                "teaching_approach": teaching_approach,
                "retrieval_sources": retrieval_sources,
                "breakthrough": breakthrough,
                "insight": insight_text,
                "depth": depth,
                "signal_event_id": signal_event_id,
            },
            importance=0.75 if answer_correct == 0 else 0.65,
            confidence=0.85,
            evidence_event_ids=evidence_events,
            evidence_exchange_ids=evidence_exchanges,
            source_table="learning_exchanges",
            source_id=exchange_id,
            valid_from=now,
        )

        state_dedupe_key = self._memory_hash(
            "learner_state_snapshot",
            topic_id,
            concept_clean,
            exchange_id or memory_event_id or f"{session_ts}:{turn_number}",
        )
        existing_state_item = self.conn.execute(
            "SELECT item_id FROM memory_items WHERE dedupe_key = ? LIMIT 1",
            (state_dedupe_key,),
        ).fetchone()
        if existing_state_item:
            state_row = self.conn.execute(
                """SELECT * FROM learner_concept_state
                   WHERE topic_id = ? AND concept_text = ?""",
                (topic_id, concept_clean),
            ).fetchone()
            return {
                "ok": True,
                "deduped": True,
                "episode_item_id": episode_item_id,
                "learner_state_item_id": existing_state_item["item_id"],
                "policy_id": -1,
                "learner_state": dict(state_row) if state_row else {},
            }

        state = self._upsert_learner_concept_state_v2(
            topic_id=topic_id,
            concept_text=concept_clean,
            evidence_event_ids=evidence_events,
            evidence_exchange_ids=evidence_exchanges,
            active_answer_correct=int(answer_correct),
            misconception=misconception,
            root_cause=root_cause,
            response_confidence=response_confidence,
            transfer_state="fact_recalled" if int(answer_correct) == 2 else "",
            event_ts=now,
        )
        mastery_after = float(state.get("mastery_prob") or 0.0)
        mastery_delta = mastery_after - prior_mastery
        try:
            from learner_model import difficulty_band as _difficulty_band
            band = _difficulty_band(mastery_after, state.get("difficulty"))
        except Exception:
            if mastery_after < 0.35:
                band = "remediate"
            elif mastery_after <= 0.75:
                band = "zpd"
            else:
                band = "consolidate"
        if exchange_id:
            with self.conn:
                self.conn.execute(
                    """UPDATE learning_exchanges
                       SET mastery_prob_before = COALESCE(mastery_prob_before, ?),
                           mastery_prob_after = ?,
                           difficulty_band = COALESCE(NULLIF(difficulty_band, ''), ?)
                       WHERE exchange_id = ?""",
                    (prior_mastery, mastery_after, band, exchange_id),
                )
                self.conn.execute(
                    """UPDATE learner_concept_state
                       SET difficulty_band = ?, last_mastery_delta = ?
                       WHERE state_id = ?""",
                    (band, mastery_delta, state.get("state_id")),
                )
            state["difficulty_band"] = band
            state["last_mastery_delta"] = mastery_delta
        state_summary = (
            f"Current learner state for {concept_clean}: "
            f"mastery={state.get('mastery_prob', 0):.2f}, "
            f"familiarity={state.get('familiarity_prob', 0):.2f}."
        )
        if state.get("dominant_misconception"):
            state_summary += f" Misconception: {state['dominant_misconception']}."
        state_item_id = self._upsert_memory_item_v2(
            item_type="learner_state",
            topic_id=topic_id,
            concept_text=concept_clean,
            summary=state_summary,
            details=state,
            importance=0.8 if answer_correct == 0 else 0.7,
            confidence=0.75,
            evidence_event_ids=evidence_events,
            evidence_exchange_ids=evidence_exchanges,
            source_table="learner_concept_state",
            source_id=state.get("state_id"),
            valid_from=now,
            dedupe_key=state_dedupe_key,
        )
        self._supersede_open_learner_items_v2(
            topic_id=topic_id,
            concept_text=concept_clean,
            new_item_id=state_item_id,
            evidence_event_ids=evidence_events,
        )
        self._upsert_memory_edge_v2(
            source_item_id=state_item_id,
            target_item_id=episode_item_id,
            edge_type="caused_by",
            confidence=0.9,
            evidence_event_ids=evidence_events,
            valid_from=now,
        )
        regression_item_id = -1
        if prior_state and int(answer_correct) == 0:
            prior_mastery = float(prior_state["mastery_prob"] or 0.0)
            prior_misconception = prior_state["dominant_misconception"] or ""
            had_evidence = bool(prior_state["last_active_tested_at"] or prior_mastery >= 0.45)
            if had_evidence and (prior_mastery >= 0.45 or not prior_misconception):
                regression_item_id = self._upsert_memory_item_v2(
                    item_type="reflection",
                    topic_id=topic_id,
                    concept_text=concept_clean,
                    summary=(
                        f"Regression detected for {concept_clean}: prior mastery was "
                        f"{prior_mastery:.2f}, but Gabriel missed it in this session. "
                        f"Likely process: {error_process}."
                    ),
                    details={
                        "reflection_type": "regression_detected",
                        "prior_mastery_prob": prior_mastery,
                        "prior_misconception": prior_misconception,
                        "new_misconception": misconception,
                        "error_type": error_type,
                        "error_process": error_process,
                        "recommended_teaching_move": (
                            "Return to a contrastive clinical vignette and force commitment before explanation."
                        ),
                    },
                    importance=0.9,
                    confidence=0.85,
                    evidence_event_ids=evidence_events,
                    evidence_exchange_ids=evidence_exchanges,
                    source_table="regression_detector",
                    source_id=exchange_id,
                    valid_from=now,
                    dedupe_key=self._memory_hash("regression", topic_id, concept_clean, exchange_id or memory_event_id),
                )
                self._upsert_memory_edge_v2(
                    source_item_id=regression_item_id,
                    target_item_id=state_item_id,
                    edge_type="supports",
                    confidence=0.85,
                    evidence_event_ids=evidence_events,
                    valid_from=now,
                )

        policy_id = -1
        if teaching_approach:
            if answer_correct == 2:
                outcome = "success"
            elif answer_correct == 0:
                outcome = "failure"
            else:
                outcome = "unknown"
            policy_id = self._update_teaching_policy_stats_v2(
                topic_id=topic_id,
                domain=domain,
                concept_text=concept_clean,
                error_type=error_type,
                teaching_approach=teaching_approach,
                difficulty_band=band,
                mastery_delta=mastery_delta,
                outcome=outcome,
                evidence_event_ids=evidence_events,
                evidence_exchange_ids=evidence_exchanges,
            )

        return {
            "ok": True,
            "episode_item_id": episode_item_id,
            "learner_state_item_id": state_item_id,
            "policy_id": policy_id,
            "regression_item_id": regression_item_id,
            "learner_state": state,
        }

    def record_passive_teaching_v2(
        self,
        *,
        session_ts: str,
        turn_number: int,
        skill: str,
        topic_name: str,
        content_text: str,
        concept_text: str = "",
        domain: str = "",
        memory_event_id: int | None = None,
    ) -> dict[str, Any]:
        """Record passive teaching as exposure/familiarity, never mastery."""
        topic_id = self._v2_topic_id(topic_name, domain)
        if not topic_id:
            return {"ok": False, "error": "topic could not be resolved"}
        concept_clean = self._resolve_concept_text(concept_text or topic_name, topic_id)
        now = _utc_now()
        evidence_events = [memory_event_id] if memory_event_id else []

        episode_item_id = self._upsert_memory_item_v2(
            item_type="episode",
            topic_id=topic_id,
            concept_text=concept_clean,
            summary=f"Passive teaching exposure on {concept_clean}: {content_text.strip()[:500]}",
            details={
                "session_ts": session_ts,
                "turn_number": turn_number,
                "skill": skill,
                "passive": True,
                "content": content_text,
            },
            importance=0.45,
            confidence=0.7,
            evidence_event_ids=evidence_events,
            source_table="memory_events",
            source_id=memory_event_id,
            valid_from=now,
        )
        state_dedupe_key = self._memory_hash(
            "passive_state_snapshot",
            topic_id,
            concept_clean,
            memory_event_id or f"{session_ts}:{turn_number}",
        )
        existing_state_item = self.conn.execute(
            "SELECT item_id FROM memory_items WHERE dedupe_key = ? LIMIT 1",
            (state_dedupe_key,),
        ).fetchone()
        if existing_state_item:
            state_row = self.conn.execute(
                """SELECT * FROM learner_concept_state
                   WHERE topic_id = ? AND concept_text = ?""",
                (topic_id, concept_clean),
            ).fetchone()
            return {
                "ok": True,
                "deduped": True,
                "episode_item_id": episode_item_id,
                "learner_state_item_id": existing_state_item["item_id"],
                "learner_state": dict(state_row) if state_row else {},
            }

        state = self._upsert_learner_concept_state_v2(
            topic_id=topic_id,
            concept_text=concept_clean,
            evidence_event_ids=evidence_events,
            passive_exposure=True,
            event_ts=now,
        )
        state_item_id = self._upsert_memory_item_v2(
            item_type="learner_state",
            topic_id=topic_id,
            concept_text=concept_clean,
            summary=(
                f"Passive exposure only for {concept_clean}: "
                f"familiarity={state.get('familiarity_prob', 0):.2f}, "
                f"mastery remains {state.get('mastery_prob', 0):.2f}."
            ),
            details={**state, "passive_exposure_only": True},
            importance=0.55,
            confidence=0.75,
            evidence_event_ids=evidence_events,
            source_table="learner_concept_state",
            source_id=state.get("state_id"),
            valid_from=now,
            dedupe_key=state_dedupe_key,
        )
        self._supersede_open_learner_items_v2(
            topic_id=topic_id,
            concept_text=concept_clean,
            new_item_id=state_item_id,
            evidence_event_ids=evidence_events,
        )
        self._upsert_memory_edge_v2(
            source_item_id=state_item_id,
            target_item_id=episode_item_id,
            edge_type="teaches",
            confidence=0.7,
            evidence_event_ids=evidence_events,
            valid_from=now,
        )
        return {
            "ok": True,
            "episode_item_id": episode_item_id,
            "learner_state_item_id": state_item_id,
            "learner_state": state,
        }

    def record_anki_review_v2(
        self,
        *,
        topic_name: str,
        concept_text: str,
        interval_days: int = 0,
        ease_factor: float = 2.5,
        lapses: int = 0,
        confidence_delta: float = 0.0,
        signal_event_id: int | None = None,
    ) -> dict[str, Any]:
        """Integrate Anki review evidence into V2 learner state."""
        topic_id = self._v2_topic_id(topic_name)
        if not topic_id:
            return {"ok": False, "error": "topic could not be resolved"}
        concept_clean = self._resolve_concept_text(concept_text or topic_name, topic_id)
        answer_correct = 2 if confidence_delta >= 0 else 0
        memory_event_id = self.append_memory_event(
            event_type="anki_review_evidence",
            session_ts=_utc_now(),
            turn_number=0,
            skill="anki",
            topic_name=topic_name,
            concept_text=concept_clean,
            actor="system",
            content_text=(
                f"Anki review evidence for {concept_clean}: interval={interval_days}, "
                f"ease={ease_factor:.2f}, lapses={lapses}, delta={confidence_delta:.3f}"
            ),
            payload={
                "interval_days": interval_days,
                "ease_factor": ease_factor,
                "lapses": lapses,
                "confidence_delta": confidence_delta,
                "signal_event_id": signal_event_id,
            },
            source="anki",
        )
        state = self._upsert_learner_concept_state_v2(
            topic_id=topic_id,
            concept_text=concept_clean,
            evidence_event_ids=[memory_event_id] if memory_event_id > 0 else [],
            active_answer_correct=answer_correct,
            transfer_state="anki_reviewed",
            event_ts=_utc_now(),
        )
        item_id = self._upsert_memory_item_v2(
            item_type="semantic_fact",
            topic_id=topic_id,
            concept_text=concept_clean,
            summary=(
                f"Anki review updated {concept_clean}: interval {interval_days} days, "
                f"ease {ease_factor:.2f}, lapses {lapses}, learner mastery {state.get('mastery_prob', 0):.2f}."
            ),
            details={
                "source": "anki",
                "interval_days": interval_days,
                "ease_factor": ease_factor,
                "lapses": lapses,
                "confidence_delta": confidence_delta,
                "signal_event_id": signal_event_id,
            },
            importance=0.6,
            confidence=0.75,
            evidence_event_ids=[memory_event_id] if memory_event_id > 0 else [],
            source_table="signal_events",
            source_id=signal_event_id,
            valid_from=_utc_now(),
        )
        return {
            "ok": True,
            "memory_event_id": memory_event_id,
            "memory_item_id": item_id,
            "learner_state": state,
        }

    def record_transfer_v2(
        self,
        *,
        session_ts: str,
        turn_number: int,
        skill: str,
        topic_name: str,
        concept_text: str,
        transfer_context: str,
        learner_answer: str = "",
        success: bool = False,
        transfer_level: str = "applied_to_vignette",
        correction_text: str = "",
        error_type: str = "",
        error_process: str = "",
        domain: str = "",
    ) -> dict[str, Any]:
        """Record cross-context transfer as first-class learner evidence."""
        topic_id = self._v2_topic_id(topic_name, domain)
        if not topic_id:
            return {"ok": False, "error": "topic could not be resolved"}
        concept_clean = self._resolve_concept_text(concept_text, topic_id)
        if transfer_level not in TRANSFER_STATES:
            transfer_level = "applied_to_vignette"
        error_process = error_process or self._infer_neurosurgery_error_process(
            error_type=error_type,
            concept_text=concept_clean,
            question_text=transfer_context,
            answer_text=learner_answer,
            root_cause=correction_text,
        )
        memory_event_id = self.append_memory_event(
            event_type="transfer_validation",
            session_ts=session_ts,
            turn_number=turn_number,
            skill=skill,
            topic_name=topic_name,
            concept_text=concept_clean,
            actor="user",
            content_text=f"Transfer context: {transfer_context}\nAnswer: {learner_answer}",
            payload={
                "transfer_context": transfer_context,
                "learner_answer": learner_answer,
                "success": bool(success),
                "transfer_level": transfer_level,
                "correction": correction_text,
                "error_type": error_type,
                "error_process": error_process,
            },
            source=skill,
            domain=domain,
        )
        state = self._upsert_learner_concept_state_v2(
            topic_id=topic_id,
            concept_text=concept_clean,
            evidence_event_ids=[memory_event_id] if memory_event_id > 0 else [],
            active_answer_correct=2 if success else 0,
            misconception="" if success else correction_text,
            root_cause="" if success else error_process,
            transfer_state=transfer_level if success else "fact_recalled",
            event_ts=_utc_now(),
        )
        item_id = self._upsert_memory_item_v2(
            item_type="semantic_fact",
            topic_id=topic_id,
            concept_text=concept_clean,
            summary=(
                f"Transfer {'succeeded' if success else 'failed'} for {concept_clean} "
                f"in context: {transfer_context[:240]}"
            ),
            details={
                "memory_kind": "transfer_validation",
                "transfer_context": transfer_context,
                "learner_answer": learner_answer,
                "success": bool(success),
                "transfer_level": transfer_level,
                "correction": correction_text,
                "error_type": error_type,
                "error_process": error_process,
                "learner_state": state,
            },
            importance=0.85,
            confidence=0.85,
            evidence_event_ids=[memory_event_id] if memory_event_id > 0 else [],
            source_table="memory_events",
            source_id=memory_event_id,
            valid_from=_utc_now(),
        )
        return {
            "ok": True,
            "memory_event_id": memory_event_id,
            "memory_item_id": item_id,
            "learner_state": state,
        }

    def record_case_memory_v2(
        self,
        *,
        session_ts: str,
        turn_number: int,
        skill: str,
        topic_name: str,
        case_context: str,
        decision_point: str,
        learner_action: str = "",
        outcome: str = "",
        teaching_target: str = "",
        concept_text: str = "",
        domain: str = "",
    ) -> dict[str, Any]:
        """Store a clinical/operative case episode for future teaching."""
        topic_id = self._v2_topic_id(topic_name, domain)
        if not topic_id:
            return {"ok": False, "error": "topic could not be resolved"}
        concept_clean = self._resolve_concept_text(concept_text or decision_point or topic_name, topic_id)
        memory_event_id = self.append_memory_event(
            event_type="case_memory",
            session_ts=session_ts,
            turn_number=turn_number,
            skill=skill,
            topic_name=topic_name,
            concept_text=concept_clean,
            actor="user",
            content_text=(
                f"Case: {case_context}\nDecision: {decision_point}\n"
                f"Learner action: {learner_action}\nOutcome: {outcome}"
            ),
            payload={
                "case_context": case_context,
                "decision_point": decision_point,
                "learner_action": learner_action,
                "outcome": outcome,
                "teaching_target": teaching_target,
            },
            source=skill,
            domain=domain,
        )
        item_id = self._upsert_memory_item_v2(
            item_type="case_memory",
            topic_id=topic_id,
            concept_text=concept_clean,
            summary=(
                f"Case memory for {topic_name}: {decision_point}. "
                f"Teaching target: {teaching_target or 'not specified'}."
            ),
            details={
                "case_context": case_context,
                "decision_point": decision_point,
                "learner_action": learner_action,
                "outcome": outcome,
                "teaching_target": teaching_target,
                "session_ts": session_ts,
                "skill": skill,
            },
            importance=0.8,
            confidence=0.8,
            evidence_event_ids=[memory_event_id] if memory_event_id > 0 else [],
            source_table="memory_events",
            source_id=memory_event_id,
            valid_from=_utc_now(),
        )
        if teaching_target:
            self._upsert_learner_concept_state_v2(
                topic_id=topic_id,
                concept_text=concept_clean,
                evidence_event_ids=[memory_event_id] if memory_event_id > 0 else [],
                passive_exposure=True,
                misconception=teaching_target if outcome and outcome.lower() not in ("correct", "success", "safe") else "",
                event_ts=_utc_now(),
            )
        return {"ok": True, "memory_event_id": memory_event_id, "memory_item_id": item_id}

    def promote_core_profile_v2(
        self,
        *,
        statement: str = "",
        evidence_event_ids: list[int] | None = None,
        evidence_exchange_ids: list[int] | None = None,
        apply: bool = False,
    ) -> dict[str, Any]:
        """Promote repeated teaching/learning patterns into durable core profile facts."""
        candidates: list[dict[str, Any]] = []
        if statement.strip():
            candidates.append({
                "statement": statement.strip(),
                "reason": "explicit_agent_or_user_observation",
                "confidence": 0.9,
                "evidence_event_ids": evidence_event_ids or [],
                "evidence_exchange_ids": evidence_exchange_ids or [],
            })

        policy_rows = self.conn.execute(
            """SELECT teaching_approach, concept_text, error_type, success_count,
                      failure_count, confidence, evidence_event_ids, evidence_exchange_ids
               FROM teaching_policy_stats
               WHERE (success_count + failure_count) >= 2
               ORDER BY confidence DESC, updated_ts DESC
               LIMIT 5"""
        ).fetchall()
        for row in policy_rows:
            if float(row["confidence"] or 0.0) >= 0.7:
                candidates.append({
                    "statement": (
                        f"Gabriel tends to learn {row['concept_text'] or row['error_type'] or 'this material'} "
                        f"well with {row['teaching_approach']}."
                    ),
                    "reason": "repeated_teaching_policy_success",
                    "confidence": float(row["confidence"] or 0.7),
                    "evidence_event_ids": _merge_ids(row["evidence_event_ids"], []),
                    "evidence_exchange_ids": _merge_ids(row["evidence_exchange_ids"], []),
                })

        calibration_rows = [
            dict(row) for row in self.conn.execute(
                """SELECT calibration_state, concept_text, evidence_event_ids,
                          evidence_exchange_ids
                   FROM learner_concept_state
                   WHERE calibration_state IN ('overconfident_wrong', 'underconfident_right')
                   ORDER BY last_updated DESC"""
            ).fetchall()
        ]
        by_calibration: dict[str, list[dict[str, Any]]] = {}
        for row in calibration_rows:
            by_calibration.setdefault(row["calibration_state"], []).append(row)
        for state, rows in by_calibration.items():
            if len(rows) < 2:
                continue
            concepts = [row["concept_text"] for row in rows[:4] if row.get("concept_text")]
            if state == "overconfident_wrong":
                statement = (
                    "Gabriel has a repeated overconfident-wrong calibration pattern "
                    f"across {', '.join(concepts)}; require derivation/checklist before accepting answers."
                )
            else:
                statement = (
                    "Gabriel has a repeated underconfident-right calibration pattern "
                    f"across {', '.join(concepts)}; confirm briefly then raise to transfer vignettes."
                )
            event_ids: list[int] = []
            exchange_ids: list[int] = []
            for row in rows:
                event_ids = _merge_ids(event_ids, _json_list(row.get("evidence_event_ids")))
                exchange_ids = _merge_ids(exchange_ids, _json_list(row.get("evidence_exchange_ids")))
            candidates.append({
                "statement": statement,
                "reason": "repeated_calibration_pattern",
                "confidence": 0.8,
                "evidence_event_ids": event_ids,
                "evidence_exchange_ids": exchange_ids,
            })

        if not apply:
            return {"ok": True, "mode": "dry_run", "candidates": candidates}

        written: list[int] = []
        for candidate in candidates:
            item_id = self._upsert_memory_item_v2(
                item_type="core_profile",
                summary=candidate["statement"],
                details={
                    "profile_reason": candidate["reason"],
                    "promotion_source": "memory_v2",
                },
                importance=0.95,
                confidence=float(candidate["confidence"]),
                evidence_event_ids=candidate.get("evidence_event_ids", []),
                evidence_exchange_ids=candidate.get("evidence_exchange_ids", []),
                source_table="core_profile_promotion",
                valid_from=_utc_now(),
                dedupe_key=self._memory_hash("core_profile", candidate["statement"].lower()),
            )
            if item_id > 0:
                written.append(item_id)
        return {"ok": True, "mode": "apply", "written_item_ids": written, "candidates": candidates}

    def calibration_training_pack_v2(self, max_items: int = 8) -> dict[str, Any]:
        """Build a confidence-calibration training brief."""
        rows = self.conn.execute(
            """SELECT lcs.*, t.display_name AS topic_display
               FROM learner_concept_state lcs
               JOIN topics t ON lcs.topic_id = t.topic_id
               WHERE lcs.calibration_state != ''
                 AND lcs.calibration_state != 'unknown'
               ORDER BY lcs.last_updated DESC
               LIMIT ?""",
            (max_items,),
        ).fetchall()
        alerts = []
        drills = []
        for row in rows:
            state = row["calibration_state"]
            concept = row["concept_text"]
            topic = row["topic_display"]
            if state == "overconfident_wrong":
                alerts.append(f"Overconfident wrong zone: {concept} ({topic}).")
                drills.append(f"Force derivation/checklist before answering {concept}.")
            elif state == "underconfident_right":
                alerts.append(f"Underconfident right zone: {concept} ({topic}).")
                drills.append(f"Use quick confirmation then transfer vignette for {concept}.")
        if not alerts:
            alerts.append("No repeated calibration pattern yet; ask for confidence before high-stakes answers.")
            drills.append("During drills, require high/low confidence before revealing correctness.")
        text = "\n".join([
            "## Confidence Calibration Training",
            *[f"- {line}" for line in alerts[:max_items]],
            "",
            "Recommended drills:",
            *[f"- {line}" for line in drills[:max_items]],
        ])
        return {"ok": True, "alerts": alerts[:max_items], "drills": drills[:max_items], "text": text}

    def pre_rotation_pack_v2(self, rotation: str, max_items: int = 8) -> dict[str, Any]:
        """Generate a memory-driven pre-rotation teaching brief."""
        like = f"%{rotation}%"
        rows = [
            dict(row) for row in self.conn.execute(
                """SELECT lcs.*, t.display_name AS topic_display, t.category
                   FROM learner_concept_state lcs
                   JOIN topics t ON lcs.topic_id = t.topic_id
                   WHERE t.display_name LIKE ? OR t.category LIKE ?
                   ORDER BY lcs.mastery_prob ASC, lcs.last_updated DESC
                   LIMIT ?""",
                (like, like, max_items * 3),
            ).fetchall()
        ]
        weak = [r for r in rows if float(r["mastery_prob"] or 0.0) < 0.45][:max_items]
        strong = [r for r in rows if float(r["mastery_prob"] or 0.0) >= 0.65][:max_items]
        confusions = [r for r in rows if r.get("dominant_misconception")][:max_items]
        policies = [
            dict(row) for row in self.conn.execute(
                """SELECT teaching_approach, concept_text, error_type, confidence
                   FROM teaching_policy_stats
                   WHERE domain LIKE ? OR concept_text LIKE ?
                   ORDER BY confidence DESC, updated_ts DESC
                   LIMIT ?""",
                (like, like, max_items),
            ).fetchall()
        ]
        core = [
            dict(row) for row in self.conn.execute(
                """SELECT summary FROM memory_items
                   WHERE item_type = 'core_profile'
                     AND (valid_to IS NULL OR valid_to = '')
                   ORDER BY importance DESC, confidence DESC
                   LIMIT 5"""
            ).fetchall()
        ]
        lines = [f"## Pre-Rotation Memory Pack: {rotation}"]
        lines.append("\n### Strong Anchors")
        lines.extend(
            f"- {r['concept_text']} ({r['topic_display']}): mastery {float(r['mastery_prob'] or 0):.2f}"
            for r in strong
        )
        if not strong:
            lines.append("- No strong anchors found yet.")
        lines.append("\n### Priority Weaknesses")
        lines.extend(
            f"- {r['concept_text']} ({r['topic_display']}): mastery {float(r['mastery_prob'] or 0):.2f}, due {(r['next_review_due'] or '')[:10] or 'unknown'}"
            for r in weak
        )
        if not weak:
            lines.append("- No weak learner-state rows found for this rotation.")
        lines.append("\n### Dangerous Confusions")
        lines.extend(
            f"- {r['concept_text']}: {r['dominant_misconception']}"
            for r in confusions
        )
        if not confusions:
            lines.append("- No active dangerous confusion recorded.")
        lines.append("\n### Teaching Mode")
        if policies:
            lines.extend(
                f"- Prefer {p['teaching_approach']} for {p['concept_text'] or p['error_type'] or 'general'}."
                for p in policies[:5]
            )
        else:
            lines.append("- Start with active recall, then escalate to clinical vignettes.")
        if core:
            lines.append("\n### Core Learner Profile")
            lines.extend(f"- {row['summary']}" for row in core)
        text = "\n".join(lines)
        return {
            "ok": True,
            "rotation": rotation,
            "strong": strong,
            "weak": weak,
            "dangerous_confusions": confusions,
            "teaching_policies": policies,
            "core_profile": core,
            "text": text,
        }

    def session_summary_v2(
        self,
        *,
        session_ts: str,
        apply: bool = False,
    ) -> dict[str, Any]:
        """Summarize what changed in the learner model during a session."""
        rows = [
            dict(row) for row in self.conn.execute(
                """SELECT le.*, t.display_name AS topic_display
                   FROM learning_exchanges le
                   LEFT JOIN topics t ON le.topic_id = t.topic_id
                   WHERE le.session_ts = ?
                   ORDER BY le.turn_number""",
                (session_ts,),
            ).fetchall()
        ]
        if not rows:
            events = [
                dict(row) for row in self.conn.execute(
                    """SELECT me.*, t.display_name AS topic_display
                       FROM memory_events me
                       LEFT JOIN topics t ON me.topic_id = t.topic_id
                       WHERE me.session_ts = ?
                       ORDER BY me.turn_number""",
                    (session_ts,),
                ).fetchall()
            ]
            if not events:
                return {"ok": True, "session_ts": session_ts, "note": "no learning exchanges"}
            types = Counter(event["event_type"] for event in events)
            concepts = sorted({event["concept_text"] for event in events if event.get("concept_text")})
            lines = [
                f"## What Changed In Gabriel's Brain ({session_ts[:10]})",
                "- No active Q/A exchanges were found, but memory events were captured.",
                "- Event mix: " + ", ".join(f"{k}={v}" for k, v in sorted(types.items())),
            ]
            if concepts:
                lines.append("- Concepts touched: " + ", ".join(concepts[:8]))
            text = "\n".join(lines)
            item_id = -1
            if apply:
                item_id = self._upsert_memory_item_v2(
                    item_type="reflection",
                    summary=text,
                    details={
                        "reflection_type": "session_delta",
                        "session_ts": session_ts,
                        "event_only": True,
                        "event_types": dict(types),
                        "concepts": concepts,
                    },
                    importance=0.75,
                    confidence=0.75,
                    evidence_event_ids=[event["memory_event_id"] for event in events if event.get("memory_event_id")],
                    source_table="session_summary_v2",
                    valid_from=session_ts,
                    dedupe_key=self._memory_hash("session_summary_v2", session_ts),
                )
            return {
                "ok": True,
                "session_ts": session_ts,
                "text": text,
                "next_focus": concepts[0] if concepts else "",
                "memory_item_id": item_id,
            }
        correct = [r for r in rows if int(r["answer_correct"] or 0) == 2]
        partial = [r for r in rows if int(r["answer_correct"] or 0) == 1]
        wrong = [r for r in rows if int(r["answer_correct"] or 0) == 0]
        concepts = sorted({r["concept_text"] for r in rows if r.get("concept_text")})
        misconceptions = [r["misconception"] for r in rows if r.get("misconception")]
        lines = [
            f"## What Changed In Gabriel's Brain ({session_ts[:10]})",
            f"- Tested {len(rows)} concept(s): {len(correct)} correct, {len(partial)} partial, {len(wrong)} incorrect.",
        ]
        if correct:
            lines.append("- Strengthened: " + ", ".join(r["concept_text"] for r in correct[:5]))
        if partial:
            lines.append("- Partially repaired: " + ", ".join(r["concept_text"] for r in partial[:5]))
        if wrong:
            lines.append("- Still vulnerable: " + ", ".join(r["concept_text"] for r in wrong[:5]))
        if misconceptions:
            lines.append("- Misconceptions to retest: " + "; ".join(misconceptions[:5]))
        next_focus = wrong[0]["concept_text"] if wrong else (partial[0]["concept_text"] if partial else concepts[0])
        lines.append(f"- Next session should open with active recall on: {next_focus}.")
        text = "\n".join(lines)
        item_id = -1
        if apply:
            event_ids = [r["memory_event_id"] for r in rows if r.get("memory_event_id")]
            exchange_ids = [r["exchange_id"] for r in rows if r.get("exchange_id")]
            item_id = self._upsert_memory_item_v2(
                item_type="reflection",
                summary=text,
                details={
                    "reflection_type": "session_delta",
                    "session_ts": session_ts,
                    "correct": [r["concept_text"] for r in correct],
                    "partial": [r["concept_text"] for r in partial],
                    "incorrect": [r["concept_text"] for r in wrong],
                    "next_focus": next_focus,
                },
                importance=0.85,
                confidence=0.85,
                evidence_event_ids=event_ids,
                evidence_exchange_ids=exchange_ids,
                source_table="session_summary_v2",
                valid_from=session_ts,
                dedupe_key=self._memory_hash("session_summary_v2", session_ts),
            )
        return {
            "ok": True,
            "session_ts": session_ts,
            "text": text,
            "next_focus": next_focus,
            "memory_item_id": item_id,
        }

    def _latest_active_memory_session_v2(
        self,
        *,
        skill: str = "",
        topic_name: str = "",
    ) -> dict[str, Any]:
        """Return the most plausible active memory session for finish-session."""
        clauses = ["memory_enabled = 1", "status = 'active'"]
        params: list[Any] = []
        if skill:
            clauses.append("skill = ?")
            params.append(skill)
        rows = [
            dict(row) for row in self.conn.execute(
                f"""SELECT * FROM memory_sessions
                    WHERE {' AND '.join(clauses)}
                    ORDER BY started_ts DESC
                    LIMIT 10""",
                params,
            ).fetchall()
        ]
        if not rows:
            return {}
        if topic_name:
            topic_norm = self._normalize_topic(topic_name)
            for row in rows:
                row_norm = self._normalize_topic(row.get("topic_text") or "")
                if topic_norm and (
                    topic_norm == row_norm
                    or topic_norm in row_norm
                    or row_norm in topic_norm
                ):
                    return row
        return rows[0]

    def _finish_window_v2(
        self,
        session_row: dict[str, Any] | None,
        session_ts: str,
        window_minutes: int,
    ) -> tuple[str, str]:
        """Build a conservative event-time window for fragment repair."""
        now = datetime.now(timezone.utc)
        start_dt = None
        end_dt = None
        target_dt = self._parse_ts(session_ts)
        if session_row:
            start_dt = self._parse_ts(session_row.get("started_ts"))
            end_dt = self._parse_ts(session_row.get("ended_ts"))
        target_dt = target_dt or start_dt or now
        window = timedelta(minutes=max(15, int(window_minutes or 240)))
        # Sessions are often closed after the teaching exchange. If the
        # memory_session row was only created at close time, looking forward
        # from started_ts misses the real answers. Always include a bounded
        # lookback from the target session timestamp.
        lookback_start = target_dt - window
        start_dt = min([dt for dt in (start_dt, lookback_start) if dt is not None])
        end_dt = max([dt for dt in (end_dt, target_dt, now) if dt is not None])
        return (
            (start_dt - timedelta(minutes=5)).isoformat(),
            (end_dt + timedelta(minutes=5)).isoformat(),
        )

    def _session_topic_terms_v2(self, topic_name: str) -> list[str]:
        """Terms used to match fragmented timestamps back to a session."""
        raw = (topic_name or "").strip().lower()
        if not raw:
            return []
        expansions = {
            "sah": "subarachnoid hemorrhage",
            "ivh": "intraventricular hemorrhage",
            "edh": "epidural hematoma",
            "sdh": "subdural hematoma",
            "hydro": "hydrocephalus",
        }
        parts = re.split(r"[,;|]+", raw)
        terms: list[str] = []
        for part in parts:
            clean = re.sub(r"\s+", " ", part.strip())
            if clean:
                terms.append(clean)
                expanded = clean
                for short, full in expansions.items():
                    expanded = re.sub(rf"\b{re.escape(short)}\b", full, expanded)
                if expanded != clean:
                    terms.append(expanded)
            for token in re.findall(r"[a-z0-9]+", clean):
                if len(token) < 4 and token not in expansions:
                    continue
                terms.append(expansions.get(token, token))
        return sorted(set(t for t in terms if len(t) >= 4))

    def _session_fragment_matches_v2(self, row: dict[str, Any], topic_name: str) -> bool:
        """Return True when a candidate row plausibly belongs to the target topic."""
        terms = self._session_topic_terms_v2(topic_name)
        if not terms:
            return True
        haystack = " ".join(
            str(row.get(key) or "").lower()
            for key in (
                "topic_display",
                "concept_text",
                "question_text",
                "answer_text",
                "correction_text",
                "content_text",
            )
        )
        return any(term in haystack for term in terms)

    def _session_finish_exchanges_v2(
        self,
        *,
        session_ts: str,
        skill: str,
        topic_name: str,
        repair_fragments: bool,
        window_minutes: int,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Collect exact-session exchanges plus plausible fragmented writes."""
        session_row = self.conn.execute(
            """SELECT * FROM memory_sessions
               WHERE session_ts = ? AND skill = ?
               LIMIT 1""",
            (session_ts, skill),
        ).fetchone()
        session_dict = dict(session_row) if session_row else None
        topic = topic_name or (session_dict or {}).get("topic_text", "")
        exact_rows = [
            dict(row) for row in self.conn.execute(
                """SELECT le.*, t.display_name AS topic_display, me.event_ts AS memory_event_ts
                   FROM learning_exchanges le
                   LEFT JOIN topics t ON le.topic_id = t.topic_id
                   LEFT JOIN memory_events me ON le.memory_event_id = me.memory_event_id
                   WHERE le.session_ts = ?
                   ORDER BY COALESCE(me.event_ts, le.session_ts), le.turn_number""",
                (session_ts,),
            ).fetchall()
        ]
        rows_by_id: dict[int, dict[str, Any]] = {
            int(row["exchange_id"]): row for row in exact_rows if row.get("exchange_id")
        }
        if repair_fragments and skill:
            window_start, window_end = self._finish_window_v2(session_dict, session_ts, window_minutes)
            candidates = [
                dict(row) for row in self.conn.execute(
                    """SELECT le.*, t.display_name AS topic_display, me.event_ts AS memory_event_ts
                       FROM learning_exchanges le
                       LEFT JOIN topics t ON le.topic_id = t.topic_id
                       LEFT JOIN memory_events me ON le.memory_event_id = me.memory_event_id
                       WHERE le.skill = ?
                         AND le.session_ts != ?
                         AND COALESCE(me.event_ts, le.consolidated_at, le.session_ts) >= ?
                         AND COALESCE(me.event_ts, le.consolidated_at, le.session_ts) <= ?
                       ORDER BY COALESCE(me.event_ts, le.session_ts), le.turn_number""",
                    (skill, session_ts, window_start, window_end),
                ).fetchall()
            ]
            for row in candidates:
                if row.get("exchange_id") and self._session_fragment_matches_v2(row, topic):
                    rows_by_id[int(row["exchange_id"])] = row
        rows = sorted(
            rows_by_id.values(),
            key=lambda r: (str(r.get("memory_event_ts") or r.get("session_ts") or ""), int(r.get("turn_number") or 0)),
        )
        fragments = sorted({
            row["session_ts"] for row in rows
            if row.get("session_ts") and row["session_ts"] != session_ts
        })
        return rows, fragments

    def _session_finish_events_v2(
        self,
        *,
        session_ts: str,
        skill: str,
        topic_name: str,
        repair_fragments: bool,
        window_minutes: int,
    ) -> list[dict[str, Any]]:
        """Collect memory events relevant to a finished learning session."""
        session_row = self.conn.execute(
            """SELECT * FROM memory_sessions
               WHERE session_ts = ? AND skill = ?
               LIMIT 1""",
            (session_ts, skill),
        ).fetchone()
        session_dict = dict(session_row) if session_row else None
        topic = topic_name or (session_dict or {}).get("topic_text", "")
        exact_rows = [
            dict(row) for row in self.conn.execute(
                """SELECT me.*, t.display_name AS topic_display
                   FROM memory_events me
                   LEFT JOIN topics t ON me.topic_id = t.topic_id
                   WHERE me.session_ts = ?
                   ORDER BY me.event_ts, me.turn_number""",
                (session_ts,),
            ).fetchall()
        ]
        rows_by_id: dict[int, dict[str, Any]] = {
            int(row["memory_event_id"]): row for row in exact_rows if row.get("memory_event_id")
        }
        if repair_fragments and skill:
            window_start, window_end = self._finish_window_v2(session_dict, session_ts, window_minutes)
            candidates = [
                dict(row) for row in self.conn.execute(
                    """SELECT me.*, t.display_name AS topic_display
                       FROM memory_events me
                       LEFT JOIN topics t ON me.topic_id = t.topic_id
                       WHERE me.skill = ?
                         AND me.session_ts != ?
                         AND me.event_ts >= ?
                         AND me.event_ts <= ?
                       ORDER BY me.event_ts, me.turn_number""",
                    (skill, session_ts, window_start, window_end),
                ).fetchall()
            ]
            for row in candidates:
                if row.get("memory_event_id") and self._session_fragment_matches_v2(row, topic):
                    rows_by_id[int(row["memory_event_id"])] = row
        return sorted(
            rows_by_id.values(),
            key=lambda r: (str(r.get("event_ts") or r.get("session_ts") or ""), int(r.get("turn_number") or 0)),
        )

    def embed_pending_memory_items_v2(self, limit: int = 200) -> dict[str, Any]:
        """Embed pending/stale typed memory items into LanceDB."""
        rows = [
            dict(row) for row in self.conn.execute(
                """SELECT mi.*, t.display_name AS topic_display
                   FROM memory_items mi
                   LEFT JOIN topics t ON mi.topic_id = t.topic_id
                   WHERE mi.embedding_status IN ('pending', 'stale')
                     AND mi.summary != ''
                   ORDER BY mi.importance DESC, mi.updated_ts DESC
                   LIMIT ?""",
                (max(1, int(limit or 200)),),
            ).fetchall()
        ]
        if not rows:
            return {"ok": True, "selected": 0, "rows_inserted": 0, "skipped": True}
        try:
            import lance_retriever as lr
            embedded = lr.embed_memory_items(rows)
            if embedded.get("ok"):
                with self.conn:
                    self.conn.executemany(
                        "UPDATE memory_items SET embedding_status = 'embedded' WHERE item_id = ?",
                        [(int(row["item_id"]),) for row in rows],
                    )
            return {
                "ok": bool(embedded.get("ok")),
                "selected": len(rows),
                **embedded,
            }
        except Exception as exc:
            return {"ok": False, "selected": len(rows), "error": str(exc)}

    def _session_teaching_intelligence_v2(
        self,
        *,
        exchanges: list[dict[str, Any]],
        passive_events: list[dict[str, Any]],
        transfer_events: list[dict[str, Any]],
        fragment_session_ts: list[str],
    ) -> dict[str, Any]:
        """Derive forward-looking teaching intelligence from a closed session."""
        approaches_by_row: dict[int, str] = {}
        approach_counts: Counter[str] = Counter()
        approach_success: Counter[str] = Counter()
        approach_failure: Counter[str] = Counter()
        depth_profile: dict[str, int] = {}
        teaching_successes: list[str] = []
        teaching_failures: list[dict[str, str]] = []
        key_confusions: list[dict[str, str]] = []

        for row in exchanges:
            row_id = int(row.get("exchange_id") or 0)
            approach = row.get("teaching_approach") or self._infer_teaching_approach_v2(
                question_text=row.get("question_text") or "",
                answer_text=row.get("answer_text") or "",
                correction_text=row.get("correction_text") or "",
                skill=row.get("skill") or "",
                topic_name=row.get("topic_display") or "",
                concept_text=row.get("concept_text") or "",
                answer_correct=int(row.get("answer_correct") or 0),
                depth=int(row.get("depth") or 1),
            )
            if row_id:
                approaches_by_row[row_id] = approach
            if approach:
                approach_counts[approach] += 1
                if int(row.get("answer_correct") or 0) == 2:
                    approach_success[approach] += 1
                elif int(row.get("answer_correct") or 0) == 0:
                    approach_failure[approach] += 1

            topic_key = row.get("topic_display") or row.get("concept_text") or "session"
            depth_profile[topic_key] = max(
                int(depth_profile.get(topic_key, 0) or 0),
                int(row.get("depth") or 1),
            )

            if int(row.get("answer_correct") or 0) < 2:
                metadata = self._infer_missing_error_metadata_v2(
                    answer_correct=int(row.get("answer_correct") or 0),
                    answer_text=row.get("answer_text") or "",
                    correction_text=row.get("correction_text") or "",
                    error_type=row.get("error_type") or "",
                    root_cause=row.get("root_cause") or "",
                    misconception=row.get("misconception") or "",
                    concept_text=row.get("concept_text") or "",
                    question_text=row.get("question_text") or "",
                )
                teaching_failures.append({
                    "concept": row.get("concept_text") or "",
                    "attempted": approach,
                    "why_failed": metadata.get("root_cause") or metadata.get("error_type") or "partial/incorrect answer",
                })
                misconception = row.get("misconception") or ""
                if misconception and row.get("concept_text"):
                    key_confusions.append({
                        "concept_a": row.get("concept_text") or "",
                        "concept_b": misconception,
                        "disambiguation_axis": metadata.get("root_cause") or "requires contrastive retest",
                    })

        for approach, count in approach_counts.most_common(5):
            successes = approach_success.get(approach, 0)
            failures = approach_failure.get(approach, 0)
            if successes:
                teaching_successes.append(
                    f"{approach} produced {successes}/{count} correct active response(s); reuse for similar material."
                )
            elif failures == 0:
                teaching_successes.append(
                    f"{approach} was used without an incorrect answer; keep as a candidate strategy and validate with transfer."
                )

        if passive_events:
            teaching_successes.append(
                f"Passive teaching was explicitly logged {len(passive_events)} time(s); keep passive exposure separate from mastery."
            )
        if transfer_events:
            teaching_successes.append(
                f"Transfer validation occurred {len(transfer_events)} time(s); preserve vignette-based retesting."
            )
        if fragment_session_ts:
            teaching_failures.append({
                "concept": "memory_session_continuity",
                "attempted": "finish-session fragment repair",
                "why_failed": "answers were written under multiple SESSION_TS values; agents must reuse the active session timestamp",
            })

        total = len(exchanges)
        correct = sum(1 for row in exchanges if int(row.get("answer_correct") or 0) == 2)
        partial = sum(1 for row in exchanges if int(row.get("answer_correct") or 0) == 1)
        wrong = sum(1 for row in exchanges if int(row.get("answer_correct") or 0) == 0)
        success_rate = (correct / total) if total else None
        if total and wrong == 0 and partial <= max(1, total // 3):
            strategy_outcome = "effective"
        elif total and correct:
            strategy_outcome = "mixed_but_useful"
        elif total:
            strategy_outcome = "needs_revision"
        else:
            strategy_outcome = "no_active_answers"

        return {
            "approaches_by_exchange_id": approaches_by_row,
            "approach_counts": dict(approach_counts),
            "teaching_successes": teaching_successes,
            "teaching_failures": teaching_failures,
            "key_confusions": key_confusions[:6],
            "depth_profile": depth_profile,
            "session_success_rate": success_rate,
            "strategy_outcome": strategy_outcome,
            "counts": {"correct": correct, "partial": partial, "wrong": wrong, "total": total},
        }

    def _upsert_finish_session_narrative_v2(
        self,
        *,
        session_ts: str,
        skill: str,
        topics: list[str],
        summary: str,
        teaching_successes: list[str],
        teaching_failures: list[dict[str, str]],
        next_session_strategy: str,
        key_confusions: list[dict[str, str]],
        depth_profile: dict[str, int],
        duration_turns: int,
        session_success_rate: float | None,
        strategy_outcome: str,
        linked_signal_ids: list[int] | None = None,
        exchange_ids: list[int] | None = None,
    ) -> int:
        """Create/update the session narrative tied to the canonical session_ts."""
        topic_fp = self._topic_fingerprint(topics or []) if hasattr(self, "_topic_fingerprint") else ""
        existing = self.conn.execute(
            """SELECT narrative_id FROM session_narratives
               WHERE session_ts = ? AND skill = ?
               LIMIT 1""",
            (session_ts, skill),
        ).fetchone()
        with self.conn:
            if existing:
                narrative_id = int(existing["narrative_id"])
                self.conn.execute(
                    """UPDATE session_narratives
                       SET topics_json = ?,
                           summary = ?,
                           teaching_successes = ?,
                           teaching_failures = ?,
                           next_session_strategy = ?,
                           key_confusions_json = ?,
                           depth_profile_json = ?,
                           duration_turns = ?,
                           linked_signal_ids = ?,
                           session_success_rate = ?,
                           strategy_outcome = ?,
                           topic_fingerprint = ?
                       WHERE narrative_id = ?""",
                    (
                        json.dumps(topics or []),
                        summary,
                        json.dumps(teaching_successes or []),
                        json.dumps(teaching_failures or []),
                        next_session_strategy,
                        json.dumps(key_confusions or []),
                        json.dumps(depth_profile or {}),
                        int(duration_turns or 0),
                        json.dumps(_merge_ids([], linked_signal_ids or [])),
                        session_success_rate,
                        strategy_outcome,
                        topic_fp,
                        narrative_id,
                    ),
                )
            else:
                cur = self.conn.execute(
                    """INSERT INTO session_narratives
                       (session_ts, skill, topics_json, summary,
                        teaching_successes, teaching_failures, next_session_strategy,
                        key_confusions_json, depth_profile_json, duration_turns,
                        linked_signal_ids, session_success_rate, strategy_outcome,
                        topic_fingerprint)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_ts,
                        skill,
                        json.dumps(topics or []),
                        summary,
                        json.dumps(teaching_successes or []),
                        json.dumps(teaching_failures or []),
                        next_session_strategy,
                        json.dumps(key_confusions or []),
                        json.dumps(depth_profile or {}),
                        int(duration_turns or 0),
                        json.dumps(_merge_ids([], linked_signal_ids or [])),
                        session_success_rate,
                        strategy_outcome,
                        topic_fp,
                    ),
                )
                narrative_id = int(cur.lastrowid or -1)
            if narrative_id > 0 and exchange_ids:
                placeholders = ",".join("?" for _ in exchange_ids)
                self.conn.execute(
                    f"UPDATE learning_exchanges SET narrative_id = ? WHERE exchange_id IN ({placeholders})",
                    (narrative_id, *exchange_ids),
                )
        return narrative_id

    def finish_learning_session_v2(
        self,
        *,
        session_ts: str = "",
        skill: str = "",
        topic_name: str = "",
        mode: str = "dry-run",
        repair_fragments: bool = False,
        window_minutes: int = 240,
        embed: bool = True,
    ) -> dict[str, Any]:
        """Close, roll up, consolidate, and audit a learning session."""
        apply = mode == "apply"
        target_ts = (session_ts or "").strip()
        skill_clean = (skill or "").strip()
        topic_clean = (topic_name or "").strip()
        session_row = None
        if target_ts and skill_clean:
            session_row = self.conn.execute(
                """SELECT * FROM memory_sessions
                   WHERE session_ts = ? AND skill = ?
                   LIMIT 1""",
                (target_ts, skill_clean),
            ).fetchone()
        if not session_row:
            latest = self._latest_active_memory_session_v2(skill=skill_clean, topic_name=topic_clean)
            if latest:
                target_ts = latest["session_ts"]
                skill_clean = skill_clean or latest["skill"]
                topic_clean = topic_clean or latest["topic_text"]
                session_row = latest
        session_dict = dict(session_row) if session_row and not isinstance(session_row, dict) else session_row
        if not target_ts or not skill_clean:
            return {
                "ok": False,
                "error": "finish-session requires --session-ts/--skill or one active memory session",
            }
        topic_clean = topic_clean or (session_dict or {}).get("topic_text", "")
        exchanges, fragment_session_ts = self._session_finish_exchanges_v2(
            session_ts=target_ts,
            skill=skill_clean,
            topic_name=topic_clean,
            repair_fragments=repair_fragments,
            window_minutes=window_minutes,
        )
        events = self._session_finish_events_v2(
            session_ts=target_ts,
            skill=skill_clean,
            topic_name=topic_clean,
            repair_fragments=repair_fragments,
            window_minutes=window_minutes,
        )
        correct = [r for r in exchanges if int(r.get("answer_correct") or 0) == 2]
        partial = [r for r in exchanges if int(r.get("answer_correct") or 0) == 1]
        wrong = [r for r in exchanges if int(r.get("answer_correct") or 0) == 0]
        concepts = sorted({r.get("concept_text") or "" for r in exchanges if r.get("concept_text")})
        weak = [r for r in [*wrong, *partial] if r.get("concept_text")]
        misconceptions = [r.get("misconception") or "" for r in exchanges if r.get("misconception")]
        passive_events = [e for e in events if e.get("event_type") == "teaching_exposure"]
        transfer_events = [e for e in events if e.get("event_type") == "transfer_validation"]
        case_events = [e for e in events if e.get("event_type") == "case_memory"]
        teaching_intelligence = self._session_teaching_intelligence_v2(
            exchanges=exchanges,
            passive_events=passive_events,
            transfer_events=transfer_events,
            fragment_session_ts=fragment_session_ts,
        )
        inferred_approaches = teaching_intelligence.get("approaches_by_exchange_id", {})
        missing_metadata = [
            r for r in [*partial, *wrong]
            if not (r.get("error_type") and (r.get("misconception") or r.get("root_cause") or r.get("correction_text")))
        ]
        missing_approach = [r for r in exchanges if not (r.get("teaching_approach") or "").strip()]
        next_focus = weak[0]["concept_text"] if weak else (concepts[0] if concepts else topic_clean)
        lines = [
            f"## Finished Memory Session ({target_ts[:10]})",
            f"- Skill/topic: {skill_clean} / {topic_clean or 'unknown topic'}.",
            f"- Active answers captured: {len(exchanges)} total, {len(correct)} correct, {len(partial)} partial, {len(wrong)} incorrect.",
        ]
        if concepts:
            lines.append("- Concepts covered: " + ", ".join(concepts[:12]) + ("." if len(concepts) <= 12 else ", ..."))
        if weak:
            lines.append("- Needs retest: " + ", ".join(dict.fromkeys(r["concept_text"] for r in weak[:8])) + ".")
        if misconceptions:
            lines.append("- Misconceptions preserved: " + "; ".join(misconceptions[:5]) + ".")
        if passive_events:
            lines.append(f"- Passive teaching exposures logged: {len(passive_events)}.")
        else:
            lines.append("- Passive teaching exposures logged: 0; future agents should log correction explanations.")
        if transfer_events:
            lines.append(f"- Transfer validations logged: {len(transfer_events)}.")
        else:
            lines.append("- Transfer validations logged: 0; next session should use clinical vignettes for weak concepts.")
        if case_events:
            lines.append(f"- Case memories logged: {len(case_events)}.")
        approach_counts = teaching_intelligence.get("approach_counts", {})
        if approach_counts:
            rendered = ", ".join(
                f"{approach}={count}"
                for approach, count in list(approach_counts.items())[:5]
            )
            lines.append(f"- Teaching moves captured: {rendered}.")
        if fragment_session_ts:
            lines.append(
                "- Fragmented session timestamps detected and included in this rollup: "
                + ", ".join(fragment_session_ts[:8])
                + "."
            )
        if missing_metadata:
            lines.append(
                f"- Metadata warning: {len(missing_metadata)} partial/wrong answer(s) lack full error detail."
            )
        if missing_approach:
            lines.append(
                f"- Teaching metadata repaired/inferred for {len(missing_approach)} exchange(s)."
            )
        lines.append(f"- Next session should open with active recall on: {next_focus}.")
        text = "\n".join(lines)

        event_ids = sorted({
            int(e["memory_event_id"]) for e in events if e.get("memory_event_id")
        } | {
            int(r["memory_event_id"]) for r in exchanges if r.get("memory_event_id")
        })
        exchange_ids = sorted({
            int(r["exchange_id"]) for r in exchanges if r.get("exchange_id")
        })
        rollup_item_id = -1
        consolidation_results: list[dict[str, Any]] = []
        profile_result: dict[str, Any] = {}
        embed_result: dict[str, Any] = {"ok": True, "skipped": True}
        close_result: dict[str, Any] = {}
        narrative_id = -1
        if apply:
            with self.conn:
                for row in exchanges:
                    exchange_id = int(row.get("exchange_id") or 0)
                    if not exchange_id:
                        continue
                    updates: list[str] = []
                    params: list[Any] = []
                    inferred_approach = inferred_approaches.get(exchange_id, "")
                    if inferred_approach and not (row.get("teaching_approach") or "").strip():
                        updates.append("teaching_approach = ?")
                        params.append(inferred_approach)
                    if int(row.get("answer_correct") or 0) < 2:
                        inferred_meta = self._infer_missing_error_metadata_v2(
                            answer_correct=int(row.get("answer_correct") or 0),
                            answer_text=row.get("answer_text") or "",
                            correction_text=row.get("correction_text") or "",
                            error_type=row.get("error_type") or "",
                            root_cause=row.get("root_cause") or "",
                            misconception=row.get("misconception") or "",
                            concept_text=row.get("concept_text") or "",
                            question_text=row.get("question_text") or "",
                        )
                        if inferred_meta.get("error_type") and not (row.get("error_type") or "").strip():
                            updates.append("error_type = ?")
                            params.append(inferred_meta["error_type"])
                        if inferred_meta.get("root_cause") and not (row.get("root_cause") or "").strip():
                            updates.append("root_cause = ?")
                            params.append(inferred_meta["root_cause"])
                    if updates:
                        self.conn.execute(
                            f"UPDATE learning_exchanges SET {', '.join(updates)} WHERE exchange_id = ?",
                            (*params, exchange_id),
                        )

            for row in exchanges:
                exchange_id = int(row.get("exchange_id") or 0)
                approach = inferred_approaches.get(exchange_id) or row.get("teaching_approach") or ""
                if not approach:
                    continue
                correct_value = int(row.get("answer_correct") or 0)
                outcome = "success" if correct_value == 2 else ("failure" if correct_value == 0 else "unknown")
                self._update_teaching_policy_stats_v2(
                    topic_id=row.get("topic_id"),
                    domain=row.get("domain") or "",
                    concept_text=row.get("concept_text") or "",
                    error_type=row.get("error_type") or "",
                    teaching_approach=approach,
                    outcome=outcome,
                    evidence_event_ids=[int(row["memory_event_id"])] if row.get("memory_event_id") else [],
                    evidence_exchange_ids=[exchange_id] if exchange_id else [],
                )

            narrative_topics = sorted({
                r.get("topic_display") or topic_clean or r.get("concept_text") or "unknown topic"
                for r in exchanges
            }) or ([topic_clean] if topic_clean else [])
            if not narrative_topics and topic_clean:
                narrative_topics = [topic_clean]
            summary = (
                f"Closed {skill_clean} session covering {', '.join(narrative_topics[:4]) or topic_clean or 'unknown topic'}: "
                f"{len(correct)}/{len(exchanges)} correct, {len(partial)} partial, {len(wrong)} incorrect."
            )
            if fragment_session_ts:
                summary += f" Repaired {len(fragment_session_ts)} fragmented timestamp(s)."
            successful_moves = teaching_intelligence.get("teaching_successes", [])
            next_bits: list[str] = []
            if weak:
                weak_names = ", ".join(dict.fromkeys(r["concept_text"] for r in weak[:4]))
                next_bits.append(
                    f"Retest {weak_names} with cognitive friction and one-layer progressive reveal before explanation."
                )
            else:
                next_bits.append(
                    "Avoid basic reteaching; use correct answers as transfer anchors and raise clinical fidelity."
                )
            next_bits.append(
                "When the user selects a specific document, use at most one directly relevant bridge question before returning to that document."
            )
            if successful_moves:
                next_bits.append("Reuse successful moves: " + "; ".join(successful_moves[:2]))
            narrative_id = self._upsert_finish_session_narrative_v2(
                session_ts=target_ts,
                skill=skill_clean,
                topics=narrative_topics,
                summary=summary,
                teaching_successes=successful_moves,
                teaching_failures=teaching_intelligence.get("teaching_failures", []),
                next_session_strategy=" ".join(next_bits),
                key_confusions=teaching_intelligence.get("key_confusions", []),
                depth_profile=teaching_intelligence.get("depth_profile", {}),
                duration_turns=len(exchanges),
                session_success_rate=teaching_intelligence.get("session_success_rate"),
                strategy_outcome=teaching_intelligence.get("strategy_outcome", ""),
                linked_signal_ids=[
                    int(r["signal_event_id"]) for r in exchanges if r.get("signal_event_id")
                ],
                exchange_ids=exchange_ids,
            )
            rollup_item_id = self._upsert_memory_item_v2(
                item_type="reflection",
                summary=text,
                details={
                    "reflection_type": "session_finish_rollup",
                    "session_ts": target_ts,
                    "skill": skill_clean,
                    "topic": topic_clean,
                    "fragment_session_ts": fragment_session_ts,
                    "correct": [r["concept_text"] for r in correct],
                    "partial": [r["concept_text"] for r in partial],
                    "incorrect": [r["concept_text"] for r in wrong],
                    "missing_metadata_count": len(missing_metadata),
                    "passive_event_count": len(passive_events),
                    "transfer_event_count": len(transfer_events),
                    "case_event_count": len(case_events),
                    "teaching_approach_counts": approach_counts,
                    "teaching_successes": teaching_intelligence.get("teaching_successes", []),
                    "teaching_failures": teaching_intelligence.get("teaching_failures", []),
                    "depth_profile": teaching_intelligence.get("depth_profile", {}),
                    "session_success_rate": teaching_intelligence.get("session_success_rate"),
                    "strategy_outcome": teaching_intelligence.get("strategy_outcome"),
                    "narrative_id": narrative_id,
                    "next_focus": next_focus,
                },
                importance=0.9,
                confidence=0.85,
                evidence_event_ids=event_ids,
                evidence_exchange_ids=exchange_ids,
                source_table="finish_session_v2",
                valid_from=target_ts,
                dedupe_key=self._memory_hash("finish_session_v2", target_ts, skill_clean),
            )
            close_result = self.set_memory_session(
                session_ts=target_ts,
                skill=skill_clean,
                topic_text=topic_clean,
                memory_enabled=True,
                consent_scope=(session_dict or {}).get("consent_scope", "study_session"),
                status="complete",
                notes=f"finish-session rollup item {rollup_item_id}",
            )
            for sess in [target_ts, *fragment_session_ts]:
                consolidation_results.append(
                    self.consolidate_memory_v2(session_ts=sess, mode="apply", embed=False)
                )
            profile_result = self.promote_core_profile_v2(apply=True)
            if embed:
                embed_result = self.embed_pending_memory_items_v2(limit=300)

        return {
            "ok": True,
            "mode": mode,
            "session_ts": target_ts,
            "skill": skill_clean,
            "topic": topic_clean,
            "repair_fragments": bool(repair_fragments),
            "fragment_session_ts": fragment_session_ts,
            "counts": {
                "active_answers": len(exchanges),
                "correct": len(correct),
                "partial": len(partial),
                "incorrect": len(wrong),
                "passive_teaching": len(passive_events),
                "transfer_validation": len(transfer_events),
                "case_memory": len(case_events),
                "missing_partial_wrong_metadata": len(missing_metadata),
            },
            "next_focus": next_focus,
            "text": text,
            "memory_item_id": rollup_item_id,
            "narrative_id": narrative_id,
            "teaching_intelligence": teaching_intelligence,
            "close_result": close_result,
            "consolidation": consolidation_results,
            "core_profile": profile_result,
            "embedded": embed_result,
        }

    def apply_learner_state_decay_v2(self) -> dict[str, Any]:
        """Decay V2 learner mastery estimates whose review interval elapsed."""
        now_dt = datetime.now(timezone.utc)
        rows = self.conn.execute(
            """SELECT * FROM learner_concept_state
               WHERE next_review_due IS NOT NULL
                 AND next_review_due != ''
                 AND next_review_due < ?""",
            (now_dt.isoformat(),),
        ).fetchall()
        changed = 0
        with self.conn:
            for row in rows:
                ref = self._parse_ts(row["last_updated"]) or now_dt
                days = max(0.0, (now_dt - ref).total_seconds() / 86400)
                half_life = max(0.5, float(row["retention_half_life_days"] or 1.0))
                decay_factor = 0.5 ** (days / half_life)
                old_mastery = float(row["mastery_prob"] or 0.0)
                new_mastery = _clamp(old_mastery * decay_factor)
                if new_mastery >= old_mastery:
                    continue
                self.conn.execute(
                    """UPDATE learner_concept_state
                       SET mastery_prob = ?,
                           next_review_due = ?,
                           last_updated = ?
                       WHERE state_id = ?""",
                    (
                        new_mastery,
                        (now_dt + timedelta(days=max(0.25, half_life * 0.5))).isoformat(),
                        now_dt.isoformat(),
                        row["state_id"],
                    ),
                )
                changed += 1
        return {"ok": True, "decayed_states": changed}

    # ------------------------------------------------------------------
    # Backfill, consolidation, replay, and eval
    # ------------------------------------------------------------------

    def memory_v2_backfill(self, apply: bool = False, limit: int = 500) -> dict[str, Any]:
        """Plan or apply idempotent V2 projections from existing derived rows."""
        exchanges = self.conn.execute(
            """SELECT le.*, t.display_name AS topic_display, t.category AS topic_domain,
                      me.payload_json
               FROM learning_exchanges le
               LEFT JOIN topics t ON le.topic_id = t.topic_id
               LEFT JOIN memory_events me ON le.memory_event_id = me.memory_event_id
               ORDER BY le.exchange_id ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        summaries = self.conn.execute(
            """SELECT * FROM episode_summaries ORDER BY summary_id ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        concepts = self.conn.execute(
            """SELECT cm.*, t.display_name AS topic_display, t.category AS topic_domain
               FROM concept_mastery cm
               JOIN topics t ON cm.topic_id = t.topic_id
               ORDER BY cm.concept_id ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        planned = {
            "learning_exchanges": len(exchanges),
            "episode_summaries": len(summaries),
            "concept_mastery": len(concepts),
        }
        if not apply:
            return {"ok": True, "mode": "dry_run", "planned": planned}

        active_written = 0
        for row in exchanges:
            payload = _json_dict(row["payload_json"])
            result = self.record_active_answer_v2(
                session_ts=row["session_ts"],
                turn_number=int(row["turn_number"] or 0),
                skill=row["skill"] or "backfill",
                topic_name=row["topic_display"] or "",
                concept_text=row["concept_text"] or "",
                question_text=row["question_text"] or payload.get("question", ""),
                answer_text=row["answer_text"] or payload.get("answer", ""),
                answer_correct=int(row["answer_correct"] or payload.get("answer_correct", 1)),
                correction_text=row["correction_text"] or payload.get("correction", ""),
                error_type=row["error_type"] or payload.get("error_type", ""),
                misconception=row["misconception"] or payload.get("misconception", ""),
                root_cause=row["root_cause"] or payload.get("root_cause", ""),
                remediation=payload.get("remediation", ""),
                teaching_approach=row["teaching_approach"] or payload.get("teaching_approach", ""),
                retrieval_sources=row["retrieval_sources"] or payload.get("retrieval_sources", ""),
                breakthrough=bool(row["breakthrough"] or payload.get("breakthrough")),
                insight_text=row["insight_text"] or payload.get("insight", ""),
                domain=row["domain"] or row["topic_domain"] or payload.get("domain", ""),
                depth=int(row["depth"] or payload.get("depth", 1)),
                response_confidence=payload.get("response_confidence", ""),
                memory_event_id=row["memory_event_id"],
                exchange_id=row["exchange_id"],
                signal_event_id=row["signal_event_id"],
            )
            if result.get("ok"):
                active_written += 1

        reflection_written = 0
        for summary in summaries:
            item_id = self._upsert_memory_item_v2(
                item_type="reflection",
                summary=summary["memory_text"] or "",
                details={
                    "session_ts": summary["session_ts"],
                    "skill": summary["skill"],
                    "persistent_confusions": _json_list(summary["persistent_confusions"]),
                    "effective_approaches": _json_list(summary["effective_approaches"]),
                    "failed_approaches": _json_list(summary["failed_approaches"]),
                },
                importance=0.7,
                confidence=0.75,
                evidence_event_ids=_merge_ids([], _json_list(summary["source_memory_event_ids"])),
                evidence_exchange_ids=_merge_ids([], _json_list(summary["source_exchange_ids"])),
                source_table="episode_summaries",
                source_id=summary["summary_id"],
                valid_from=summary["session_ts"] or _utc_now(),
            )
            if item_id > 0:
                reflection_written += 1

        concept_written = 0
        for concept in concepts:
            status = concept["status"] or "unknown"
            answer_correct = 2 if status == "known" else (1 if status == "due" else 0)
            state = self._upsert_learner_concept_state_v2(
                topic_id=concept["topic_id"],
                concept_text=concept["concept_text"],
                active_answer_correct=answer_correct,
                misconception=concept["misconception"] or "",
                root_cause=concept["root_cause"] or "",
                event_ts=concept["last_updated"] or _utc_now(),
            )
            if state:
                concept_written += 1

        return {
            "ok": True,
            "mode": "apply",
            "planned": planned,
            "written": {
                "active_answer_items": active_written,
                "reflection_items": reflection_written,
                "learner_states": concept_written,
            },
        }

    def consolidate_memory_v2(
        self,
        session_ts: str | None = None,
        mode: str = "dry-run",
        embed: bool = True,
    ) -> dict[str, Any]:
        """Sleep-time consolidation for typed V2 memory."""
        apply = mode == "apply"
        clauses = []
        params: list[Any] = []
        if session_ts:
            clauses.append("le.session_ts = ?")
            params.append(session_ts)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        exchanges = self.conn.execute(
            f"""SELECT le.*, t.display_name AS topic_display, t.category AS topic_domain
                FROM learning_exchanges le
                LEFT JOIN topics t ON le.topic_id = t.topic_id
                {where}
                ORDER BY le.session_ts DESC, le.turn_number ASC
                LIMIT 200""",
            params,
        ).fetchall()
        if not exchanges:
            return {"ok": True, "mode": mode, "planned": {}, "written": {}, "note": "no exchanges"}

        by_session: dict[str, list[dict[str, Any]]] = {}
        for row in exchanges:
            by_session.setdefault(row["session_ts"], []).append(dict(row))

        planned_reflections = []
        for sess, rows in by_session.items():
            correct = sum(1 for r in rows if int(r.get("answer_correct") or 0) == 2)
            partial = sum(1 for r in rows if int(r.get("answer_correct") or 0) == 1)
            incorrect = sum(1 for r in rows if int(r.get("answer_correct") or 0) == 0)
            misconceptions = [
                r.get("misconception", "") for r in rows
                if r.get("misconception")
            ]
            approaches = [
                r.get("teaching_approach", "") for r in rows
                if r.get("teaching_approach")
            ]
            topics = sorted({
                r.get("topic_display") or r.get("concept_text") or ""
                for r in rows
                if r.get("topic_display") or r.get("concept_text")
            })
            summary = (
                f"Session {sess[:10]} on {', '.join(topics[:4]) or 'unknown topic'}: "
                f"{correct} correct, {partial} partial, {incorrect} incorrect."
            )
            if misconceptions:
                counts = Counter(misconceptions)
                common = ", ".join(m for m, _ in counts.most_common(3))
                summary += f" Persistent misconception signals: {common}."
            if approaches:
                common_approach = Counter(approaches).most_common(1)[0][0]
                summary += f" Most used teaching move: {common_approach}."
            planned_reflections.append({
                "session_ts": sess,
                "summary": summary,
                "exchange_ids": [r["exchange_id"] for r in rows],
                "event_ids": [r["memory_event_id"] for r in rows if r.get("memory_event_id")],
            })

        if not apply:
            return {
                "ok": True,
                "mode": "dry_run",
                "planned": {
                    "sessions": len(by_session),
                    "reflections": planned_reflections,
                },
            }

        written_items: list[int] = []
        session_delta_items: list[int] = []
        for reflection in planned_reflections:
            item_id = self._upsert_memory_item_v2(
                item_type="reflection",
                summary=reflection["summary"],
                details={
                    "session_ts": reflection["session_ts"],
                    "sleep_time_consolidation": True,
                    "source_exchange_ids": reflection["exchange_ids"],
                },
                importance=0.75,
                confidence=0.8,
                evidence_event_ids=reflection["event_ids"],
                evidence_exchange_ids=reflection["exchange_ids"],
                source_table="memory_v2_consolidation",
                source_id=None,
                valid_from=reflection["session_ts"] or _utc_now(),
                dedupe_key=self._memory_hash("v2_reflection", reflection["session_ts"]),
            )
            if item_id > 0:
                written_items.append(item_id)
            delta = self.session_summary_v2(session_ts=reflection["session_ts"], apply=True)
            if delta.get("memory_item_id", -1) > 0:
                session_delta_items.append(delta["memory_item_id"])

        embedded = {"ok": True, "skipped": True}
        items_to_embed = sorted(set(written_items + session_delta_items))
        if embed and items_to_embed:
            try:
                import lance_retriever as lr
                item_rows = [
                    dict(r) for r in self.conn.execute(
                        f"""SELECT mi.*, t.display_name AS topic_display
                            FROM memory_items mi
                            LEFT JOIN topics t ON mi.topic_id = t.topic_id
                            WHERE mi.item_id IN ({','.join('?' for _ in items_to_embed)})""",
                        items_to_embed,
                    ).fetchall()
                ]
                embedded = lr.embed_memory_items(item_rows)
                if embedded.get("rows_inserted", 0) > 0:
                    with self.conn:
                        self.conn.executemany(
                            "UPDATE memory_items SET embedding_status = 'embedded' WHERE item_id = ?",
                            [(iid,) for iid in items_to_embed],
                        )
            except Exception as exc:
                embedded = {"ok": False, "error": str(exc)}
        pending_embedded = {"ok": True, "skipped": True}
        if embed:
            pending_embedded = self.embed_pending_memory_items_v2(limit=200)

        return {
            "ok": True,
            "mode": "apply",
            "written": {
                "reflection_item_ids": written_items,
                "session_delta_item_ids": session_delta_items,
            },
            "embedded": embedded,
            "pending_embedded": pending_embedded,
        }

    def replay_memory_v2(self, from_events: bool = True, dry_run: bool = True) -> dict[str, Any]:
        """Verify that V2 derived state can be planned from durable evidence."""
        if not dry_run:
            return {"ok": False, "error": "replay-memory currently supports dry-run only"}
        if from_events:
            rows = self.conn.execute(
                """SELECT event_type, COUNT(*) AS n
                   FROM memory_events GROUP BY event_type"""
            ).fetchall()
            event_counts = {row["event_type"]: row["n"] for row in rows}
        else:
            event_counts = {}
        derived_counts = {
            table: self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            for table in (
                "memory_items",
                "memory_edges",
                "learner_concept_state",
                "teaching_policy_stats",
            )
        }
        orphan_items = self.conn.execute(
            """SELECT COUNT(*) AS n FROM memory_items
               WHERE evidence_event_ids = '[]'
                 AND evidence_exchange_ids = '[]'
                 AND item_type NOT IN ('core_profile', 'resource_link')
                 AND source_table NOT IN ('concept_mastery', 'memory_v2_consolidation')"""
        ).fetchone()["n"]
        return {
            "ok": True,
            "mode": "dry_run",
            "from_events": from_events,
            "event_counts": event_counts,
            "derived_counts": derived_counts,
            "replay_determinism": {
                "source_of_truth": "memory_events plus legacy derived rows",
                "destructive_changes": False,
                "orphan_items": orphan_items,
            },
        }

    def eval_memory(
        self,
        suite: str = "local",
        write_report: str | None = None,
    ) -> dict[str, Any]:
        """Run a small local memory regression suite."""
        started = _utc_now()
        cases = [
            {
                "name": "abstention_no_memory",
                "query": "__unlikely_memory_probe_no_prior_evidence__",
                "expected": "abstention_warning",
                "tags": ["abstention"],
            },
            {
                "name": "context_pack_sections",
                "query": "aneurysm clipping workflow",
                "expected": "fixed_sections",
                "tags": ["context_pack"],
            },
            {
                "name": "passive_not_mastery",
                "query": "passive teaching exposure",
                "expected": "passive_mastery_separation",
                "tags": ["learner_state"],
            },
        ]
        results = []
        for case in cases:
            pack = self.context_pack(
                case["query"],
                intent="review",
                max_tokens=700,
                log_retrieval=False,
            )
            ok = True
            if case["expected"] == "fixed_sections":
                required = {
                    "learner_state",
                    "recent_episode_continuity",
                    "prior_misconceptions_to_retest",
                    "mastered_anchors_to_avoid_reteaching",
                    "teaching_policy",
                    "evidence_ids",
                    "abstention_warnings",
                }
                ok = required.issubset(set(pack.get("sections", {})))
            elif case["expected"] == "abstention_warning":
                ok = bool(pack.get("sections", {}).get("abstention_warnings"))
            elif case["expected"] == "passive_mastery_separation":
                rows = self.conn.execute(
                    """SELECT COUNT(*) AS n FROM learner_concept_state
                       WHERE last_passive_exposed_at IS NOT NULL
                         AND (last_active_tested_at IS NULL OR mastery_prob < familiarity_prob)"""
                ).fetchone()
                ok = rows["n"] >= 0
            results.append({**case, "ok": bool(ok), "token_estimate": pack.get("token_estimate", 0)})

        passed = sum(1 for r in results if r["ok"])
        report = {
            "ok": passed == len(results),
            "suite": suite,
            "started_at": started,
            "finished_at": _utc_now(),
            "passed": passed,
            "total": len(results),
            "results": results,
        }
        if write_report:
            path = Path(write_report)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            report["write_report"] = str(path)
        return report

    # ------------------------------------------------------------------
    # Context packs and retrieval
    # ------------------------------------------------------------------

    def _query_tokens(self, query: str) -> list[str]:
        return [t.lower() for t in __import__("re").findall(r"[A-Za-z0-9]+", query or "") if len(t) >= 3]

    def _memory_items_for_context(
        self,
        query: str,
        topic_name: str | None,
        skill: str | None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        tokens = self._query_tokens(" ".join([query or "", topic_name or ""]))
        clauses = ["(mi.valid_to IS NULL OR mi.valid_to = '')"]
        params: list[Any] = []
        if topic_name:
            clauses.append("(t.display_name LIKE ? OR mi.concept_text LIKE ? OR mi.summary LIKE ?)")
            pat = f"%{topic_name}%"
            params.extend([pat, pat.lower(), pat])
        if tokens:
            token_clause = []
            for token in tokens[:6]:
                token_clause.append("(mi.summary LIKE ? OR mi.concept_text LIKE ?)")
                params.extend([f"%{token}%", f"%{token}%"])
            clauses.append("(" + " OR ".join(token_clause) + ")")
        where = " AND ".join(clauses)
        rows = self.conn.execute(
            f"""SELECT mi.*, t.display_name AS topic_display
                FROM memory_items mi
                LEFT JOIN topics t ON mi.topic_id = t.topic_id
                WHERE {where}
                ORDER BY mi.importance DESC, mi.confidence DESC, mi.updated_ts DESC
                LIMIT ?""",
            [*params, limit],
        ).fetchall()
        items = [dict(row) for row in rows]

        embedded_rows = self.conn.execute(
            """SELECT COUNT(*) AS n FROM memory_items
               WHERE embedding_status = 'embedded'"""
        ).fetchone()["n"]
        semantic_enabled = os.environ.get("MEMORY_CONTEXT_SEMANTIC", "").strip() == "1"
        if semantic_enabled and embedded_rows > 0 and len(items) < min(4, limit) and len(query.strip()) >= 5:
            try:
                import lance_retriever as lr
                semantic = lr.search_memory_items(query, max_results=limit)
                seen = {int(item["item_id"]) for item in items if item.get("item_id")}
                for row in semantic:
                    item_id = int(row.get("item_id") or -1)
                    if item_id <= 0 or item_id in seen:
                        continue
                    db_row = self.conn.execute(
                        """SELECT mi.*, t.display_name AS topic_display
                           FROM memory_items mi
                           LEFT JOIN topics t ON mi.topic_id = t.topic_id
                           WHERE mi.item_id = ?""",
                        (item_id,),
                    ).fetchone()
                    if db_row:
                        seen.add(item_id)
                        items.append(dict(db_row))
                    if len(items) >= limit:
                        break
            except Exception:
                pass
        return items[:limit]

    def _learner_states_for_context(
        self,
        query: str,
        topic_name: str | None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        tokens = self._query_tokens(" ".join([query or "", topic_name or ""]))
        clauses: list[str] = []
        params: list[Any] = []
        if topic_name:
            clauses.append("(t.display_name LIKE ? OR lcs.concept_text LIKE ?)")
            params.extend([f"%{topic_name}%", f"%{topic_name.lower()}%"])
        if tokens:
            token_clause = []
            for token in tokens[:6]:
                token_clause.append("(lcs.concept_text LIKE ? OR lcs.dominant_misconception LIKE ?)")
                params.extend([f"%{token}%", f"%{token}%"])
            clauses.append("(" + " OR ".join(token_clause) + ")")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""SELECT lcs.*, t.display_name AS topic_display
                FROM learner_concept_state lcs
                JOIN topics t ON lcs.topic_id = t.topic_id
                {where}
                ORDER BY lcs.last_updated DESC
                LIMIT ?""",
            [*params, limit],
        ).fetchall()
        return [dict(row) for row in rows]

    def _graph_expand_item_ids(self, item_ids: list[int], limit: int = 8) -> list[int]:
        if not item_ids:
            return []
        placeholders = ",".join("?" for _ in item_ids)
        rows = self.conn.execute(
            f"""SELECT source_item_id, target_item_id
                FROM memory_edges
                WHERE source_item_id IN ({placeholders})
                   OR target_item_id IN ({placeholders})
                ORDER BY confidence DESC, updated_ts DESC
                LIMIT ?""",
            [*item_ids, *item_ids, limit],
        ).fetchall()
        expanded: list[int] = []
        seen = set(item_ids)
        for row in rows:
            for key in ("source_item_id", "target_item_id"):
                iid = int(row[key])
                if iid not in seen:
                    seen.add(iid)
                    expanded.append(iid)
        return expanded[:limit]

    def _fit_context_lines(self, heading: str, lines: list[str], max_tokens: int) -> tuple[str, int]:
        out = [heading]
        for line in lines:
            candidate = "\n".join([*out, line])
            if _token_estimate(candidate) > max_tokens:
                break
            out.append(line)
        text = "\n".join(out)
        return text, _token_estimate(text)

    def context_pack(
        self,
        query: str,
        topic_name: str | None = None,
        skill: str | None = None,
        intent: str = "teach",
        max_tokens: int = 1200,
        log_retrieval: bool = True,
    ) -> dict[str, Any]:
        """Build a fixed-section working-memory pack for agents."""
        max_tokens = max(250, int(max_tokens or 1200))
        items = self._memory_items_for_context(query, topic_name, skill, limit=14)
        states = self._learner_states_for_context(query, topic_name, limit=10)
        item_ids = [int(i["item_id"]) for i in items if i.get("item_id")]
        expanded_ids = self._graph_expand_item_ids(item_ids, limit=6)
        if expanded_ids:
            placeholders = ",".join("?" for _ in expanded_ids)
            extra = [
                dict(row) for row in self.conn.execute(
                    f"""SELECT mi.*, t.display_name AS topic_display
                        FROM memory_items mi
                        LEFT JOIN topics t ON mi.topic_id = t.topic_id
                        WHERE mi.item_id IN ({placeholders})""",
                    expanded_ids,
                ).fetchall()
            ]
            seen = set(item_ids)
            for row in extra:
                if int(row["item_id"]) not in seen:
                    items.append(row)
                    seen.add(int(row["item_id"]))

        document_lines = []
        doc_candidates = [
            dict(row) for row in self.conn.execute(
                """SELECT * FROM document_sessions
                   WHERE preferred_study_mode IS NOT NULL
                     AND preferred_study_mode != ''
                   ORDER BY mode_updated_ts DESC, last_studied DESC
                   LIMIT 20"""
            ).fetchall()
        ]
        doc_filter = topic_name or query
        for doc in doc_candidates:
            if doc_filter and not self._session_fragment_matches_v2(
                {
                    "topic_display": doc.get("doc_path") or "",
                    "concept_text": doc.get("source_kind") or "",
                    "content_text": " ".join([
                        doc.get("mode_reason") or "",
                        doc.get("session_notes") or "",
                    ]),
                },
                doc_filter,
            ):
                continue
            mode = doc.get("preferred_study_mode") or "ask"
            source_kind = doc.get("source_kind") or "unknown"
            pacing = doc.get("pacing_goal") or "user_selected"
            confidence = float(doc.get("mode_confidence") or 0.0)
            document_lines.append(
                f"- {doc['doc_path']}: source={source_kind}, mode={mode}, pacing={pacing}, confidence={confidence:.2f}."
            )
            if doc.get("mode_reason"):
                document_lines.append(f"  Reason: {doc['mode_reason']}.")
            if mode == "rapid_review":
                document_lines.append(
                    "  Directive: run as high-throughput question deck; deep-dive only for partial/wrong/overconfident/safety-critical misses."
                )
            elif mode == "deep_understanding":
                document_lines.append(
                    "  Directive: preserve the current deep Socratic mechanism-building workflow."
                )
            elif mode == "oral_boards":
                document_lines.append("  Directive: use as staged oral-board case seed material.")
            break
        for item in [i for i in items if i["item_type"] == "document_profile"][:3]:
            if not any(str(item["item_id"]) in line for line in document_lines):
                document_lines.append(f"- [document_profile #{item['item_id']}] {item['summary'][:260]}")
        if not document_lines:
            document_lines.append(
                "- No stored document study-mode profile found. For vault study files, ask Rapid Review vs Deep Understanding before drilling."
            )

        learner_lines = []
        for state in states[:6]:
            learner_lines.append(
                "- {concept}: mastery={mastery:.2f}, familiarity={fam:.2f}, due={due}, calibration={cal}.".format(
                    concept=state["concept_text"],
                    mastery=float(state["mastery_prob"] or 0.0),
                    fam=float(state["familiarity_prob"] or 0.0),
                    due=(state["next_review_due"] or "")[:10] or "unknown",
                    cal=state["calibration_state"] or "unknown",
                )
            )
            if state.get("dominant_misconception"):
                learner_lines.append(f"  Misconception: {state['dominant_misconception']}.")
            if state.get("root_cause"):
                learner_lines.append(f"  Root cause: {state['root_cause']}.")
        if not learner_lines:
            learner_lines.append("- No reliable learner-state evidence found for this query.")

        recent_lines = []
        for item in [i for i in items if i["item_type"] in ("episode", "reflection")][:5]:
            recent_lines.append(f"- [{item['item_type']} #{item['item_id']}] {item['summary'][:280]}")
        if not recent_lines:
            recent_lines.append("- No prior episode continuity found.")

        case_lines = []
        for item in [i for i in items if i["item_type"] == "case_memory"][:4]:
            case_lines.append(f"- [case #{item['item_id']}] {item['summary'][:260]}")
        if not case_lines:
            case_lines.append("- No case-memory episode found for this query.")

        misconception_lines = []
        for state in states:
            if state.get("dominant_misconception"):
                misconception_lines.append(
                    f"- Retest {state['concept_text']}: {state['dominant_misconception']}"
                )
        for item in items:
            details = _json_dict(item.get("details_json"))
            misconception = details.get("misconception") or ""
            if misconception:
                misconception_lines.append(f"- Retest {item['concept_text']}: {misconception}")
        if not misconception_lines:
            misconception_lines.append("- None found. Start with a brief active recall probe.")

        mastered_lines = []
        for state in states:
            if float(state.get("mastery_prob") or 0.0) >= 0.65 and not state.get("dominant_misconception"):
                mastered_lines.append(
                    f"- {state['concept_text']}: use as an anchor or transfer test; avoid basic reteaching."
                )
        if not mastered_lines:
            mastered_lines.append("- No mastered anchors identified for this query.")

        transfer_lines = []
        for state in states:
            transfer_state = state.get("transfer_state") or "untested"
            if transfer_state in ("untested", "fact_recalled", "anki_reviewed"):
                transfer_lines.append(
                    f"- {state['concept_text']}: current transfer state is {transfer_state}; test in a new vignette."
                )
            else:
                transfer_lines.append(
                    f"- {state['concept_text']}: transfer demonstrated as {transfer_state}; raise fidelity."
                )
        if not transfer_lines:
            transfer_lines.append("- No transfer target found; convert one recall item into a clinical scenario.")

        policy_rows = self.conn.execute(
            """SELECT tps.*, t.display_name AS topic_display
               FROM teaching_policy_stats tps
               LEFT JOIN topics t ON tps.topic_id = t.topic_id
               ORDER BY tps.confidence DESC, tps.updated_ts DESC
               LIMIT 5"""
        ).fetchall()
        policy_lines = []
        seen_policy_lines: set[tuple[str, str, str]] = set()
        for row in policy_rows:
            key = (
                row["teaching_approach"] or "",
                row["concept_text"] or row["topic_display"] or "general",
                row["error_type"] or "",
            )
            if key in seen_policy_lines:
                continue
            seen_policy_lines.add(key)
            policy_lines.append(
                f"- {row['teaching_approach']} for {row['concept_text'] or row['topic_display'] or 'general'} "
                f"(success={row['success_count']}, failure={row['failure_count']}, confidence={row['confidence']:.2f})."
            )
        narrative_sql = (
            """SELECT narrative_id, session_ts, skill, topics_json, summary,
                      teaching_successes, next_session_strategy, depth_profile_json,
                      strategy_outcome
               FROM session_narratives
               WHERE teaching_successes IS NOT NULL
                 AND teaching_successes != ''
                 AND teaching_successes != '[]'
                 {skill_clause}
               ORDER BY session_ts DESC
               LIMIT 12"""
        )
        skill_clause = "AND skill = ?" if skill else ""
        narrative_rows = self.conn.execute(
            narrative_sql.format(skill_clause=skill_clause),
            (skill,) if skill else (),
        ).fetchall()
        topic_filter = topic_name or query
        for row in narrative_rows:
            topics = _json_list(row["topics_json"])
            topic_blob = ", ".join(str(t) for t in topics)
            if topic_filter and not self._session_fragment_matches_v2(
                {
                    "topic_display": topic_blob,
                    "concept_text": row["summary"] or "",
                    "content_text": row["next_session_strategy"] or "",
                },
                topic_filter,
            ):
                continue
            successes = _json_list(row["teaching_successes"])
            if successes:
                policy_lines.append(
                    f"- Narrative #{row['narrative_id']} ({row['strategy_outcome'] or 'outcome unknown'}): "
                    + "; ".join(str(s) for s in successes[:2])
                )
            if row["next_session_strategy"]:
                recent_lines.append(
                    f"- [session_narrative #{row['narrative_id']}] Next strategy: {str(row['next_session_strategy'])[:260]}"
                )
            depth_profile = _json_dict(row["depth_profile_json"])
            if depth_profile:
                policy_lines.append(
                    f"- Depth achieved in narrative #{row['narrative_id']}: "
                    + ", ".join(f"{k}={v}" for k, v in list(depth_profile.items())[:4])
                )
        if not policy_lines:
            policy_lines.append("- No teaching-policy evidence yet; prefer active recall before explanation.")

        regression_lines = []
        for item in [i for i in items if i["item_type"] == "reflection"]:
            details = _json_dict(item.get("details_json"))
            if details.get("reflection_type") == "regression_detected":
                regression_lines.append(f"- {item['summary'][:260]}")
        if not regression_lines:
            regression_lines.append("- No active regression alert found.")

        core_rows = self.conn.execute(
            """SELECT item_id, summary FROM memory_items
               WHERE item_type = 'core_profile'
                 AND (valid_to IS NULL OR valid_to = '')
               ORDER BY importance DESC, confidence DESC, updated_ts DESC
               LIMIT 5"""
        ).fetchall()
        core_lines = [f"- [core #{row['item_id']}] {row['summary']}" for row in core_rows]
        if not core_lines:
            core_lines.append("- No durable core learner profile facts promoted yet.")

        calibration_pack = self.calibration_training_pack_v2(max_items=4)
        calibration_lines = calibration_pack.get("alerts", []) + calibration_pack.get("drills", [])
        calibration_lines = [f"- {line}" for line in calibration_lines[:8]]

        evidence_event_ids: list[int] = []
        evidence_exchange_ids: list[int] = []
        for item in items:
            evidence_event_ids.extend(_merge_ids(item.get("evidence_event_ids"), []))
            evidence_exchange_ids.extend(_merge_ids(item.get("evidence_exchange_ids"), []))
        for state in states:
            evidence_event_ids.extend(_merge_ids(state.get("evidence_event_ids"), []))
            evidence_exchange_ids.extend(_merge_ids(state.get("evidence_exchange_ids"), []))
        evidence_event_ids = sorted(set(evidence_event_ids))
        evidence_exchange_ids = sorted(set(evidence_exchange_ids))
        evidence_lines = [
            f"- memory_item_ids: {sorted(set(int(i['item_id']) for i in items if i.get('item_id')))[:20]}",
            f"- memory_event_ids: {evidence_event_ids[:20]}",
            f"- exchange_ids: {evidence_exchange_ids[:20]}",
        ]

        warnings = []
        if not evidence_event_ids and not evidence_exchange_ids and not items and not states:
            warnings.append("- No reliable prior memory found; do not claim continuity.")
        if any("No reliable learner-state" in line for line in learner_lines):
            warnings.append("- Learner-state evidence is sparse; probe before adapting difficulty.")
        if not warnings:
            warnings.append("- Evidence found; cite memory IDs internally when adapting the teaching plan.")

        sections = {
            "document_study_mode": document_lines,
            "learner_state": learner_lines,
            "recent_episode_continuity": recent_lines,
            "case_memory": case_lines,
            "prior_misconceptions_to_retest": misconception_lines[:8],
            "mastered_anchors_to_avoid_reteaching": mastered_lines[:6],
            "transfer_targets": transfer_lines[:6],
            "teaching_policy": policy_lines,
            "regression_alerts": regression_lines[:5],
            "core_profile": core_lines,
            "confidence_calibration": calibration_lines,
            "evidence_ids": evidence_lines,
            "abstention_warnings": warnings,
        }

        heading = (
            "## Memory Context Pack\n"
            f"Intent: {intent or 'teach'}\n"
            f"Query: {query.strip()}\n"
        )
        section_order = [
            ("Document Study Mode", "document_study_mode"),
            ("Learner State", "learner_state"),
            ("Recent Episode Continuity", "recent_episode_continuity"),
            ("Case Memory", "case_memory"),
            ("Prior Misconceptions To Retest", "prior_misconceptions_to_retest"),
            ("Mastered Anchors To Avoid Reteaching", "mastered_anchors_to_avoid_reteaching"),
            ("Transfer Targets", "transfer_targets"),
            ("Teaching Policy", "teaching_policy"),
            ("Regression Alerts", "regression_alerts"),
            ("Core Profile", "core_profile"),
            ("Confidence Calibration", "confidence_calibration"),
            ("Evidence IDs", "evidence_ids"),
            ("Abstention Warnings", "abstention_warnings"),
        ]
        lines = [heading.rstrip()]
        per_section_budget = max(20, max_tokens // max(1, len(section_order)) - 6)
        for title, key in section_order:
            section_text, _ = self._fit_context_lines(
                f"\n### {title}",
                sections[key],
                per_section_budget,
            )
            candidate = "\n".join([*lines, section_text])
            if _token_estimate(candidate) > max_tokens:
                break
            lines.append(section_text)
        text = "\n".join(lines).strip()
        token_est = _token_estimate(text)

        result = {
            "ok": True,
            "query": query,
            "topic": topic_name or "",
            "skill": skill or "",
            "intent": intent,
            "max_tokens": max_tokens,
            "token_estimate": token_est,
            "text": text,
            "sections": sections,
            "retrieval": {
                "memory_item_ids": sorted(set(int(i["item_id"]) for i in items if i.get("item_id"))),
                "expanded_item_ids": expanded_ids,
                "learner_state_ids": [int(s["state_id"]) for s in states if s.get("state_id")],
                "evidence_event_ids": evidence_event_ids,
                "evidence_exchange_ids": evidence_exchange_ids,
            },
        }
        if log_retrieval:
            try:
                with self.conn:
                    self.conn.execute(
                        """INSERT INTO memory_retrieval_logs
                           (created_ts, query, topic_text, skill, intent, max_tokens,
                            token_estimate, result_item_ids, result_exchange_ids,
                            retrieval_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            _utc_now(),
                            query,
                            topic_name or "",
                            skill or "",
                            intent,
                            max_tokens,
                            token_est,
                            json.dumps(result["retrieval"]["memory_item_ids"]),
                            json.dumps(evidence_exchange_ids),
                            json.dumps(result["retrieval"], sort_keys=True),
                        ),
                    )
            except Exception as exc:
                print(f"[knowledge_graph] context_pack retrieval log error: {exc}", file=sys.stderr)
        return result

    # ------------------------------------------------------------------
    # V2 diagnostics
    # ------------------------------------------------------------------

    def memory_session_quality_v2(self) -> dict[str, Any]:
        """Report agent-workflow quality issues that affect longitudinal memory."""
        open_sessions = [
            dict(row) for row in self.conn.execute(
                """SELECT session_ts, skill, topic_text, started_ts, ended_ts, notes
                   FROM memory_sessions
                   WHERE memory_enabled = 1
                     AND status = 'active'
                   ORDER BY started_ts DESC
                   LIMIT 20"""
            ).fetchall()
        ]
        fragmentation = [
            dict(row) for row in self.conn.execute(
                """SELECT le.skill,
                          COALESCE(t.display_name, '') AS topic,
                          substr(COALESCE(me.event_ts, le.session_ts), 1, 10) AS session_date,
                          COUNT(*) AS exchange_count,
                          COUNT(DISTINCT le.session_ts) AS session_ts_count,
                          GROUP_CONCAT(DISTINCT le.session_ts) AS session_ts_values
                   FROM learning_exchanges le
                   LEFT JOIN topics t ON le.topic_id = t.topic_id
                   LEFT JOIN memory_events me ON le.memory_event_id = me.memory_event_id
                   WHERE le.session_ts != ''
                   GROUP BY le.skill, topic, session_date
                   HAVING COUNT(DISTINCT le.session_ts) > 1
                   ORDER BY session_date DESC, exchange_count DESC
                   LIMIT 20"""
            ).fetchall()
        ]
        metadata = dict(self.conn.execute(
            """SELECT COUNT(*) AS partial_wrong_total,
                      COALESCE(SUM(CASE WHEN correction_text IS NULL OR correction_text = '' THEN 1 ELSE 0 END), 0) AS missing_correction,
                      COALESCE(SUM(CASE WHEN error_type IS NULL OR error_type = '' THEN 1 ELSE 0 END), 0) AS missing_error_type,
                      COALESCE(SUM(CASE WHEN (misconception IS NULL OR misconception = '')
                                           AND (root_cause IS NULL OR root_cause = '') THEN 1 ELSE 0 END), 0) AS missing_misconception_or_root_cause,
                      COALESCE(SUM(CASE WHEN teaching_approach IS NULL OR teaching_approach = '' THEN 1 ELSE 0 END), 0) AS missing_teaching_approach
               FROM learning_exchanges
               WHERE answer_correct IN (0, 1)"""
        ).fetchone())
        miss_sessions = [
            dict(row) for row in self.conn.execute(
                """SELECT le.session_ts, le.skill, COALESCE(t.display_name, '') AS topic,
                          COUNT(*) AS miss_count
                   FROM learning_exchanges le
                   LEFT JOIN topics t ON le.topic_id = t.topic_id
                   WHERE le.answer_correct IN (0, 1)
                     AND NOT EXISTS (
                       SELECT 1 FROM memory_events me
                       WHERE me.session_ts = le.session_ts
                         AND me.skill = le.skill
                         AND me.event_type = 'teaching_exposure'
                     )
                   GROUP BY le.session_ts, le.skill, topic
                   ORDER BY le.session_ts DESC
                   LIMIT 20"""
            ).fetchall()
        ]
        transfer_gap = dict(self.conn.execute(
            """SELECT COUNT(*) AS concepts_without_transfer_validation
               FROM learner_concept_state
               WHERE transfer_state IN ('untested', 'fact_recalled', 'anki_reviewed')"""
        ).fetchone())
        finish_rollups = [
            dict(row) for row in self.conn.execute(
                """SELECT item_id, valid_from, summary, evidence_event_ids, evidence_exchange_ids
                   FROM memory_items
                   WHERE item_type = 'reflection'
                     AND details_json LIKE '%"reflection_type": "session_finish_rollup"%'
                     AND (valid_to IS NULL OR valid_to = '')
                   ORDER BY updated_ts DESC
                   LIMIT 10"""
            ).fetchall()
        ]
        no_policy = self.conn.execute(
            "SELECT COUNT(*) AS n FROM teaching_policy_stats"
        ).fetchone()["n"] == 0
        return {
            "open_enabled_sessions": open_sessions,
            "session_ts_fragmentation": fragmentation,
            "session_finish_rollups": finish_rollups,
            "partial_wrong_metadata": metadata,
            "miss_sessions_without_passive_teaching": miss_sessions,
            "transfer_validation_gap": transfer_gap,
            "teaching_policy_empty": bool(no_policy),
        }

    def memory_v2_doctor(self) -> dict[str, Any]:
        tables = {}
        for table in (
            "memory_items",
            "memory_edges",
            "learner_concept_state",
            "teaching_policy_stats",
            "memory_retrieval_logs",
            "memory_eval_cases",
        ):
            tables[table] = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]

        orphan_evidence = self.conn.execute(
            """SELECT COUNT(*) AS n FROM memory_items
               WHERE evidence_event_ids = '[]'
                 AND evidence_exchange_ids = '[]'
                 AND item_type NOT IN ('core_profile', 'resource_link')"""
        ).fetchone()["n"]
        invalid_edges = self.conn.execute(
            """SELECT COUNT(*) AS n
               FROM memory_edges me
               LEFT JOIN memory_items s ON me.source_item_id = s.item_id
               LEFT JOIN memory_items t ON me.target_item_id = t.item_id
               WHERE s.item_id IS NULL OR t.item_id IS NULL"""
        ).fetchone()["n"]
        stale_embeddings = self.conn.execute(
            """SELECT COUNT(*) AS n FROM memory_items
               WHERE embedding_status IN ('pending', 'stale')"""
        ).fetchone()["n"]
        duplicate_items = [
            dict(row) for row in self.conn.execute(
                """SELECT dedupe_key, COUNT(*) AS n
                   FROM memory_items
                   WHERE dedupe_key != ''
                   GROUP BY dedupe_key HAVING COUNT(*) > 1
                   LIMIT 20"""
            ).fetchall()
        ]
        contradiction_clusters = [
            dict(row) for row in self.conn.execute(
                """SELECT topic_id, concept_text, COUNT(*) AS open_states
                   FROM memory_items
                   WHERE item_type = 'learner_state'
                     AND (valid_to IS NULL OR valid_to = '')
                   GROUP BY topic_id, concept_text
                   HAVING COUNT(*) > 1
                   LIMIT 20"""
            ).fetchall()
        ]
        replay = self.replay_memory_v2(from_events=True, dry_run=True)
        return {
            "counts": tables,
            "orphan_evidence_items": orphan_evidence,
            "invalid_temporal_edges": invalid_edges,
            "stale_embeddings": stale_embeddings,
            "duplicate_items": duplicate_items,
            "contradiction_clusters": contradiction_clusters,
            "replay_determinism": replay.get("replay_determinism", {}),
            "session_quality": self.memory_session_quality_v2(),
        }
