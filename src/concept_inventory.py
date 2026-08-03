"""Canonical neurosurgery concept inventory: build, validate, scope, and learner mapping.

The inventory is the stable, comprehensive domain map the teaching policy needs:
a curated set of concepts (grown from the ACGME milestone skeleton) stored as
committed JSON sources in data/concept_inventory/ and compiled into a dedicated
SQLite database (data/concept_inventory.db). It is intentionally separate from
every existing datastore.

Agent surface (all deterministic, no embeddings, no LLM):
  build        compile JSON sources into the inventory DB
  validate     integrity-check the JSON sources without writing
  stats        counts by domain/tier/type
  scope        bounded subgraph for a query/topic — never load the whole map
  map-learner  project learner memory (read-only) onto a scoped subgraph and
               compute the inventory-grounded teaching plan

`map-learner` opens data/study_memory.db strictly read-only and reuses
study_memory._compute_teaching_policy so the phase semantics are identical to
the per-turn policy engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
INVENTORY_DIR = Path(__import__("os").environ.get("NEURO_CONCEPT_INVENTORY_DIR", BASE_DIR / "data" / "concept_inventory"))
DB_PATH = Path(__import__("os").environ.get("NEURO_CONCEPT_INVENTORY_DB", BASE_DIR / "data" / "concept_inventory.db"))
ACGME_PATH = BASE_DIR / "data" / "acgme_curriculum.json"

VALID_TYPES = frozenset({
    "anatomy", "physiology", "pathology", "presentation", "diagnostics", "imaging",
    "classification", "management", "operative", "complication", "pharmacology", "evidence",
})
VALID_TIERS = frozenset({"foundation", "core", "advanced", "expert"})
TIER_ORDER = {"foundation": 0, "core": 1, "advanced": 2, "expert": 3}
EDGE_TYPES = ("prereq", "discriminator", "related")

DEFAULT_SCOPE_BUDGET = 80
DEFAULT_ENTRY_LIMIT = 30
TOPIC_ANCHOR_THRESHOLD = 0.6
# A topic also anchors when at least this many of its concepts match the query —
# essential when the canonical topic name shares no tokens with learner phrasing.
CONCEPT_ANCHOR_MIN_CONCEPTS = 2
CONCEPT_MATCH_THRESHOLD = 0.34
# Learner→inventory projection recall. Verbose, multi-qualifier learner labels
# ("xanthochromia mechanism" vs node "LP and xanthochromia") legitimately land at
# 0.85*0.5 = 0.425 — a real same-concept hit that the old 0.5 floor dropped,
# leaving studied nodes "unexposed" and mislabeling drilled topics as ORIENT. This
# is the startup projection floor only; per-turn session binding stays stricter.
LEARNER_MATCH_THRESHOLD = 0.4

_STOPWORDS = frozenset({
    "of", "the", "in", "and", "or", "vs", "for", "a", "an", "to", "with", "on",
    "by", "at", "from", "into", "after", "before", "their", "its",
})

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS domains (
    slug TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topics (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL REFERENCES domains(slug),
    name TEXT NOT NULL,
    blurb TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id),
    domain TEXT NOT NULL REFERENCES domains(slug),
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    tier TEXT NOT NULL,
    blurb TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS aliases (
    concept_id TEXT NOT NULL REFERENCES concepts(id),
    alias TEXT NOT NULL,
    UNIQUE(concept_id, alias)
);
CREATE TABLE IF NOT EXISTS edges (
    src TEXT NOT NULL REFERENCES concepts(id),
    dst TEXT NOT NULL REFERENCES concepts(id),
    edge_type TEXT NOT NULL CHECK(edge_type IN ('prereq', 'discriminator', 'related')),
    UNIQUE(src, dst, edge_type)
);
CREATE TABLE IF NOT EXISTS acgme_links (
    concept_id TEXT NOT NULL REFERENCES concepts(id),
    milestone TEXT NOT NULL,
    acgme_title TEXT NOT NULL,
    UNIQUE(concept_id, milestone, acgme_title)
);
CREATE INDEX IF NOT EXISTS idx_concepts_topic ON concepts(topic_id);
CREATE INDEX IF NOT EXISTS idx_concepts_domain ON concepts(domain);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
"""


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def _tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 1)


def _lexical_score(query_tokens: frozenset[str], candidate_tokens: frozenset[str]) -> float:
    if not query_tokens or not candidate_tokens:
        return 0.0
    overlap = query_tokens & candidate_tokens
    if not overlap:
        return 0.0
    jaccard = len(overlap) / len(query_tokens | candidate_tokens)
    containment = len(overlap) / min(len(query_tokens), len(candidate_tokens))
    return max(jaccard, 0.85 * containment)


# ── Source loading and validation ───────────────────────────────────


def _source_files(inventory_dir: Path) -> list[Path]:
    return sorted(p for p in inventory_dir.glob("*.json"))


def _source_hash(inventory_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in _source_files(inventory_dir):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_sources(inventory_dir: Path) -> tuple[list[dict], list[str]]:
    documents: list[dict] = []
    errors: list[str] = []
    files = _source_files(inventory_dir)
    if not files:
        errors.append(f"no JSON sources found in {inventory_dir}")
    for path in files:
        try:
            doc = json.loads(path.read_text())
        except ValueError as exc:
            errors.append(f"{path.name}: invalid JSON ({exc})")
            continue
        doc["_file"] = path.name
        documents.append(doc)
    return documents, errors


def validate_sources(inventory_dir: Path = INVENTORY_DIR, single_file: Path | None = None) -> dict:
    """Integrity report for the JSON sources. Never writes anything."""
    if single_file is not None:
        try:
            doc = json.loads(Path(single_file).read_text())
        except ValueError as exc:
            return {"ok": False, "errors": [f"invalid JSON: {exc}"], "warnings": []}
        doc["_file"] = Path(single_file).name
        documents = [doc]
        errors: list[str] = []
        dir_level = False
    else:
        documents, errors = _load_sources(inventory_dir)
        dir_level = True

    warnings: list[str] = []
    all_concept_ids: dict[str, str] = {}
    all_topic_ids: dict[str, str] = {}
    edge_refs: list[tuple[str, str, str, str]] = []  # (file, src, dst, edge_type)
    concept_count = 0

    for doc in documents:
        fname = doc["_file"]
        domain = str(doc.get("domain", ""))
        code = str(doc.get("code", ""))
        if not domain:
            errors.append(f"{fname}: missing 'domain'")
        if not code:
            errors.append(f"{fname}: missing 'code'")
        if not doc.get("display_name"):
            errors.append(f"{fname}: missing 'display_name'")
        topics = doc.get("topics", [])
        concepts = doc.get("concepts", [])
        if not isinstance(topics, list) or not topics:
            errors.append(f"{fname}: 'topics' must be a non-empty list")
            topics = []
        if not isinstance(concepts, list) or not concepts:
            errors.append(f"{fname}: 'concepts' must be a non-empty list")
            concepts = []

        local_topic_ids = set()
        for topic in topics:
            tid = str(topic.get("id", ""))
            if not tid:
                errors.append(f"{fname}: topic missing 'id'")
                continue
            if code and not tid.startswith(f"{code}."):
                errors.append(f"{fname}: topic id '{tid}' must start with '{code}.'")
            if tid in all_topic_ids:
                errors.append(f"{fname}: duplicate topic id '{tid}' (also in {all_topic_ids[tid]})")
            all_topic_ids[tid] = fname
            local_topic_ids.add(tid)
            if not topic.get("name"):
                errors.append(f"{fname}: topic '{tid}' missing 'name'")

        for concept in concepts:
            cid = str(concept.get("id", ""))
            if not cid:
                errors.append(f"{fname}: concept missing 'id'")
                continue
            concept_count += 1
            if code and not cid.startswith(f"{code}."):
                errors.append(f"{fname}: concept id '{cid}' must start with '{code}.'")
            if cid in all_concept_ids:
                errors.append(f"{fname}: duplicate concept id '{cid}' (also in {all_concept_ids[cid]})")
            all_concept_ids[cid] = fname
            if not concept.get("name"):
                errors.append(f"{fname}: concept '{cid}' missing 'name'")
            if not concept.get("blurb"):
                warnings.append(f"{fname}: concept '{cid}' missing 'blurb'")
            ctype = str(concept.get("type", ""))
            if ctype not in VALID_TYPES:
                errors.append(f"{fname}: concept '{cid}' has invalid type '{ctype}'")
            tier = str(concept.get("tier", ""))
            if tier not in VALID_TIERS:
                errors.append(f"{fname}: concept '{cid}' has invalid tier '{tier}'")
            topic_ref = str(concept.get("topic", ""))
            if topic_ref not in local_topic_ids:
                errors.append(f"{fname}: concept '{cid}' references unknown topic '{topic_ref}'")
            for field, edge_type in (("prereqs", "prereq"), ("discriminators", "discriminator"), ("related", "related")):
                for ref in concept.get(field, []) or []:
                    edge_refs.append((fname, cid, str(ref), edge_type))

    if dir_level:
        for fname, src, dst, edge_type in edge_refs:
            if dst not in all_concept_ids:
                warnings.append(f"{fname}: {edge_type} edge {src} -> {dst} is dangling (dropped at build)")
            if dst == src:
                errors.append(f"{fname}: self-edge {src} -> {dst}")

    return {
        "ok": not errors,
        "files": len(documents),
        "topics": len(all_topic_ids),
        "concepts": concept_count,
        "edges_declared": len(edge_refs),
        "errors": errors,
        "warnings": warnings[:200],
        "warning_count": len(warnings),
    }


# ── ACGME linking ───────────────────────────────────────────────────


def _acgme_titles() -> list[tuple[str, str, frozenset[str]]]:
    """(milestone_key, title, tokens) for every ACGME catalog topic."""
    try:
        catalog = json.loads(ACGME_PATH.read_text())
    except (OSError, ValueError):
        return []
    out: list[tuple[str, str, frozenset[str]]] = []
    for key, milestone in (catalog.get("milestones") or {}).items():
        for topic in milestone.get("topics", []) or []:
            title = str(topic.get("title", ""))
            if title:
                out.append((str(key), title, _tokens(title)))
    return out


def _match_acgme(ref: str, acgme: list[tuple[str, str, frozenset[str]]]) -> tuple[str, str] | None:
    ref_tokens = _tokens(ref)
    best: tuple[float, str, str] | None = None
    for key, title, title_tokens in acgme:
        if title.lower() == ref.lower():
            return (key, title)
        score = _lexical_score(ref_tokens, title_tokens)
        if best is None or score > best[0]:
            best = (score, key, title)
    if best and best[0] >= 0.5:
        return (best[1], best[2])
    return None


# ── Build ───────────────────────────────────────────────────────────


def build_db(inventory_dir: Path = INVENTORY_DIR, db_path: Path = DB_PATH, force: bool = False) -> dict:
    report = validate_sources(inventory_dir)
    if not report["ok"]:
        return {"ok": False, "stage": "validate", "errors": report["errors"][:50]}

    source_hash = _source_hash(inventory_dir)
    if not force and db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute("SELECT value FROM meta WHERE key = 'source_hash'").fetchone()
            conn.close()
            if row and row[0] == source_hash:
                return {"ok": True, "stage": "build", "status": "up_to_date", "source_hash": source_hash}
        except sqlite3.Error:
            pass

    documents, _ = _load_sources(inventory_dir)
    acgme = _acgme_titles()

    tmp_path = db_path.with_suffix(".building")
    if tmp_path.exists():
        tmp_path.unlink()
    conn = sqlite3.connect(str(tmp_path))
    conn.executescript(SCHEMA_SQL)

    concept_ids: set[str] = set()
    for doc in documents:
        for concept in doc.get("concepts", []):
            concept_ids.add(str(concept["id"]))

    dropped_edges: list[str] = []
    unmatched_acgme: list[str] = []
    edge_count = 0
    acgme_link_count = 0

    for doc in sorted(documents, key=lambda d: d["_file"]):
        domain = str(doc["domain"])
        conn.execute(
            "INSERT INTO domains (slug, code, display_name) VALUES (?, ?, ?)",
            (domain, str(doc["code"]), str(doc["display_name"])),
        )
        for topic in doc.get("topics", []):
            conn.execute(
                "INSERT INTO topics (id, domain, name, blurb) VALUES (?, ?, ?, ?)",
                (str(topic["id"]), domain, str(topic["name"]), str(topic.get("blurb", ""))),
            )
        for concept in doc.get("concepts", []):
            cid = str(concept["id"])
            conn.execute(
                "INSERT INTO concepts (id, topic_id, domain, name, type, tier, blurb) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, str(concept["topic"]), domain, str(concept["name"]),
                 str(concept["type"]), str(concept["tier"]), str(concept.get("blurb", ""))),
            )
            for alias in sorted({str(a).strip().lower() for a in concept.get("aliases", []) or [] if str(a).strip()}):
                conn.execute("INSERT OR IGNORE INTO aliases (concept_id, alias) VALUES (?, ?)", (cid, alias))
            for field, edge_type in (("prereqs", "prereq"), ("discriminators", "discriminator"), ("related", "related")):
                for ref in concept.get(field, []) or []:
                    ref = str(ref)
                    if ref in concept_ids and ref != cid:
                        conn.execute(
                            "INSERT OR IGNORE INTO edges (src, dst, edge_type) VALUES (?, ?, ?)",
                            (cid, ref, edge_type),
                        )
                        edge_count += 1
                    else:
                        dropped_edges.append(f"{cid} -[{edge_type}]-> {ref}")
            for ref in concept.get("acgme", []) or []:
                match = _match_acgme(str(ref), acgme)
                if match:
                    conn.execute(
                        "INSERT OR IGNORE INTO acgme_links (concept_id, milestone, acgme_title) VALUES (?, ?, ?)",
                        (cid, match[0], match[1]),
                    )
                    acgme_link_count += 1
                else:
                    unmatched_acgme.append(f"{cid}: {ref}")

    counts = {
        "domains": conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0],
        "topics": conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0],
        "concepts": conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0],
        "aliases": conn.execute("SELECT COUNT(*) FROM aliases").fetchone()[0],
        "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        "acgme_links": acgme_link_count,
    }
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('source_hash', ?)", (source_hash,))
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('counts', ?)", (_json_dumps(counts),))
    conn.commit()
    conn.close()
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    tmp_path.rename(db_path)

    return {
        "ok": True,
        "stage": "build",
        "status": "rebuilt",
        "source_hash": source_hash,
        "counts": counts,
        "dropped_edges": dropped_edges[:50],
        "dropped_edge_count": len(dropped_edges),
        "unmatched_acgme": unmatched_acgme[:50],
        "unmatched_acgme_count": len(unmatched_acgme),
    }


def _open_inventory(inventory_dir: Path = INVENTORY_DIR, db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open the inventory DB, rebuilding automatically when sources changed."""
    needs_build = True
    if db_path.exists():
        try:
            probe = sqlite3.connect(str(db_path))
            row = probe.execute("SELECT value FROM meta WHERE key = 'source_hash'").fetchone()
            probe.close()
            needs_build = not row or row[0] != _source_hash(inventory_dir)
        except sqlite3.Error:
            needs_build = True
    if needs_build:
        result = build_db(inventory_dir, db_path)
        if not result.get("ok"):
            raise RuntimeError(f"concept inventory build failed: {result.get('errors')}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ── Scope ───────────────────────────────────────────────────────────


def _concept_index(conn: sqlite3.Connection, domain: str = "") -> list[dict]:
    where = "WHERE c.domain = ?" if domain else ""
    params = (domain,) if domain else ()
    rows = conn.execute(
        f"""SELECT c.id, c.topic_id, c.domain, c.name, c.type, c.tier, c.blurb, t.name AS topic_name
            FROM concepts c JOIN topics t ON c.topic_id = t.id {where} ORDER BY c.id""",
        params,
    ).fetchall()
    alias_rows = conn.execute("SELECT concept_id, alias FROM aliases ORDER BY concept_id, alias").fetchall()
    alias_map: dict[str, list[str]] = {}
    for r in alias_rows:
        alias_map.setdefault(r["concept_id"], []).append(r["alias"])
    out = []
    for r in rows:
        aliases = alias_map.get(r["id"], [])
        match_tokens = _tokens(r["name"])
        for alias in aliases:
            match_tokens = match_tokens | _tokens(alias)
        out.append({
            "id": r["id"],
            "topic_id": r["topic_id"],
            "topic_name": r["topic_name"],
            "domain": r["domain"],
            "name": r["name"],
            "type": r["type"],
            "tier": r["tier"],
            "blurb": r["blurb"],
            "aliases": aliases,
            "match_tokens": match_tokens,
        })
    return out


def scope_subgraph(
    conn: sqlite3.Connection,
    *,
    query: str = "",
    topic_id: str = "",
    domain: str = "",
    domain_hint: str = "",
    anchor_tokens: frozenset[str] = frozenset(),
    budget: int = DEFAULT_SCOPE_BUDGET,
    entry_limit: int = DEFAULT_ENTRY_LIMIT,
) -> dict:
    """Deterministic bounded subgraph: entry nodes + 1-hop prereq/discriminator/related closure."""
    concepts = _concept_index(conn, domain=domain)
    by_id = {c["id"]: c for c in concepts}
    multi_scope_query = bool(
        re.search(r"\b(?:across|compare|comparison|versus|vs)\b", str(query).lower())
    )

    entries: list[tuple[float, str]] = []
    anchored_topics: list[str] = []
    if topic_id:
        if not conn.execute("SELECT 1 FROM topics WHERE id = ?", (topic_id,)).fetchone():
            return {"ok": False, "reason": "unknown_topic_id", "topic_id": topic_id}
        anchored_topics = [topic_id]
        entries = [(1.0, c["id"]) for c in concepts if c["topic_id"] == topic_id]
    elif query:
        query_tokens = _tokens(query)
        # Learner concept tokens pull the concepts the learner actually studied into
        # scope, so a short topic string that under-recalls does not collapse the map.
        anchor_only = frozenset(anchor_tokens) - query_tokens
        # First pass: score every concept by the query (no topic boost yet).
        base_scores: dict[str, float] = {}
        topic_match_count: dict[str, int] = {}
        topic_match_mass: dict[str, float] = {}
        for c in concepts:
            score = _lexical_score(query_tokens, c["match_tokens"])
            if anchor_only:
                score = max(score, _lexical_score(anchor_only, c["match_tokens"]))
            base_scores[c["id"]] = score
            if score >= CONCEPT_MATCH_THRESHOLD:
                topic_match_count[c["topic_id"]] = topic_match_count.get(c["topic_id"], 0) + 1
                topic_match_mass[c["topic_id"]] = topic_match_mass.get(c["topic_id"], 0.0) + score
        # Anchor a topic by NAME match, or because several of its concepts match the
        # query. The latter is essential when the topic name shares no tokens with
        # the learner's phrasing (topic "Aneurysmal Subarachnoid Hemorrhage" vs query
        # "sah vasospasm") — concept-based anchoring still pulls the whole topic in.
        topic_rows = conn.execute("SELECT id, name FROM topics ORDER BY id").fetchall()
        name_anchored = [
            r["id"] for r in topic_rows
            if _lexical_score(query_tokens, _tokens(r["name"])) >= TOPIC_ANCHOR_THRESHOLD
        ][:3]
        concept_anchored = sorted(
            (tid for tid, cnt in topic_match_count.items() if cnt >= CONCEPT_ANCHOR_MIN_CONCEPTS),
            key=lambda tid: (-topic_match_mass[tid], tid),
        )[:3]
        anchored_topics = list(dict.fromkeys([*name_anchored, *concept_anchored]))[:4]
        anchored_set = set(anchored_topics)
        scored = []
        for c in concepts:
            score = base_scores[c["id"]]
            if c["topic_id"] in anchored_set:
                score = max(score, 0.75)
            if score >= CONCEPT_MATCH_THRESHOLD:
                scored.append((score, c["id"]))
        scored.sort(key=lambda x: (-x[0], x[1]))
        # Domain-coherence guard: a single study session is almost always within
        # one clinical domain. A lexical collision across domains (e.g.
        # "subarachnoid hemorrhage" matching a *traumatic* SAH node while the
        # session is aneurysmal/vascular) must not seed entry nodes from an
        # unrelated domain. Prune before the entry cap so the budget is spent on
        # in-domain concepts. Neighbor (1-hop edge) expansion may still legitimately
        # cross domains and is intentionally left untouched.
        anchored_domains = {c["domain"] for c in concepts if c["topic_id"] in anchored_set}
        if scored and not multi_scope_query:
            scored_domains = {by_id[cid]["domain"] for _, cid in scored}
            # anchored_domains comes from the anchored topics, not the matched
            # concepts, so intersect first — never filter to a domain that has no
            # matches, which would collapse the scope to nothing.
            allowed_anchored = anchored_domains & scored_domains
            if allowed_anchored:
                scored = [t for t in scored if by_id[t[1]]["domain"] in allowed_anchored]
            elif domain_hint and domain_hint in scored_domains:
                # The learner topic's domain disambiguates a cross-domain lexical
                # collision (e.g. aneurysmal vs traumatic SAH) deterministically,
                # but only when it actually names a domain present in the matches.
                scored = [t for t in scored if by_id[t[1]]["domain"] == domain_hint]
            else:
                domain_mass: dict[str, float] = {}
                for s, cid in scored:
                    domain_mass[by_id[cid]["domain"]] = domain_mass.get(by_id[cid]["domain"], 0.0) + s
                total = sum(domain_mass.values())
                top_domain, top_mass = max(domain_mass.items(), key=lambda kv: kv[1])
                # Only prune on a clear majority so genuinely multi-domain lexical
                # queries (no strong topic anchor) are left intact.
                if len(domain_mass) > 1 and total > 0 and (top_mass / total) >= 0.6:
                    scored = [t for t in scored if by_id[t[1]]["domain"] == top_domain]
        entries = scored[: max(entry_limit, len([s for s in scored if by_id[s[1]]["topic_id"] in anchored_set]))]
    else:
        return {"ok": False, "reason": "query_or_topic_required"}

    entry_ids = [cid for _, cid in entries]
    entry_set = set(entry_ids)

    # 1-hop closure: prerequisites (both directions for awareness), discriminators, related.
    expansion: dict[str, tuple[int, str]] = {}  # id -> (edge_priority, via)
    edge_priority = {"prereq": 0, "discriminator": 1, "related": 2}
    if entry_ids:
        placeholders = ",".join("?" for _ in entry_ids)
        rows = conn.execute(
            f"""SELECT src, dst, edge_type FROM edges
                WHERE src IN ({placeholders}) OR dst IN ({placeholders})
                ORDER BY edge_type, src, dst""",
            entry_ids + entry_ids,
        ).fetchall()
    else:
        rows = []
    scope_edges = []
    for r in rows:
        scope_edges.append({"src": r["src"], "dst": r["dst"], "edge_type": r["edge_type"]})
        for neighbor in (r["src"], r["dst"]):
            if neighbor not in entry_set and neighbor in by_id:
                prio = edge_priority[r["edge_type"]]
                if neighbor not in expansion or prio < expansion[neighbor][0]:
                    expansion[neighbor] = (prio, r["edge_type"])

    expansion_ranked = sorted(
        expansion.items(),
        key=lambda kv: (kv[1][0], TIER_ORDER.get(by_id[kv[0]]["tier"], 9), kv[0]),
    )
    included = list(entry_ids)
    omitted_expansion = 0
    for cid, _ in expansion_ranked:
        if len(included) >= budget:
            omitted_expansion += 1
            continue
        included.append(cid)
    included_set = set(included)
    omitted_entries = 0
    if len(included) > budget:
        omitted_entries = len(included) - budget
        included = included[:budget]
        included_set = set(included)

    nodes = []
    for cid in included:
        c = by_id[cid]
        nodes.append({
            "id": c["id"],
            "name": c["name"],
            "topic_id": c["topic_id"],
            "topic_name": c["topic_name"],
            "domain": c["domain"],
            "type": c["type"],
            "tier": c["tier"],
            "blurb": c["blurb"],
            "role": "entry" if cid in entry_set else f"neighbor_{expansion[cid][1]}",
        })
    edges_in_scope = [e for e in scope_edges if e["src"] in included_set and e["dst"] in included_set]

    return {
        "ok": True,
        "scope": {
            "query": query,
            "topic_id": topic_id,
            "domain": domain,
            "anchored_topics": anchored_topics,
            "multi_scope_query": multi_scope_query,
            "budget": budget,
        },
        "nodes": nodes,
        "edges": edges_in_scope,
        "counts": {
            "nodes": len(nodes),
            "entries": len([n for n in nodes if n["role"] == "entry"]),
            "neighbors": len([n for n in nodes if n["role"] != "entry"]),
            "edges": len(edges_in_scope),
            "omitted_neighbors": omitted_expansion,
            "omitted_entries": omitted_entries,
        },
    }


# ── Learner mapping ─────────────────────────────────────────────────


def _open_memory_readonly(memory_db: Path) -> sqlite3.Connection | None:
    if not Path(memory_db).exists():
        return None
    conn = sqlite3.connect(f"file:{memory_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _learner_topic_ids(mem: sqlite3.Connection, learner_topics: list[str], resolve_topic) -> dict[str, int]:
    """Resolve learner topic hints to learner-memory topic ids deterministically.

    Reuses study_memory.resolve_topic — the same read-only resolver that created
    the topics — so a hint maps to the identical canonical topic the agent logged
    against, regardless of catalog rewriting or alias storage form.
    """
    resolved: dict[str, int] = {}
    for hint in learner_topics:
        try:
            res = resolve_topic(mem, str(hint), "")
        except Exception:
            continue
        if not res or not getattr(res, "slug", ""):
            continue
        row = mem.execute("SELECT id FROM topics WHERE canonical_slug = ?", (res.slug,)).fetchone()
        if row:
            resolved[res.slug] = int(row["id"])
    return resolved


# Learner-memory domain labels do not all share the inventory's domain slugs.
# Map the known divergences so a learner topic's domain can hint inventory scope.
_MEMORY_DOMAIN_ALIASES = {"critical-care": "neurocritical-care"}


def _resolved_topic_domain_hint(mem: sqlite3.Connection, topic_ids: list[int]) -> str:
    """Most common concrete domain across resolved learner topics, as an inventory hint.

    The catch-all 'general' label and empty domains are ignored. The returned slug
    is only a hint; scope_subgraph applies it solely when it names a domain actually
    present in the lexical matches, so a vocabulary mismatch is harmless.
    """
    if not topic_ids:
        return ""
    placeholders = ",".join("?" for _ in topic_ids)
    rows = mem.execute(
        f"""SELECT domain, COUNT(*) AS n FROM topics
            WHERE id IN ({placeholders}) AND COALESCE(domain, '') NOT IN ('', 'general')
            GROUP BY domain ORDER BY n DESC, domain""",
        topic_ids,
    ).fetchall()
    if not rows:
        return ""
    domain = str(rows[0]["domain"])
    return _MEMORY_DOMAIN_ALIASES.get(domain, domain)


def map_learner(
    *,
    inventory_conn: sqlite3.Connection,
    memory_db: Path,
    learner_topics: list[str],
    query: str = "",
    topic_id: str = "",
    domain: str = "",
    budget: int = DEFAULT_SCOPE_BUDGET,
) -> dict:
    """Project learner memory onto a scoped inventory subgraph (memory DB opened read-only)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cognitive_ops import mastery_depth_from_evidence, trusted_operation_from_signal  # noqa: PLC0415
    from study_memory import (  # noqa: PLC0415 - shared deterministic policy semantics
        TARGET_CONCEPTS_COMPACT_CAP,
        _compute_teaching_policy,
        _due_claims_for_summary,
        resolve_topic,
        shadow_rule_signals_for_summary,
    )

    mem = _open_memory_readonly(Path(memory_db))
    learner_status = "ok"
    learner_concepts: list[dict] = []
    resolved_topics: dict[str, int] = {}
    due_claims: list[dict] = []
    shadow_signals: list[dict] = []
    domain_hint = ""
    anchor_tokens: frozenset[str] = frozenset()
    if mem is None:
        learner_status = "memory_db_absent"
    else:
        resolved_topics = _learner_topic_ids(mem, learner_topics, resolve_topic)
        if learner_topics and not resolved_topics:
            learner_status = "no_learner_topics_resolved"
        topic_id_list = sorted(resolved_topics.values())
        domain_hint = _resolved_topic_domain_hint(mem, topic_id_list)
        if topic_id_list:
            placeholders = ",".join("?" for _ in topic_id_list)
            token_acc: set[str] = set()
            for r in mem.execute(
                f"SELECT display_name FROM concepts WHERE topic_id IN ({placeholders})",
                topic_id_list,
            ):
                token_acc |= set(_tokens(r["display_name"]))
            anchor_tokens = frozenset(token_acc)

    # Scope after the learner topic domain and studied-concept tokens are known so
    # a cross-domain lexical collision is disambiguated toward the learner's domain
    # and the concepts the learner actually drilled are pulled into the map.
    scope = scope_subgraph(
        inventory_conn, query=query, topic_id=topic_id, domain=domain,
        domain_hint=domain_hint, anchor_tokens=anchor_tokens, budget=budget,
    )
    if not scope.get("ok"):
        if mem is not None:
            mem.close()
        return scope

    scope_node_ids = {str(node["id"]) for node in scope["nodes"]}

    if mem is not None:
        selected_topic_ids = set(resolved_topics.values())
        # Canonical identity crosses document/topic envelopes. Once the inventory
        # scope is known, include every assessed claim explicitly bound to one of
        # those nodes, even when it was learned under another report, service, or
        # prior topic label. Unbound lexical evidence remains selected-topic only.
        cross_topic_ids: set[int] = set()
        if scope_node_ids:
            placeholders = ",".join("?" for _ in scope_node_ids)
            cross_topic_ids = {
                int(row["topic_id"])
                for row in mem.execute(
                    f"""SELECT DISTINCT cr.topic_id
                          FROM claim_results cr
                          JOIN concepts c ON c.id = cr.concept_id
                         WHERE cr.origin = 'assessed'
                           AND COALESCE(NULLIF(cr.inventory_concept_id, ''),
                                        NULLIF(c.inventory_concept_id, ''))
                               IN ({placeholders})""",
                    sorted(scope_node_ids),
                )
            }
        topic_ids = sorted(selected_topic_ids | cross_topic_ids)
        for tid in topic_ids:
            selected_topic = tid in selected_topic_ids
            topic_row = mem.execute(
                "SELECT canonical_slug, display_name FROM topics WHERE id = ?",
                (tid,),
            ).fetchone()
            topic_slug = str(topic_row["canonical_slug"] or "") if topic_row else ""
            concept_meta = {
                int(r["id"]): {
                    "name": r["display_name"],
                    "slug": r["canonical_slug"],
                    "binding": str(r["inventory_concept_id"] or ""),
                }
                for r in mem.execute(
                    """SELECT id, display_name, canonical_slug,
                              COALESCE(inventory_concept_id, '') AS inventory_concept_id
                         FROM concepts WHERE topic_id = ? ORDER BY id""",
                    (tid,),
                )
            }
            # CLAIM-LEVEL PROJECTION. Aggregate each concept's assessed attempts by the
            # claim's OWN inventory binding (falling back to the concept binding when a
            # claim carries none), so a single concept whose claims were tested against
            # several canonical nodes distributes its mastery to each — instead of the
            # old per-concept rollup that collapsed every claim onto one node and lost,
            # e.g., NASCIS history buried inside a STASCIS-bound concept.
            claim_rows = mem.execute(
                """SELECT cr.concept_id, COALESCE(cr.inventory_concept_id, '') AS claim_inv,
                          cr.claim_slug, cr.score, cr.learning_operation,
                          cr.agent_signal_json, cr.created_at, cr.id, ex.session_id
                     FROM claim_results cr
                     JOIN exchanges ex ON ex.id = cr.exchange_id
                    WHERE cr.topic_id = ? AND cr.origin = 'assessed'
                    ORDER BY cr.created_at DESC, cr.id DESC""",
                (tid,),
            ).fetchall()
            units: dict[tuple[int, str], list[tuple[str, int, int]]] = {}
            unit_operation_evidence: dict[
                tuple[int, str], dict[str, dict[str, object]]
            ] = {}
            slug_inv: dict[tuple[int, str], str] = {}
            for cr in claim_rows:
                cid = int(cr["concept_id"])
                meta = concept_meta.get(cid)
                if meta is None:
                    continue
                eff_inv = str(cr["claim_inv"]) or meta["binding"]
                if not selected_topic and eff_inv not in scope_node_ids:
                    continue
                units.setdefault((cid, eff_inv), []).append(
                    (str(cr["created_at"]), int(cr["id"]), int(cr["score"]))
                )
                if int(cr["score"]) >= 2:
                    operation = trusted_operation_from_signal(
                        operation=str(cr["learning_operation"] or ""),
                        agent_signal_json=str(cr["agent_signal_json"] or ""),
                    )
                    if operation:
                        op_evidence = unit_operation_evidence.setdefault((cid, eff_inv), {}).setdefault(
                            operation,
                            {"count": 0, "session_ids": set()},
                        )
                        op_evidence["count"] = int(op_evidence["count"]) + 1
                        session_ids = op_evidence["session_ids"]
                        if isinstance(session_ids, set) and cr["session_id"]:
                            session_ids.add(str(cr["session_id"]))
                slug_inv[(cid, str(cr["claim_slug"]))] = eff_inv
            unit_states: dict[tuple[int, str], list[dict]] = {}
            for sr in mem.execute(
                """SELECT concept_id, claim_slug, state, priority, stability, gap_type
                     FROM claim_state WHERE topic_id = ? AND origin = 'assessed' ORDER BY id""",
                (tid,),
            ):
                cid = int(sr["concept_id"])
                meta = concept_meta.get(cid)
                if meta is None:
                    continue
                # Route the gap to the same node its claim's attempts went to, so an
                # open gap holds the right node at superficial (states join results on
                # claim_slug; fall back to the concept binding for orphan states).
                eff_inv = slug_inv.get((cid, str(sr["claim_slug"])), meta["binding"])
                if not selected_topic and eff_inv not in scope_node_ids:
                    continue
                unit_states.setdefault((cid, eff_inv), []).append({
                    "state": sr["state"], "priority": sr["priority"],
                    "stability": sr["stability"], "gap_type": sr["gap_type"],
                })
            concepts_with_claims = {cid for (cid, _e) in units}
            for (cid, eff_inv), scored in units.items():
                meta = concept_meta[cid]
                operation_evidence = {
                    operation: {
                        "count": int(values["count"]),
                        "session_ids": sorted(values["session_ids"]),
                        "session_count": len(values["session_ids"]),
                    }
                    for operation, values in unit_operation_evidence.get((cid, eff_inv), {}).items()
                }
                learner_concepts.append({
                    "learner_concept_id": cid,
                    "name": meta["name"],
                    "slug": meta["slug"],
                    "memory_topic": topic_slug,
                    "inventory_concept_id": eff_inv,
                    "scored": scored,  # [(created_at, id, score)] most-recent-first
                    "attempts": len(scored),
                    "successes": sum(1 for _t, _i, s in scored if s >= 2),
                    "last_score": scored[0][2] if scored else 0,
                    "successful_operations": sorted(operation_evidence),
                    "successful_operation_evidence": operation_evidence,
                    "states": unit_states.get((cid, eff_inv), []),
                    "tokens": _tokens(meta["name"]),
                })
            # Concepts with no assessed claims still project (unexposed) at their binding
            # so a scoped-but-untested node is visible rather than silently dropped.
            for cid, meta in concept_meta.items():
                if cid in concepts_with_claims:
                    continue
                if not selected_topic:
                    continue
                learner_concepts.append({
                    "learner_concept_id": cid,
                    "name": meta["name"],
                    "slug": meta["slug"],
                    "memory_topic": topic_slug,
                    "inventory_concept_id": meta["binding"],
                    "scored": [],
                    "attempts": 0,
                    "successes": 0,
                    "last_score": 0,
                    "successful_operations": [],
                    "successful_operation_evidence": {},
                    "states": unit_states.get((cid, meta["binding"]), []),
                    "tokens": _tokens(meta["name"]),
                })
            try:
                topic_due = _due_claims_for_summary(mem, topic_id=tid, limit=8)
                due_claims.extend(
                    item for item in topic_due
                    if selected_topic or str(item.get("inventory_concept_id") or "") in scope_node_ids
                )
            except Exception as exc:  # noqa: BLE001 - optional signal, but observe the loss
                print(f"WARN map_learner_due_claims_failed topic_id={tid}: {exc}", file=sys.stderr)
        matched_ids = [lc["learner_concept_id"] for lc in learner_concepts]
        if matched_ids:
            try:
                shadow_signals = shadow_rule_signals_for_summary(mem, relevant_concept_ids=matched_ids, limit=4)
            except Exception as exc:  # noqa: BLE001 - optional signal, but observe the loss
                shadow_signals = []
                print(f"WARN map_learner_shadow_signals_failed: {exc}", file=sys.stderr)
        mem.close()

    # Deterministic lexical projection of learner concepts onto scoped inventory nodes.
    node_tokens: dict[str, frozenset[str]] = {}
    alias_rows = inventory_conn.execute("SELECT concept_id, alias FROM aliases ORDER BY concept_id, alias").fetchall()
    alias_map: dict[str, list[str]] = {}
    for r in alias_rows:
        alias_map.setdefault(r["concept_id"], []).append(r["alias"])
    for node in scope["nodes"]:
        toks = _tokens(node["name"])
        for alias in alias_map.get(node["id"], []):
            toks = toks | _tokens(alias)
        node_tokens[node["id"]] = toks

    assignments: dict[str, list[dict]] = {}
    unmatched: list[dict] = []
    for lc in learner_concepts:
        # Identity layer wins: an explicit inventory binding is honored directly so
        # the projection aggregates by the canonical node (and many fragmented rows
        # for one node consolidate) instead of re-deriving from the prose label.
        explicit = lc.get("inventory_concept_id")
        if explicit and explicit in scope_node_ids:
            assignments.setdefault(explicit, []).append({**lc, "match_score": 1.0, "binding_source": "explicit"})
            continue
        if explicit:
            unmatched.append({**lc, "binding_source": "explicit_out_of_scope"})
            continue
        best: tuple[float, str] | None = None
        for node in scope["nodes"]:
            score = _lexical_score(lc["tokens"], node_tokens[node["id"]])
            if best is None or score > best[0] or (score == best[0] and node["id"] < best[1]):
                best = (score, node["id"])
        if best and best[0] >= LEARNER_MATCH_THRESHOLD:
            assignments.setdefault(best[1], []).append({**lc, "match_score": round(best[0], 3)})
        else:
            unmatched.append(lc)

    open_gap_states = {"missed", "partially_repaired", "regressed"}
    misconception_gap_types = {"conceptual_confusion", "cross_contamination"}
    knowledge_map: list[dict] = []
    for node in scope["nodes"]:
        mapped = assignments.get(node["id"], [])
        # Merge the claim-level scored attempts of every unit mapped to this node and
        # order by recency, so last_score and the recency-weighted rate reflect the
        # node's actual most-recent attempts (not the per-unit max, which over-promoted).
        merged = sorted(
            (s for m in mapped for s in m.get("scored", [])),
            key=lambda x: (x[0], x[1]),
            reverse=True,
        )
        attempts = len(merged)
        successes = sum(1 for _t, _i, sc in merged if sc >= 2)
        last_score = merged[0][2] if merged else 0
        recent = merged[:3]
        recent_rate = round(sum(1 for _t, _i, sc in recent if sc >= 2) / len(recent), 3) if recent else 0.0
        successful_operations = sorted({
            operation
            for learner_concept in mapped
            for operation in learner_concept.get("successful_operations", [])
        })
        operation_evidence: dict[str, dict[str, object]] = {}
        for learner_concept in mapped:
            for operation, values in (
                learner_concept.get("successful_operation_evidence") or {}
            ).items():
                if not isinstance(values, dict):
                    continue
                bucket = operation_evidence.setdefault(
                    str(operation), {"count": 0, "session_ids": set()}
                )
                bucket["count"] = int(bucket["count"]) + int(values.get("count", 0) or 0)
                sessions = bucket["session_ids"]
                if isinstance(sessions, set):
                    sessions.update(str(item) for item in values.get("session_ids", []) if str(item))
        all_states = [s for m in mapped for s in m["states"]]
        stabilities = [s["stability"] for s in all_states if s["stability"] is not None]
        avg_stability = sum(stabilities) / len(stabilities) if stabilities else 1.0
        success_rate = round(successes / attempts, 3) if attempts else 0.0

        # The claim layer marks a confirmed/retained correct claim "durable"; this
        # map's state vocab calls that "passed". Without the mapping a durable-only
        # node falls through to "untested" — indistinguishable from never-tested, and
        # contradicting the live-session patch path, which already emits "passed".
        state_severity = {"missed": 0, "partially_repaired": 1, "regressed": 2, "repaired_same_session": 3, "passed": 4}
        worst_state = None
        worst_val = 99
        for s in all_states:
            st = "passed" if s["state"] == "durable" else s["state"]
            if st in state_severity and state_severity[st] < worst_val:
                worst_val = state_severity[st]
                worst_state = st

        is_gap = worst_state in open_gap_states if worst_state else False
        # Canonical exposure rule (mirrors study_memory._mastery_exposure): an open gap
        # holds at superficial, a single attempt never promotes, and the threshold reads
        # the recency-weighted rate so a turned-around node escapes its stale failures.
        if attempts == 0:
            exposure = "unexposed"
        elif last_score == 2 and not is_gap and attempts > 1:
            exposure = "exposed_deep"
        elif attempts == 1 or avg_stability < 2.0 or recent_rate < 0.6 or is_gap:
            exposure = "exposed_superficial"
        else:
            exposure = "exposed_deep"

        serialized_operation_evidence = {
            operation: {
                "count": int(values["count"]),
                "session_count": len(values["session_ids"]),
                "session_ids": sorted(values["session_ids"]),
            }
            for operation, values in operation_evidence.items()
        }
        knowledge_map.append({
            "concept_id": node["id"],
            "concept": node["name"],
            "topic_id": node["topic_id"],
            "tier": node["tier"],
            "type": node["type"],
            "role": node["role"],
            "exposure_status": exposure,
            "knowledge_state": worst_state or "untested",
            "attempts_count": attempts,
            "successes_count": successes,
            "sqlite_success_rate": success_rate,
            "successful_operations": successful_operations,
            "successful_operation_evidence": serialized_operation_evidence,
            "mastery_depth": mastery_depth_from_evidence(
                serialized_operation_evidence,
                active_gap=is_gap,
            ),
            "safety_critical": any(s["priority"] in ("urgent", "high") for s in all_states),
            "active_misconception": any(
                s["state"] in open_gap_states and str(s["gap_type"] or "") in misconception_gap_types
                for s in all_states
            ),
            "matched_learner_concepts": [
                {"learner_concept_id": m["learner_concept_id"], "name": m["name"],
                 "memory_topic": m.get("memory_topic", ""),
                 "match_score": m["match_score"], "binding_source": m.get("binding_source", "lexical")}
                for m in mapped
            ],
            "memory_context_count": len({str(m.get("memory_topic") or "") for m in mapped}),
        })

    plan = _compute_teaching_policy(knowledge_map, due_claims=due_claims, shadow_rule_signals=shadow_signals)
    if isinstance(plan.get("target_concepts"), list) and len(plan["target_concepts"]) > TARGET_CONCEPTS_COMPACT_CAP:
        targets = list(plan["target_concepts"])
        plan = dict(plan)
        plan["target_concepts"] = targets[:TARGET_CONCEPTS_COMPACT_CAP]
        plan["target_concepts_omitted"] = len(targets) - TARGET_CONCEPTS_COMPACT_CAP

    exposure_counts = {"unexposed": 0, "exposed_superficial": 0, "exposed_deep": 0}
    for entry in knowledge_map:
        exposure_counts[entry["exposure_status"]] += 1

    return {
        "ok": True,
        "learner_status": learner_status,
        "resolved_learner_topics": resolved_topics,
        "scope": scope["scope"],
        "knowledge_map": knowledge_map,
        "edges": scope["edges"],
        "sequential_teaching_plan": plan,
        "unmatched_learner_concepts": [
            {
                "learner_concept_id": lc["learner_concept_id"],
                "name": lc["name"],
                "inventory_concept_id": lc.get("inventory_concept_id") or "",
                "binding_source": lc.get("binding_source", "lexical_unmatched"),
            }
            for lc in unmatched
        ],
        "counts": {
            **scope["counts"],
            **exposure_counts,
            "learner_concepts": len(learner_concepts),
            "matched_learner_concepts": len(learner_concepts) - len(unmatched),
            "unmatched_learner_concepts": len(unmatched),
            "due_claims": len(due_claims),
        },
    }


# ── Stats ───────────────────────────────────────────────────────────


def stats(conn: sqlite3.Connection) -> dict:
    by_domain = {
        r["domain"]: r["cnt"]
        for r in conn.execute("SELECT domain, COUNT(*) AS cnt FROM concepts GROUP BY domain ORDER BY domain")
    }
    by_tier = {
        r["tier"]: r["cnt"]
        for r in conn.execute("SELECT tier, COUNT(*) AS cnt FROM concepts GROUP BY tier ORDER BY tier")
    }
    by_type = {
        r["type"]: r["cnt"]
        for r in conn.execute("SELECT type, COUNT(*) AS cnt FROM concepts GROUP BY type ORDER BY type")
    }
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta")}
    return {
        "ok": True,
        "concepts": conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0],
        "topics": conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0],
        "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        "acgme_links": conn.execute("SELECT COUNT(*) FROM acgme_links").fetchone()[0],
        "by_domain": by_domain,
        "by_tier": by_tier,
        "by_type": by_type,
        "source_hash": meta.get("source_hash", ""),
    }


# ── CLI ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Canonical neurosurgery concept inventory")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build")
    p_build.add_argument("--force", action="store_true")

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--file", default="", help="Validate a single domain JSON file")

    sub.add_parser("stats")

    p_scope = sub.add_parser("scope")
    p_scope.add_argument("--query", default="")
    p_scope.add_argument("--topic-id", default="")
    p_scope.add_argument("--domain", default="")
    p_scope.add_argument("--budget", type=int, default=DEFAULT_SCOPE_BUDGET)

    p_map = sub.add_parser("map-learner")
    p_map.add_argument("--query", default="")
    p_map.add_argument("--topic-id", default="")
    p_map.add_argument("--domain", default="")
    p_map.add_argument("--budget", type=int, default=DEFAULT_SCOPE_BUDGET)
    p_map.add_argument(
        "--memory-db",
        default=__import__("os").environ.get("NEURO_STUDY_MEMORY_DB", str(BASE_DIR / "data" / "study_memory.db")),
    )
    p_map.add_argument("--learner-topic", action="append", default=[],
                       help="Learner-memory topic slug/name to project (repeatable)")

    args = parser.parse_args(argv)

    if args.command == "build":
        result = build_db(force=args.force)
        print(_json_dumps(result))
        return 0 if result.get("ok") else 1
    if args.command == "validate":
        result = validate_sources(single_file=Path(args.file) if args.file else None)
        print(_json_dumps(result))
        return 0 if result.get("ok") else 1
    if args.command == "stats":
        conn = _open_inventory()
        result = stats(conn)
        conn.close()
        print(_json_dumps(result))
        return 0
    if args.command == "scope":
        conn = _open_inventory()
        result = scope_subgraph(
            conn, query=args.query, topic_id=args.topic_id, domain=args.domain, budget=args.budget,
        )
        conn.close()
        print(_json_dumps(result))
        return 0 if result.get("ok") else 1
    if args.command == "map-learner":
        conn = _open_inventory()
        result = map_learner(
            inventory_conn=conn,
            memory_db=Path(args.memory_db),
            learner_topics=list(args.learner_topic),
            query=args.query,
            topic_id=args.topic_id,
            domain=args.domain,
            budget=args.budget,
        )
        conn.close()
        print(_json_dumps(result))
        return 0 if result.get("ok") else 1
    return 1


if __name__ == "__main__":
    try:
        from _env_guard import check_environment
        check_environment(marker_file="concept_inventory.py")
    except ImportError:
        pass
    raise SystemExit(main())
