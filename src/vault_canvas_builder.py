#!/usr/bin/env python3
"""ACGME milestone canvas builder.

Generates one Obsidian `.canvas` file per ACGME milestone under
`<vault>/ACGME Canvases/`, laying out every curriculum concept as a file-node
colored by mastery bucket, with prerequisite/extension edges drawn from the
concept_relationships table.

The Canvas file format is a plain JSON document recognized by Obsidian:
    {
      "nodes": [ {id, type, x, y, width, height, file|text, color}, ... ],
      "edges": [ {id, fromNode, toNode, label}, ... ]
    }

Colors (Obsidian built-in): "1"=red "2"=orange "3"=yellow "4"=green
"5"=cyan "6"=purple. We map mastery to red/orange/yellow/green buckets.

Layout: concepts sorted by priority then confidence, laid out in a grid —
`GRID_COLS` nodes per row. A header text-card sits above the grid with
milestone progress. One canvas per distinct acgme_milestone in
curriculum_topics (milestones with 0 topics are skipped).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vault_kg_sync import stub_filename, load_curriculum_index, safe_write_vault_file


# ═══════════════════════════════════════════════════════════════════════════
# Layout constants
# ═══════════════════════════════════════════════════════════════════════════

# Nodes are sized to comfortably show two-line concept titles in Obsidian's
# default canvas font. Width tuned for ~50-character titles.
GRID_COLS = 4
NODE_WIDTH = 460
NODE_HEIGHT = 150
X_GAP = 80
Y_GAP = 90

# Vertical separation between priority bands (core / important / advanced).
BAND_GAP = 200
# Per-band header card sits to the LEFT of its row of nodes.
BAND_HEADER_WIDTH = 240
BAND_HEADER_HEIGHT = 120
BAND_HEADER_GAP = 60

HEADER_HEIGHT = 200
HEADER_WIDTH = 1100
HEADER_X = 0
HEADER_Y = -HEADER_HEIGHT - 120   # hover above the grid

GRID_ORIGIN_X = 0
GRID_ORIGIN_Y = 0

PRIORITY_BANDS = (
    (1, "Core",      "Foundation — required PGY-1 mastery"),
    (2, "Important", "High-yield secondary topics"),
    (3, "Advanced",  "Subspecialty / late-residency depth"),
)


# ═══════════════════════════════════════════════════════════════════════════
# Color mapping
# ═══════════════════════════════════════════════════════════════════════════


def _mastery_color(confidence: float, encounters: int, depth: int) -> str:
    """Map mastery state to an Obsidian canvas color key.

        "1" red    — not studied
        "2" orange — studied but shallow (conf < 0.2)
        "3" yellow — mechanistic (conf 0.2–0.5)
        "4" green  — at or near mastery (conf >= 0.5 and depth >= 2)
    """
    if encounters <= 0:
        return "1"
    if confidence >= 0.5 and depth >= 2:
        return "4"
    if confidence >= 0.2:
        return "3"
    return "2"


def _bucket_label(color: str) -> str:
    return {
        "1": "not studied",
        "2": "surface",
        "3": "mechanistic",
        "4": "mastered",
    }.get(color, "unknown")


# ═══════════════════════════════════════════════════════════════════════════
# Data collection
# ═══════════════════════════════════════════════════════════════════════════


def _fetch_milestones(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Return `{milestone_key: {name, domain, topics: [...]}}` for every
    non-empty acgme_milestone in curriculum_topics. Each topics entry has
    display_name, filename, confidence, depth, encounters, priority."""
    rows = conn.execute(
        """SELECT ct.curriculum_id, ct.acgme_milestone, ct.domain,
                  ct.display_name, ct.topic_name, ct.priority, ct.pgy_target,
                  MAX(COALESCE(t.confidence, 0.0))    AS confidence,
                  MAX(COALESCE(t.encounter_count, 0)) AS encounter_count,
                  MAX(COALESCE(t.depth, 0))           AS depth,
                  MAX(t.last_seen)                    AS last_seen
           FROM curriculum_topics ct
           LEFT JOIN topics t ON t.curriculum_id = ct.curriculum_id
           GROUP BY ct.curriculum_id
           ORDER BY ct.acgme_milestone, ct.priority, confidence DESC"""
    ).fetchall()

    milestones: dict[str, dict[str, Any]] = {}
    for row in rows:
        ms = (row["acgme_milestone"] or "").strip() or "Unclassified"
        if ms not in milestones:
            milestones[ms] = {
                "milestone": ms,
                "domain": row["domain"] or "",
                "topics": [],
            }
        display = row["display_name"] or row["topic_name"] or ""
        conf = float(row["confidence"] or 0.0)
        depth = int(row["depth"] or 0)
        enc = int(row["encounter_count"] or 0)
        milestones[ms]["topics"].append({
            "curriculum_id": int(row["curriculum_id"]),
            "display_name": display,
            "filename": stub_filename(display),
            "confidence": conf,
            "depth": depth,
            "encounters": enc,
            "priority": int(row["priority"] or 2),
            "pgy_target": int(row["pgy_target"] or 1),
            "topic_name": row["topic_name"] or "",
            "domain": row["domain"] or "",
            "color": _mastery_color(conf, enc, depth),
        })
    return milestones


def _fetch_concept_relationships(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT concept_a, topic_a, concept_b, topic_b, relationship, strength
           FROM concept_relationships
           WHERE relationship IN ('prerequisite_of', 'extends', 'confusable_with', 'differentiates_from')"""
    ).fetchall()
    return [dict(r) for r in rows]


_STOPWORDS = {
    "the", "and", "for", "with", "into", "from", "that", "this", "after",
    "before", "during", "vs", "of", "in", "on", "at", "to", "or", "a", "an",
    "by", "is", "are", "as", "be", "its", "their", "between", "without",
    "post", "pre",
}


def _tokens(text: str) -> set[str]:
    """Lowercase alphabetic tokens of length >=3, minus stopwords."""
    import re as _re
    raw = _re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", (text or "").lower())
    return {t for t in raw if t not in _STOPWORDS}


def _concept_head(concept_text: str) -> str:
    """Strip parenthetical clarifier so 'CSW (sodium loss…)' → 'CSW'."""
    if not concept_text:
        return ""
    idx = concept_text.find("(")
    head = concept_text[:idx] if idx >= 0 else concept_text
    return head.strip()


def build_concept_to_curriculum_candidates(
    conn: sqlite3.Connection,
    relationship_concepts: list[str],
    min_overlap: int = 1,
    top_k: int = 4,
) -> dict[str, list[int]]:
    """Token-overlap matcher that returns RANKED candidate curriculum_ids per
    concept (not just the best). Pair-level disambiguation in _build_edges
    uses the candidate list to break ties when both endpoints of a relationship
    would otherwise resolve to the same topic.

    Score is precision-weighted: shared_tokens^2 / topic_token_count, so a
    crisp 2-token topic overlapping with both of the concept's tokens beats a
    sprawling 8-token topic that happens to share the same 2 tokens. This
    correctly disambiguates 'epidural hematoma ct appearance' from
    'subdural hematoma ct appearance'.
    """
    curriculum_tokens: list[tuple[int, set[str]]] = []
    for row in conn.execute(
        "SELECT curriculum_id, display_name, topic_name FROM curriculum_topics"
    ):
        toks = _tokens(row["display_name"]) | _tokens((row["topic_name"] or "").replace("_", " "))
        curriculum_tokens.append((row["curriculum_id"], toks))

    out: dict[str, list[int]] = {}
    for concept in relationship_concepts:
        if not concept:
            continue
        head_tokens = _tokens(_concept_head(concept))
        if not head_tokens:
            continue
        scored: list[tuple[float, int]] = []
        for cid, toks in curriculum_tokens:
            if not toks:
                continue
            shared = len(head_tokens & toks)
            if shared < min_overlap:
                continue
            # Precision-weighted score, with raw shared as tie-breaker.
            precision = (shared * shared) / len(toks)
            scored.append((precision, cid))
        if not scored:
            continue
        scored.sort(key=lambda x: -x[0])
        out[concept.lower()] = [cid for _, cid in scored[:top_k]]
    return out


def build_concept_to_curriculum_map(
    conn: sqlite3.Connection,
    relationship_concepts: list[str],
    min_overlap: int = 1,
) -> dict[str, int]:
    """Backwards-compatible single-best wrapper around the candidate matcher."""
    candidates = build_concept_to_curriculum_candidates(
        conn, relationship_concepts, min_overlap=min_overlap, top_k=1
    )
    return {k: v[0] for k, v in candidates.items() if v}


# ═══════════════════════════════════════════════════════════════════════════
# Canvas node/edge builders
# ═══════════════════════════════════════════════════════════════════════════


def _header_node(milestone: str, topics: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(topics)
    touched = sum(1 for t in topics if t["encounters"] > 0)
    mastered = sum(1 for t in topics if t["color"] == "4")
    shallow = sum(1 for t in topics if t["color"] in ("2", "3"))
    not_started = sum(1 for t in topics if t["color"] == "1")
    coverage = round(100.0 * touched / total, 1) if total else 0.0
    domain = topics[0]["domain"] if topics else ""

    text = (
        f"# {milestone} — {domain}\n\n"
        f"**Coverage**: {touched}/{total} topics touched ({coverage}%) | "
        f"**Mastered**: {mastered} | **Surface**: {shallow} | **Not started**: {not_started}\n\n"
        "**How to read this canvas:**\n"
        "- Each card is a curriculum concept (click to open the Concept file).\n"
        "- Cards cluster into priority bands: Core (top), Important (middle), Advanced (bottom).\n"
        "- Card color = mastery: red (not studied), orange (surface), yellow (mechanistic), green (mastered).\n"
        "- Arrows = knowledge-graph edges (prerequisite, extends, confusable).\n"
        "- Use this view to spot blocking gaps (red Core cards) and find next study targets.\n\n"
        f"_Regenerated {datetime.now(timezone.utc).date().isoformat()}_"
    )
    return {
        "id": f"header_{milestone}",
        "type": "text",
        "x": HEADER_X,
        "y": HEADER_Y,
        "width": HEADER_WIDTH,
        "height": HEADER_HEIGHT,
        "text": text,
        "color": "6",  # purple
    }


def _topic_nodes(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cluster layout: one horizontal band per priority tier (Core / Important
    / Advanced). Inside each band, topics flow left-to-right sorted by
    confidence (highest first) then alphabetical, wrapping into multiple rows
    if a band has more than GRID_COLS topics. Each band gets a labeled header
    card to its left so the topology is immediately legible.
    """
    nodes: list[dict[str, Any]] = []
    # Bucket topics by priority.
    by_band: dict[int, list[dict[str, Any]]] = {p: [] for p, _, _ in PRIORITY_BANDS}
    for t in topics:
        band = t["priority"] if t["priority"] in by_band else 2
        by_band[band].append(t)
    for band_topics in by_band.values():
        band_topics.sort(key=lambda t: (-t["confidence"], t["display_name"]))

    band_origin_y = GRID_ORIGIN_Y
    grid_x_origin = GRID_ORIGIN_X + BAND_HEADER_WIDTH + BAND_HEADER_GAP

    for band_priority, band_label, band_desc in PRIORITY_BANDS:
        band_topics = by_band.get(band_priority, [])
        if not band_topics:
            continue
        rows_in_band = (len(band_topics) + GRID_COLS - 1) // GRID_COLS
        band_height = rows_in_band * NODE_HEIGHT + (rows_in_band - 1) * Y_GAP

        # Band header card on the left.
        touched = sum(1 for t in band_topics if t["encounters"] > 0)
        mastered = sum(1 for t in band_topics if t["color"] == "4")
        header_y = band_origin_y + max(0, (band_height - BAND_HEADER_HEIGHT) // 2)
        nodes.append({
            "id": f"band_{band_priority}",
            "type": "text",
            "x": GRID_ORIGIN_X,
            "y": header_y,
            "width": BAND_HEADER_WIDTH,
            "height": BAND_HEADER_HEIGHT,
            "text": (
                f"## {band_label}\n\n"
                f"{band_desc}\n\n"
                f"**{touched}/{len(band_topics)}** touched | **{mastered}** mastered"
            ),
            "color": "6",  # purple
        })

        # Topic nodes in this band.
        for idx, t in enumerate(band_topics):
            row = idx // GRID_COLS
            col = idx % GRID_COLS
            x = grid_x_origin + col * (NODE_WIDTH + X_GAP)
            y = band_origin_y + row * (NODE_HEIGHT + Y_GAP)
            stem = t["filename"].replace(".md", "")
            node_id = f"n_{t['topic_name'] or stem}".replace(" ", "_")
            nodes.append({
                "id": node_id,
                "type": "file",
                "file": f"Concepts/{t['filename']}",
                "x": x,
                "y": y,
                "width": NODE_WIDTH,
                "height": NODE_HEIGHT,
                "color": t["color"],
            })
            t["_node_id"] = node_id

        band_origin_y += band_height + BAND_GAP

    return nodes


def _resolve_pair(
    cands_a: list[int],
    cands_b: list[int],
) -> tuple[int | None, int | None]:
    """Pick the best (cid_a, cid_b) pair such that cid_a != cid_b. Tries the
    cartesian product in rank order; falls back to top-1 each if no distinct
    pair is reachable."""
    if not cands_a or not cands_b:
        return (cands_a[0] if cands_a else None,
                cands_b[0] if cands_b else None)
    for i, a in enumerate(cands_a):
        for j, b in enumerate(cands_b):
            if a != b:
                return (a, b)
    return (cands_a[0], cands_b[0])


def _build_edges(
    topics: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    concept_candidates: dict[str, list[int]],
) -> list[dict[str, Any]]:
    """Draw edges only between topics present on this canvas. Uses ranked
    candidate cids per concept so that when both endpoints would resolve to
    the same curriculum topic, we can fall back to the next-best alternative."""
    cid_to_node: dict[int, str] = {}
    for t in topics:
        cid = t.get("curriculum_id")
        if cid is not None:
            cid_to_node[int(cid)] = t["_node_id"]

    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for idx, r in enumerate(relationships):
        ca = (r.get("concept_a") or "").lower()
        cb = (r.get("concept_b") or "").lower()
        cands_a = concept_candidates.get(ca, [])
        cands_b = concept_candidates.get(cb, [])
        # Filter to candidates that actually exist on this canvas, then pick
        # a distinct pair.
        on_canvas_a = [c for c in cands_a if c in cid_to_node]
        on_canvas_b = [c for c in cands_b if c in cid_to_node]
        cid_a, cid_b = _resolve_pair(on_canvas_a, on_canvas_b)
        if cid_a is None or cid_b is None:
            continue
        na = cid_to_node.get(cid_a)
        nb = cid_to_node.get(cid_b)
        if not na or not nb or na == nb:
            continue
        rel = r["relationship"]
        label = {
            "prerequisite_of": "prereq",
            "extends": "extends",
            "confusable_with": "confusable",
            "differentiates_from": "differs",
        }.get(rel, rel)
        key = (na, nb, rel)
        if key in seen:
            continue
        seen.add(key)
        edges.append({
            "id": f"e_{idx}",
            "fromNode": na,
            "toNode": nb,
            "label": label,
        })
    return edges


# ═══════════════════════════════════════════════════════════════════════════
# Canvas file builder
# ═══════════════════════════════════════════════════════════════════════════


def _canvas_filename(milestone: str) -> str:
    safe = milestone.replace("/", "-").replace(":", "-").strip()
    return f"ACGME {safe}.canvas"


def build_canvas_for_milestone(
    milestone_entry: dict[str, Any],
    relationships: list[dict[str, Any]],
    concept_candidates: dict[str, list[int]],
) -> dict[str, Any]:
    topics = milestone_entry["topics"]
    nodes: list[dict[str, Any]] = []
    nodes.append(_header_node(milestone_entry["milestone"], topics))
    nodes.extend(_topic_nodes(topics))
    edges = _build_edges(topics, relationships, concept_candidates)
    return {"nodes": nodes, "edges": edges}


def sync_canvases(
    kg,
    vault_root: Path,
    canvases_dir_name: str = "ACGME Canvases",
) -> dict[str, Any]:
    """Regenerate every ACGME milestone canvas. Returns metrics dict."""
    canvases_dir = vault_root / canvases_dir_name
    canvases_dir.mkdir(parents=True, exist_ok=True)

    milestones = _fetch_milestones(kg.conn)
    relationships = _fetch_concept_relationships(kg.conn)
    # Build a single concept→curriculum_id map covering every concept that
    # participates in a relationship. Reused across all milestones.
    rel_concepts: list[str] = []
    for r in relationships:
        if r.get("concept_a"):
            rel_concepts.append(r["concept_a"])
        if r.get("concept_b"):
            rel_concepts.append(r["concept_b"])
    concept_candidates = build_concept_to_curriculum_candidates(
        kg.conn, rel_concepts, min_overlap=1, top_k=4
    )

    written = 0
    total_nodes = 0
    total_edges = 0
    written_files: list[str] = []
    for milestone, entry in milestones.items():
        if not entry["topics"]:
            continue
        canvas = build_canvas_for_milestone(entry, relationships, concept_candidates)
        path = canvases_dir / _canvas_filename(milestone)
        path.write_text(json.dumps(canvas, indent=2), encoding="utf-8")
        written += 1
        total_nodes += len(canvas["nodes"])
        total_edges += len(canvas["edges"])
        written_files.append(str(path.relative_to(vault_root)))

    # Write an INDEX.md inside the canvases folder listing each canvas file.
    _write_canvas_index(canvases_dir, milestones)

    return {
        "canvases_written": written,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "files": written_files,
    }


def _write_canvas_index(canvases_dir: Path, milestones: dict[str, dict[str, Any]]) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    lines: list[str] = []
    lines.append("**ACGME Milestone Canvases** — one canvas per ACGME milestone. Each node is a curriculum concept file colored by mastery bucket. Topics cluster into Core / Important / Advanced priority bands. Prerequisite and confusable edges are drawn from the knowledge graph.")
    lines.append("")
    lines.append("| Milestone | Domain | Topics | Touched | Mastered | Canvas |")
    lines.append("|-----------|--------|--------|---------|----------|--------|")
    for milestone, entry in sorted(milestones.items()):
        topics = entry["topics"]
        if not topics:
            continue
        total = len(topics)
        touched = sum(1 for t in topics if t["encounters"] > 0)
        mastered = sum(1 for t in topics if t["color"] == "4")
        canvas_name = _canvas_filename(milestone).replace(".canvas", "")
        link = f"[[ACGME Canvases/{canvas_name}|{milestone}]]"
        lines.append(f"| {milestone} | {entry['domain']} | {total} | {touched} | {mastered} | {link} |")
    lines.append("")
    lines.append("---")
    lines.append(f"updated: {today}")
    lines.append("tags:")
    lines.append("  - type/reference")
    lines.append("  - source/agent")
    lines.append("---")
    safe_write_vault_file(canvases_dir / "INDEX.md", "\n".join(lines) + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# CLI entrypoint (for standalone manual runs)
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from knowledge_graph import KnowledgeGraph

    parser = argparse.ArgumentParser(description="Regenerate ACGME milestone canvases.")
    parser.add_argument(
        "--vault-root",
        default="/Users/gabrielreyes/Documents/Obsidian/agentic-neuro",
        help="Vault root path",
    )
    args = parser.parse_args()

    kg = KnowledgeGraph()
    result = sync_canvases(kg, Path(args.vault_root))
    print(json.dumps(result, indent=2))
