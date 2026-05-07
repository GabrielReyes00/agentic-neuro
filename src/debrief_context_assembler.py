#!/usr/bin/env python3
"""Deterministic context assembler for the /debrief skill.

This script performs NO LLM calls. It gathers retrieval-layer context that
the debrief command (Gemini CLI or Claude skill) will reason over:

  - Knowledge-graph learner context for the target pathology
  - Blocking prerequisite gaps
  - Unknown-unknowns (adjacent curriculum blind spots)
  - Vault hits across Reports / Study Material / Operative Guides / Concepts /
    Review Sessions / existing Debriefs (Jaccard over filename tokens + YAML list fields)
  - Merge-target detection: the most similar existing debrief note, if any
  - Per-scaffold RAG-needed flags (intern-essential sections)

The output JSON is the deterministic substrate. All prose generation happens
afterwards in the LLM skill.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
try:
    from knowledge_graph import KnowledgeGraph
except ImportError:
    KnowledgeGraph = None


DEFAULT_VAULT_ROOT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
DEBRIEFS_DIRNAME = "Debriefs"

# Scaffold slots the debrief always tries to fill. These mirror the
# "intern-essential" sections a chief would cover in a tutoring pass.
SCAFFOLD_SLOTS: tuple[str, ...] = (
    "pathology_oneliner",
    "mechanism",
    "imaging",
    "labs",
    "consults",
    "preop_course",
    "intraop_concepts",
    "postop_course",
    "red_flags",
    "intern_priorities",
)

# Vault folders scanned for contextual hits. Order matters only for output stability.
_VAULT_FOLDERS: tuple[tuple[str, str], ...] = (
    ("reports", "Reports"),
    ("study_material", "Study Material"),
    ("operative_guides", "Operative Guides"),
    ("concepts", "Concepts"),
    ("review_sessions", "Review Sessions"),
    ("debriefs", DEBRIEFS_DIRNAME),
)

# YAML list-valued fields we treat as additional retrieval signal.
_INDEX_LIST_FIELDS: tuple[str, ...] = ("key_terms", "aliases", "tags")

_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "of", "and", "or", "for", "in", "on", "to", "with",
    "is", "are", "was", "were", "be", "been", "by", "at", "from", "as",
    "patient", "patients", "new", "case", "cases", "evaluation", "consult",
    "management", "workup", "work", "up", "review", "session",
})

# Scoring thresholds (caller can override via CLI for ablation).
DEFAULT_HIT_SIMILARITY = 0.15
STRONG_VAULT_SIMILARITY = 0.30
DEFAULT_MERGE_SIMILARITY = 0.45


# ── Tokenization and similarity ──────────────────────────────────────────────


def tokenize(text: str) -> set[str]:
    """Lowercase, strip stopwords, and return a token set for Jaccard similarity."""
    if not text:
        return set()
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── YAML frontmatter extraction (top-or-bottom) ──────────────────────────────


_YAML_BLOCK_RE = re.compile(r"^---\s*$(.*?)^---\s*$", re.MULTILINE | re.DOTALL)


def _extract_yaml_list_terms(md_path: Path) -> list[str]:
    """Return all tokens from list-valued YAML fields we recognize.

    Tolerant of both top and bottom YAML blocks (the project standard is bottom).
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    terms: list[str] = []
    for block in _YAML_BLOCK_RE.findall(text):
        try:
            parsed = yaml.safe_load(block) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(parsed, dict):
            continue
        for field in _INDEX_LIST_FIELDS:
            value = parsed.get(field)
            if isinstance(value, list):
                terms.extend(str(v) for v in value if v is not None)
            elif isinstance(value, str):
                terms.append(value)
    return terms


def _file_tokens(md_path: Path) -> set[str]:
    """Combine filename tokens with YAML list tokens for retrieval matching."""
    title_tokens = tokenize(md_path.stem)
    for term in _extract_yaml_list_terms(md_path):
        title_tokens |= tokenize(term)
    return title_tokens


# ── Vault scanning ───────────────────────────────────────────────────────────


def scan_vault(
    vault_root: Path,
    query_tokens: set[str],
    min_similarity: float = DEFAULT_HIT_SIMILARITY,
    per_folder_limit: int = 8,
) -> dict[str, list[dict]]:
    """Return vault hits grouped by folder, sorted by similarity descending."""
    hits: dict[str, list[dict]] = {key: [] for key, _ in _VAULT_FOLDERS}
    for key, folder in _VAULT_FOLDERS:
        dirpath = vault_root / folder
        if not dirpath.exists() or not dirpath.is_dir():
            continue
        for md in sorted(dirpath.glob("*.md")):
            if md.name == "INDEX.md":
                continue
            sim = jaccard(query_tokens, _file_tokens(md))
            if sim >= min_similarity:
                hits[key].append({
                    "path": str(md.relative_to(vault_root)),
                    "title": md.stem,
                    "similarity": round(sim, 3),
                    "wikilink": f"[[{folder}/{md.stem}|{md.stem}]]",
                })
        hits[key].sort(key=lambda x: -x["similarity"])
        hits[key] = hits[key][:per_folder_limit]
    return hits


def find_merge_target(
    vault_root: Path,
    query_tokens: set[str],
    merge_threshold: float = DEFAULT_MERGE_SIMILARITY,
) -> dict | None:
    """Return the most similar existing debrief file above threshold, else None."""
    debriefs_dir = vault_root / DEBRIEFS_DIRNAME
    if not debriefs_dir.exists():
        return None
    best: dict | None = None
    for md in sorted(debriefs_dir.glob("*.md")):
        if md.name == "INDEX.md":
            continue
        sim = jaccard(query_tokens, _file_tokens(md))
        if sim >= merge_threshold and (best is None or sim > best["similarity"]):
            best = {
                "path": str(md.relative_to(vault_root)),
                "title": md.stem,
                "similarity": round(sim, 3),
            }
    return best


# ── Scaffold RAG-gating ──────────────────────────────────────────────────────


def derive_scaffold_flags(
    kg_context: dict,
    vault_hits: dict[str, list[dict]],
) -> dict[str, dict]:
    """For each scaffold slot, decide whether RAG is likely needed.

    RAG is suppressed when there is any studied KG coverage (depth >= 2) or
    when any Report / Study Material / Concept / Operative Guide matches at
    STRONG_VAULT_SIMILARITY or above. Intraop concepts additionally trust
    the presence of any matching Operative Guide.
    """
    topics = kg_context.get("topics", []) if isinstance(kg_context, dict) else []
    has_kg_coverage = any(
        (t.get("status") == "known") and (t.get("depth") or 0) >= 2
        for t in topics
    )
    strong_vault = any(
        h["similarity"] >= STRONG_VAULT_SIMILARITY
        for key in ("reports", "study_material", "concepts", "operative_guides")
        for h in vault_hits.get(key, [])
    )
    operative_guide_found = bool(vault_hits.get("operative_guides"))

    scaffold: dict[str, dict] = {}
    for slot in SCAFFOLD_SLOTS:
        rag_needed = not (has_kg_coverage or strong_vault)
        if slot == "intraop_concepts" and operative_guide_found:
            rag_needed = False
        scaffold[slot] = {
            "rag_needed": rag_needed,
            "has_kg_coverage": has_kg_coverage,
            "has_vault_support": strong_vault,
        }
    return scaffold


# ── Top-level orchestration ──────────────────────────────────────────────────


def assemble_context(
    pathology: str,
    user_context: str = "",
    vault_root: Path = DEFAULT_VAULT_ROOT,
    db_path: Path | None = None,
    merge_threshold: float = DEFAULT_MERGE_SIMILARITY,
    min_hit_similarity: float = DEFAULT_HIT_SIMILARITY,
) -> dict[str, Any]:
    """Build the deterministic context bundle for a /debrief session."""
    if not pathology or not pathology.strip():
        raise ValueError("pathology is required")

    query_text = f"{pathology} {user_context}".strip()
    query_tokens = tokenize(query_text)

    kg_context: dict = {"topics": []}
    blocking_gaps: list = []
    unknown_unknowns: list = []
    if KnowledgeGraph is not None:
        kg_path = Path(db_path) if db_path else (DATA_DIR / "knowledge_graph.db")
        if kg_path.exists() and kg_path.stat().st_size > 0:
            kg = KnowledgeGraph(kg_path)
            try:
                try:
                    kg_context = kg.learner_context(pathology)
                except Exception as exc:  # noqa: BLE001
                    kg_context = {"error": str(exc), "topics": []}
                try:
                    blocking_gaps = kg.get_blocking_gaps(pathology)
                except Exception as exc:  # noqa: BLE001
                    blocking_gaps = []
                try:
                    unknown_unknowns = kg.detect_unknown_unknowns(pathology, n=5)
                except Exception as exc:  # noqa: BLE001
                    unknown_unknowns = []
            finally:
                kg.close()

    vault_hits = scan_vault(vault_root, query_tokens, min_similarity=min_hit_similarity)
    merge_target = find_merge_target(vault_root, query_tokens, merge_threshold)
    scaffold = derive_scaffold_flags(kg_context, vault_hits)
    rag_needed_slots = sorted(slot for slot, meta in scaffold.items() if meta["rag_needed"])

    return {
        "pathology": pathology,
        "user_context": user_context,
        "query_tokens": sorted(query_tokens),
        "kg_context": kg_context,
        "blocking_gaps": blocking_gaps,
        "unknown_unknowns": unknown_unknowns,
        "vault_hits": vault_hits,
        "merge_target": merge_target,
        "scaffold_slots": scaffold,
        "rag_needed_slots": rag_needed_slots,
        "rag_required": bool(rag_needed_slots),
        "merge_threshold": merge_threshold,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble deterministic context for a /debrief session (no LLM).",
    )
    # Accept pathology as either a positional arg OR --pathology flag so the LLM
    # cannot accidentally omit the flag and get a "required" error.
    parser.add_argument("pathology_pos", nargs="?", default=None,
                        metavar="PATHOLOGY",
                        help="Pathology (positional shorthand — prefer --pathology for clarity)")
    parser.add_argument("--pathology", default=None,
                        help="Pathology or clinical scenario (e.g. 'L4-L5 TLIF for spondylolisthesis')")
    parser.add_argument("--context", default="",
                        help="Freeform dump of what the user already knows or is uncertain about")
    parser.add_argument("--vault-root", default=str(DEFAULT_VAULT_ROOT),
                        help="Override vault root (testing)")
    parser.add_argument("--db", default=None,
                        help="Override KG database path (testing)")
    parser.add_argument("--output", default=None,
                        help="Write JSON bundle to this path")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress stdout. Requires --output. Errors still go to stderr.")
    parser.add_argument("--merge-threshold", type=float, default=DEFAULT_MERGE_SIMILARITY,
                        help=f"Jaccard merge threshold (default {DEFAULT_MERGE_SIMILARITY})")
    parser.add_argument("--min-hit-similarity", type=float, default=DEFAULT_HIT_SIMILARITY,
                        help=f"Minimum vault-hit similarity (default {DEFAULT_HIT_SIMILARITY})")
    args = parser.parse_args(argv)

    # Resolve pathology from flag or positional; flag wins.
    pathology = args.pathology or args.pathology_pos
    if not pathology:
        parser.error("pathology is required (use --pathology or pass it as a positional argument)")

    if args.quiet and not args.output:
        parser.error("--quiet requires --output so the bundle is still accessible")

    bundle = assemble_context(
        pathology=pathology,
        user_context=args.context,
        vault_root=Path(args.vault_root),
        db_path=Path(args.db) if args.db else None,
        merge_threshold=args.merge_threshold,
        min_hit_similarity=args.min_hit_similarity,
    )
    out = json.dumps(bundle, indent=2, default=str)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out, encoding="utf-8")
    if not args.quiet:
        print(out)
    return 0


if __name__ == "__main__":
    from _env_guard import check_environment
    check_environment("debrief_context_assembler.py")
    sys.exit(main())
