#!/usr/bin/env python3
"""Shared constants for the learner knowledge graph."""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SESSIONS_DIR = DATA_DIR / "Sessions"

ABBREVIATION_MAP: dict[str, str] = {
    "sah": "subarachnoid hemorrhage",
    "tbi": "traumatic brain injury",
    "evd": "external ventricular drain",
    "avm": "arteriovenous malformation",
    "dbs": "deep brain stimulation",
    "icp": "intracranial pressure",
    "csf": "cerebrospinal fluid",
    "vp": "ventriculoperitoneal",
    "srs": "stereotactic radiosurgery",
    "mca": "middle cerebral artery",
    "aca": "anterior cerebral artery",
    "pca": "posterior cerebral artery",
    "pica": "posterior inferior cerebellar artery",
    "gbm": "glioblastoma",
    "idh": "isocitrate dehydrogenase",
    "acdf": "anterior cervical discectomy and fusion",
    "sci": "spinal cord injury",
}

CANONICAL_TEACHING_APPROACHES: tuple[str, ...] = (
    "active_recall_probe",
    "forced_discrimination",
    "contrastive_imaging_axis",
    "pathophys_derivation",
    "management_algorithm",
    "operative_sequence",
    "clinical_vignette_transfer",
    "threshold_drill",
    "complication_rescue",
    "oral_board_defense",
    "rapid_review_jeopardy",
)

TEACHING_APPROACH_ALIASES: dict[str, str] = {
    "recall": "active_recall_probe",
    "socratic_probe": "active_recall_probe",
    "forced_disambiguation": "forced_discrimination",
    "contrastive_vignette": "forced_discrimination",
    "imaging_axis": "contrastive_imaging_axis",
    "imaging_discrimination": "contrastive_imaging_axis",
    "mechanism_first": "pathophys_derivation",
    "mechanism_to_management": "pathophys_derivation",
    "algorithm": "management_algorithm",
    "sequence": "management_algorithm",
    "operative_walkthrough": "operative_sequence",
    "clinical_transfer": "clinical_vignette_transfer",
    "near_transfer": "clinical_vignette_transfer",
    "numbers_drill": "threshold_drill",
    "threshold_probe": "threshold_drill",
    "rescue_algorithm": "complication_rescue",
    "case_defense": "oral_board_defense",
    "mock_oral": "oral_board_defense",
    "rapid_review": "rapid_review_jeopardy",
    "rapid_review_escalated_deep_dive": "pathophys_derivation",
    "deep_understanding_progressive_reveal": "active_recall_probe",
}
