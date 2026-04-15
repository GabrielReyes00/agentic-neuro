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
