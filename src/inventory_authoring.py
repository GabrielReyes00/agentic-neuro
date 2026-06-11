"""Pillar C: disciplined addition of concepts to the canonical inventory.

The inventory JSON is the committed, curated source of truth. Nodes are added by
deliberate, reviewed commits — never runtime writes — and placement determines
whether the knowledge map's edges are correct. This tool makes the decision
inspectable and guards against the failure mode of an inventory that explodes
with redundant, over-granular nodes:

  propose  -> a report (placement, genuine-gap assessment via dedup, suggested
              connections, validation) plus the ready-to-insert node JSON.
              DEFAULT and side-effect free. The user reviews this and approves.
  apply    -> after approval, append the node to its domain JSON, validate, and
              rebuild. This is the only step that mutates the source of truth.

The report exists because the user cannot see the knowledge map (it is a local
JSON graph): it states where the node lands, whether it fills a real gap, and
what it connects to.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "src"))

# A proposed name this close to an existing concept is almost certainly a
# duplicate; recommend binding to the existing node instead of adding.
DUPLICATE_BLOCK_THRESHOLD = 0.7
DEDUP_REPORT_THRESHOLD = 0.4


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _slug(text: str) -> str:
    """Inventory id slug: lowercase, hyphenated, per data/concept_inventory/SCHEMA.md."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def canonical_dump(doc: dict) -> str:
    """Canonical inventory-file layout: scalar keys inline; `topics` and `concepts`
    one object per line with inline arrays. This is the committed standard — compact,
    diff-friendly (editing one concept is a one-line diff), and what every writer emits.
    """
    keys = list(doc.keys())
    parts: list[str] = []
    for ki, key in enumerate(keys):
        tail = "," if ki < len(keys) - 1 else ""
        val = doc[key]
        if key in ("topics", "concepts") and isinstance(val, list):
            parts.append(f'  {json.dumps(key)}: [')
            for i, item in enumerate(val):
                comma = "," if i < len(val) - 1 else ""
                parts.append("    " + json.dumps(item, ensure_ascii=False, separators=(", ", ": ")) + comma)
            parts.append("  ]" + tail)
        else:
            parts.append(f'  {json.dumps(key)}: {json.dumps(val, ensure_ascii=False, separators=(", ", ": "))}{tail}')
    return "{\n" + "\n".join(parts) + "\n}\n"


def normalize_format() -> dict:
    """Rewrite every domain JSON into the canonical one-per-line layout (round-trips
    through json, so content is unchanged), then validate and rebuild."""
    from concept_inventory import INVENTORY_DIR, build_db, validate_sources  # noqa: PLC0415

    changed: list[str] = []
    for path in sorted(INVENTORY_DIR.glob("*.json")):
        original = path.read_text()
        doc = json.loads(original)
        canonical = canonical_dump(doc)
        if canonical != original:
            path.write_text(canonical)
            rep = validate_sources(single_file=path)
            if not rep.get("ok"):
                path.write_text(original)  # roll back this file on validation failure
                return {"ok": False, "stage": "validate", "file": path.name, "errors": rep.get("errors", [])}
            changed.append(path.name)
    build = build_db(force=True)
    return {"ok": bool(build.get("ok")), "files_normalized": changed, "build_status": build.get("status")}


def _domain_file(domain: str) -> Path | None:
    from concept_inventory import INVENTORY_DIR  # noqa: PLC0415

    for path in sorted(INVENTORY_DIR.glob("*.json")):
        try:
            if json.loads(path.read_text()).get("domain") == domain:
                return path
        except (OSError, ValueError):
            continue
    return None


def _near_neighbors(
    inv: sqlite3.Connection, name: str, domain: str, *, limit: int = 5,
) -> list[dict]:
    """Existing concepts most lexically similar to the proposed name (dedup signal)."""
    from concept_inventory import _lexical_score, _tokens  # noqa: PLC0415

    query = _tokens(name)
    if not query:
        return []
    rows = inv.execute("SELECT id, name, domain, tier, topic_id FROM concepts").fetchall()
    aliases: dict[str, set[str]] = {}
    for r in inv.execute("SELECT concept_id, alias FROM aliases"):
        aliases.setdefault(str(r["concept_id"]), set()).add(str(r["alias"]))
    scored: list[tuple[float, dict]] = []
    for r in rows:
        cid = str(r["id"])
        toks = _tokens(r["name"])
        for alias in aliases.get(cid, set()):
            toks = toks | _tokens(alias)
        score = _lexical_score(query, toks)
        if score >= DEDUP_REPORT_THRESHOLD:
            scored.append((score, {
                "inventory_concept_id": cid, "concept": r["name"],
                "domain": r["domain"], "tier": r["tier"], "score": round(score, 3),
                "same_domain": r["domain"] == domain,
            }))
    scored.sort(key=lambda item: (-item[0], item[1]["inventory_concept_id"]))
    return [d for _s, d in scored[:limit]]


def _validate_edge_ids(inv: sqlite3.Connection, ids: list[str]) -> tuple[list[str], list[str]]:
    valid = {str(r["id"]) for r in inv.execute("SELECT id FROM concepts")}
    ok = [i for i in ids if i in valid]
    missing = [i for i in ids if i not in valid]
    return ok, missing


def propose_node(
    inv: sqlite3.Connection,
    *,
    name: str,
    domain: str,
    concept_type: str,
    tier: str,
    blurb: str,
    topic_id: str = "",
    topic_name: str = "",
    aliases: list[str] | None = None,
    prereqs: list[str] | None = None,
    discriminators: list[str] | None = None,
    related: list[str] | None = None,
) -> dict:
    """Build an approval report + ready-to-insert node JSON. No side effects."""
    from concept_inventory import VALID_TIERS, VALID_TYPES  # noqa: PLC0415

    errors: list[str] = []
    dom_row = inv.execute("SELECT slug, code, display_name FROM domains WHERE slug = ?", (domain,)).fetchone()
    if not dom_row:
        return {"ok": False, "errors": [f"unknown domain '{domain}'"]}
    code = dom_row["code"]
    if concept_type not in VALID_TYPES:
        errors.append(f"invalid type '{concept_type}' (one of {sorted(VALID_TYPES)})")
    if tier not in VALID_TIERS:
        errors.append(f"invalid tier '{tier}' (one of {sorted(VALID_TIERS)})")
    if not blurb.strip():
        errors.append("blurb is required (one sentence stating what mastery means)")

    # Topic: reuse an existing one, or stage a new one.
    new_topic = None
    if topic_id:
        trow = inv.execute("SELECT id, name FROM topics WHERE id = ?", (topic_id,)).fetchone()
        if not trow:
            errors.append(f"unknown topic_id '{topic_id}'")
        elif not topic_id.startswith(f"{code}."):
            errors.append(f"topic_id '{topic_id}' must start with '{code}.'")
    elif topic_name:
        topic_id = f"{code}.{_slug(topic_name)}"
        new_topic = {"id": topic_id, "name": topic_name, "blurb": ""}
    else:
        errors.append("provide either an existing --topic-id or a --topic-name for a new topic")

    concept_id = f"{topic_id}.{_slug(name)}" if topic_id else ""
    if concept_id and inv.execute("SELECT 1 FROM concepts WHERE id = ?", (concept_id,)).fetchone():
        errors.append(f"concept id '{concept_id}' already exists")

    # Dedup / genuine-gap assessment.
    neighbors = _near_neighbors(inv, name, domain)
    strong_dup = next((n for n in neighbors if n["score"] >= DUPLICATE_BLOCK_THRESHOLD), None)
    if strong_dup:
        gap = "possible_duplicate"
    elif neighbors:
        gap = "adjacent_nodes_exist_likely_genuine"
    else:
        gap = "genuine_gap"

    # Validate any agent-supplied edges; the missing ones are surfaced, not silently dropped.
    prereq_ok, prereq_bad = _validate_edge_ids(inv, prereqs or [])
    disc_ok, disc_bad = _validate_edge_ids(inv, discriminators or [])
    rel_ok, rel_bad = _validate_edge_ids(inv, related or [])
    for label, bad in (("prereqs", prereq_bad), ("discriminators", disc_bad), ("related", rel_bad)):
        if bad:
            errors.append(f"{label} reference unknown inventory ids: {bad}")

    proposed_node = {
        "id": concept_id,
        "name": name,
        "topic": topic_id,
        "type": concept_type,
        "tier": tier,
        "blurb": blurb,
        "aliases": sorted({a.strip().lower() for a in (aliases or []) if a.strip()}),
        "prereqs": prereq_ok,
        "discriminators": disc_ok,
        "related": rel_ok,
    }

    return {
        "ok": not errors,
        "errors": errors,
        "placement": {
            "domain": domain,
            "domain_display_name": dom_row["display_name"],
            "topic_id": topic_id,
            "topic_status": "new" if new_topic else "existing",
            "type": concept_type,
            "tier": tier,
            "concept_id": concept_id,
        },
        "gap_assessment": gap,
        "near_duplicates": neighbors,
        "connections": {
            "prereqs": prereq_ok,
            "discriminators": disc_ok,
            "related": rel_ok,
        },
        "new_topic": new_topic,
        "proposed_node": proposed_node,
        "review_note": (
            "Approve only if gap_assessment is not 'possible_duplicate'. If a near "
            "duplicate exists, bind the learner concept to it instead of adding a node."
        ),
    }


def apply_node(report: dict) -> dict:
    """Append an approved proposed node (and any new topic) to its domain JSON,
    validate, and rebuild. Only run after the user approves the proposal report."""
    from concept_inventory import build_db, validate_sources  # noqa: PLC0415

    if not report.get("ok"):
        return {"ok": False, "stage": "precheck", "errors": report.get("errors", ["report not ok"])}
    node = report["proposed_node"]
    domain = report["placement"]["domain"]
    path = _domain_file(domain)
    if not path:
        return {"ok": False, "stage": "locate", "errors": [f"no JSON file for domain '{domain}'"]}
    doc = json.loads(path.read_text())
    if any(c.get("id") == node["id"] for c in doc.get("concepts", [])):
        return {"ok": False, "stage": "dedup", "errors": [f"id {node['id']} already present in {path.name}"]}
    if report.get("new_topic"):
        doc.setdefault("topics", []).append(report["new_topic"])
    doc.setdefault("concepts", []).append(node)
    path.write_text(canonical_dump(doc))

    file_report = validate_sources(single_file=path)
    if not file_report.get("ok"):
        return {"ok": False, "stage": "validate", "errors": file_report.get("errors", []), "file": path.name}
    build = build_db(force=True)
    return {
        "ok": bool(build.get("ok")),
        "stage": "build",
        "file": path.name,
        "concept_id": node["id"],
        "build_status": build.get("status"),
        "counts": build.get("counts"),
    }


def add_aliases(alias_map: dict[str, list[str]]) -> dict:
    """Append aliases to existing inventory nodes (additive enrichment, no new nodes).

    Edits each domain JSON line-surgically so the one-concept-per-line format is
    preserved (minimal diff), validates, and rebuilds. Aliases make verbose learner
    phrasings bind to the canonical node and fix abbreviation-driven scope misses.
    """
    from concept_inventory import _open_inventory, build_db, validate_sources  # noqa: PLC0415

    inv = _open_inventory()
    id_domain = {str(r["id"]): str(r["domain"]) for r in inv.execute("SELECT id, domain FROM concepts")}
    inv.close()
    unknown = [cid for cid in alias_map if cid not in id_domain]
    if unknown:
        return {"ok": False, "stage": "validate_ids", "unknown_ids": unknown}

    by_domain: dict[str, dict[str, list[str]]] = {}
    for cid, aliases in alias_map.items():
        by_domain.setdefault(id_domain[cid], {})[cid] = aliases

    def _merge(existing: list[str], additions: list[str]) -> tuple[list[str], int]:
        out = list(existing)
        seen = {a.lower() for a in out}
        n = 0
        for alias in additions:
            norm = alias.strip().lower()
            if norm and norm not in seen:
                out.append(norm)
                seen.add(norm)
                n += 1
        return out, n

    touched_files: list[str] = []
    errors: list[str] = []
    added = 0
    alias_line_re = re.compile(r'^(\s*"aliases":\s*)(\[.*?\])(\s*,?)\s*$')
    for domain, cmap in by_domain.items():
        path = _domain_file(domain)
        if not path:
            return {"ok": False, "stage": "locate", "errors": [f"no JSON for domain {domain}"]}
        lines = path.read_text().split("\n")
        # Index concept id lines (works for both one-per-line and multi-line files).
        id_line = {}
        for i, line in enumerate(lines):
            for cid in cmap:
                if f'"id": "{cid}"' in line:
                    id_line[cid] = i
        for cid, new_aliases in cmap.items():
            if cid not in id_line:
                errors.append(f"{cid} not found in {path.name}")
                continue
            idx = id_line[cid]
            line = lines[idx]
            stripped = line.strip().rstrip(",")
            if stripped.startswith("{") and stripped.endswith("}"):
                # one concept per line: rewrite the whole object line
                obj = json.loads(stripped)
                obj["aliases"], n = _merge(list(obj.get("aliases", [])), new_aliases)
                added += n
                indent = line[: len(line) - len(line.lstrip())]
                trailing = "," if line.rstrip().endswith(",") else ""
                lines[idx] = indent + json.dumps(obj, ensure_ascii=False, separators=(", ", ": ")) + trailing
            else:
                # multi-line: find this concept's standalone "aliases": line
                alias_idx = None
                for j in range(idx, min(idx + 16, len(lines))):
                    if j != idx and '"id":' in lines[j]:
                        break  # next concept; aliases missing
                    if alias_line_re.match(lines[j]):
                        alias_idx = j
                        break
                if alias_idx is None:
                    errors.append(f"{cid}: no aliases line found in {path.name}")
                    continue
                m = alias_line_re.match(lines[alias_idx])
                merged, n = _merge(json.loads(m.group(2)), new_aliases)
                added += n
                lines[alias_idx] = m.group(1) + json.dumps(merged, ensure_ascii=False, separators=(", ", ": ")) + (m.group(3).strip() or "")
        path.write_text("\n".join(lines))
        touched_files.append(path.name)
        file_report = validate_sources(single_file=path)
        if not file_report.get("ok"):
            return {"ok": False, "stage": "validate", "file": path.name, "errors": file_report.get("errors", [])}
    if errors:
        return {"ok": False, "stage": "locate_concepts", "errors": errors}

    build = build_db(force=True)
    return {
        "ok": bool(build.get("ok")),
        "stage": "build",
        "aliases_added": added,
        "files_touched": sorted(touched_files),
        "build_status": build.get("status"),
        "alias_count": build.get("counts", {}).get("aliases"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Propose / apply a canonical inventory concept")
    parser.add_argument("--name", default="")
    parser.add_argument("--domain", default="")
    parser.add_argument("--type", dest="concept_type", default="")
    parser.add_argument("--tier", default="")
    parser.add_argument("--blurb", default="")
    parser.add_argument("--topic-id", default="")
    parser.add_argument("--topic-name", default="")
    parser.add_argument("--alias", action="append", default=[])
    parser.add_argument("--prereq", action="append", default=[])
    parser.add_argument("--discriminator", action="append", default=[])
    parser.add_argument("--related", action="append", default=[])
    parser.add_argument("--apply", action="store_true", help="Apply after approval (writes the domain JSON and rebuilds)")
    parser.add_argument("--add-aliases", default="", help="Path to a {concept_id: [aliases]} JSON; enriches existing nodes")
    parser.add_argument("--normalize", action="store_true", help="Rewrite all domain JSON into the canonical one-per-line layout")
    args = parser.parse_args(argv)

    if args.normalize:
        print(_json_dumps(normalize_format()))
        return 0
    if args.add_aliases:
        alias_map = json.loads(Path(args.add_aliases).read_text())
        result = add_aliases(alias_map)
        print(_json_dumps(result))
        return 0 if result.get("ok") else 1

    from concept_inventory import _open_inventory  # noqa: PLC0415

    inv = _open_inventory()
    try:
        report = propose_node(
            inv, name=args.name, domain=args.domain, concept_type=args.concept_type,
            tier=args.tier, blurb=args.blurb, topic_id=args.topic_id, topic_name=args.topic_name,
            aliases=args.alias, prereqs=args.prereq, discriminators=args.discriminator, related=args.related,
        )
    finally:
        inv.close()

    if args.apply:
        result = apply_node(report)
        print(_json_dumps({"proposal": report, "apply": result}))
        return 0 if result.get("ok") else 1
    print(_json_dumps(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
