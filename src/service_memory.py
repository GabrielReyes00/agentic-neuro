#!/usr/bin/env python3
"""Service-rotation learning helpers for the study memory ledger."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CURRICULUM_CATALOG_PATH = DATA_DIR / "acgme_curriculum.json"

SERVICE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL,
    site_id INTEGER NOT NULL,
    pgy INTEGER,
    block_label TEXT NOT NULL DEFAULT '',
    started TEXT NOT NULL DEFAULT '',
    ended TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(service_id) REFERENCES services(id),
    FOREIGN KEY(site_id) REFERENCES sites(id)
);
CREATE INDEX IF NOT EXISTS idx_memory_rotations_service ON rotations(service_id);
CREATE INDEX IF NOT EXISTS idx_memory_rotations_active ON rotations(active);

CREATE TABLE IF NOT EXISTS competency_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL,
    slug TEXT NOT NULL,
    text TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'acgme' CHECK(origin IN ('acgme', 'chief', 'attending', 'emergent')),
    pgy_target INTEGER,
    priority TEXT NOT NULL DEFAULT 'core',
    status TEXT NOT NULL DEFAULT 'open',
    site_id INTEGER,
    created_at TEXT NOT NULL DEFAULT '',
    UNIQUE(service_id, slug),
    FOREIGN KEY(service_id) REFERENCES services(id),
    FOREIGN KEY(site_id) REFERENCES sites(id)
);
CREATE INDEX IF NOT EXISTS idx_memory_competency_targets_service ON competency_targets(service_id);
"""

SERVICE_ALIASES = {
    "onc": "tumor", "oncology": "tumor", "neuro onc": "tumor",
    "neuro oncology": "tumor", "neurooncology": "tumor", "brain tumor": "tumor",
    "peds": "pediatric", "pediatrics": "pediatric", "pediatric": "pediatric",
    "neurocritical care": "critical-care", "neurocritical": "critical-care",
    "nccu": "critical-care", "icu": "critical-care", "critical care": "critical-care",
    "epilepsy": "functional", "movement": "functional",
    "movement disorders": "functional", "dbs": "functional", "stereotactic": "functional",
    "nerve": "peripheral-nerve", "peripheral nerve": "peripheral-nerve",
    "endovascular": "vascular", "cerebrovascular": "vascular", "open vascular": "vascular",
}

SITE_ALIASES = {
    "va": "va", "michael e debakey va": "va", "debakey va": "va", "debakey": "va", "mevamc": "va",
    "tch": "texas-childrens", "texas children s": "texas-childrens",
    "texas childrens": "texas-childrens", "childrens": "texas-childrens",
    "ben taub": "ben-taub", "bt": "ben-taub", "bentaub": "ben-taub",
    "md anderson": "md-anderson", "mda": "md-anderson", "anderson": "md-anderson",
    "st luke s": "st-lukes", "st lukes": "st-lukes", "saint lukes": "st-lukes",
    "st luke": "st-lukes", "baylor st lukes": "st-lukes", "bslmc": "st-lukes",
}

SITE_DISPLAY = {
    "va": "Michael E. DeBakey VA Medical Center",
    "texas-childrens": "Texas Children's Hospital",
    "ben-taub": "Ben Taub Hospital",
    "md-anderson": "MD Anderson Cancer Center",
    "st-lukes": "Baylor St. Luke's Medical Center",
}


def _normalize(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^\w\s\-/]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _slug(text: str) -> str:
    out = _normalize(text).replace("/", " ").replace("-", " ")
    out = re.sub(r"\s+", "-", out).strip("-")
    return out or "uncategorized"


def _display(text: str) -> str:
    keep_upper = {"tbi", "evd", "sah", "ich", "dci", "icp", "cpp", "avm", "mri", "ct", "cta", "dsa"}
    return " ".join(w.upper() if w in keep_upper else w.capitalize() for w in _normalize(text.replace("-", " ")).split())


def _domain_from_catalog(domain_name: str) -> str:
    hay = _normalize(domain_name)
    table = (
        ("vascular", "vascular"), ("spine", "spine"), ("tumor", "tumor"),
        ("trauma", "trauma"), ("functional", "functional"), ("pediatric", "pediatric"),
        ("peripheral nerve", "peripheral-nerve"), ("anatomy", "anatomy"),
        ("neuroimaging", "imaging"), ("imaging", "imaging"), ("critical care", "critical-care"),
    )
    for needle, tag in table:
        if needle in hay:
            return tag
    return "general"


def _normalize_service(raw: str) -> str:
    base = re.sub(r"\b(service|rotation|team)\b", " ", _normalize(raw))
    base = re.sub(r"\s+", " ", base).strip()
    if base in SERVICE_ALIASES:
        return SERVICE_ALIASES[base]
    domain = _domain_from_catalog(base)
    if domain != "general":
        return domain
    return _slug(base)


def _normalize_site(raw: str) -> str:
    base = re.sub(r"\b(hospital|medical center|the)\b", " ", _normalize(raw))
    base = re.sub(r"\s+", " ", base).strip()
    return SITE_ALIASES.get(base, _slug(base))


def _resolve_or_create_service(conn: sqlite3.Connection, raw: str, now: str) -> sqlite3.Row:
    slug = _normalize_service(raw)
    row = conn.execute("SELECT * FROM services WHERE slug = ?", (slug,)).fetchone()
    if row:
        return row
    conn.execute(
        "INSERT INTO services (slug, display_name, domain, created_at) VALUES (?, ?, ?, ?)",
        (slug, _display(slug), slug, now),
    )
    return conn.execute("SELECT * FROM services WHERE slug = ?", (slug,)).fetchone()


def _resolve_or_create_site(conn: sqlite3.Connection, raw: str, now: str) -> sqlite3.Row:
    slug = _normalize_site(raw)
    row = conn.execute("SELECT * FROM sites WHERE slug = ?", (slug,)).fetchone()
    if row:
        return row
    conn.execute(
        "INSERT INTO sites (slug, display_name, created_at) VALUES (?, ?, ?)",
        (slug, SITE_DISPLAY.get(slug, _display(slug)), now),
    )
    return conn.execute("SELECT * FROM sites WHERE slug = ?", (slug,)).fetchone()


def service_for_rotation(conn: sqlite3.Connection, rotation_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT s.* FROM services s
             JOIN rotations r ON r.service_id = s.id
            WHERE r.id = ?""",
        (int(rotation_id),),
    ).fetchone()


def site_for_rotation(conn: sqlite3.Connection, rotation_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT st.* FROM sites st
             JOIN rotations r ON r.site_id = st.id
            WHERE r.id = ?""",
        (int(rotation_id),),
    ).fetchone()


def _seed_service_rubric(
    conn: sqlite3.Connection, *, service_id: int, service_domain: str, pgy: int | None, now: str
) -> int:
    try:
        data = json.loads(CURRICULUM_CATALOG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return 0
    seeded = 0
    for milestone in data.get("milestones", {}).values():
        for topic in milestone.get("topics", []):
            title = str(topic.get("title") or "").strip()
            if not title or _domain_from_catalog(str(topic.get("domain") or "")) != service_domain:
                continue
            target = topic.get("pgy_target")
            if pgy is not None and isinstance(target, int) and target > pgy:
                continue
            cur = conn.execute(
                """INSERT OR IGNORE INTO competency_targets
                   (service_id, slug, text, domain, origin, pgy_target, priority, status, created_at)
                   VALUES (?, ?, ?, ?, 'acgme', ?, ?, 'open', ?)""",
                (
                    service_id, _slug(title), title, service_domain,
                    target if isinstance(target, int) else None,
                    str(topic.get("priority") or "core"), now,
                ),
            )
            seeded += cur.rowcount
    return seeded


def _rotation_view(conn: sqlite3.Connection, row: sqlite3.Row | None) -> dict[str, object] | None:
    if row is None:
        return None
    service = conn.execute("SELECT slug, display_name, domain FROM services WHERE id = ?", (row["service_id"],)).fetchone()
    site = conn.execute("SELECT slug, display_name FROM sites WHERE id = ?", (row["site_id"],)).fetchone()
    return {
        "rotation_id": int(row["id"]),
        "service": service["slug"] if service else "",
        "service_display": service["display_name"] if service else "",
        "domain": service["domain"] if service else "",
        "site": site["slug"] if site else "",
        "site_display": site["display_name"] if site else "",
        "pgy": row["pgy"],
        "block_label": row["block_label"],
        "started": row["started"],
        "ended": row["ended"],
        "active": bool(row["active"]),
    }


def start_rotation(
    conn: sqlite3.Connection, *, service: str, site: str,
    pgy: int | None = None, block_label: str = "", now: str | None = None,
) -> dict[str, object]:
    now = now or datetime.now(timezone.utc).isoformat()
    service_row = _resolve_or_create_service(conn, service, now)
    site_row = _resolve_or_create_site(conn, site, now)
    existing_targets = int(
        conn.execute("SELECT COUNT(*) FROM competency_targets WHERE service_id = ?", (service_row["id"],)).fetchone()[0]
    )
    seeded = 0
    if existing_targets == 0:
        seeded = _seed_service_rubric(
            conn, service_id=int(service_row["id"]), service_domain=service_row["domain"], pgy=pgy, now=now
        )
    conn.execute("UPDATE rotations SET active = 0 WHERE active = 1")
    conn.execute(
        """INSERT INTO rotations (service_id, site_id, pgy, block_label, started, active)
           VALUES (?, ?, ?, ?, ?, 1)""",
        (service_row["id"], site_row["id"], pgy, block_label, now),
    )
    rotation_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    view = _rotation_view(conn, conn.execute("SELECT * FROM rotations WHERE id = ?", (rotation_id,)).fetchone())
    assert view is not None
    view["rubric_seeded"] = seeded
    view["rubric_total"] = existing_targets + seeded
    return view


def current_rotation(conn: sqlite3.Connection) -> dict[str, object] | None:
    row = conn.execute("SELECT * FROM rotations WHERE active = 1 ORDER BY id DESC LIMIT 1").fetchone()
    return _rotation_view(conn, row)


def list_rotations(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute("SELECT * FROM rotations ORDER BY active DESC, id DESC").fetchall()
    return [view for view in (_rotation_view(conn, r) for r in rows) if view is not None]


def end_rotation(conn: sqlite3.Connection, *, rotation_id: int, now: str | None = None) -> dict[str, object] | None:
    now = now or datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE rotations SET active = 0, ended = ? WHERE id = ?", (now, int(rotation_id)))
    conn.commit()
    return _rotation_view(conn, conn.execute("SELECT * FROM rotations WHERE id = ?", (int(rotation_id),)).fetchone())


def service_rubric_view(
    conn: sqlite3.Connection, *, service: str, seed: bool = False, pgy: int | None = None
) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    service_row = _resolve_or_create_service(conn, service, now)
    seeded = 0
    if seed:
        seeded = _seed_service_rubric(
            conn, service_id=int(service_row["id"]), service_domain=service_row["domain"], pgy=pgy, now=now
        )
        conn.commit()
    targets = conn.execute(
        """SELECT slug, text, origin, pgy_target, priority, status, site_id
             FROM competency_targets WHERE service_id = ?
            ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'developing' THEN 1 ELSE 2 END,
                     CASE priority WHEN 'core' THEN 0 WHEN 'important' THEN 1 ELSE 2 END,
                     pgy_target ASC, slug ASC""",
        (service_row["id"],),
    ).fetchall()
    status_counts: dict[str, int] = {}
    for target in targets:
        status = str(target["status"] or "open")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "service": service_row["slug"],
        "service_display": service_row["display_name"],
        "domain": service_row["domain"],
        "rubric_seeded": seeded,
        "counts": {"total": len(targets), **status_counts},
        "competency_targets": [
            {
                "slug": t["slug"], "text": t["text"], "origin": t["origin"],
                "pgy_target": t["pgy_target"], "priority": t["priority"], "status": t["status"],
            }
            for t in targets
        ],
    }


def mark_competency_developing(
    conn: sqlite3.Connection, *, service_id: int, target: str
) -> None:
    """Advance a touched service rubric target without claiming completion."""
    conn.execute(
        """UPDATE competency_targets SET status = 'developing'
           WHERE service_id = ? AND slug = ? AND status = 'open'""",
        (service_id, _slug(target)),
    )


def service_recall(
    conn: sqlite3.Connection, *, service: str = "", site: str = "",
    rotation_id: int | None = None, context: str = "", limit: int = 8,
) -> str:
    limit = max(0, limit)
    rotation = None
    if rotation_id:
        rotation = conn.execute("SELECT * FROM rotations WHERE id = ?", (int(rotation_id),)).fetchone()
    elif not service:
        rotation = conn.execute("SELECT * FROM rotations WHERE active = 1 ORDER BY id DESC LIMIT 1").fetchone()
    if rotation is not None:
        service_row = conn.execute("SELECT * FROM services WHERE id = ?", (rotation["service_id"],)).fetchone()
        site_row = conn.execute("SELECT * FROM sites WHERE id = ?", (rotation["site_id"],)).fetchone()
    else:
        service_row = (
            conn.execute("SELECT * FROM services WHERE slug = ?", (_normalize_service(service),)).fetchone()
            if service else None
        )
        site_row = (
            conn.execute("SELECT * FROM sites WHERE slug = ?", (_normalize_site(site),)).fetchone()
            if site else None
        )
        if service_row is not None:
            params: list[object] = [int(service_row["id"])]
            site_clause = ""
            if site_row is not None:
                site_clause = "AND site_id = ?"
                params.append(int(site_row["id"]))
            rotation = conn.execute(
                f"""SELECT * FROM rotations
                      WHERE active = 1 AND service_id = ? {site_clause}
                      ORDER BY id DESC LIMIT 1""",
                params,
            ).fetchone()
    if service_row is None:
        return json.dumps({
            "lens": "service",
            "resolution_warning": f"No service resolved for {service or 'active rotation'!r}. "
                                  "Start a rotation with rotation-start or pass --service.",
            "rotation": None,
            "service_gaps": [], "conventions": [], "formal_secondary": [], "rubric_open": [],
            "pending_review_candidates": [],
            "rubric_progress": {"total": 0, "open": 0, "developing": 0, "completed": 0},
            "data_quality_warnings": [],
            "counts": {
                "service_gaps": 0, "conventions": 0, "formal_secondary": 0,
                "rubric_open": 0, "pending_review_candidates": 0,
                "unmapped_review_candidates": 0,
            },
        }, indent=2)

    service_id = int(service_row["id"])
    domain = service_row["domain"]
    current_site_id = int(site_row["id"]) if site_row else None

    gap_rows = conn.execute(
        """SELECT cs.id, cs.claim_text, cs.state, cs.priority, cs.next_due_ts,
                  cs.rotation_id, t.canonical_slug AS topic, c.display_name AS concept
             FROM claim_state cs
             JOIN rotations r ON r.id = cs.rotation_id
             JOIN topics t ON t.id = cs.topic_id
             JOIN concepts c ON c.id = cs.concept_id
            WHERE cs.origin = 'service' AND r.service_id = ? AND cs.gap_type != 'convention'
            ORDER BY CASE cs.state WHEN 'missed' THEN 0 WHEN 'regressed' THEN 0
                                   WHEN 'partially_repaired' THEN 1 ELSE 2 END,
                     CASE cs.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                                      WHEN 'medium' THEN 2 ELSE 3 END,
                     COALESCE(NULLIF(cs.next_due_ts, ''), '9999') ASC
            LIMIT ?""",
        (service_id, limit),
    ).fetchall()

    convention_rows: list[sqlite3.Row] = []
    if current_site_id is not None:
        convention_rows = conn.execute(
            """SELECT cs.id, cs.claim_text, cs.state, cs.priority,
                      t.canonical_slug AS topic, c.display_name AS concept
                 FROM claim_state cs
                 JOIN rotations r ON r.id = cs.rotation_id
                 JOIN topics t ON t.id = cs.topic_id
                 JOIN concepts c ON c.id = cs.concept_id
                WHERE cs.origin = 'service' AND cs.gap_type = 'convention'
                  AND r.service_id = ? AND r.site_id = ?
                ORDER BY cs.last_seen_ts DESC LIMIT ?""",
            (service_id, current_site_id, limit),
        ).fetchall()

    cap = max(0, min(5, limit))
    formal_rows = conn.execute(
        """SELECT cs.id, cs.claim_text, cs.state, cs.priority,
                  t.canonical_slug AS topic, c.display_name AS concept
             FROM claim_state cs
             JOIN topics t ON t.id = cs.topic_id
             JOIN concepts c ON c.id = cs.concept_id
            WHERE cs.origin = 'assessed' AND t.domain = ?
              AND cs.state IN ('missed', 'partially_repaired', 'regressed')
            ORDER BY CASE cs.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                                      WHEN 'medium' THEN 2 ELSE 3 END,
                     cs.last_seen_ts DESC
            LIMIT ?""",
        (domain, cap),
    ).fetchall()

    rubric_rows = conn.execute(
        """SELECT slug, text, origin, pgy_target, priority, status
             FROM competency_targets
            WHERE service_id = ? AND status IN ('open', 'developing')
            ORDER BY CASE status WHEN 'developing' THEN 0 ELSE 1 END,
                     CASE priority WHEN 'core' THEN 0 WHEN 'important' THEN 1 ELSE 2 END,
                     pgy_target ASC LIMIT ?""",
        (service_id, limit),
    ).fetchall()

    rubric_counts = {
        str(row["status"] or "open"): int(row["n"])
        for row in conn.execute(
            """SELECT status, COUNT(*) AS n
                 FROM competency_targets
                WHERE service_id = ?
                GROUP BY status""",
            (service_id,),
        ).fetchall()
    }

    # Candidates are future assessment opportunities, never mastery evidence.
    # Service-origin rows must belong to this service; site-local conventions are
    # further restricted to the selected site. Portable assessed candidates enter
    # only when their topic has an explicit matching domain. Generic-domain rows
    # are counted as unmapped instead of being guessed into a rotation.
    candidate_rows = conn.execute(
        """SELECT b.id, b.doc_path, b.prompt, b.claim_text, b.provenance_tier,
                  b.origin, b.rotation_id, b.convention, b.updated_at,
                  t.canonical_slug AS topic, t.domain AS topic_domain,
                  c.display_name AS concept
             FROM shift_debrief_review_candidates b
             JOIN topics t ON t.id = b.topic_id
             JOIN concepts c ON c.id = b.concept_id
             LEFT JOIN rotations candidate_rotation ON candidate_rotation.id = b.rotation_id
            WHERE b.status = 'pending'
              AND (
                    (b.origin = 'assessed' AND t.domain = ?)
                 OR (b.origin = 'service' AND candidate_rotation.service_id = ?
                     AND (b.convention = 0 OR candidate_rotation.site_id = ?))
              )
            ORDER BY CASE b.origin WHEN 'service' THEN 0 ELSE 1 END,
                     b.updated_at DESC
            LIMIT ?""",
        (domain, service_id, current_site_id, limit),
    ).fetchall()
    unmapped_candidate_count = int(
        conn.execute(
            """SELECT COUNT(*)
                 FROM shift_debrief_review_candidates b
                 JOIN topics t ON t.id = b.topic_id
                WHERE b.status = 'pending' AND b.origin = 'assessed'
                  AND COALESCE(NULLIF(t.domain, ''), 'general') = 'general'"""
        ).fetchone()[0]
    )

    def _gap(row: sqlite3.Row, gap_origin: str) -> dict[str, object]:
        return {
            "claim_state_id": int(row["id"]), "origin": gap_origin,
            "topic": row["topic"], "concept": row["concept"], "claim": row["claim_text"],
            "state": row["state"], "priority": row["priority"],
        }

    def _candidate(row: sqlite3.Row) -> dict[str, object]:
        return {
            "candidate_id": int(row["id"]),
            "topic": row["topic"],
            "concept": row["concept"],
            "claim": row["claim_text"] or row["prompt"],
            "doc": row["doc_path"],
            "provenance_tier": row["provenance_tier"],
            "origin": row["origin"],
            "rotation_id": row["rotation_id"],
            "convention": bool(row["convention"]),
            "weight": "low",
            "next_action": "Offer a Socratic probe before assigning learner state.",
        }

    rotation_view = _rotation_view(conn, rotation) if rotation is not None else None
    rubric_progress = {
        "total": sum(rubric_counts.values()),
        "open": rubric_counts.get("open", 0),
        "developing": rubric_counts.get("developing", 0),
        "completed": sum(
            count for status, count in rubric_counts.items()
            if status not in {"open", "developing"}
        ),
    }
    warnings: list[str] = []
    if rotation_view is None:
        warnings.append("No active or explicit rotation is attached to this service recall.")
    if rubric_progress["total"] == 0:
        warnings.append("No competency rubric is seeded for this service.")
    if unmapped_candidate_count:
        warnings.append(
            f"{unmapped_candidate_count} pending portable review candidates remain in the general domain; "
            "they are excluded until explicitly classified."
        )

    payload = {
        "lens": "service",
        "service": service_row["slug"],
        "service_display": service_row["display_name"],
        "domain": domain,
        "site": site_row["slug"] if site_row else "",
        "site_display": site_row["display_name"] if site_row else "",
        "rotation_id": int(rotation["id"]) if rotation else None,
        "rotation": rotation_view,
        "context": context,
        "weighting_policy": "service_primary_formal_capped",
        "service_gaps": [_gap(r, "service") for r in gap_rows],
        "conventions": [_gap(r, "service") for r in convention_rows],
        "formal_secondary": [_gap(r, "assessed") for r in formal_rows],
        "rubric_open": [
            {"slug": r["slug"], "text": r["text"], "origin": r["origin"],
             "priority": r["priority"], "status": r["status"]}
            for r in rubric_rows
        ],
        "rubric_progress": rubric_progress,
        "pending_review_candidates": [_candidate(r) for r in candidate_rows],
        "data_quality_warnings": warnings,
        "counts": {
            "service_gaps": len(gap_rows), "conventions": len(convention_rows),
            "formal_secondary": len(formal_rows), "rubric_open": len(rubric_rows),
            "pending_review_candidates": len(candidate_rows),
            "unmapped_review_candidates": unmapped_candidate_count,
        },
    }
    return json.dumps(payload, indent=2)
