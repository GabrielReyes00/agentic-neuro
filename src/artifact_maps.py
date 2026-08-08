"""Versioned, content-hash-verified artifact concept maps."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def content_hash(doc_path: str, vault_root: Path) -> str:
    if not doc_path:
        return ""
    candidate = Path(doc_path)
    if not candidate.is_absolute():
        candidate = vault_root / candidate
    try:
        return hashlib.sha256(candidate.read_bytes()).hexdigest()
    except OSError:
        return ""


def _row_for_doc(
    conn: sqlite3.Connection, doc_path: str, *, doc_family_alias: Any
) -> tuple[sqlite3.Row | None, str]:
    if not doc_path:
        return None, "none"
    exact = conn.execute("SELECT * FROM artifact_maps WHERE doc_path = ?", (doc_path,)).fetchone()
    if exact:
        return exact, "exact"
    family = doc_family_alias(doc_path)
    if family:
        for row in conn.execute("SELECT * FROM artifact_maps ORDER BY updated_at DESC, id DESC"):
            if doc_family_alias(str(row["doc_path"])) == family:
                return row, "doc_family"
    return None, "none"


def _payload_from_row(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    current_hash: str,
    match_type: str,
) -> dict[str, object]:
    concepts = [
        {
            "artifact_concept": item["artifact_concept"],
            "inventory_concept_id": item["inventory_concept_id"] or "",
            "mapping_status": item["mapping_status"],
            "confidence": item["confidence"],
            "role": item["role"],
            "evidence": json.loads(item["evidence_json"] or "[]"),
            "source_sections": json.loads(item["source_sections_json"] or "[]"),
            "source_anchors": json.loads(item["source_anchors_json"] or "[]"),
            "section_hashes": json.loads(item["section_hashes_json"] or "{}"),
            "learning_objectives": json.loads(item["learning_objectives_json"] or "[]"),
            "prerequisites": json.loads(item["prerequisites_json"] or "[]"),
            "confusers": json.loads(item["confusers_json"] or "[]"),
            "consequences": json.loads(item["consequences_json"] or "[]"),
            "transfer_targets": json.loads(item["transfer_targets_json"] or "[]"),
            "source_provenance": json.loads(item["source_provenance_json"] or "{}"),
            "unresolved_reason": item["unresolved_reason"] or "",
            "notes": item["notes"] or "",
        }
        for item in conn.execute(
            "SELECT * FROM artifact_map_concepts WHERE artifact_map_id = ? ORDER BY ordinal, id",
            (int(row["id"]),),
        )
    ]
    stored_hash = str(row["content_hash"] or "")
    if current_hash and stored_hash and current_hash != stored_hash:
        cache_status = "stale"
    elif match_type == "doc_family":
        cache_status = "family_match_unverified"
    elif stored_hash:
        cache_status = "available_hash_unchecked" if not current_hash else "available_hash_matched"
    else:
        cache_status = "available_hash_missing"
    return {
        "status": "available",
        "cache_status": cache_status,
        "match_type": match_type,
        "doc_path": row["doc_path"],
        "artifact_title": row["artifact_title"],
        "content_hash": stored_hash,
        "schema_version": row["schema_version"],
        "map_status": row["map_status"],
        "updated_at": row["updated_at"],
        "concepts": concepts,
        "counts": {
            "concepts": len(concepts),
            "mapped": sum(1 for item in concepts if item["inventory_concept_id"]),
            "unresolved": sum(1 for item in concepts if not item["inventory_concept_id"]),
        },
    }


def get(
    conn: sqlite3.Connection,
    *,
    doc_path: str,
    current_hash: str,
    schema_version: str,
    doc_family_alias: Any,
) -> dict[str, object]:
    row, match_type = _row_for_doc(conn, doc_path, doc_family_alias=doc_family_alias)
    if row is None:
        return {
            "status": "missing",
            "doc_path": doc_path,
            "cache_status": "missing",
            "concepts": [],
            "counts": {"concepts": 0, "mapped": 0, "unresolved": 0},
            "next_action": "Read the full artifact, map its concepts, and save with artifact-map-upsert.",
        }
    payload = _payload_from_row(conn, row, current_hash=current_hash, match_type=match_type)
    cache_status = str(payload.get("cache_status") or "")
    if (
        cache_status == "available_hash_matched"
        and payload.get("map_status") == "complete"
        and payload.get("schema_version") == schema_version
    ):
        payload["status"] = "available"
    elif cache_status == "stale":
        payload["status"] = "stale"
    else:
        payload["status"] = "unverified"
    payload["current_hash"] = current_hash
    payload["next_action"] = (
        "Use the verified artifact map and retrieve source sections just in time."
        if payload["status"] == "available"
        else "Rebuild from the full artifact because this map is stale or unverified."
    )
    return payload


def upsert(
    conn: sqlite3.Connection,
    *,
    doc_path: str,
    topic: str,
    payload: dict[str, object],
    content_hash_value: str,
    created_by: str,
    schema_version: str,
    engine: Any,
) -> dict[str, object]:
    if not doc_path:
        raise ValueError("artifact map requires --doc")
    concepts = payload.get("concepts")
    if not isinstance(concepts, list) or not concepts:
        raise ValueError("artifact map payload must contain a non-empty `concepts` list")
    resolution = engine.resolve_topic(conn, topic or str(payload.get("topic", "")), doc_path)
    topic_id = engine._ensure_topic(conn, resolution, doc_path)
    now = datetime.now(timezone.utc).isoformat()
    artifact_title = str(payload.get("artifact_title") or Path(doc_path).stem).strip()
    final_schema = str(payload.get("schema_version") or schema_version)
    map_status = engine._controlled_value(str(payload.get("map_status") or "complete"))
    if map_status not in {"complete", "partial", "needs_review"}:
        map_status = "complete"
    if not content_hash_value and map_status == "complete":
        map_status = "needs_review"
    conn.execute(
        """INSERT INTO artifact_maps
           (doc_path, topic_id, artifact_title, content_hash, schema_version, map_status,
            created_by, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(doc_path) DO UPDATE SET
             topic_id=excluded.topic_id, artifact_title=excluded.artifact_title,
             content_hash=excluded.content_hash, schema_version=excluded.schema_version,
             map_status=excluded.map_status, created_by=excluded.created_by,
             notes=excluded.notes, updated_at=excluded.updated_at""",
        (doc_path, topic_id, artifact_title, content_hash_value, final_schema, map_status,
         created_by or "agent", str(payload.get("notes") or ""), now, now),
    )
    map_id = int(conn.execute("SELECT id FROM artifact_maps WHERE doc_path = ?", (doc_path,)).fetchone()[0])
    conn.execute("DELETE FROM artifact_map_concepts WHERE artifact_map_id = ?", (map_id,))
    for idx, raw in enumerate(concepts):
        if not isinstance(raw, dict):
            raise ValueError(f"concepts[{idx}] must be an object")
        artifact_concept = str(raw.get("artifact_concept") or raw.get("concept") or "").strip()
        if not artifact_concept:
            raise ValueError(f"concepts[{idx}] missing artifact_concept")
        inventory_id = str(raw.get("inventory_concept_id") or "").strip()
        conn.execute(
            """INSERT INTO artifact_map_concepts
               (artifact_map_id, artifact_concept, inventory_concept_id, mapping_status,
                confidence, role, evidence_json, source_sections_json, source_anchors_json,
                section_hashes_json, learning_objectives_json, prerequisites_json,
                confusers_json, consequences_json, transfer_targets_json,
                source_provenance_json, unresolved_reason, notes, ordinal)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                map_id, artifact_concept, inventory_id,
                engine._normalize_mapping_status(inventory_id, raw.get("mapping_status")),
                engine._normalize_artifact_confidence(raw.get("confidence")),
                engine._normalize_artifact_role(raw.get("role")),
                json.dumps(engine._json_array(raw.get("evidence")), sort_keys=True),
                json.dumps(engine._json_array(raw.get("source_sections")), sort_keys=True),
                json.dumps(engine._json_array(raw.get("source_anchors")), sort_keys=True),
                json.dumps(raw.get("section_hashes") if isinstance(raw.get("section_hashes"), dict) else {}, sort_keys=True),
                json.dumps(engine._json_array(raw.get("learning_objectives")), sort_keys=True),
                json.dumps(engine._json_array(raw.get("prerequisites")), sort_keys=True),
                json.dumps(engine._json_array(raw.get("confusers")), sort_keys=True),
                json.dumps(engine._json_array(raw.get("consequences")), sort_keys=True),
                json.dumps(engine._json_array(raw.get("transfer_targets")), sort_keys=True),
                json.dumps(raw.get("source_provenance") if isinstance(raw.get("source_provenance"), dict) else {}, sort_keys=True),
                str(raw.get("unresolved_reason") or ""), str(raw.get("notes") or ""), idx,
            ),
        )
    conn.commit()
    saved = get(
        conn,
        doc_path=doc_path,
        current_hash=content_hash_value,
        schema_version=schema_version,
        doc_family_alias=engine._doc_family_alias,
    )
    saved.update({"ok": True, "resolved_topic": resolution.slug})
    return saved
