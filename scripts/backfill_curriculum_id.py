#!/usr/bin/env python3
"""One-time migration: backfill curriculum_id on topics table.

Matches orphan topics (curriculum_id IS NULL) to curriculum_topics using
a multi-strategy approach:

  Strategy 1 — Normalized exact: canonical_name with underscores→spaces
               matches curriculum topic_name with underscores→spaces.
  Strategy 2 — Display containment: one display_name is a substantial
               substring of the other (>= 60% of the shorter string's tokens).
  Strategy 3 — Token overlap with domain alignment: Jaccard similarity >= 0.35
               on tokenized display names, boosted when category→domain match.

Usage:
    python3 scripts/backfill_curriculum_id.py              # dry-run
    python3 scripts/backfill_curriculum_id.py --apply      # apply changes
    python3 scripts/backfill_curriculum_id.py --verbose     # show all candidates
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge_graph.db"

# ── Category → Domain mapping ────────────────────────────────────────────────

CATEGORY_TO_DOMAIN: dict[str, str] = {
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
    "medical_knowledge_—_neuroanatomy_and_neuroimaging": "Medical Knowledge — Neuroanatomy and Neuroimaging",
    "medical_knowledge_—_neurosciences,_neuropathology,_and_neurology": "Medical Knowledge — Neurosciences, Neuropathology, and Neurology",
    "Anatomy": "Anatomy",
}

# Minimum token count for a topic to be matchable (skip noise like "contraindications")
MIN_TOKENS = 2

# Jaccard threshold for Strategy 3
JACCARD_THRESHOLD = 0.40

# Containment threshold for Strategy 2 (fraction of shorter's tokens in longer)
CONTAINMENT_THRESHOLD = 0.70

# Minimum overlap tokens required for containment (prevents false matches on short names)
MIN_OVERLAP_TOKENS = 2

# Medically distinct terms — if topic has one and curriculum has the other, reject
CONFLICTING_PAIRS: list[tuple[set[str], set[str]]] = [
    ({"abscess"}, {"hematoma"}),
    ({"deformity", "scoliosis"}, {"dysraphism", "tethered"}),
    ({"revision", "complication"}, {"dystonia"}),
    ({"peritumoral", "edema", "dexamethasone"}, {"prolactinoma", "prolactin"}),
    ({"electrode", "dbs", "lead"}, {"biopsy"}),
    ({"lumbar"}, {"parafascicular", "intracerebral"}),
]


STOPWORDS = {"and", "the", "of", "in", "for", "a", "an", "vs", "with", "from", "to", "is", "or", "by"}

# Generic medical terms that alone should not drive a match
GENERIC_TERMS = {
    "management", "treatment", "diagnosis", "technique", "approach",
    "classification", "evaluation", "assessment", "observation",
    "decision", "making", "principles", "overview", "review",
    "complications", "outcomes", "indications", "surgical", "medical",
}


def tokenize(s: str) -> set[str]:
    """Extract lowercase alphanumeric tokens, dropping stopwords."""
    tokens = set(re.findall(r"[a-z0-9]+", s.lower()))
    return tokens - STOPWORDS


def normalize(name: str) -> str:
    """Normalize a name for comparison: underscores→spaces, lowercase, strip."""
    return re.sub(r"[_\-]+", " ", name).strip().lower()


def domain_matches(category: str, domain: str) -> bool:
    """Check if a topic category maps to a curriculum domain."""
    if not category:
        return False
    mapped = CATEGORY_TO_DOMAIN.get(category, "")
    return mapped == domain


def has_conflict(t_tokens: set[str], c_tokens: set[str]) -> bool:
    """Return True if the token sets contain a known conflicting pair."""
    all_tokens = t_tokens | c_tokens
    for set_a, set_b in CONFLICTING_PAIRS:
        if (t_tokens & set_a and c_tokens & set_b) or (t_tokens & set_b and c_tokens & set_a):
            # Only conflict if the distinguishing terms are NOT shared
            if not (t_tokens & set_a & c_tokens):
                return True
    return False


def compute_matches(conn: sqlite3.Connection) -> list[dict]:
    """Find the best curriculum match for each orphan topic.

    Returns a list of dicts with topic_id, display_name, curriculum_id,
    curriculum_display, strategy, and score.
    """
    # Load orphan topics
    orphans = conn.execute(
        """SELECT topic_id, canonical_name, display_name, category
           FROM topics WHERE curriculum_id IS NULL"""
    ).fetchall()

    # Load curriculum
    curriculum = conn.execute(
        """SELECT curriculum_id, topic_name, display_name, domain
           FROM curriculum_topics"""
    ).fetchall()

    # Build lookup structures
    # Strategy 1: normalized topic_name → curriculum_id
    norm_lookup: dict[str, dict] = {}
    for c in curriculum:
        key = normalize(c["topic_name"])
        norm_lookup[key] = dict(c)

    # Tokenized curriculum for strategies 2 and 3
    curriculum_tokenized: list[tuple[dict, set[str]]] = []
    for c in curriculum:
        tokens = tokenize(c["display_name"])
        curriculum_tokenized.append((dict(c), tokens))

    matches: list[dict] = []

    for orphan in orphans:
        o = dict(orphan)
        t_tokens = tokenize(o["display_name"])

        # Skip noise topics with too few meaningful tokens
        if len(t_tokens) < MIN_TOKENS:
            continue

        best: dict | None = None

        # Strategy 1: Normalized exact match on canonical_name → topic_name
        o_norm = normalize(o["canonical_name"])
        if o_norm in norm_lookup:
            c = norm_lookup[o_norm]
            best = {
                "topic_id": o["topic_id"],
                "display_name": o["display_name"],
                "category": o["category"],
                "curriculum_id": c["curriculum_id"],
                "curriculum_display": c["display_name"],
                "curriculum_domain": c["domain"],
                "strategy": "exact_normalized",
                "score": 1.0,
            }

        if not best:
            # Strategy 2 & 3: Token-based matching
            candidates: list[dict] = []

            for c, c_tokens in curriculum_tokenized:
                if not c_tokens:
                    continue

                overlap = len(t_tokens & c_tokens)
                union = len(t_tokens | c_tokens)
                jaccard = overlap / union if union else 0.0

                # Strategy 2: Containment check
                shorter_len = min(len(t_tokens), len(c_tokens))
                containment = overlap / shorter_len if shorter_len else 0.0

                # Reject known conflicting term pairs
                if has_conflict(t_tokens, c_tokens):
                    continue

                # Reject if all overlapping tokens are generic medical terms
                specific_overlap = (t_tokens & c_tokens) - GENERIC_TERMS
                if not specific_overlap:
                    continue

                # Domain alignment bonus
                domain_bonus = 0.1 if domain_matches(o["category"], c["domain"]) else 0.0

                # Require higher thresholds when domains don't align
                no_domain = domain_bonus == 0.0

                # Pick the better of jaccard and containment-based score
                if containment >= CONTAINMENT_THRESHOLD and overlap >= MIN_OVERLAP_TOKENS:
                    strategy = "containment"
                    score = containment + domain_bonus
                elif jaccard >= JACCARD_THRESHOLD and overlap >= MIN_OVERLAP_TOKENS:
                    # Without domain alignment, require higher jaccard to avoid
                    # false matches on generic terms
                    if no_domain and jaccard < 0.45:
                        continue
                    strategy = "jaccard"
                    score = jaccard + domain_bonus
                else:
                    continue

                candidates.append({
                    "topic_id": o["topic_id"],
                    "display_name": o["display_name"],
                    "category": o["category"],
                    "curriculum_id": c["curriculum_id"],
                    "curriculum_display": c["display_name"],
                    "curriculum_domain": c["domain"],
                    "strategy": strategy,
                    "score": score,
                })

            if candidates:
                # Pick highest score; break ties by curriculum_id (deterministic)
                candidates.sort(key=lambda x: (-x["score"], x["curriculum_id"]))
                best = candidates[0]

        if best:
            matches.append(best)

    return matches


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill curriculum_id on topics table")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument("--verbose", action="store_true", help="Show all proposed matches")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Pre-state
    null_before = conn.execute("SELECT COUNT(*) FROM topics WHERE curriculum_id IS NULL").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    print(f"Pre-migration: {null_before}/{total} topics have NULL curriculum_id")

    matches = compute_matches(conn)

    # Group by strategy
    by_strategy: dict[str, list[dict]] = {}
    for m in matches:
        by_strategy.setdefault(m["strategy"], []).append(m)

    print(f"\nProposed matches: {len(matches)}")
    for strat, items in sorted(by_strategy.items()):
        print(f"  {strat}: {len(items)}")

    if args.verbose:
        print("\n--- All proposed matches ---")
        for m in sorted(matches, key=lambda x: (-x["score"], x["display_name"])):
            domain_ok = "+" if domain_matches(m["category"], m["curriculum_domain"]) else " "
            print(
                f"  [{m['strategy']:18s}] score={m['score']:.3f} {domain_ok} "
                f"\"{m['display_name']}\" -> \"{m['curriculum_display']}\""
            )

    if args.apply:
        print("\nApplying changes...")
        updated = 0
        with conn:
            for m in matches:
                conn.execute(
                    "UPDATE topics SET curriculum_id = ? WHERE topic_id = ? AND curriculum_id IS NULL",
                    (m["curriculum_id"], m["topic_id"]),
                )
                updated += 1
        print(f"Updated {updated} topics")

        null_after = conn.execute("SELECT COUNT(*) FROM topics WHERE curriculum_id IS NULL").fetchone()[0]
        print(f"Post-migration: {null_after}/{total} topics have NULL curriculum_id")

        # Validate: check that matchable topics are now linked
        matchable_remaining = conn.execute(
            """SELECT COUNT(*) FROM topics
               WHERE curriculum_id IS NULL
               AND LENGTH(display_name) > 20"""
        ).fetchone()[0]
        print(f"Remaining NULL with display_name > 20 chars: {matchable_remaining}")
    else:
        print("\nDry-run mode. Use --apply to execute migration.")

    conn.close()


if __name__ == "__main__":
    main()
