#!/usr/bin/env python3
"""Topic hygiene migration: deduplication + category backfill + normalization.

Three phases:
  Phase 1 — Merge duplicate topic pairs (re-point signals/mastery, delete orphan)
  Phase 2 — Backfill category for uncategorized topics (curriculum inheritance + keyword)
  Phase 3 — Normalize all categories to canonical ACGME domain names

Usage:
    python3 scripts/topic_hygiene.py                  # dry-run (all phases)
    python3 scripts/topic_hygiene.py --apply           # apply changes
    python3 scripts/topic_hygiene.py --phase dedup     # dry-run dedup only
    python3 scripts/topic_hygiene.py --phase category  # dry-run category only
    python3 scripts/topic_hygiene.py --verbose          # show all details
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge_graph.db"

# ── Phase 1: Duplicate Merge Definitions ─────────────────────────────────────
# (canonical_id, orphan_id, reason)
# For multi-way merges, list each orphan separately pointing to the same canonical.

MERGE_PAIRS: list[tuple[int, int, str]] = [
    # Exact duplicates
    (312, 239, "exact duplicate: ICP Physiology (Monro-Kellie Doctrine)"),
    (107, 348, "exact duplicate: Parasagittal and Falcine Meningioma"),
    # Same curriculum_id duplicates
    (92, 359, "same cid=308: WHO CNS/Brain Tumor Classification (2021)"),
    (152, 376, "same cid=327: Responsive Neurostimulation (RNS)"),
    (141, 403, "same cid=360: Peripheral Nerve Sheath Tumors"),
    (380, 156, "same cid=332: DBS for Parkinson Disease"),
    (167, 364, "same cid=314: Stereotactic Radiosurgery Principles"),
    (462, 200, "same cid=427: Hydrocephalus Pathophysiology"),
    (128, 361, "same cid=310: Epidermoid and Dermoid Cysts"),
    (414, 54, "same cid=371: Lumbar Laminectomy and Decompression"),
    (7, 438, "same cid=400: Anterior Circulation Aneurysm"),
    (106, 347, "same cid=290: Convexity Meningioma"),
    (434, 57, "same cid=396: Spondylolisthesis/Lumbar Spondylolisthesis"),
    (25, 452, "same cid=414: Dural AVF Classification"),
    (52, 418, "same cid=375: Posterior Cervical Laminectomy"),
    (40, 456, "same cid=421: Circle of Willis Anatomy"),
    # Semantic duplicates (no shared cid but clearly same concept)
    (585, 589, "semantic dup: endothelin receptor antagonists (pathways vs mechanisms)"),
    (14, 576, "semantic dup: Cerebral Vasospasm Pathophysiology"),
    (292, 291, "semantic dup: Levophed norepinephrine ordering (word reorder)"),
    (667, 700, "semantic dup: Brainstem and Cranial Nerve Anatomy"),
    # Judgment calls (approved by user)
    (658, 662, "J1: Cavernous malformation MRI description"),
    (580, 588, "J2: molecular mechanisms vs pathophysiology of vasospasm"),
    (14, 578, "J5: management of cerebral vasospasm subsumes into #14"),
    (289, 577, "J4: BP management / management after SAH — same cid=399"),
    # J3: 3-way cluster — cerebral autoregulation (all -> cid=530)
    (276, 243, "J3: CBF Autoregulation mismapped to CPP, should be cid=530"),
    (276, 737, "J3: cerebral autoregulation -> CBF Regulation"),
]


# ── Phase 2: Category Keyword Rules ──────────────────────────────────────────
# Order matters: first match wins. More specific patterns before general ones.

CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Vascular Neurological Surgery", [
        "aneurysm", "acha", "anterior choroidal artery", "vasospasm", "sah",
        "subarachnoid hemorrhage", "clipping", "coiling", "flow diversion",
        "circle of willis", "endothelin", "nimodipine", "dci",
        "pipeline embolization", "pcomm", "pcoma", "pcom", "acomm", "acom",
        "cavernous malformation", "avm", "arteriovenous", "dural av fistula",
        "endovascular", "saccular", "berry", "charcot-bouchard",
        "microsurgical clipping", "induced hypertension",
    ]),
    ("Traumatic Brain Injury", [
        "tbi", "traumatic brain", "epidural hematoma", "subdural hematoma",
        "ich blood pressure", "decompressive craniectomy", "icp management",
        "cpp management", "secondary injury", "enrich", "mistie", "stich",
        "temporal lobe ich", "temporal ich", "hemorrhage management",
    ]),
    ("Critical Care", [
        "icp", "cpp", "intracranial pressure", "neurocritical",
        "antihypertensive pharmacology", "pres", "hypertensive encephalopathy",
        "autonomic dysreflexia", "map augmentation", "sci map",
        "perfusion pressure breakthrough", "bp management",
        "cushing reflex", "osmotherapy", "mannitol",
    ]),
    ("Brain Tumor", [
        "meningioma", "glioma", "glioblastoma", "temozolomide", "tumor",
        "who cns", "craniotomy", "awake craniotomy", "cortical stimulation",
        "diffusion tensor", "corticospinal tract", "cushing disease",
        "pituitary adenoma", "acth syndrome", "dermoid", "epidermoid",
        "molecular markers predict treatment",
    ]),
    ("Medical Knowledge \u2014 Neuroanatomy and Neuroimaging", [
        "internal capsule", "plic", "alic", "basal ganglia", "thalamus",
        "thalamic", "hippocampus", "papez circuit", "fornix", "cingulum",
        "commissure", "limbic", "homunculus", "somatotopic", "brainstem",
        "cranial nerve", "neuraxis", "central sulcus", "sylvian",
        "ventricle", "septum pellucidum", "lamina terminalis",
        "corpus callosum", "lateral surface", "ventral surface",
        "cns orientation", "striatum", "putamen", "globus pallidus",
        "caudate", "lentiform", "optic tract", "optic pathway",
        "geniculate", "frontopontine", "capsulotomy", "thalamostriate",
        "foramen of monro", "genu", "corticospinal", "corticobulbar",
        "aphasia", "asymbolia", "pseudobulbar", "bulbar",
        "retina", "diencephalon", "aca supplies", "atr content",
        "mtt amnesia", "thalamic radiations", "topography of the internal",
        "forniceal anatomy", "cingulate", "amygdala", "parafascicular",
        "thalamoperforating",
    ]),
    ("Spinal Neurological Surgery", [
        "cervical", "lumbar", "thoracic", "spine", "spinal",
        "spondylolisthesis", "laminectomy", "disc herniation",
        "syringomyelia", "chiari", "thoracic outlet", "scalenectomy",
        "duraplasty",
    ]),
    ("Pediatric Neurological Surgery", [
        "hydrocephalus", "vp shunt", "evd", "csf shunting",
        "brain development", "evans index", "ventriculomegaly",
        "transependymal", "overdrainage",
    ]),
    ("Surgical Treatment of Epilepsy and Movement Disorders", [
        "dbs", "deep brain stimulation", "capsulotomy", "atn",
        "responsive neurostimulation",
    ]),
    ("Pain and Peripheral Nerve Disorders", [
        "peripheral nerve", "thoracic outlet syndrome",
    ]),
]

# ── Phase 3: Category Normalization Map ──────────────────────────────────────

NORMALIZE_CATEGORY: dict[str, str] = {
    "vascular": "Vascular Neurological Surgery",
    "vascular_neurological_surgery": "Vascular Neurological Surgery",
    "spine": "Spinal Neurological Surgery",
    "spinal_neurological_surgery": "Spinal Neurological Surgery",
    "tumor_(neuro-oncology)": "Brain Tumor",
    "brain_tumor": "Brain Tumor",
    "trauma": "Traumatic Brain Injury",
    "traumatic_brain_injury": "Traumatic Brain Injury",
    "critical_care": "Critical Care",
    "critical_care_and_general_neurosurgery": "Critical Care",
    "pediatric": "Pediatric Neurological Surgery",
    "pediatric_neurological_surgery": "Pediatric Neurological Surgery",
    "functional_and_stereotactic": "Surgical Treatment of Epilepsy and Movement Disorders",
    "surgical_treatment_of_epilepsy_and_movement_disorders": "Surgical Treatment of Epilepsy and Movement Disorders",
    "pain_and_peripheral_nerve_disorders": "Pain and Peripheral Nerve Disorders",
    "medical_knowledge_\u2014_neuroanatomy_and_neuroimaging": "Medical Knowledge \u2014 Neuroanatomy and Neuroimaging",
    "medical_knowledge_\u2014_neurosciences,_neuropathology,_and_neurology": "Medical Knowledge \u2014 Neurosciences, Neuropathology, and Neurology",
    "Anatomy": "Anatomy",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def infer_category(display_name: str) -> str | None:
    """Return inferred category from keyword matching, or None."""
    name_lower = display_name.lower()
    for category, keywords in CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in name_lower:
                return category
    return None


# ── Phase Runners ────────────────────────────────────────────────────────────

def run_dedup(conn: sqlite3.Connection, apply: bool, verbose: bool) -> dict:
    """Phase 1: merge duplicate topic pairs."""
    stats = {"pairs_processed": 0, "signals_moved": 0, "mastery_moved": 0,
             "topics_deleted": 0, "skipped_missing": 0}

    for canonical_id, orphan_id, reason in MERGE_PAIRS:
        # Verify both exist
        canonical = conn.execute(
            "SELECT topic_id, display_name, confidence, depth, encounter_count, curriculum_id "
            "FROM topics WHERE topic_id = ?", (canonical_id,)
        ).fetchone()
        orphan = conn.execute(
            "SELECT topic_id, display_name, confidence, depth, encounter_count, curriculum_id "
            "FROM topics WHERE topic_id = ?", (orphan_id,)
        ).fetchone()

        if not canonical or not orphan:
            if verbose:
                missing = "canonical" if not canonical else "orphan"
                print(f"  SKIP ({missing} missing): {reason}")
            stats["skipped_missing"] += 1
            continue

        # Count what we'll move
        sig_count = conn.execute(
            "SELECT COUNT(*) FROM signal_events WHERE topic_id = ?", (orphan_id,)
        ).fetchone()[0]
        mas_count = conn.execute(
            "SELECT COUNT(*) FROM concept_mastery WHERE topic_id = ?", (orphan_id,)
        ).fetchone()[0]

        # Compute merged values
        merged_depth = max(canonical["depth"], orphan["depth"])
        merged_conf = max(canonical["confidence"], orphan["confidence"])
        merged_encounters = canonical["encounter_count"] + orphan["encounter_count"]
        # Prefer canonical's curriculum_id, fall back to orphan's
        merged_cid = canonical["curriculum_id"] or orphan["curriculum_id"]

        if verbose or not apply:
            print(f"  {'MERGE' if apply else 'WOULD MERGE'}: {reason}")
            print(f"    canonical={canonical_id} \"{canonical['display_name']}\" "
                  f"(depth={canonical['depth']}, conf={canonical['confidence']:.4f}, "
                  f"enc={canonical['encounter_count']}, cid={canonical['curriculum_id']})")
            print(f"    orphan={orphan_id} \"{orphan['display_name']}\" "
                  f"(depth={orphan['depth']}, conf={orphan['confidence']:.4f}, "
                  f"enc={orphan['encounter_count']}, cid={orphan['curriculum_id']})")
            print(f"    -> signals: {sig_count}, mastery: {mas_count}")
            print(f"    -> merged: depth={merged_depth}, conf={merged_conf:.4f}, "
                  f"enc={merged_encounters}, cid={merged_cid}")

        if apply:
            # Re-point signal_events (handle unique constraint conflicts)
            conn.execute(
                "UPDATE signal_events SET topic_id = ? WHERE topic_id = ?",
                (canonical_id, orphan_id),
            )
            # Re-point concept_mastery (may have duplicates on concept_text)
            # For conflicts: keep the one with more times_confirmed
            existing_concepts = {
                r[0] for r in conn.execute(
                    "SELECT LOWER(concept_text) FROM concept_mastery WHERE topic_id = ?",
                    (canonical_id,),
                )
            }
            orphan_mastery = conn.execute(
                "SELECT * FROM concept_mastery WHERE topic_id = ?", (orphan_id,)
            ).fetchall()
            for row in orphan_mastery:
                if row["concept_text"].lower() in existing_concepts:
                    # Duplicate concept — delete the orphan's copy
                    conn.execute(
                        "DELETE FROM concept_mastery WHERE concept_id = ?",
                        (row["concept_id"],),
                    )
                else:
                    conn.execute(
                        "UPDATE concept_mastery SET topic_id = ? WHERE concept_id = ?",
                        (canonical_id, row["concept_id"]),
                    )
            # Update canonical topic stats
            conn.execute(
                "UPDATE topics SET depth = ?, confidence = ?, encounter_count = ?, "
                "curriculum_id = COALESCE(curriculum_id, ?) WHERE topic_id = ?",
                (merged_depth, merged_conf, merged_encounters, merged_cid, canonical_id),
            )
            # Delete orphan
            conn.execute("DELETE FROM topics WHERE topic_id = ?", (orphan_id,))

            stats["signals_moved"] += sig_count
            stats["mastery_moved"] += mas_count
            stats["topics_deleted"] += 1

        stats["pairs_processed"] += 1

    return stats


def run_category_backfill(conn: sqlite3.Connection, apply: bool, verbose: bool) -> dict:
    """Phase 2: assign categories to uncategorized topics."""
    stats = {"from_curriculum": 0, "from_keyword": 0, "still_uncategorized": 0}

    uncategorized = conn.execute(
        "SELECT topic_id, display_name, curriculum_id FROM topics "
        "WHERE category IS NULL OR category = '' ORDER BY topic_id"
    ).fetchall()

    for row in uncategorized:
        tid = row["topic_id"]
        name = row["display_name"]
        cid = row["curriculum_id"]
        new_cat = None
        source = None

        # Strategy 1: inherit from curriculum
        if cid:
            cur = conn.execute(
                "SELECT domain FROM curriculum_topics WHERE curriculum_id = ?", (cid,)
            ).fetchone()
            if cur:
                new_cat = cur["domain"]
                source = "curriculum"

        # Strategy 2: keyword inference
        if not new_cat:
            new_cat = infer_category(name)
            if new_cat:
                source = "keyword"

        if new_cat:
            if verbose or not apply:
                print(f"  {'SET' if apply else 'WOULD SET'} [{source}] "
                      f"\"{name}\" -> {new_cat}")
            if apply:
                conn.execute(
                    "UPDATE topics SET category = ? WHERE topic_id = ?",
                    (new_cat, tid),
                )
            stats[f"from_{source}"] += 1
        else:
            if verbose:
                print(f"  NO MATCH: \"{name}\"")
            stats["still_uncategorized"] += 1

    return stats


def run_normalize(conn: sqlite3.Connection, apply: bool, verbose: bool) -> dict:
    """Phase 3: normalize all categories to canonical domain names."""
    stats = {"normalized": 0, "already_canonical": 0}

    categories = conn.execute(
        "SELECT DISTINCT category FROM topics WHERE category IS NOT NULL AND category != ''"
    ).fetchall()

    for row in categories:
        old_cat = row["category"]
        new_cat = NORMALIZE_CATEGORY.get(old_cat)
        if new_cat and new_cat != old_cat:
            count = conn.execute(
                "SELECT COUNT(*) FROM topics WHERE category = ?", (old_cat,)
            ).fetchone()[0]
            if verbose or not apply:
                print(f"  {'RENAME' if apply else 'WOULD RENAME'} "
                      f"\"{old_cat}\" -> \"{new_cat}\" ({count} topics)")
            if apply:
                conn.execute(
                    "UPDATE topics SET category = ? WHERE category = ?",
                    (new_cat, old_cat),
                )
            stats["normalized"] += count
        elif new_cat == old_cat:
            stats["already_canonical"] += conn.execute(
                "SELECT COUNT(*) FROM topics WHERE category = ?", (old_cat,)
            ).fetchone()[0]
        else:
            # Category not in map — might be newly assigned canonical name
            count = conn.execute(
                "SELECT COUNT(*) FROM topics WHERE category = ?", (old_cat,)
            ).fetchone()[0]
            stats["already_canonical"] += count
            if verbose:
                print(f"  KEEP (already canonical): \"{old_cat}\" ({count} topics)")

    return stats


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Topic hygiene migration")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument("--verbose", action="store_true", help="Show all details")
    parser.add_argument("--phase", choices=["dedup", "category", "normalize", "all"],
                        default="all", help="Run specific phase (default: all)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== TOPIC HYGIENE MIGRATION ({mode}) ===\n")

    # Backup before apply
    if args.apply:
        backup = DB_PATH.with_suffix(".db.pre_hygiene_backup")
        shutil.copy2(DB_PATH, backup)
        print(f"Backup: {backup}\n")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")

    # Pre-state
    pre_topics = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    pre_uncat = conn.execute(
        "SELECT COUNT(*) FROM topics WHERE category IS NULL OR category = ''"
    ).fetchone()[0]
    pre_cats = conn.execute(
        "SELECT COUNT(DISTINCT category) FROM topics WHERE category IS NOT NULL AND category != ''"
    ).fetchone()[0]

    print(f"Pre-state: {pre_topics} topics, {pre_uncat} uncategorized, {pre_cats} distinct categories\n")

    # Phase 1: Dedup
    if args.phase in ("dedup", "all"):
        print("--- Phase 1: Duplicate Merging ---")
        dedup_stats = run_dedup(conn, args.apply, args.verbose)
        print(f"\n  Pairs processed: {dedup_stats['pairs_processed']}")
        print(f"  Topics deleted: {dedup_stats['topics_deleted']}")
        print(f"  Signals moved: {dedup_stats['signals_moved']}")
        print(f"  Mastery moved: {dedup_stats['mastery_moved']}")
        print(f"  Skipped (missing): {dedup_stats['skipped_missing']}\n")

    # Phase 2: Category backfill
    if args.phase in ("category", "all"):
        print("--- Phase 2: Category Backfill ---")
        cat_stats = run_category_backfill(conn, args.apply, args.verbose)
        print(f"\n  From curriculum: {cat_stats['from_curriculum']}")
        print(f"  From keyword: {cat_stats['from_keyword']}")
        print(f"  Still uncategorized: {cat_stats['still_uncategorized']}\n")

    # Phase 3: Normalize
    if args.phase in ("normalize", "all"):
        print("--- Phase 3: Category Normalization ---")
        norm_stats = run_normalize(conn, args.apply, args.verbose)
        print(f"\n  Topics normalized: {norm_stats['normalized']}")
        print(f"  Already canonical: {norm_stats['already_canonical']}\n")

    if args.apply:
        conn.commit()

    # Post-state
    post_topics = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    post_uncat = conn.execute(
        "SELECT COUNT(*) FROM topics WHERE category IS NULL OR category = ''"
    ).fetchone()[0]
    post_cats = conn.execute(
        "SELECT COUNT(DISTINCT category) FROM topics WHERE category IS NOT NULL AND category != ''"
    ).fetchone()[0]

    # Exact duplicates check
    exact_dupes = conn.execute(
        "SELECT COUNT(*) FROM (SELECT LOWER(display_name), COUNT(*) as cnt "
        "FROM topics GROUP BY LOWER(display_name) HAVING cnt > 1)"
    ).fetchone()[0]

    print("--- Post-state ---")
    print(f"  Topics: {pre_topics} -> {post_topics} (delta: {post_topics - pre_topics})")
    print(f"  Uncategorized: {pre_uncat} -> {post_uncat}")
    print(f"  Distinct categories: {pre_cats} -> {post_cats}")
    print(f"  Exact duplicates remaining: {exact_dupes}")

    if not args.apply:
        print(f"\n  Category distribution (would be):")
    else:
        print(f"\n  Category distribution:")
    for row in conn.execute(
        "SELECT COALESCE(NULLIF(category, ''), '(uncategorised)') as cat, COUNT(*) as cnt "
        "FROM topics GROUP BY cat ORDER BY cnt DESC"
    ):
        print(f"    {row['cat']}: {row['cnt']}")

    conn.close()
    print(f"\n{'CHANGES APPLIED' if args.apply else 'DRY-RUN COMPLETE (use --apply to execute)'}")


if __name__ == "__main__":
    main()
