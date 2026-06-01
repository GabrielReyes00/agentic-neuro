"""Reviewed clinical reference graph for bounded context-aware memory retrieval."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALLOWED_NODE_TYPES = frozenset({
    "anatomy", "complication", "context", "physiology", "procedure", "threshold",
})
ALLOWED_RELATION_TYPES = frozenset({
    "anatomy_of", "complication_of", "management_depends_on", "mimics",
    "prerequisite", "relevant_context",
})
GENERIC_TOKENS = frozenset({
    "acute", "anterior", "care", "classification", "critical", "management",
    "medical", "posterior", "surgical",
})
STOPWORDS = frozenset({
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "is", "of",
    "on", "or", "the", "to", "with",
})
BROAD_BINDING_TOKENS = GENERIC_TOKENS | frozenset({
    "anatomy", "cord", "fracture", "injury", "spinal", "threshold", "thresholds", "trauma",
})

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reference_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    node_type TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    provenance TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reference_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_node_id INTEGER NOT NULL,
    target_node_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0.5 CHECK(weight >= 0 AND weight <= 1),
    required_context_any_json TEXT NOT NULL DEFAULT '[]',
    provenance TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK(source_node_id != target_node_id),
    UNIQUE(source_node_id, target_node_id, relation_type),
    FOREIGN KEY(source_node_id) REFERENCES reference_nodes(id),
    FOREIGN KEY(target_node_id) REFERENCES reference_nodes(id)
);
CREATE INDEX IF NOT EXISTS idx_reference_edges_source ON reference_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_reference_edges_target ON reference_edges(target_node_id);
"""


def ensure_reference_graph_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def _normalize(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^\w\s\-/]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in _normalize(text).replace("-", " ").replace("/", " ").split()
        if len(token) > 1 and token not in STOPWORDS
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validated_payload(conn: sqlite3.Connection, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _require(isinstance(payload, dict), "reference graph payload must be an object")
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    _require(isinstance(nodes, list), "nodes must be a list")
    _require(isinstance(edges, list), "edges must be a list")
    keys: set[str] = {
        row["node_key"] for row in conn.execute("SELECT node_key FROM reference_nodes").fetchall()
    }
    payload_keys: set[str] = set()
    for idx, node in enumerate(nodes):
        _require(isinstance(node, dict), f"nodes[{idx}] must be an object")
        for field in ("node_key", "label", "node_type", "provenance", "reviewed_at"):
            _require(isinstance(node.get(field), str) and node[field].strip(), f"nodes[{idx}].{field} must be a non-empty string")
        _require(node["node_type"] in ALLOWED_NODE_TYPES, f"nodes[{idx}].node_type must be one of {sorted(ALLOWED_NODE_TYPES)}")
        aliases = node.get("aliases") or []
        _require(isinstance(aliases, list) and all(isinstance(alias, str) for alias in aliases), f"nodes[{idx}].aliases must be a string list")
        _require(node["node_key"] not in payload_keys, f"duplicate node_key in payload: {node['node_key']!r}")
        payload_keys.add(node["node_key"])
    keys.update(payload_keys)
    for idx, edge in enumerate(edges):
        _require(isinstance(edge, dict), f"edges[{idx}] must be an object")
        for field in ("source", "target", "relation_type", "provenance", "reviewed_at"):
            _require(isinstance(edge.get(field), str) and edge[field].strip(), f"edges[{idx}].{field} must be a non-empty string")
        _require(edge["source"] in keys, f"edges[{idx}].source references unknown node {edge['source']!r}")
        _require(edge["target"] in keys, f"edges[{idx}].target references unknown node {edge['target']!r}")
        _require(edge["source"] != edge["target"], f"edges[{idx}] self-edge is forbidden")
        _require(edge["relation_type"] in ALLOWED_RELATION_TYPES, f"edges[{idx}].relation_type must be one of {sorted(ALLOWED_RELATION_TYPES)}")
        weight = edge.get("weight", 0.5)
        _require(isinstance(weight, (int, float)) and 0 <= float(weight) <= 1, f"edges[{idx}].weight must be in [0, 1]")
        required = edge.get("required_context_any") or []
        _require(isinstance(required, list) and all(isinstance(token, str) for token in required), f"edges[{idx}].required_context_any must be a string list")
    return nodes, edges


def load_reference_graph_payload(conn: sqlite3.Connection, payload: dict[str, Any], *, apply: bool = False) -> dict[str, object]:
    """Validate reviewed reference nodes and edges; write only after explicit apply."""
    ensure_reference_graph_schema(conn)
    nodes, edges = _validated_payload(conn, payload)
    result: dict[str, object] = {
        "nodes_reviewed": len(nodes),
        "edges_reviewed": len(edges),
        "apply_requested": apply,
    }
    if not apply:
        result["guardrail"] = "Dry run only. Re-run with --apply after reviewing nodes, typed edges, predicates, and provenance."
        return result
    now = datetime.now(timezone.utc).isoformat()
    try:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN")
        for node in nodes:
            conn.execute(
                """INSERT INTO reference_nodes
                       (node_key, label, node_type, aliases_json, provenance, reviewed_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(node_key) DO UPDATE SET
                       label = excluded.label, node_type = excluded.node_type,
                       aliases_json = excluded.aliases_json, provenance = excluded.provenance,
                       reviewed_at = excluded.reviewed_at, updated_at = excluded.updated_at""",
                (
                    node["node_key"], node["label"], node["node_type"],
                    json.dumps(node.get("aliases") or [], sort_keys=True),
                    node["provenance"], node["reviewed_at"], now,
                ),
            )
        node_ids = {
            row["node_key"]: int(row["id"])
            for row in conn.execute("SELECT id, node_key FROM reference_nodes").fetchall()
        }
        for edge in edges:
            conn.execute(
                """INSERT INTO reference_edges
                       (source_node_id, target_node_id, relation_type, weight,
                        required_context_any_json, provenance, reviewed_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_node_id, target_node_id, relation_type) DO UPDATE SET
                       weight = excluded.weight,
                       required_context_any_json = excluded.required_context_any_json,
                       provenance = excluded.provenance,
                       reviewed_at = excluded.reviewed_at,
                       updated_at = excluded.updated_at""",
                (
                    node_ids[edge["source"]], node_ids[edge["target"]], edge["relation_type"],
                    float(edge.get("weight", 0.5)),
                    json.dumps(edge.get("required_context_any") or [], sort_keys=True),
                    edge["provenance"], edge["reviewed_at"], now,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    result["applied"] = True
    return result


def load_reference_graph_file(conn: sqlite3.Connection, path: Path, *, apply: bool = False) -> dict[str, object]:
    return load_reference_graph_payload(conn, json.loads(path.read_text()), apply=apply)


def _match_tokens(context_tokens: set[str], text: str, *, min_specific: int = 1) -> tuple[int, int, list[str]] | None:
    matched = context_tokens & _tokens(text)
    specific = matched - GENERIC_TOKENS
    if not matched or len(specific) < min_specific:
        return None
    return len(specific), len(matched), sorted(matched)


def _claim_match_tokens(node_tokens: set[str], claim_text: str) -> tuple[int, int, list[str]] | None:
    matched = node_tokens & _tokens(claim_text)
    meaningful = matched - BROAD_BINDING_TOKENS
    if len(matched) < 2 or not meaningful:
        return None
    return len(meaningful), len(matched), sorted(matched)


def _seed_match_tokens(context_tokens: set[str], row: sqlite3.Row, aliases: list[str]) -> tuple[int, int, list[str]] | None:
    match = _match_tokens(context_tokens, f"{row['node_key']} {row['label']} {' '.join(aliases)}")
    if not match or row["node_type"] != "procedure" or match[1] > 1:
        return match
    context = " ".join(sorted(context_tokens))
    exact_names = {_normalize(row["node_key"]), *(_normalize(alias) for alias in aliases)}
    return match if context in exact_names else None


def context_graph_focus_for_summary(
    conn: sqlite3.Connection,
    *,
    context: str,
    due_claims: list[dict[str, object]],
    limit: int = 6,
    max_hops: int = 2,
) -> list[dict[str, object]]:
    """Return reviewed, predicate-aware graph paths and due claims reached within two hops."""
    ensure_reference_graph_schema(conn)
    context_tokens = _tokens(context)
    if not context_tokens:
        return []
    nodes = conn.execute("SELECT * FROM reference_nodes").fetchall()
    if not nodes:
        return []
    node_by_id = {int(row["id"]): row for row in nodes}
    seeds: list[tuple[int, int, int, list[str]]] = []
    for row in nodes:
        aliases = json.loads(row["aliases_json"] or "[]")
        match = _seed_match_tokens(context_tokens, row, aliases)
        if match:
            seeds.append((int(row["id"]), match[0], match[1], match[2]))
    seeds.sort(key=lambda value: (-value[1], -value[2], node_by_id[value[0]]["node_key"]))
    paths: dict[int, dict[str, object]] = {}
    frontier: list[tuple[int, int, float, list[dict[str, object]]]] = []
    for node_id, specific, overlap, matched in seeds[: max(1, limit)]:
        node = node_by_id[node_id]
        path = [{
            "node_key": node["node_key"],
            "label": node["label"],
            "relation_type": "context_seed",
        }]
        paths[node_id] = {
            "node_id": node_id,
            "path_weight": 1.0,
            "hops": 0,
            "matched_context_tokens": matched,
            "path": path,
        }
        frontier.append((node_id, 0, 1.0, path))
    while frontier:
        source_id, hops, weight, path = frontier.pop(0)
        if hops >= max_hops:
            continue
        rows = conn.execute(
            """SELECT re.*, rn.node_key, rn.label
                 FROM reference_edges re
                 JOIN reference_nodes rn ON rn.id = re.target_node_id
                WHERE re.source_node_id = ?
                ORDER BY re.weight DESC, rn.node_key""",
            (source_id,),
        ).fetchall()
        for edge in rows:
            required = {_normalize(token) for token in json.loads(edge["required_context_any_json"] or "[]")}
            if required and not (required & context_tokens):
                continue
            target_id = int(edge["target_node_id"])
            target_weight = round(weight * float(edge["weight"]), 3)
            target_path = [
                *path,
                {
                    "node_key": edge["node_key"],
                    "label": edge["label"],
                    "relation_type": edge["relation_type"],
                },
            ]
            existing = paths.get(target_id)
            if existing is not None and float(existing["path_weight"]) >= target_weight:
                continue
            paths[target_id] = {
                "node_id": target_id,
                "path_weight": target_weight,
                "hops": hops + 1,
                "matched_context_tokens": [],
                "path": target_path,
            }
            frontier.append((target_id, hops + 1, target_weight, target_path))
    out: list[dict[str, object]] = []
    for node_id, path in paths.items():
        node = node_by_id[node_id]
        aliases = " ".join(json.loads(node["aliases_json"] or "[]"))
        due_matches = []
        for claim in due_claims:
            claim_text = " ".join(str(claim.get(key, "")) for key in ("topic", "concept", "claim"))
            match = _claim_match_tokens(_tokens(f"{node['label']} {aliases}"), claim_text)
            if match:
                due_matches.append(claim)
        out.append({
            **path,
            "node_key": node["node_key"],
            "node_label": node["label"],
            "node_type": node["node_type"],
            "due_claims": due_matches[:3],
            "next_action": "Use as context weighting only. Preserve urgent due gaps and verify the path predicate before teaching.",
        })
    out.sort(key=lambda item: (-len(item["due_claims"]), -float(item["path_weight"]), int(item["hops"]), str(item["node_key"])))
    return out[: max(0, limit)]
