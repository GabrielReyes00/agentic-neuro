#!/usr/bin/env python3
"""Compile Obsidian vault notes into a field-aware retrieval index.

This module keeps the vault as the canonical human-readable source while
materializing small section payloads for fast agent retrieval. It deliberately
does not write into study_memory.db: learner-state telemetry and vault content
remain separate layers that agents combine at runtime.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    from vault_schema import parse_frontmatter, split_frontmatter
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from .vault_schema import parse_frontmatter, split_frontmatter


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_VAULT_ROOT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
DEFAULT_INDEX_DB = DATA_DIR / "vault_index.db"
DEFAULT_LANCE_DIR = Path(os.environ.get("NEURO_VAULT_LANCE_DIR", BASE_DIR / "neurosurgery_v4.lance"))
DEFAULT_LANCE_TABLE = os.environ.get("NEURO_VAULT_LANCE_TABLE", "vault_notes")
MODEL_CACHE_DIR = Path(os.environ.get("NEURO_MODEL_CACHE_DIR", DATA_DIR / "models" / "huggingface"))
BGE_M3_MODEL_ID = os.environ.get("NEURO_BGE_MODEL_ID", "BAAI/bge-m3")
MODEL_LOAD_LOCAL_ONLY = os.environ.get("NEURO_MODEL_LOAD_LOCAL_ONLY", "1") != "0"

INDEX_FOLDERS = (
    "Reports",
    "Study Material",
    "Operative Guides",
    "Shift Debriefs",
    "Concepts",
    "Consults",
    "Journal Club",
    "Reference",
    "Presentations",
    "Residency",
)

SECTION_ALIASES: dict[str, str] = {
    "quick reference": "quick_reference",
    "clinical utility & quick reference": "quick_reference",
    "clinical focus": "clinical_focus",
    "priority takeaways": "priority_takeaways",
    "clinical use": "clinical_use",
    "clinical & anatomical synthesis": "clinical_synthesis",
    "clinical and anatomical synthesis": "clinical_synthesis",
    "synthesis & integration": "clinical_synthesis",
    "synthesis and integration": "clinical_synthesis",
    "durable mental model": "durable_mental_model",
    "operational mental models": "operational_mental_model",
    "critical discriminators": "critical_discriminators",
    "execution check": "execution_check",
    "evidence card": "evidence_card",
    "surgical coordinates": "surgical_coordinates",
    "consequence matrix": "consequence_matrix",
    "bedside decision rule": "bedside_decision_rule",
    "imaging read": "imaging_read",
    "imaging & diagnostic workup": "imaging_read",
    "imaging and diagnostic workup": "imaging_read",
    "mastery objectives": "mastery_objectives",
    "institutional & local clarifications": "local_clarifications",
    "institutional and local clarifications": "local_clarifications",
    "clarify or verify locally": "local_clarifications",
    "related in this vault": "related",
    "references": "references",
    "sources": "references",
    "source chunk inventory": "source_inventory",
    "atomic fact ledger": "atomic_fact_ledger",
    "concept summary": "concept_summary",
    "questions": "questions",
    "start here": "quick_reference",
    "clinical foundation": "clinical_synthesis",
    "essential concepts for this paper": "durable_mental_model",
    "why this study exists": "evidence_card",
    "study architecture": "evidence_card",
    "results that matter": "evidence_card",
    "figures and tables explained": "evidence_card",
    "interpretation": "critical_discriminators",
    "limitations that actually matter": "critical_discriminators",
    "neurosurgical relevance": "clinical_use",
    "historical and current context": "evidence_card",
    "presentation core": "execution_check",
    "faculty defense": "execution_check",
    "source trace": "references",
}

TASK_SECTION_POLICY: dict[str, tuple[str, ...]] = {
    "doc-review": (
        "mastery_objectives",
        "critical_discriminators",
        "durable_mental_model",
        "execution_check",
        "quick_reference",
        "clinical_synthesis",
        "related",
    ),
    "study-material-generation": (
        "quick_reference",
        "critical_discriminators",
        "durable_mental_model",
        "clinical_synthesis",
        "related",
    ),
    "weak-spot-review": (
        "critical_discriminators",
        "durable_mental_model",
        "execution_check",
        "evidence_card",
        "bedside_decision_rule",
        "clinical_use",
    ),
    "concept-repair": (
        "durable_mental_model",
        "critical_discriminators",
        "execution_check",
        "clinical_use",
    ),
    "consult": (
        "quick_reference",
        "bedside_decision_rule",
        "evidence_card",
        "clinical_use",
        "references",
    ),
    "service-local": (
        "local_clarifications",
        "priority_takeaways",
        "clinical_synthesis",
        "operational_mental_model",
        "mastery_objectives",
    ),
    "operative-rehearsal": (
        "surgical_coordinates",
        "critical_discriminators",
        "execution_check",
        "operational_mental_model",
        "clinical_use",
    ),
    "imaging": (
        "imaging_read",
        "critical_discriminators",
        "clinical_use",
        "quick_reference",
    ),
    "trial-evidence": (
        "evidence_card",
        "quick_reference",
        "critical_discriminators",
        "references",
    ),
    "report-generation": (
        "quick_reference",
        "clinical_synthesis",
        "evidence_card",
        "related",
        "references",
    ),
    "journal-club": (
        "quick_reference",
        "clinical_synthesis",
        "durable_mental_model",
        "evidence_card",
        "critical_discriminators",
        "clinical_use",
        "execution_check",
        "references",
        "related",
    ),
    "presentation-generation": (
        "quick_reference",
        "clinical_synthesis",
        "evidence_card",
        "critical_discriminators",
        "surgical_coordinates",
        "imaging_read",
        "local_clarifications",
        "related",
        "references",
    ),
}

LOCAL_SECTION_TYPES = {"local_clarifications"}
SERVICE_FOLDERS = {"Shift Debriefs"}
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
REFERENCE_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", flags=re.M)
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./+-]{1,}")
STOPWORDS = frozenset(
    "the a an and or of in to for with without on by from into onto this that "
    "what when where why how should would could about patient patients after "
    "before during using use uses"
    .split()
)

KNOWLEDGE_BOUNDARY = (
    "Vault retrieval is personalized supplemental context, not the curriculum ceiling. "
    "Use native clinical knowledge and formal verification when the vault is silent, "
    "thin, local, or source-sensitive."
)
PACKET_TEXT_LIMIT = 900


@dataclass(frozen=True)
class VaultNote:
    note_path: str
    title: str
    folder: str
    note_type: str
    artifact_type: str
    status: str
    domain: tuple[str, ...]
    aliases: tuple[str, ...]
    tags: tuple[str, ...]
    summary: str
    display: str
    created: str
    generated: str
    provenance: str
    institution: str
    service: str
    rotation: str
    conference: str
    internal_knowledge_used: bool | None
    content_hash: str
    modified_ns: int


@dataclass(frozen=True)
class VaultSection:
    section_id: str
    note_path: str
    title: str
    folder: str
    note_type: str
    domain: tuple[str, ...]
    aliases: tuple[str, ...]
    tags: tuple[str, ...]
    summary: str
    section_heading: str
    section_type: str
    section_path: str
    ordinal: int
    text: str
    text_hash: str
    token_estimate: int
    wikilinks: tuple[str, ...]
    references: tuple[dict[str, str], ...]
    provenance_tier: str
    source_role: str = "personalized_supplement"


def _json_dumps(payload: object, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(payload, indent=2, sort_keys=True)
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned or "untitled"


def _as_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    if not text:
        return ()
    if "," in text:
        return tuple(item.strip() for item in text.split(",") if item.strip())
    return (text,)


def _normalize_domain(value: Any, tags: Iterable[str]) -> tuple[str, ...]:
    raw: list[str] = []
    if isinstance(value, (list, tuple)):
        for item in value:
            raw.extend(re.split(r"[,/]", str(item)))
    elif value is not None:
        raw.extend(re.split(r"[,/]", str(value)))
    for tag in tags:
        if tag.lower().startswith("domain/"):
            raw.append(tag.split("/", 1)[1])
    out: list[str] = []
    for item in raw:
        token = item.strip().lower().replace(" ", "-").replace("_", "-")
        if token and token not in out:
            out.append(token)
    return tuple(out)


def _note_type(folder: str, tags: tuple[str, ...]) -> str:
    by_folder = {
        "Reports": "report",
        "Study Material": "study_material",
        "Operative Guides": "operative_guide",
        "Shift Debriefs": "shift_debrief",
        "Concepts": "concept",
        "Consults": "consult",
        "Journal Club": "journal_club",
        "Reference": "reference",
        "Presentations": "presentation",
        "Residency": "residency_context",
    }
    for tag in tags:
        if tag.startswith("type/"):
            return tag.split("/", 1)[1].replace("-", "_")
    return by_folder.get(folder, _slug(folder).replace("-", "_"))


def _section_type(heading: str) -> str:
    normalized = re.sub(r"\s+", " ", heading.strip().lower())
    return SECTION_ALIASES.get(normalized, "general_content")


def _wikilinks(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in WIKILINK_RE.finditer(text):
        target = match.group(1).strip()
        if target and target not in found:
            found.append(target)
    return tuple(found)


def _link_property(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    match = WIKILINK_RE.search(value)
    return (match.group(1) if match else value).strip()


def _metadata_wikilinks(meta: dict[str, Any]) -> tuple[str, ...]:
    found: list[str] = []
    for key in (
        "institution",
        "service",
        "rotation",
        "conference",
        "source_file",
        "source_note",
        "presentation",
        "deck_file",
        "related",
    ):
        value = meta.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str):
                continue
            targets = _wikilinks(item)
            if not targets:
                target = _link_property(item)
                targets = (target,) if target else ()
            for target in targets:
                if target not in found:
                    found.append(target)
    return tuple(found)


def _references(text: str) -> tuple[dict[str, str], ...]:
    refs: list[dict[str, str]] = []
    for match in REFERENCE_LINK_RE.finditer(text):
        refs.append({"label": match.group(1).strip(), "url": match.group(2).strip()})
    return tuple(refs)


def _provenance_tier(folder: str, section_type: str, text: str, meta: dict[str, Any]) -> str:
    lower = text.lower()
    if section_type in LOCAL_SECTION_TYPES:
        return "local_or_institutional"
    if folder in SERVICE_FOLDERS:
        return "experiential_service_context"
    if "clinical knowledge - verify" in lower or "model knowledge" in lower:
        return "verify_before_clinical_use"
    if _references(text):
        return "source_linked"
    if meta.get("internal_knowledge_used") is True:
        return "mixed_internal_knowledge"
    return "curated_vault_context"


def _token_estimate(text: str) -> int:
    return max(1, len(re.findall(r"\w+", text)))


def parse_note(path: Path, vault_root: Path) -> tuple[VaultNote, list[VaultSection]]:
    text = path.read_text(encoding="utf-8")
    body, parsed_meta = split_frontmatter(text)
    meta = parsed_meta or {}
    rel = path.relative_to(vault_root)
    parts = rel.parts
    folder = parts[0] if parts else ""
    tags = _as_list(meta.get("tags"))
    aliases = _as_list(meta.get("aliases"))
    domain = _normalize_domain(meta.get("domain"), tags)
    note = VaultNote(
        note_path=rel.as_posix(),
        title=path.stem,
        folder=folder,
        note_type=_note_type(folder, tags),
        artifact_type=str(meta.get("artifact_type") or _note_type(folder, tags)).strip(),
        status=str(meta.get("status") or "current").strip(),
        domain=domain,
        aliases=aliases,
        tags=tags,
        summary=str(meta.get("summary") or "").strip(),
        display=str(meta.get("display") or path.stem).strip(),
        created=str(meta.get("created") or meta.get("date") or "").strip(),
        generated=str(meta.get("generated") or "").strip(),
        provenance=str(meta.get("provenance") or meta.get("extracted_from") or "").strip(),
        institution=_link_property(meta.get("institution")),
        service=_link_property(meta.get("service")),
        rotation=_link_property(meta.get("rotation")),
        conference=_link_property(meta.get("conference")),
        internal_knowledge_used=(
            bool(meta["internal_knowledge_used"]) if "internal_knowledge_used" in meta else None
        ),
        content_hash=_sha256(body),
        modified_ns=path.stat().st_mtime_ns,
    )

    sections: list[VaultSection] = []
    matches = list(HEADING_RE.finditer(body))
    if matches and matches[0].start() > 0:
        lead = body[: matches[0].start()].strip()
        if lead:
            sections.append(_build_section(note, "Definition", "definition", lead, 0, meta))
    elif not matches and body.strip():
        sections.append(_build_section(note, "Body", "body", body.strip(), 0, meta))

    for idx, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        section_text = body[start:end].strip()
        if not section_text:
            continue
        sections.append(
            _build_section(note, heading, _section_type(heading), section_text, len(sections), meta)
        )
    return note, sections


def _build_section(
    note: VaultNote,
    heading: str,
    section_type: str,
    section_text: str,
    ordinal: int,
    meta: dict[str, Any],
) -> VaultSection:
    path = f"{note.note_path}#{heading}"
    section_id = _sha256(f"{note.note_path}\n{ordinal}\n{heading}")
    return VaultSection(
        section_id=section_id,
        note_path=note.note_path,
        title=note.title,
        folder=note.folder,
        note_type=note.note_type,
        domain=note.domain,
        aliases=note.aliases,
        tags=note.tags,
        summary=note.summary,
        section_heading=heading,
        section_type=section_type,
        section_path=path,
        ordinal=ordinal,
        text=section_text,
        text_hash=_sha256(section_text),
        token_estimate=_token_estimate(section_text),
        wikilinks=tuple(
            dict.fromkeys((*_wikilinks(section_text), *_metadata_wikilinks(meta)))
        ),
        references=_references(section_text),
        provenance_tier=_provenance_tier(note.folder, section_type, section_text, meta),
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS vault_notes (
            note_path TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            folder TEXT NOT NULL,
            note_type TEXT NOT NULL,
            artifact_type TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'current',
            domain_json TEXT NOT NULL DEFAULT '[]',
            aliases_json TEXT NOT NULL DEFAULT '[]',
            tags_json TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '',
            display TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL DEFAULT '',
            generated TEXT NOT NULL DEFAULT '',
            provenance TEXT NOT NULL DEFAULT '',
            institution TEXT NOT NULL DEFAULT '',
            service TEXT NOT NULL DEFAULT '',
            rotation TEXT NOT NULL DEFAULT '',
            conference TEXT NOT NULL DEFAULT '',
            internal_knowledge_used INTEGER,
            content_hash TEXT NOT NULL,
            modified_ns INTEGER NOT NULL,
            indexed_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS vault_sections (
            section_id TEXT PRIMARY KEY,
            note_path TEXT NOT NULL,
            title TEXT NOT NULL,
            folder TEXT NOT NULL,
            note_type TEXT NOT NULL,
            domain_json TEXT NOT NULL DEFAULT '[]',
            aliases_json TEXT NOT NULL DEFAULT '[]',
            tags_json TEXT NOT NULL DEFAULT '[]',
            summary TEXT NOT NULL DEFAULT '',
            section_heading TEXT NOT NULL,
            section_type TEXT NOT NULL,
            section_path TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            text TEXT NOT NULL,
            text_hash TEXT NOT NULL,
            token_estimate INTEGER NOT NULL,
            wikilinks_json TEXT NOT NULL DEFAULT '[]',
            references_json TEXT NOT NULL DEFAULT '[]',
            provenance_tier TEXT NOT NULL,
            source_role TEXT NOT NULL DEFAULT 'personalized_supplement',
            indexed_at TEXT NOT NULL,
            FOREIGN KEY(note_path) REFERENCES vault_notes(note_path) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_vault_sections_note ON vault_sections(note_path);
        CREATE INDEX IF NOT EXISTS idx_vault_sections_folder ON vault_sections(folder);
        CREATE INDEX IF NOT EXISTS idx_vault_sections_type ON vault_sections(section_type);
        CREATE INDEX IF NOT EXISTS idx_vault_sections_note_type ON vault_sections(note_type);
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS vault_sections_fts
        USING fts5(section_id UNINDEXED, note_path, title, section_heading, section_type, text)
        """
    )
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(vault_notes)")
    }
    for column, declaration in (
        ("artifact_type", "TEXT NOT NULL DEFAULT ''"),
        ("status", "TEXT NOT NULL DEFAULT 'current'"),
        ("institution", "TEXT NOT NULL DEFAULT ''"),
        ("service", "TEXT NOT NULL DEFAULT ''"),
        ("rotation", "TEXT NOT NULL DEFAULT ''"),
        ("conference", "TEXT NOT NULL DEFAULT ''"),
    ):
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE vault_notes ADD COLUMN {column} {declaration}")
    conn.commit()


def _iter_note_paths(vault_root: Path, folders: Iterable[str] = INDEX_FOLDERS) -> list[Path]:
    paths: list[Path] = []
    for folder_name in folders:
        folder = vault_root / folder_name
        if not folder.exists():
            continue
        glob = folder.rglob("*.md") if folder_name in {"Presentations", "Residency"} else folder.glob("*.md")
        paths.extend(p for p in glob if p.name != "INDEX.md")
    return sorted(paths)


def sync_vault(
    *,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    db_path: Path = DEFAULT_INDEX_DB,
    folders: Iterable[str] = INDEX_FOLDERS,
) -> dict[str, object]:
    notes: list[VaultNote] = []
    sections: list[VaultSection] = []
    errors: list[dict[str, str]] = []
    for path in _iter_note_paths(vault_root, folders):
        try:
            note, note_sections = parse_note(path, vault_root)
        except Exception as exc:  # pragma: no cover - defensive for malformed user notes
            errors.append({"path": str(path), "error": str(exc)})
            continue
        notes.append(note)
        sections.extend(note_sections)

    indexed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            conn.execute("DELETE FROM vault_sections_fts")
            conn.execute("DELETE FROM vault_sections")
            conn.execute("DELETE FROM vault_notes")
            for note in notes:
                conn.execute(
                    """INSERT INTO vault_notes
                       (note_path, title, folder, note_type, artifact_type, status,
                        domain_json, aliases_json,
                        tags_json, summary, display, created, generated, provenance,
                        institution, service, rotation, conference,
                        internal_knowledge_used, content_hash, modified_ns, indexed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        note.note_path,
                        note.title,
                        note.folder,
                        note.note_type,
                        note.artifact_type,
                        note.status,
                        json.dumps(note.domain),
                        json.dumps(note.aliases),
                        json.dumps(note.tags),
                        note.summary,
                        note.display,
                        note.created,
                        note.generated,
                        note.provenance,
                        note.institution,
                        note.service,
                        note.rotation,
                        note.conference,
                        None if note.internal_knowledge_used is None else int(note.internal_knowledge_used),
                        note.content_hash,
                        note.modified_ns,
                        indexed_at,
                    ),
                )
            for section in sections:
                conn.execute(
                    """INSERT INTO vault_sections
                       (section_id, note_path, title, folder, note_type, domain_json,
                        aliases_json, tags_json, summary, section_heading, section_type,
                        section_path, ordinal, text, text_hash, token_estimate,
                        wikilinks_json, references_json, provenance_tier, source_role, indexed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        section.section_id,
                        section.note_path,
                        section.title,
                        section.folder,
                        section.note_type,
                        json.dumps(section.domain),
                        json.dumps(section.aliases),
                        json.dumps(section.tags),
                        section.summary,
                        section.section_heading,
                        section.section_type,
                        section.section_path,
                        section.ordinal,
                        section.text,
                        section.text_hash,
                        section.token_estimate,
                        json.dumps(section.wikilinks),
                        json.dumps(section.references),
                        section.provenance_tier,
                        section.source_role,
                        indexed_at,
                    ),
                )
                conn.execute(
                    """INSERT INTO vault_sections_fts
                       (section_id, note_path, title, section_heading, section_type, text)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        section.section_id,
                        section.note_path,
                        section.title,
                        section.section_heading,
                        section.section_type,
                        section.text,
                    ),
                )
    return {
        "ok": not errors,
        "vault_root": str(vault_root),
        "db_path": str(db_path),
        "notes_indexed": len(notes),
        "sections_indexed": len(sections),
        "errors": errors,
        "knowledge_boundary": KNOWLEDGE_BOUNDARY,
    }


def refresh_default_index_after_vault_write(
    *,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    db_path: Path = DEFAULT_INDEX_DB,
) -> dict[str, object]:
    """Refresh the machine index after writes to the real Obsidian vault.

    Guard scripts are also used against temp vaults during tests and draft
    validation. Those installs should update their local folder INDEX.md files
    without mutating the user's persistent retrieval database.
    """
    resolved_root = vault_root.expanduser().resolve()
    default_root = DEFAULT_VAULT_ROOT.expanduser().resolve()
    if resolved_root != default_root:
        return {
            "ok": True,
            "skipped": True,
            "reason": "non_default_vault_root",
            "vault_root": str(vault_root),
            "db_path": str(db_path),
            "knowledge_boundary": KNOWLEDGE_BOUNDARY,
        }
    result = sync_vault(vault_root=resolved_root, db_path=db_path)
    result["skipped"] = False
    return result


def _tokens(query: str) -> list[str]:
    out: list[str] = []
    for token in TOKEN_RE.findall(query.lower()):
        if token not in STOPWORDS and token not in out:
            out.append(token)
    return out


def _fts_query(query: str) -> str:
    tokens = _tokens(query)
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in tokens[:12])


def _json_tuple(value: str) -> tuple[Any, ...]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return ()
    return tuple(parsed) if isinstance(parsed, list) else ()


def _row_to_section(row: sqlite3.Row, *, score: float) -> dict[str, object]:
    payload = {
        "section_id": row["section_id"],
        "note_path": row["note_path"],
        "title": row["title"],
        "folder": row["folder"],
        "note_type": row["note_type"],
        "domain": list(_json_tuple(row["domain_json"])),
        "aliases": list(_json_tuple(row["aliases_json"])),
        "summary": row["summary"],
        "section_heading": row["section_heading"],
        "section_type": row["section_type"],
        "section_path": row["section_path"],
        "text": row["text"],
        "token_estimate": row["token_estimate"],
        "wikilinks": list(_json_tuple(row["wikilinks_json"])),
        "references": list(_json_tuple(row["references_json"])),
        "provenance_tier": row["provenance_tier"],
        "source_role": row["source_role"],
        "score": round(score, 4),
    }
    keys = set(row.keys())
    for key in ("artifact_type", "status", "institution", "service", "rotation", "conference"):
        payload[key] = row[key] if key in keys else ""
    return payload


def _scope_clause(
    *,
    folders: tuple[str, ...] = (),
    domains: tuple[str, ...] = (),
    section_types: tuple[str, ...] = (),
    note_types: tuple[str, ...] = (),
    statuses: tuple[str, ...] = (),
    institutions: tuple[str, ...] = (),
    services: tuple[str, ...] = (),
    rotations: tuple[str, ...] = (),
    conferences: tuple[str, ...] = (),
    include_local: bool = True,
) -> tuple[str, list[object]]:
    where: list[str] = []
    params: list[object] = []
    if folders:
        where.append("s.folder IN (%s)" % ",".join("?" for _ in folders))
        params.extend(folders)
    if section_types:
        where.append("s.section_type IN (%s)" % ",".join("?" for _ in section_types))
        params.extend(section_types)
    if note_types:
        where.append("s.note_type IN (%s)" % ",".join("?" for _ in note_types))
        params.extend(note_types)
    for column, values in (
        ("status", statuses),
        ("institution", institutions),
        ("service", services),
        ("rotation", rotations),
        ("conference", conferences),
    ):
        if values:
            where.append(f"n.{column} IN (%s)" % ",".join("?" for _ in values))
            params.extend(values)
    if domains:
        domain_filters = []
        for domain in domains:
            domain_filters.append("s.domain_json LIKE ?")
            params.append(f'%"{domain}"%')
        where.append("(" + " OR ".join(domain_filters) + ")")
    if not include_local:
        where.append("s.section_type NOT IN (%s)" % ",".join("?" for _ in LOCAL_SECTION_TYPES))
        params.extend(sorted(LOCAL_SECTION_TYPES))
        where.append("s.folder NOT IN (%s)" % ",".join("?" for _ in SERVICE_FOLDERS))
        params.extend(sorted(SERVICE_FOLDERS))
    return (" AND " + " AND ".join(where)) if where else "", params


def _preferred_section_types(task: str) -> tuple[str, ...]:
    return TASK_SECTION_POLICY.get(task, ())


def _field_boost(section_type: str, preferred: tuple[str, ...]) -> float:
    if not preferred:
        return 0.0
    try:
        idx = preferred.index(section_type)
    except ValueError:
        return 0.0
    return max(0.05, 0.35 - (idx * 0.03))


def search_sections(
    query: str,
    *,
    db_path: Path = DEFAULT_INDEX_DB,
    task: str = "",
    folders: tuple[str, ...] = (),
    domains: tuple[str, ...] = (),
    section_types: tuple[str, ...] = (),
    note_types: tuple[str, ...] = (),
    statuses: tuple[str, ...] = (),
    institutions: tuple[str, ...] = (),
    services: tuple[str, ...] = (),
    rotations: tuple[str, ...] = (),
    conferences: tuple[str, ...] = (),
    include_local: bool = True,
    strict_fields: bool = False,
    limit: int = 5,
) -> dict[str, object]:
    preferred = _preferred_section_types(task)
    effective_section_types = section_types or (preferred if strict_fields else ())
    scope_sql, scope_params = _scope_clause(
        folders=folders,
        domains=domains,
        section_types=effective_section_types,
        note_types=note_types,
        statuses=statuses,
        institutions=institutions,
        services=services,
        rotations=rotations,
        conferences=conferences,
        include_local=include_local,
    )
    fts = _fts_query(query)
    rows: list[tuple[sqlite3.Row, float]] = []
    with _connect(db_path) as conn:
        if fts:
            try:
                sql = f"""SELECT s.*, n.artifact_type, n.status, n.institution,
                                 n.service, n.rotation, n.conference,
                                 bm25(vault_sections_fts) AS bm25_score
                          FROM vault_sections_fts
                          JOIN vault_sections s ON s.section_id = vault_sections_fts.section_id
                          JOIN vault_notes n ON n.note_path = s.note_path
                          WHERE vault_sections_fts MATCH ? {scope_sql}
                          ORDER BY bm25_score
                          LIMIT ?"""
                for row in conn.execute(sql, [fts, *scope_params, max(limit * 4, 20)]):
                    base = 1.0 / (1.0 + abs(float(row["bm25_score"])))
                    rows.append((row, base + _field_boost(row["section_type"], preferred)))
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            sql = f"""SELECT s.*, n.artifact_type, n.status, n.institution,
                             n.service, n.rotation, n.conference
                      FROM vault_sections s
                      JOIN vault_notes n ON n.note_path = s.note_path
                      WHERE 1=1 {scope_sql}
                      LIMIT ?"""
            tokens = _tokens(query)
            for row in conn.execute(sql, [*scope_params, 500]):
                blob = " ".join(
                    [
                        row["title"],
                        row["section_heading"],
                        row["section_type"],
                        row["summary"],
                        row["text"],
                    ]
                ).lower()
                overlap = sum(1 for token in tokens if token in blob)
                if overlap or not tokens:
                    rows.append((row, float(overlap) + _field_boost(row["section_type"], preferred)))
    rows.sort(key=lambda pair: pair[1], reverse=True)
    hits = [_row_to_section(row, score=score) for row, score in rows[:limit]]
    return {
        "ok": True,
        "query": query,
        "task": task,
        "preferred_section_types": list(preferred),
        "strict_fields": strict_fields,
        "hits": hits,
        "count": len(hits),
        "knowledge_boundary": KNOWLEDGE_BOUNDARY,
    }


DEFAULT_CATALOG_PATH = DATA_DIR / "acgme_curriculum.json"
CONTRAST_TOKENS = frozenset({"versus", "vs", "differential", "mimic", "mimics", "contrast"})
# Folder roles drive light edge typing. Concepts are atomic part-of nodes;
# Reports/Operative Guides/Study Material are composite artifacts a concept is
# part-of; Shift Debriefs/Consults are associated experiential context.
PART_OF_FOLDERS = frozenset({"Reports", "Operative Guides", "Study Material", "Journal Club"})


def _resolve_anchor_note(conn: sqlite3.Connection, note: str) -> sqlite3.Row | None:
    candidates = [note, note if note.endswith(".md") else f"{note}.md"]
    row = conn.execute(
        "SELECT note_path, title, folder, domain_json FROM vault_notes "
        "WHERE note_path IN (?, ?) OR title = ? LIMIT 1",
        (candidates[0], candidates[1], note),
    ).fetchone()
    return row


def _infer_edge_type(neighbor_folder: str, neighbor_title: str, direction: str) -> str:
    title_tokens = set(_tokens(neighbor_title))
    if title_tokens & CONTRAST_TOKENS:
        return "contrasts-with"
    if direction == "outbound" and neighbor_folder == "Concepts":
        return "part-of"
    if direction == "inbound" and neighbor_folder in PART_OF_FOLDERS:
        return "part-of"
    return "associated-with"


def _acgme_neighbors(catalog_path: Path, anchor_title: str, anchor_domain: list[str], limit: int) -> list[dict[str, object]]:
    try:
        catalog = json.loads(catalog_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    anchor_tokens = set(_tokens(anchor_title))
    if not anchor_tokens:
        return []
    domain_lower = {str(d).lower() for d in anchor_domain}
    scored: list[tuple[float, dict[str, object]]] = []
    for _key, milestone in (catalog.get("milestones") or {}).items():
        for topic in milestone.get("topics", []) or []:
            title = str(topic.get("title", ""))
            topic_tokens = set(_tokens(title))
            if not topic_tokens:
                continue
            overlap = anchor_tokens & topic_tokens
            if not overlap:
                continue
            # Skip the anchor itself; surface only *adjacent* competencies.
            if topic_tokens <= anchor_tokens and anchor_tokens <= topic_tokens:
                continue
            score = len(overlap) / len(anchor_tokens | topic_tokens)
            if str(topic.get("domain", "")).lower() in domain_lower:
                score += 0.1
            scored.append((score, {
                "competency": title,
                "domain": topic.get("domain", ""),
                "pgy_target": topic.get("pgy_target"),
                "priority": topic.get("priority", ""),
                "shared_tokens": sorted(overlap),
            }))
    scored.sort(key=lambda x: (-x[0], str(x[1]["competency"])))
    seen: set[str] = set()
    out: list[dict[str, object]] = []
    for _score, item in scored:
        if item["competency"] in seen:
            continue
        seen.add(str(item["competency"]))
        out.append(item)
        if len(out) >= limit:
            break
    return out


def landscape_map(
    *,
    db_path: Path = DEFAULT_INDEX_DB,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    note: str,
    max_neighbors: int = 8,
    include_acgme: bool = True,
) -> dict[str, object]:
    """Deterministic pre-session knowledge landscape for an artifact-anchored review.

    Curriculum adjacency comes from the vault wikilink graph (outbound links the
    artifact makes plus inbound links other notes make to it), never embedding
    similarity. Branching is capped at `max_neighbors`; edge types are inferred
    from folder role and link direction. ACGME competency neighbors are added by
    token overlap against the catalog. No embeddings, no LLM, no textbook RAG.

    The result is meant to populate the agent's context before the session so it
    has neighboring nodes ready to probe, repair, or extend mid-session, even
    when the neighbors are never surfaced to the learner (brief 4a).
    """
    with _connect(db_path) as conn:
        anchor = _resolve_anchor_note(conn, note)
        if anchor is None:
            return {"ok": False, "reason": "anchor_note_not_found", "note": note,
                    "neighbors": [], "acgme_neighbors": [], "knowledge_boundary": KNOWLEDGE_BOUNDARY}
        anchor_path = anchor["note_path"]
        anchor_title = anchor["title"]
        anchor_domain = list(_json_tuple(anchor["domain_json"]))
        anchor_link_keys = {anchor_path[:-3] if anchor_path.endswith(".md") else anchor_path, anchor_title}

        # Outbound: every wikilink the anchor's sections make.
        outbound_targets: list[str] = []
        for row in conn.execute(
            "SELECT wikilinks_json FROM vault_sections WHERE note_path = ?", (anchor_path,)
        ):
            for target in _json_tuple(row["wikilinks_json"]):
                target = str(target)
                if target not in outbound_targets and target not in anchor_link_keys:
                    outbound_targets.append(target)

        # Inbound: notes whose sections link to the anchor.
        inbound_paths: list[str] = []
        for row in conn.execute(
            "SELECT DISTINCT note_path, wikilinks_json FROM vault_sections "
            "WHERE note_path != ? AND wikilinks_json LIKE ?",
            (anchor_path, f'%{anchor_title}%'),
        ):
            links = {str(t) for t in _json_tuple(row["wikilinks_json"])}
            if links & anchor_link_keys and row["note_path"] not in inbound_paths:
                inbound_paths.append(row["note_path"])

        neighbors: list[dict[str, object]] = []
        seen_paths: set[str] = {anchor_path}

        def resolve_note(link_or_path: str) -> sqlite3.Row | None:
            cand = link_or_path if link_or_path.endswith(".md") else f"{link_or_path}.md"
            return conn.execute(
                "SELECT note_path, title, folder, domain_json, summary FROM vault_notes "
                "WHERE note_path = ? OR title = ? LIMIT 1",
                (cand, link_or_path),
            ).fetchone()

        def add_neighbor(link_or_path: str, direction: str) -> None:
            row = resolve_note(link_or_path)
            if row is None or row["note_path"] in seen_paths:
                return
            seen_paths.add(row["note_path"])
            ndomain = list(_json_tuple(row["domain_json"]))
            shared_domain = bool(set(ndomain) & set(anchor_domain))
            neighbors.append({
                "note_path": row["note_path"],
                "title": row["title"],
                "folder": row["folder"],
                "domain": ndomain,
                "summary": row["summary"],
                "direction": direction,
                "edge_type": _infer_edge_type(row["folder"], row["title"], direction),
                "edge_type_inferred": True,
                "shared_domain": shared_domain,
            })

        for target in outbound_targets:
            add_neighbor(target, "outbound")
        for path in inbound_paths:
            add_neighbor(path, "inbound")

        # Branching cap: prioritize same-domain Concepts/part-of edges, then the rest.
        neighbors.sort(key=lambda n: (
            0 if n["shared_domain"] else 1,
            0 if n["edge_type"] in ("part-of", "contrasts-with") else 1,
            str(n["title"]),
        ))
        capped = neighbors[:max(0, max_neighbors)]

        acgme = (
            _acgme_neighbors(catalog_path, anchor_title, anchor_domain, max_neighbors)
            if include_acgme else []
        )

    return {
        "ok": True,
        "anchor": {"note_path": anchor_path, "title": anchor_title, "domain": anchor_domain},
        "max_neighbors": max_neighbors,
        "neighbor_count": len(capped),
        "neighbors_available": len(neighbors),
        "neighbors": capped,
        "acgme_neighbors": acgme,
        "adjacency_source": "vault_wikilinks+acgme_catalog",
        "knowledge_boundary": KNOWLEDGE_BOUNDARY,
    }


def get_section(
    *,
    db_path: Path = DEFAULT_INDEX_DB,
    note: str,
    section_type: str = "",
    heading: str = "",
) -> dict[str, object]:
    where = ["(s.note_path = ? OR s.title = ?)"]
    params: list[object] = [note, note]
    if section_type:
        where.append("s.section_type = ?")
        params.append(section_type)
    if heading:
        where.append("LOWER(s.section_heading) = LOWER(?)")
        params.append(heading)
    sql = "SELECT s.* FROM vault_sections s WHERE " + " AND ".join(where) + " ORDER BY s.ordinal"
    with _connect(db_path) as conn:
        hits = [_row_to_section(row, score=1.0) for row in conn.execute(sql, params)]
    return {"ok": bool(hits), "hits": hits, "count": len(hits), "knowledge_boundary": KNOWLEDGE_BOUNDARY}


def task_plan(task: str) -> dict[str, object]:
    return {
        "ok": task in TASK_SECTION_POLICY,
        "task": task,
        "preferred_section_types": list(_preferred_section_types(task)),
        "knowledge_boundary": KNOWLEDGE_BOUNDARY,
    }


def index_status(*, db_path: Path = DEFAULT_INDEX_DB) -> dict[str, object]:
    with _connect(db_path) as conn:
        note_count = int(conn.execute("SELECT COUNT(*) FROM vault_notes").fetchone()[0])
        section_count = int(conn.execute("SELECT COUNT(*) FROM vault_sections").fetchone()[0])
        by_folder = [
            {"folder": row["folder"], "notes": int(row["notes"])}
            for row in conn.execute(
                "SELECT folder, COUNT(*) AS notes FROM vault_notes GROUP BY folder ORDER BY folder"
            )
        ]
        by_section_type = [
            {"section_type": row["section_type"], "sections": int(row["sections"])}
            for row in conn.execute(
                "SELECT section_type, COUNT(*) AS sections FROM vault_sections GROUP BY section_type ORDER BY sections DESC, section_type"
            )
        ]
        indexed_at = conn.execute("SELECT MAX(indexed_at) FROM vault_sections").fetchone()[0] or ""
    return {
        "ok": True,
        "db_path": str(db_path),
        "notes_indexed": note_count,
        "sections_indexed": section_count,
        "indexed_at": indexed_at,
        "by_folder": by_folder,
        "by_section_type": by_section_type,
        "knowledge_boundary": KNOWLEDGE_BOUNDARY,
    }


def _embedding_text(row: sqlite3.Row) -> str:
    return "\n".join(
        [
            f"Title: {row['title']}",
            f"Folder: {row['folder']}",
            f"Section: {row['section_heading']} ({row['section_type']})",
            f"Summary: {row['summary']}",
            row["text"],
        ]
    ).strip()


def _embedding_device() -> str:
    try:
        import torch

        return "mps" if torch.backends.mps.is_available() else "cpu"
    except Exception:
        return "cpu"


def _load_embedding_model(device: str = ""):
    model_name_or_path = BGE_M3_MODEL_ID
    if MODEL_LOAD_LOCAL_ONLY:
        from retrieval.pipeline import _bge_cache_status

        status = _bge_cache_status(cache_dir=MODEL_CACHE_DIR)
        if not status.get("ok"):
            raise RuntimeError(
                "BGE-M3 local cache is incomplete; run `python3 src/lance_retriever.py warmup --download` "
                "with network access before syncing the vault LanceDB table."
            )
        snapshot = Path(str(status.get("snapshot", "")))
        required = ("config.json", "tokenizer_config.json")
        missing = [name for name in required if not (snapshot / name).exists()]
        if missing:
            raise RuntimeError(
                "BGE-M3 local cache is missing tokenizer/config files required for offline vault embeddings: "
                + ", ".join(missing)
            )
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        model_name_or_path = str(snapshot)
    from FlagEmbedding import BGEM3FlagModel

    return BGEM3FlagModel(
        model_name_or_path,
        use_fp16=True,
        cache_dir=str(MODEL_CACHE_DIR),
        devices=device or _embedding_device(),
    )


def _encode_passages(texts: list[str], *, batch_size: int = 16, device: str = "") -> list[list[float]]:
    model = _load_embedding_model(device=device)
    out = model.encode(
        texts,
        batch_size=batch_size,
        max_length=512,
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    return [vec.astype("float32").tolist() for vec in out["dense_vecs"]]


def _encode_passages_quiet(texts: list[str], *, batch_size: int = 16, device: str = "") -> list[list[float]]:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return _encode_passages(texts, batch_size=batch_size, device=device)


def sync_lance(
    *,
    db_path: Path = DEFAULT_INDEX_DB,
    lance_dir: Path = DEFAULT_LANCE_DIR,
    table_name: str = DEFAULT_LANCE_TABLE,
    replace: bool = True,
    batch_size: int = 16,
    device: str = "",
) -> dict[str, object]:
    with _connect(db_path) as conn:
        rows = list(conn.execute("SELECT * FROM vault_sections ORDER BY note_path, ordinal"))
    texts = [_embedding_text(row) for row in rows]
    vectors = _encode_passages_quiet(texts, batch_size=batch_size, device=device)
    records: list[dict[str, object]] = []
    for row, vector, embedding_text in zip(rows, vectors, texts):
        records.append(
            {
                "section_id": row["section_id"],
                "note_path": row["note_path"],
                "title": row["title"],
                "folder": row["folder"],
                "note_type": row["note_type"],
                "domain_json": row["domain_json"],
                "summary": row["summary"],
                "section_heading": row["section_heading"],
                "section_type": row["section_type"],
                "section_path": row["section_path"],
                "text": row["text"],
                "embedding_text": embedding_text,
                "wikilinks_json": row["wikilinks_json"],
                "references_json": row["references_json"],
                "provenance_tier": row["provenance_tier"],
                "source_role": row["source_role"],
                "dense_vec": vector,
            }
        )
    import lancedb
    import pyarrow as pa

    db = lancedb.connect(str(lance_dir))
    existing = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
    existing_names = list(existing.tables) if hasattr(existing, "tables") else list(existing)
    if replace and table_name in existing_names:
        db.drop_table(table_name)
    if records:
        vector_dim = len(records[0]["dense_vec"])
        schema = pa.schema(
            [
                pa.field("section_id", pa.string()),
                pa.field("note_path", pa.string()),
                pa.field("title", pa.string()),
                pa.field("folder", pa.string()),
                pa.field("note_type", pa.string()),
                pa.field("domain_json", pa.string()),
                pa.field("summary", pa.string()),
                pa.field("section_heading", pa.string()),
                pa.field("section_type", pa.string()),
                pa.field("section_path", pa.string()),
                pa.field("text", pa.string()),
                pa.field("embedding_text", pa.string()),
                pa.field("wikilinks_json", pa.string()),
                pa.field("references_json", pa.string()),
                pa.field("provenance_tier", pa.string()),
                pa.field("source_role", pa.string()),
                pa.field("dense_vec", pa.list_(pa.float32(), vector_dim)),
            ]
        )
        db.create_table(
            table_name,
            data=pa.Table.from_pylist(records, schema=schema),
            mode="overwrite" if replace else "create",
        )
    return {
        "ok": True,
        "lance_dir": str(lance_dir),
        "table": table_name,
        "sections_embedded": len(records),
        "device": device or _embedding_device(),
        "knowledge_boundary": KNOWLEDGE_BOUNDARY,
    }


def search_lance(
    query: str,
    *,
    lance_dir: Path = DEFAULT_LANCE_DIR,
    table_name: str = DEFAULT_LANCE_TABLE,
    folders: tuple[str, ...] = (),
    section_types: tuple[str, ...] = (),
    limit: int = 5,
    device: str = "",
) -> dict[str, object]:
    vector = _encode_passages_quiet([query], batch_size=1, device=device)[0]
    import lancedb

    db = lancedb.connect(str(lance_dir))
    table = db.open_table(table_name)
    rows = (
        table.search(vector, vector_column_name="dense_vec")
        .metric("cosine")
        .limit(max(limit * 4, 20))
        .to_list()
    )
    hits = []
    for row in rows:
        if folders and row.get("folder") not in folders:
            continue
        if section_types and row.get("section_type") not in section_types:
            continue
        distance = float(row.get("_distance", 1.0))
        similarity = 1.0 - (distance / 2.0)
        hits.append(
            {
                "section_id": row.get("section_id", ""),
                "note_path": row.get("note_path", ""),
                "title": row.get("title", ""),
                "folder": row.get("folder", ""),
                "note_type": row.get("note_type", ""),
                "summary": row.get("summary", ""),
                "section_heading": row.get("section_heading", ""),
                "section_type": row.get("section_type", ""),
                "section_path": row.get("section_path", ""),
                "text": row.get("text", ""),
                "references": json.loads(row.get("references_json") or "[]"),
                "wikilinks": json.loads(row.get("wikilinks_json") or "[]"),
                "provenance_tier": row.get("provenance_tier", ""),
                "source_role": row.get("source_role", ""),
                "score": round(similarity, 4),
            }
        )
        if len(hits) >= limit:
            break
    return {
        "ok": True,
        "query": query,
        "hits": hits,
        "count": len(hits),
        "retriever": "lancedb",
        "knowledge_boundary": KNOWLEDGE_BOUNDARY,
    }


def _packet_text(text: object, *, limit: int = PACKET_TEXT_LIMIT) -> tuple[str, bool]:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw, False
    boundary = raw.rfind("\n", 0, limit)
    if boundary < max(240, limit // 2):
        boundary = raw.rfind(". ", 0, limit)
    if boundary < max(240, limit // 2):
        boundary = limit
    return raw[:boundary].rstrip() + " ...", True


def _compact_hit(hit: dict[str, object]) -> dict[str, object]:
    text, truncated = _packet_text(hit.get("text", ""))
    note = hit.get("note_path", "")
    section_type = hit.get("section_type", "")
    return {
        "ref": hit.get("section_path", ""),
        "note": note,
        "title": hit.get("title", ""),
        "folder": hit.get("folder", ""),
        "section_type": section_type,
        "heading": hit.get("section_heading", ""),
        "summary": hit.get("summary", ""),
        "text": text,
        "text_truncated": truncated,
        "full_text_command": (
            f'python3 src/vault_retriever.py get --note "{note}" --section-type {section_type}'
            if truncated and note and section_type
            else ""
        ),
        "provenance_tier": hit.get("provenance_tier", ""),
        "source_role": hit.get("source_role", ""),
        "wikilinks": hit.get("wikilinks", []),
        "references": hit.get("references", []),
    }


def _merge_retrieval_hits(
    *,
    sqlite_hits: list[dict[str, object]],
    vector_hits: list[dict[str, object]],
    limit: int,
) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for retriever, hits in (("sqlite", sqlite_hits), ("lance", vector_hits)):
        for hit in hits:
            key = str(hit.get("section_id") or hit.get("section_path") or hit.get("note_path"))
            if key not in merged:
                merged[key] = _compact_hit(hit)
                merged[key]["retrievers"] = []
                merged[key]["scores"] = {}
                order.append(key)
            retrievers = merged[key]["retrievers"]
            if isinstance(retrievers, list) and retriever not in retrievers:
                retrievers.append(retriever)
            scores = merged[key]["scores"]
            if isinstance(scores, dict):
                scores[retriever] = hit.get("score", 0)
    rows = list(merged.values())
    rows.sort(
        key=lambda item: (
            len(item.get("retrievers", [])) if isinstance(item.get("retrievers"), list) else 0,
            max(
                float(score)
                for score in (item.get("scores", {}) or {"_": 0}).values()
                if isinstance(score, (int, float))
            ),
        ),
        reverse=True,
    )
    if not rows:
        return []
    ordered_rows = rows[:limit]
    if len(ordered_rows) < min(limit, len(order)):
        seen = {str(row.get("ref")) for row in ordered_rows}
        for key in order:
            row = merged[key]
            if str(row.get("ref")) not in seen:
                ordered_rows.append(row)
            if len(ordered_rows) >= limit:
                break
    return ordered_rows[:limit]


def _field_context(hits: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    context: dict[str, list[dict[str, object]]] = {}
    for hit in hits:
        section_type = str(hit.get("section_type") or "general_content")
        context.setdefault(section_type, []).append(
            {
                "ref": hit.get("ref", ""),
                "title": hit.get("title", ""),
                "provenance_tier": hit.get("provenance_tier", ""),
                "retrievers": hit.get("retrievers", []),
            }
        )
    return context


def _hit_refs(hits: list[dict[str, object]]) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for hit in hits:
        refs.append(
            {
                "ref": hit.get("section_path", ""),
                "title": hit.get("title", ""),
                "section_type": hit.get("section_type", ""),
                "score": hit.get("score", 0),
            }
        )
    return refs


def recall_packet(
    query: str,
    *,
    db_path: Path = DEFAULT_INDEX_DB,
    lance_dir: Path = DEFAULT_LANCE_DIR,
    table_name: str = DEFAULT_LANCE_TABLE,
    task: str = "",
    folders: tuple[str, ...] = (),
    domains: tuple[str, ...] = (),
    section_types: tuple[str, ...] = (),
    note_types: tuple[str, ...] = (),
    statuses: tuple[str, ...] = (),
    institutions: tuple[str, ...] = (),
    services: tuple[str, ...] = (),
    rotations: tuple[str, ...] = (),
    conferences: tuple[str, ...] = (),
    include_local: bool = True,
    strict_fields: bool = False,
    sqlite_limit: int = 6,
    vector_limit: int = 6,
    limit: int = 8,
    device: str = "",
) -> dict[str, object]:
    preferred = _preferred_section_types(task)
    sqlite = search_sections(
        query,
        db_path=db_path,
        task=task,
        folders=folders,
        domains=domains,
        section_types=section_types,
        note_types=note_types,
        statuses=statuses,
        institutions=institutions,
        services=services,
        rotations=rotations,
        conferences=conferences,
        include_local=include_local,
        strict_fields=strict_fields,
        limit=sqlite_limit,
    )
    vector_filter = section_types or (preferred if strict_fields else ())
    try:
        vector = search_lance(
            query,
            lance_dir=lance_dir,
            table_name=table_name,
            folders=folders,
            section_types=vector_filter,
            limit=vector_limit,
            device=device,
        )
    except Exception as exc:
        vector = {
            "ok": False,
            "query": query,
            "hits": [],
            "count": 0,
            "retriever": "lancedb",
            "error": str(exc),
            "knowledge_boundary": KNOWLEDGE_BOUNDARY,
        }
    merged_hits = _merge_retrieval_hits(
        sqlite_hits=list(sqlite.get("hits", [])),
        vector_hits=list(vector.get("hits", [])),
        limit=limit,
    )
    sqlite_ok = bool(sqlite.get("ok"))
    vector_ok = bool(vector.get("ok"))
    if sqlite_ok and vector_ok:
        retrieval_status = "complete"
    elif merged_hits and (sqlite_ok or vector_ok):
        retrieval_status = "partial"
    else:
        retrieval_status = "failed"
    warnings: list[str] = []
    if not sqlite_ok:
        warnings.append("SQLite field-aware retrieval failed.")
    if not vector_ok:
        vector_error = str(vector.get("error", "")).strip()
        warnings.append(
            "LanceDB semantic retrieval failed"
            + (f": {vector_error}" if vector_error else ".")
        )
    return {
        "ok": retrieval_status != "failed",
        "schema": "vault_intelligence_compact_v1",
        "query": query,
        "task": task,
        "retrieval_status": retrieval_status,
        "warnings": warnings,
        "retrieval_plan": {
            "sqlite": "field-aware FTS over data/vault_index.db",
            "vector": f"LanceDB semantic search over {table_name}",
            "combined": True,
            "strict_fields": strict_fields,
            "include_local": include_local,
        },
        "preferred_section_types": list(preferred),
        "sqlite": {
            "ok": bool(sqlite.get("ok")),
            "count": sqlite.get("count", 0),
            "refs": _hit_refs(list(sqlite.get("hits", []))),
        },
        "vector": {
            "ok": bool(vector.get("ok")),
            "count": vector.get("count", 0),
            "error": vector.get("error", ""),
            "refs": _hit_refs(list(vector.get("hits", []))),
        },
        "merged_hits": merged_hits,
        "field_context": _field_context(merged_hits),
        "knowledge_boundary": KNOWLEDGE_BOUNDARY,
    }


def _split_arg(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile and query the Obsidian vault intelligence index")
    parser.add_argument("--db", default=str(DEFAULT_INDEX_DB))
    parser.add_argument("--vault-root", default=str(DEFAULT_VAULT_ROOT))
    parser.add_argument("--pretty", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sync_parser = sub.add_parser("sync")
    sync_parser.add_argument("--folders", default="")
    sync_parser.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)

    search_parser = sub.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--task", default="")
    search_parser.add_argument("--folder", default="")
    search_parser.add_argument("--domain", default="")
    search_parser.add_argument("--section-type", default="")
    search_parser.add_argument("--note-type", default="")
    search_parser.add_argument("--status", default="")
    search_parser.add_argument("--institution", default="")
    search_parser.add_argument("--service", default="")
    search_parser.add_argument("--rotation", default="")
    search_parser.add_argument("--conference", default="")
    search_parser.add_argument("--limit", type=int, default=5)
    search_parser.add_argument("--strict-fields", action="store_true")
    search_parser.add_argument("--exclude-local", action="store_true")
    search_parser.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)

    recall_parser = sub.add_parser("recall")
    recall_parser.add_argument("query")
    recall_parser.add_argument("--task", default="")
    recall_parser.add_argument("--folder", default="")
    recall_parser.add_argument("--domain", default="")
    recall_parser.add_argument("--section-type", default="")
    recall_parser.add_argument("--note-type", default="")
    recall_parser.add_argument("--status", default="")
    recall_parser.add_argument("--institution", default="")
    recall_parser.add_argument("--service", default="")
    recall_parser.add_argument("--rotation", default="")
    recall_parser.add_argument("--conference", default="")
    recall_parser.add_argument("--limit", type=int, default=8)
    recall_parser.add_argument("--sqlite-limit", type=int, default=6)
    recall_parser.add_argument("--vector-limit", type=int, default=6)
    recall_parser.add_argument("--strict-fields", action="store_true")
    recall_parser.add_argument("--exclude-local", action="store_true")
    recall_parser.add_argument("--lance-dir", default=str(DEFAULT_LANCE_DIR))
    recall_parser.add_argument("--table", default=DEFAULT_LANCE_TABLE)
    recall_parser.add_argument("--device", default="")
    recall_parser.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)

    get_parser = sub.add_parser("get")
    get_parser.add_argument("--note", required=True)
    get_parser.add_argument("--section-type", default="")
    get_parser.add_argument("--heading", default="")
    get_parser.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)

    landscape_parser = sub.add_parser("landscape")
    landscape_parser.add_argument("--note", required=True)
    landscape_parser.add_argument("--max-neighbors", type=int, default=8)
    landscape_parser.add_argument("--no-acgme", action="store_true")
    landscape_parser.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)

    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("task")
    plan_parser.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)

    status_parser = sub.add_parser("status")
    status_parser.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)

    lance_sync = sub.add_parser("sync-lance")
    lance_sync.add_argument("--lance-dir", default=str(DEFAULT_LANCE_DIR))
    lance_sync.add_argument("--table", default=DEFAULT_LANCE_TABLE)
    lance_sync.add_argument("--append", action="store_true")
    lance_sync.add_argument("--batch-size", type=int, default=16)
    lance_sync.add_argument("--device", default="")
    lance_sync.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)

    lance_search = sub.add_parser("search-lance")
    lance_search.add_argument("query")
    lance_search.add_argument("--lance-dir", default=str(DEFAULT_LANCE_DIR))
    lance_search.add_argument("--table", default=DEFAULT_LANCE_TABLE)
    lance_search.add_argument("--folder", default="")
    lance_search.add_argument("--section-type", default="")
    lance_search.add_argument("--limit", type=int, default=5)
    lance_search.add_argument("--device", default="")
    lance_search.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS)

    args = parser.parse_args()
    db_path = Path(args.db)
    if args.command == "sync":
        folders = _split_arg(args.folders) or INDEX_FOLDERS
        payload = sync_vault(vault_root=Path(args.vault_root), db_path=db_path, folders=folders)
    elif args.command == "search":
        payload = search_sections(
            args.query,
            db_path=db_path,
            task=args.task,
            folders=_split_arg(args.folder),
            domains=_split_arg(args.domain),
            section_types=_split_arg(args.section_type),
            note_types=_split_arg(args.note_type),
            statuses=_split_arg(args.status),
            institutions=_split_arg(args.institution),
            services=_split_arg(args.service),
            rotations=_split_arg(args.rotation),
            conferences=_split_arg(args.conference),
            include_local=not args.exclude_local,
            strict_fields=args.strict_fields,
            limit=args.limit,
        )
    elif args.command == "recall":
        payload = recall_packet(
            args.query,
            db_path=db_path,
            lance_dir=Path(args.lance_dir),
            table_name=args.table,
            task=args.task,
            folders=_split_arg(args.folder),
            domains=_split_arg(args.domain),
            section_types=_split_arg(args.section_type),
            note_types=_split_arg(args.note_type),
            statuses=_split_arg(args.status),
            institutions=_split_arg(args.institution),
            services=_split_arg(args.service),
            rotations=_split_arg(args.rotation),
            conferences=_split_arg(args.conference),
            include_local=not args.exclude_local,
            strict_fields=args.strict_fields,
            sqlite_limit=args.sqlite_limit,
            vector_limit=args.vector_limit,
            limit=args.limit,
            device=args.device,
        )
    elif args.command == "get":
        payload = get_section(
            db_path=db_path,
            note=args.note,
            section_type=args.section_type,
            heading=args.heading,
        )
    elif args.command == "landscape":
        payload = landscape_map(
            db_path=db_path,
            note=args.note,
            max_neighbors=args.max_neighbors,
            include_acgme=not args.no_acgme,
        )
    elif args.command == "plan":
        payload = task_plan(args.task)
    elif args.command == "status":
        payload = index_status(db_path=db_path)
    elif args.command == "sync-lance":
        payload = sync_lance(
            db_path=db_path,
            lance_dir=Path(args.lance_dir),
            table_name=args.table,
            replace=not args.append,
            batch_size=args.batch_size,
            device=args.device,
        )
    else:
        payload = search_lance(
            args.query,
            lance_dir=Path(args.lance_dir),
            table_name=args.table,
            folders=_split_arg(args.folder),
            section_types=_split_arg(args.section_type),
            limit=args.limit,
            device=args.device,
        )
    print(_json_dumps(payload, pretty=args.pretty))
    if not payload.get("ok", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
