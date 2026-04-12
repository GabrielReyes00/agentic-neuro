#!/usr/bin/env python3
"""Vault ↔ Knowledge-Graph sync.

Pure data-gathering and rendering functions that turn the SQLite KG into
Dataview-queryable Concept files. A Concept file is composed of:

    1. Headline (one-line human summary)
    2. ## Learning State        — inline Dataview fields (mastery, next_due, ...)
    3. ## Prerequisites          — KG edges (relationship = 'prerequisite_of')
    4. ## Confusable With        — KG edges (relationship = 'confusable_with')
    5. ## Extends Into           — KG edges (relationship = 'extends')
    6. ## Differentiates From    — KG edges (relationship = 'differentiates_from')
    7. ## Encounter History      — ledger of signal_events for this topic
    8. ## Known Confusion Points — Error Atlas disambiguation pages
    9. ## Related Vault Content  — reports/guides/study material cross-refs
   10. Bottom YAML metadata block (tags, aliases) — unchanged convention

Empty sections are omitted. Relationship sections with no edges show the
marker line "*No edges recorded yet.*" to make it visible that the ledger
exists but hasn't been populated.

This module has no I/O side effects beyond the one `sync_studied_concepts`
helper, which writes files. Everything else is pure.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# We avoid importing KnowledgeGraph at module load so this file can be used in
# lightweight contexts (canvas builder, unit tests). The sync helper takes a
# KnowledgeGraph instance at call time.


# ═══════════════════════════════════════════════════════════════════════════
# Label maps (kept in sync with knowledge_graph.py and write_concept_stubs.py)
# ═══════════════════════════════════════════════════════════════════════════

DEPTH_LABEL_MAP = {
    0: "not_studied",
    1: "surface",
    2: "mechanistic",
    3: "decision-making",
    4: "expert",
    5: "mastery",
}

PRIORITY_LABEL_MAP = {
    1: "core",
    2: "important",
    3: "advanced",
}

RELATIONSHIP_HEADERS = {
    "prerequisite_of": "## Prerequisites",
    "confusable_with": "## Confusable With",
    "extends":         "## Extends Into",
    "differentiates_from": "## Differentiates From",
}

# Rendering order
RELATIONSHIP_ORDER = (
    "prerequisite_of",
    "confusable_with",
    "extends",
    "differentiates_from",
)

PROTECTED_CONCEPTS: set[str] = {
    "Neurosurgery Consult Checklists by Pathology.md",
    "Neurosurgery Consult Workflow.md",
    "Peripheral Nerve Injury Classifications (Seddon & Sunderland).md",
}

MATURE_ANKI_INTERVAL_DAYS = 21

ENCOUNTER_HISTORY_LIMIT = 15

# Section headings that the agent owns and rewrites on every sync.
# Any ## heading NOT in this set is treated as user-authored and preserved.
AGENT_MANAGED_SECTIONS: set[str] = {
    "Learning State",
    "Prerequisites",
    "Confusable With",
    "Extends Into",
    "Differentiates From",
    "Encounter History",
    "Known Confusion Points",
    "Related Vault Content",
}


# ═══════════════════════════════════════════════════════════════════════════
# Filename / wikilink helpers
# ═══════════════════════════════════════════════════════════════════════════


def stub_filename(display_name: str) -> str:
    """Sanitize a curriculum display_name into an Obsidian-safe filename.

    Mirrors KnowledgeGraph._stub_filename so vault_kg_sync can run without a
    KG instance (e.g., canvas builder).
    """
    name = display_name or ""
    name = re.sub(r":", " -", name)
    name = re.sub(r"[/\\]", " or ", name)
    name = name.replace("&", "and")
    name = re.sub(r"[—–]", "-", name)
    name = re.sub(r"[^\w\s\-\(\)]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > 100:
        name = name[:97] + "..."
    return name + ".md"


def _depth_label(depth: int) -> str:
    return DEPTH_LABEL_MAP.get(depth, f"depth-{depth}")


def _priority_label(priority: int) -> str:
    return PRIORITY_LABEL_MAP.get(priority, "important")


def _esc_table_cell(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ").strip()


# ═══════════════════════════════════════════════════════════════════════════
# Curriculum topic → filename map (for wikilink resolution)
# ═══════════════════════════════════════════════════════════════════════════


def load_curriculum_index(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Return `{canonical_topic_name: {filename, display_name, domain, acgme_milestone}}`
    for every curriculum topic. Used to turn raw `topic_a`/`topic_b` strings from
    concept_relationships into real Concept file wikilinks.

    Matching keys: normalized topic_name (canonical slug) AND normalized display_name.
    """
    idx: dict[str, dict[str, Any]] = {}
    rows = conn.execute(
        """SELECT curriculum_id, topic_name, display_name, domain, acgme_milestone,
                  priority, pgy_target
           FROM curriculum_topics"""
    ).fetchall()
    for row in rows:
        display = row["display_name"] or row["topic_name"] or ""
        filename = stub_filename(display)
        entry = {
            "curriculum_id": row["curriculum_id"],
            "display_name": display,
            "filename": filename,
            "domain": row["domain"] or "",
            "acgme_milestone": row["acgme_milestone"] or "",
            "priority": row["priority"] or 2,
            "pgy_target": row["pgy_target"] or 1,
        }
        for key in (
            (row["topic_name"] or "").strip().lower(),
            display.strip().lower(),
        ):
            if key:
                idx[key] = entry
    return idx


def _wikilink_for_topic(
    raw_topic: str,
    curriculum_index: dict[str, dict[str, Any]],
) -> str:
    """Turn a raw topic string into a markdown wikilink. Resolves to
    `[[Concepts/<File>|Display]]` if found, else a plain dangling wikilink."""
    if not raw_topic:
        return ""
    key = raw_topic.strip().lower()
    entry = curriculum_index.get(key)
    if entry:
        stem = entry["filename"].replace(".md", "")
        display = entry["display_name"]
        return f"[[Concepts/{stem}|{display}]]"
    # Dangling wikilink — Obsidian still renders it; surfaces the gap.
    pretty = raw_topic.strip()
    return f"[[{pretty}]]"


# ═══════════════════════════════════════════════════════════════════════════
# Per-concept state collection
# ═══════════════════════════════════════════════════════════════════════════


def collect_concept_state(
    conn: sqlite3.Connection,
    curriculum_row: dict[str, Any],
    curriculum_index: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Gather all KG data needed to render one Concept file.

    Accepts a plain dict (from curriculum_topics JOIN topics) rather than
    a KG instance so it can be called from multiple writers.
    """
    # Resolve curriculum_id. Callers that know it pass an int; callers that
    # only have slug/title (export_concept_stubs) pass a placeholder — look it up.
    raw_cid = curriculum_row.get("curriculum_id")
    curriculum_id: int | None
    if isinstance(raw_cid, int):
        curriculum_id = raw_cid
    else:
        cid_row = None
        slug = curriculum_row.get("slug") or ""
        title_lookup = curriculum_row.get("title") or curriculum_row.get("display_name") or ""
        if slug:
            cid_row = conn.execute(
                "SELECT curriculum_id FROM curriculum_topics WHERE topic_name = ? LIMIT 1",
                (slug,),
            ).fetchone()
        if not cid_row and title_lookup:
            cid_row = conn.execute(
                "SELECT curriculum_id FROM curriculum_topics WHERE display_name = ? LIMIT 1",
                (title_lookup,),
            ).fetchone()
        curriculum_id = int(cid_row["curriculum_id"]) if cid_row else None

    title = curriculum_row.get("title") or curriculum_row.get("display_name") or ""
    domain = curriculum_row.get("domain") or ""
    acgme = curriculum_row.get("acgme_milestone") or ""
    pgy = int(curriculum_row.get("pgy_target") or 1)
    priority = int(curriculum_row.get("priority") or 2)
    confidence = float(curriculum_row.get("confidence") or 0.0)
    depth = int(curriculum_row.get("depth") or 0)
    encounters = int(curriculum_row.get("encounter_count") or 0)
    last_seen = (curriculum_row.get("last_seen") or "")
    last_seen_date = last_seen[:10] if last_seen else ""

    # Look up the aggregated topic row joined via curriculum_id.
    topic_row = None
    if curriculum_id is not None:
        topic_row = conn.execute(
            """SELECT topic_id, canonical_name, display_name
               FROM topics
               WHERE curriculum_id = ?
               ORDER BY encounter_count DESC LIMIT 1""",
            (curriculum_id,),
        ).fetchone()

    topic_id = topic_row["topic_id"] if topic_row else None
    canonical_name = topic_row["canonical_name"] if topic_row else ""

    # ── Mastery / SRS ──────────────────────────────────────────────────────
    mastery = round(confidence, 4)

    next_due = ""
    error_type = ""
    if topic_id is not None:
        due_row = conn.execute(
            """SELECT MIN(next_review_due) AS due_ts
               FROM concept_mastery
               WHERE topic_id = ? AND next_review_due IS NOT NULL""",
            (topic_id,),
        ).fetchone()
        if due_row and due_row["due_ts"]:
            next_due = str(due_row["due_ts"])[:10]

        err_row = conn.execute(
            """SELECT error_type FROM concept_mastery
               WHERE topic_id = ? AND error_type != ''
               ORDER BY last_updated DESC LIMIT 1""",
            (topic_id,),
        ).fetchone()
        if err_row:
            error_type = err_row["error_type"] or ""

    # ── Anki counts ─────────────────────────────────────────────────────────
    anki_total = 0
    anki_mature = 0
    if topic_id is not None:
        anki_row = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN interval_days >= ? THEN 1 ELSE 0 END) AS mature
               FROM anki_card_stats WHERE matched_topic_id = ?""",
            (MATURE_ANKI_INTERVAL_DAYS, topic_id),
        ).fetchone()
        if anki_row:
            anki_total = int(anki_row["total"] or 0)
            anki_mature = int(anki_row["mature"] or 0)

    # ── Relationship edges ──────────────────────────────────────────────────
    # Matching strategy (concept_relationships rows frequently have empty
    # topic_a/topic_b but always have concept_a/concept_b):
    #   1. Collect all concept_text values that belong to this topic (via
    #      concept_mastery WHERE topic_id = ?).
    #   2. Any relationship row with concept_a OR concept_b in that set belongs
    #      to this topic. The "other side" is the opposite concept.
    #   3. Also match by topic_a/topic_b when those are populated (legacy path).
    relationships: dict[str, list[dict[str, Any]]] = {
        "prerequisite_of": [],
        "confusable_with": [],
        "extends": [],
        "differentiates_from": [],
    }
    owned_concepts: set[str] = set()
    if topic_id is not None:
        cm_rows = conn.execute(
            "SELECT DISTINCT LOWER(concept_text) AS c FROM concept_mastery WHERE topic_id = ?",
            (topic_id,),
        ).fetchall()
        owned_concepts = {r["c"] for r in cm_rows if r["c"]}

    canonical_lower = (canonical_name or "").lower()
    title_lower = title.lower()
    topic_match_keys = {k for k in (canonical_lower, title_lower) if k}

    if owned_concepts or topic_match_keys:
        rel_rows = conn.execute(
            "SELECT concept_a, topic_a, concept_b, topic_b, relationship, notes, strength FROM concept_relationships"
        ).fetchall()
        seen_pairs: set[tuple[str, str, str]] = set()
        for r in rel_rows:
            rel = r["relationship"]
            if rel not in relationships:
                continue
            ca = (r["concept_a"] or "").lower()
            cb = (r["concept_b"] or "").lower()
            ta = (r["topic_a"] or "").lower()
            tb = (r["topic_b"] or "").lower()

            side: str | None = None
            if ca in owned_concepts or (ta and ta in topic_match_keys):
                side = "a"
            elif cb in owned_concepts or (tb and tb in topic_match_keys):
                side = "b"
            if side is None:
                continue

            if side == "a":
                other_topic = r["topic_b"] or ""
                other_concept = r["concept_b"] or ""
            else:
                other_topic = r["topic_a"] or ""
                other_concept = r["concept_a"] or ""

            key = (rel, other_topic.lower(), other_concept.lower())
            if key in seen_pairs:
                continue
            seen_pairs.add(key)

            relationships[rel].append({
                "concept": other_concept,
                "topic": other_topic,
                "notes": r["notes"] or "",
                "strength": float(r["strength"] or 0.0),
            })

    # ── Blocking gaps count (topic-level) ──────────────────────────────────
    blocking_gaps_count = 0
    if topic_id is not None:
        # Count concept_mastery rows for this topic that are 'unknown' or 'due'
        # AND have a prerequisite_of edge pointing at them from any concept.
        bg_row = conn.execute(
            """SELECT COUNT(DISTINCT cm.concept_text) AS cnt
               FROM concept_mastery cm
               WHERE cm.topic_id = ?
                 AND cm.status IN ('unknown', 'due')
                 AND EXISTS (
                     SELECT 1 FROM concept_relationships cr
                     WHERE cr.concept_b = cm.concept_text
                       AND cr.relationship = 'prerequisite_of'
                 )""",
            (topic_id,),
        ).fetchone()
        blocking_gaps_count = int(bg_row["cnt"] if bg_row else 0)

    # ── Encounter history (signal_events ledger) ───────────────────────────
    encounter_history: list[dict[str, Any]] = []
    if topic_id is not None:
        ev_rows = conn.execute(
            """SELECT timestamp, source, signal_type, depth_at_event
               FROM signal_events
               WHERE topic_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (topic_id, ENCOUNTER_HISTORY_LIMIT),
        ).fetchall()
        for ev in ev_rows:
            ts = str(ev["timestamp"] or "")
            encounter_history.append({
                "date": ts[:10],
                "signal": ev["signal_type"] or "",
                "source": ev["source"] or "",
                "depth": int(ev["depth_at_event"] or 0),
            })

    # ── Confusion matrix Atlas entries (from JSON file, matched by slug) ───
    atlas_entries: list[str] = curriculum_row.get("confusable_atlas_entries", []) or []

    # ── Derived status ──────────────────────────────────────────────────────
    if encounters == 0:
        status = "not_studied"
    elif mastery >= 0.15 and depth >= 2:
        status = "known"
    else:
        status = "gap"

    return {
        "curriculum_id": curriculum_id,
        "title": title,
        "filename": stub_filename(title),
        "domain": domain,
        "domain_tag": curriculum_row.get("domain_tag", ""),
        "acgme_milestone": acgme,
        "pgy_target": pgy,
        "priority": priority,
        "priority_label": _priority_label(priority),
        "mastery": mastery,
        "confidence": mastery,
        "depth": depth,
        "depth_label": _depth_label(depth),
        "encounters": encounters,
        "last_tested": last_seen_date,
        "next_due": next_due,
        "status": status,
        "error_type": error_type,
        "anki_total": anki_total,
        "anki_mature": anki_mature,
        "blocking_gaps": blocking_gaps_count,
        "relationships": relationships,
        "encounter_history": encounter_history,
        "atlas_entries": atlas_entries,
        "slug": curriculum_row.get("slug", ""),
        "canonical_name": canonical_name,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Section builders
# ═══════════════════════════════════════════════════════════════════════════


def build_headline(state: dict[str, Any]) -> str:
    acgme = state["acgme_milestone"] or "-"
    domain = state["domain"] or "-"
    pgy = state["pgy_target"]
    confidence = state["confidence"]
    depth_label = state["depth_label"].capitalize()
    depth = state["depth"]
    line = (
        f"**ACGME**: {acgme} ({domain}) | **PGY Target**: Year {pgy} | "
        f"**Confidence**: {confidence:.3f} | **Depth**: {depth_label} ({depth})"
    )
    encounters = state["encounters"]
    last_tested = state["last_tested"]
    second = f"Encountered {encounters} time{'s' if encounters != 1 else ''}."
    if last_tested:
        second += f" Last studied: {last_tested}."
    return line + "\n\n" + second


def build_learning_state_block(state: dict[str, Any]) -> str:
    """Inline Dataview field block. Fields use `key:: value` syntax which
    Dataview parses from anywhere in the body."""
    rows: list[tuple[str, Any]] = [
        ("mastery", f"{state['mastery']:.3f}"),
        ("confidence", f"{state['confidence']:.3f}"),
        ("depth", state["depth"]),
        ("depth_label", state["depth_label"]),
        ("encounters", state["encounters"]),
        ("last_tested", state["last_tested"] or "~"),
        ("next_due", state["next_due"] or "~"),
        ("status", state["status"]),
        ("error_type", state["error_type"] or "~"),
        ("acgme_milestone", state["acgme_milestone"] or "~"),
        ("domain", state["domain"] or "~"),
        ("priority", state["priority_label"]),
        ("pgy_target", state["pgy_target"]),
        ("anki_cards", state["anki_total"]),
        ("anki_mature", state["anki_mature"]),
        ("blocking_gaps", state["blocking_gaps"]),
    ]
    body = "\n".join(f"{k}:: {v}" for k, v in rows)
    return "## Learning State\n\n" + body


def build_relationship_section(
    state: dict[str, Any],
    curriculum_index: dict[str, dict[str, Any]],
) -> str:
    """Render all four KG-edge sections. Omits sections with no edges."""
    out: list[str] = []
    for rel in RELATIONSHIP_ORDER:
        edges = state["relationships"].get(rel, [])
        if not edges:
            continue
        header = RELATIONSHIP_HEADERS[rel]
        out.append(header)
        out.append("")
        seen: set[str] = set()
        for edge in edges:
            link = _wikilink_for_topic(edge["topic"], curriculum_index)
            if not link:
                # Fallback — use raw concept text as a dangling link.
                concept_pretty = edge["concept"].title() if edge["concept"] else ""
                if not concept_pretty:
                    continue
                link = f"[[{concept_pretty}]]"
            if link in seen:
                continue
            seen.add(link)
            note = f" — {edge['notes']}" if edge["notes"] else ""
            out.append(f"- {link}{note}")
        out.append("")
    return "\n".join(out).rstrip()


def build_confusion_atlas_section(state: dict[str, Any]) -> str:
    entries = state.get("atlas_entries") or []
    if not entries:
        return ""
    lines = ["## Known Confusion Points", ""]
    for entry in entries:
        lines.append(f"- [[Error Atlas/{entry}]]")
    return "\n".join(lines)


def build_encounter_history_section(state: dict[str, Any]) -> str:
    history = state.get("encounter_history") or []
    if not history:
        return ""
    lines = [
        "## Encounter History",
        "",
        "| Date | Signal | Source | Depth |",
        "|------|--------|--------|-------|",
    ]
    for ev in history:
        lines.append(
            f"| {_esc_table_cell(ev['date'])} "
            f"| {_esc_table_cell(ev['signal'])} "
            f"| {_esc_table_cell(ev['source'])} "
            f"| {ev['depth']} |"
        )
    return "\n".join(lines)


def build_bottom_yaml(state: dict[str, Any]) -> str:
    """Bottom YAML metadata block (tags/aliases only — the inline Dataview
    fields above are the source of truth for queries)."""
    slug = state.get("slug") or ""
    aliases_block = f'aliases:\n  - "{slug}"' if slug else "aliases: []"
    domain_tag = state.get("domain_tag") or "general"
    pgy = state["pgy_target"]
    priority = state["priority_label"]
    depth_label = state["depth_label"]
    status = state["status"]
    tags = [
        "type/concept",
        f"domain/{domain_tag}",
        f"status/{status}",
        f"depth/{depth_label}",
        f"pgy/{pgy}",
        f"priority/{priority}",
    ]
    tags_yaml = "\n".join(f"  - {t}" for t in tags)
    last_tested = state.get("last_tested") or ""
    last_line = f"last_studied: {last_tested}" if last_tested else "last_studied: ~"
    return (
        "---\n"
        f"{aliases_block}\n"
        f"confidence: {state['confidence']:.3f}\n"
        f"depth: {state['depth']}\n"
        f"depth_label: {depth_label}\n"
        f"domain: {state['domain']}\n"
        f"domain_tag: {domain_tag}\n"
        f"acgme: {state['acgme_milestone']}\n"
        f"pgy_target: {pgy}\n"
        f"status: {status}\n"
        f"encounter_count: {state['encounters']}\n"
        f"{last_line}\n"
        f"priority: {priority}\n"
        "tags:\n"
        f"{tags_yaml}\n"
        "---\n"
    )


def build_concept_file(
    state: dict[str, Any],
    curriculum_index: dict[str, dict[str, Any]],
    user_sections: list[str] | None = None,
) -> str:
    """Compose the full Concept file from gathered state.

    If ``user_sections`` is provided, those blocks are injected after all
    agent-managed sections and before the bottom YAML metadata block. This
    preserves any custom headings (e.g., "## Clinical Pearls", "## My Notes")
    that the user added in Obsidian between syncs.
    """
    parts: list[str] = []
    parts.append(build_headline(state))
    parts.append("")
    parts.append(build_learning_state_block(state))

    rel_block = build_relationship_section(state, curriculum_index)
    if rel_block:
        parts.append("")
        parts.append(rel_block)

    atlas_block = build_confusion_atlas_section(state)
    if atlas_block:
        parts.append("")
        parts.append(atlas_block)

    history_block = build_encounter_history_section(state)
    if history_block:
        parts.append("")
        parts.append(history_block)

    # Related Vault Content placeholder — skills fill this during their own
    # write phase. Kept as a stable anchor so cross-ref injection stays idempotent.
    parts.append("")
    parts.append("## Related Vault Content")
    parts.append("")
    parts.append("*Agent fills this during vault write phase with matching Reports/Operative Guides wikilinks.*")

    # Inject preserved user-authored sections before the bottom YAML.
    if user_sections:
        for section in user_sections:
            parts.append("")
            parts.append(section)

    parts.append("")
    parts.append(build_bottom_yaml(state))
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# Minimal stub builder (for not-yet-studied curriculum topics)
# ═══════════════════════════════════════════════════════════════════════════


def build_stub_minimal(curriculum_row: dict[str, Any]) -> str:
    """Unchanged minimal stub for curriculum topics with zero encounters."""
    domain_tag = curriculum_row.get("domain_tag") or "general"
    pgy = int(curriculum_row.get("pgy_target") or 1)
    priority = _priority_label(int(curriculum_row.get("priority") or 1))
    acgme = curriculum_row.get("acgme_milestone") or ""
    domain = curriculum_row.get("domain") or ""
    tags = [
        "type/concept",
        f"domain/{domain_tag}",
        "status/not-studied",
        f"pgy/{pgy}",
        f"priority/{priority}",
    ]
    tags_yaml = "\n".join(f"  - {t}" for t in tags)
    return (
        f"**ACGME**: {acgme} ({domain}) | **PGY Target**: Year {pgy} | **Priority**: {priority.capitalize()}\n\n"
        "Not yet studied.\n\n"
        "## Learning State\n\n"
        "mastery:: 0.000\n"
        "confidence:: 0.000\n"
        "depth:: 0\n"
        "depth_label:: not_studied\n"
        "encounters:: 0\n"
        "last_tested:: ~\n"
        "next_due:: ~\n"
        "status:: not_studied\n"
        "error_type:: ~\n"
        f"acgme_milestone:: {acgme or '~'}\n"
        f"domain:: {domain or '~'}\n"
        f"priority:: {priority}\n"
        f"pgy_target:: {pgy}\n"
        "anki_cards:: 0\n"
        "anki_mature:: 0\n"
        "blocking_gaps:: 0\n\n"
        "---\n"
        "aliases: []\n"
        "confidence: 0.000\n"
        "depth: 0\n"
        "depth_label: not_studied\n"
        f"domain: {domain}\n"
        f"domain_tag: {domain_tag}\n"
        f"acgme: {acgme}\n"
        f"pgy_target: {pgy}\n"
        "status: not_studied\n"
        "encounter_count: 0\n"
        "last_studied: ~\n"
        f"priority: {priority}\n"
        "tags:\n"
        f"{tags_yaml}\n"
        "---\n"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Vault format guard
# ═══════════════════════════════════════════════════════════════════════════


class VaultFormatError(RuntimeError):
    """Raised when a vault file write would violate the no-top-YAML / no-H1 rule."""


def assert_vault_format(content: str, path: Path) -> None:
    """Hard guard against the two repeatedly-violated vault rules:
       1. No top-of-file YAML frontmatter (`---` as first non-blank line)
       2. No H1 heading (`# Title`) as first non-blank line — filename is the title

    Raise a VaultFormatError instead of silently writing a bad file. The user
    has corrected this >=6 times; the assertion is the prevention.
    """
    stripped = content.lstrip()
    if stripped.startswith("---"):
        raise VaultFormatError(
            f"Refusing to write {path}: starts with top-of-file YAML frontmatter. "
            "Move ALL `---` metadata to the BOTTOM of the file."
        )
    first_line = stripped.split("\n", 1)[0] if stripped else ""
    if first_line.startswith("# "):
        raise VaultFormatError(
            f"Refusing to write {path}: starts with H1 heading '{first_line}'. "
            "Filename is the Obsidian title — start with body content instead."
        )


def safe_write_vault_file(path: Path, content: str) -> None:
    """Write `content` to `path` only after passing the vault-format guard."""
    assert_vault_format(content, path)
    path.write_text(content, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# User-section preservation (concept file merge strategy)
# ═══════════════════════════════════════════════════════════════════════════


def _parse_sections(content: str) -> list[tuple[str | None, str]]:
    """Split a concept file into (heading_title, body) tuples.

    The first tuple has heading_title=None (the preamble before any ## heading).
    The bottom YAML block (``---`` ... ``---``) is returned as a final tuple
    with heading_title="__yaml__".
    """
    # Strip the bottom YAML block first.
    yaml_block = ""
    stripped = content.rstrip()
    if stripped.endswith("---"):
        # Find the opening --- that is NOT the closing ---
        last_close = stripped.rfind("---")
        # Walk backwards past the closing ---
        before_close = stripped[:last_close].rstrip()
        open_pos = before_close.rfind("\n---")
        if open_pos != -1:
            yaml_block = stripped[open_pos + 1:]  # includes the leading ---
            content = stripped[:open_pos + 1]

    lines = content.split("\n")
    sections: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("## "):
            # Flush previous section
            sections.append((current_heading, current_lines))
            current_heading = line[3:].strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    sections.append((current_heading, current_lines))

    result: list[tuple[str | None, str]] = [
        (heading, "\n".join(body)) for heading, body in sections
    ]
    if yaml_block:
        result.append(("__yaml__", yaml_block))
    return result


def extract_user_sections(existing_content: str) -> list[str]:
    """Extract user-authored sections from an existing Concept file.

    Returns a list of section strings (each starting with ``## <heading>``)
    whose heading is NOT in ``AGENT_MANAGED_SECTIONS``. The preamble (headline)
    and bottom YAML block are always agent-managed and excluded.
    """
    if not existing_content or not existing_content.strip():
        return []
    sections = _parse_sections(existing_content)
    user_parts: list[str] = []
    for heading, body in sections:
        if heading is None or heading == "__yaml__":
            continue
        if heading in AGENT_MANAGED_SECTIONS:
            continue
        text = body.strip()
        if text:
            user_parts.append(text)
    return user_parts


# ═══════════════════════════════════════════════════════════════════════════
# Top-level sync entrypoints
# ═══════════════════════════════════════════════════════════════════════════


def _curriculum_rows_from_stubs(stubs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert KnowledgeGraph.export_concept_stubs output into the shape
    collect_concept_state expects."""
    rows = []
    for s in stubs:
        rows.append({
            "curriculum_id": s.get("curriculum_id") or s.get("slug") or s.get("title"),
            "title": s.get("title") or s.get("filename", "").replace(".md", ""),
            "display_name": s.get("title") or "",
            "slug": s.get("slug") or "",
            "domain": s.get("domain") or "",
            "domain_tag": s.get("domain_tag") or "",
            "acgme_milestone": s.get("acgme_milestone") or "",
            "pgy_target": s.get("pgy_target") or 1,
            "priority": s.get("priority") or 2,
            "confidence": s.get("confidence") or 0.0,
            "depth": s.get("depth") or 0,
            "encounter_count": s.get("encounter_count") or 0,
            "last_seen": s.get("last_studied") or "",
            "confusable_atlas_entries": s.get("confusable_atlas_entries", []),
        })
    return rows


def sync_studied_concepts(
    kg,
    concepts_dir: Path,
    protected: set[str] | None = None,
) -> dict[str, int]:
    """Rewrite every studied curriculum Concept file with full KG-sync content.

    Uses KnowledgeGraph.export_concept_stubs(only_studied=True) as the source of
    truth for which concepts to touch, then layers on relationships/encounters/
    anki/SRS data via direct KG SQL.

    **Merge strategy**: before overwriting, reads the existing file and extracts
    any user-authored sections (## headings not in AGENT_MANAGED_SECTIONS). These
    are re-injected into the new content, so personal notes survive syncs.

    Returns {"written": N, "skipped_protected": M, "user_sections_preserved": K}.
    """
    protected = protected or PROTECTED_CONCEPTS
    concepts_dir.mkdir(parents=True, exist_ok=True)
    stubs = kg.export_concept_stubs(only_studied=True)
    curriculum_rows = _curriculum_rows_from_stubs(stubs)
    curriculum_index = load_curriculum_index(kg.conn)

    written = 0
    skipped = 0
    user_preserved = 0
    for row in curriculum_rows:
        filename = stub_filename(row["title"])
        if filename in protected:
            skipped += 1
            continue
        state = collect_concept_state(kg.conn, row, curriculum_index)
        # collect_concept_state recomputes filename from title
        filename = state["filename"]
        if filename in protected:
            skipped += 1
            continue

        # Read existing file and extract user-authored sections.
        target = concepts_dir / filename
        user_sections: list[str] = []
        if target.exists():
            try:
                existing = target.read_text(encoding="utf-8")
                user_sections = extract_user_sections(existing)
            except OSError:
                pass
        if user_sections:
            user_preserved += len(user_sections)

        content = build_concept_file(state, curriculum_index, user_sections=user_sections)
        safe_write_vault_file(target, content)
        written += 1
    return {"written": written, "skipped_protected": skipped, "user_sections_preserved": user_preserved}


def sync_all_concepts(
    kg,
    concepts_dir: Path,
    protected: set[str] | None = None,
) -> dict[str, int]:
    """Full-vault regeneration: minimal stub for unstudied + rich KG-sync for studied.

    Used by scripts/write_concept_stubs.py.

    **Merge strategy**: for studied concepts, reads existing files and preserves
    user-authored sections (see ``extract_user_sections``). Unstudied stubs are
    overwritten wholesale since they contain no user content worth preserving.
    """
    protected = protected or PROTECTED_CONCEPTS
    concepts_dir.mkdir(parents=True, exist_ok=True)
    stubs = kg.export_concept_stubs(only_studied=False)
    curriculum_index = load_curriculum_index(kg.conn)

    written = 0
    skipped = 0
    rich = 0
    minimal = 0
    user_preserved = 0
    for stub in stubs:
        filename = stub.get("filename") or stub_filename(stub.get("title", ""))
        if filename in protected:
            skipped += 1
            continue
        if stub.get("studied"):
            row = _curriculum_rows_from_stubs([stub])[0]
            state = collect_concept_state(kg.conn, row, curriculum_index)

            # Read existing file and extract user-authored sections.
            target = concepts_dir / filename
            user_sections: list[str] = []
            if target.exists():
                try:
                    existing = target.read_text(encoding="utf-8")
                    user_sections = extract_user_sections(existing)
                except OSError:
                    pass
            if user_sections:
                user_preserved += len(user_sections)

            content = build_concept_file(state, curriculum_index, user_sections=user_sections)
            rich += 1
        else:
            content = build_stub_minimal({
                "domain_tag": stub.get("domain_tag") or "",
                "pgy_target": stub.get("pgy_target") or 1,
                "priority": stub.get("priority") or 1,
                "acgme_milestone": stub.get("acgme_milestone") or "",
                "domain": stub.get("domain") or "",
            })
            minimal += 1
        safe_write_vault_file(concepts_dir / filename, content)
        written += 1
    return {
        "written": written,
        "skipped_protected": skipped,
        "rich": rich,
        "minimal": minimal,
        "user_sections_preserved": user_preserved,
    }
