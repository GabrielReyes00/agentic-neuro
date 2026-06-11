"""Pillar B: migrate legacy learner concepts onto the canonical inventory.

The new architecture keys teaching on inventory ids, but historic learner concepts
were logged before binding existed (as of the audit, 1 of 222 concepts were bound),
so the system runs almost entirely on fallbacks. This tool backfills the binding.

Design constraints (from the redesign plan):
  - Runs against a COPY of the memory DB (NEURO_STUDY_MEMORY_DB); never the live one
    unless explicitly pointed there. The original stays as an untouched legacy copy.
  - Hybrid: auto-bind only confident, atomic matches; everything else goes to an
    agent-review queue. NEVER auto-bind a guess.
  - Non-destructive and idempotent: re-running --apply only fills unbound rows.
  - Auditable: --report emits tiered counts and per-concept detail.

Tiers:
  auto        score >= AUTO_BIND_THRESHOLD and the label is atomic  -> bind now
  provisional PROVISIONAL_THRESHOLD <= score < AUTO, or conflated   -> review queue
  unbindable  score < PROVISIONAL_THRESHOLD                          -> real gap (Pillar C)
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "src"))

AUTO_BIND_THRESHOLD = 0.6
PROVISIONAL_THRESHOLD = 0.42


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def _inventory_token_index(inv: sqlite3.Connection) -> list[tuple[str, str, str, frozenset]]:
    """(id, name, domain, name+alias tokens) for every inventory concept."""
    from concept_inventory import _tokens  # noqa: PLC0415

    rows = inv.execute("SELECT id, name, domain FROM concepts").fetchall()
    tok: dict[str, frozenset] = {str(r["id"]): _tokens(r["name"]) for r in rows}
    name: dict[str, str] = {str(r["id"]): str(r["name"]) for r in rows}
    domain: dict[str, str] = {str(r["id"]): str(r["domain"]) for r in rows}
    for r in inv.execute("SELECT concept_id, alias FROM aliases"):
        cid = str(r["concept_id"])
        if cid in tok:
            tok[cid] = tok[cid] | _tokens(r["alias"])
    return [(cid, name[cid], domain[cid], tok[cid]) for cid in tok]


def _best_match(
    concept_name: str,
    index: list[tuple[str, str, str, frozenset]],
) -> tuple[str, str, float]:
    """Best inventory (id, name, score) for a learner concept label."""
    from concept_inventory import _lexical_score, _tokens  # noqa: PLC0415

    query = _tokens(concept_name)
    if not query:
        return "", "", 0.0
    best: tuple[float, str, str] | None = None
    for cid, name, _domain, toks in index:
        score = _lexical_score(query, toks)
        if best is None or score > best[0] or (score == best[0] and cid < best[1]):
            best = (score, cid, name)
    if not best:
        return "", "", 0.0
    return best[1], best[2], best[0]


def _classify(score: float, conflated: bool, cross_domain: bool) -> str:
    """Auto-bind only confident, atomic, in-domain matches; demote the rest.

    A cross-domain best match (e.g. a vascular concept whose top lexical hit is a
    trauma node) is never auto-bound — global lexical matching has no domain
    context, so the demotion routes it to agent review instead of a silent mis-bind.
    """
    blocked = conflated or cross_domain
    if score >= AUTO_BIND_THRESHOLD and not blocked:
        return "auto"
    if score >= PROVISIONAL_THRESHOLD or (score >= AUTO_BIND_THRESHOLD and blocked):
        return "provisional"
    return "unbindable"


def migrate(
    conn: sqlite3.Connection,
    inv: sqlite3.Connection,
    *,
    apply: bool = False,
) -> dict[str, object]:
    """Classify every learner concept; optionally apply the confident bindings."""
    from concept_inventory import _MEMORY_DOMAIN_ALIASES  # noqa: PLC0415
    from memory_logging import atomicity_warnings  # noqa: PLC0415

    index = _inventory_token_index(inv)
    domain_by_id = {cid: domain for cid, _name, domain, _toks in index}
    rows = conn.execute(
        """SELECT c.id, c.display_name, COALESCE(c.inventory_concept_id, '') AS bound,
                  COALESCE(t.domain, '') AS learner_domain,
                  COALESCE(a.attempts, 0) AS attempts
             FROM concepts c
             LEFT JOIN topics t ON t.id = c.topic_id
             LEFT JOIN (
                 SELECT concept_id, COUNT(*) AS attempts
                   FROM claim_results WHERE origin = 'assessed'
                  GROUP BY concept_id
             ) a ON a.concept_id = c.id
            ORDER BY a.attempts DESC, c.id"""
    ).fetchall()

    tiers = {"auto": [], "provisional": [], "unbindable": [], "already_bound": []}
    applied = 0
    claim_rows_bound = 0
    for r in rows:
        cid = int(r["id"])
        name = str(r["display_name"])
        attempts = int(r["attempts"])
        if r["bound"]:
            tiers["already_bound"].append({"learner_concept_id": cid, "name": name, "inventory_concept_id": r["bound"]})
            continue
        inv_id, inv_name, score = _best_match(name, index)
        conflated = bool(atomicity_warnings(name))
        learner_domain = _MEMORY_DOMAIN_ALIASES.get(str(r["learner_domain"]), str(r["learner_domain"]))
        inv_domain = domain_by_id.get(inv_id, "")
        cross_domain = bool(
            learner_domain and inv_domain
            and learner_domain != "general"
            and inv_domain != learner_domain
        )
        tier = _classify(score, conflated, cross_domain)
        record = {
            "learner_concept_id": cid,
            "name": name,
            "attempts": attempts,
            "best_inventory_id": inv_id,
            "best_inventory_name": inv_name,
            "score": round(score, 3),
            "conflated_label": conflated,
            "cross_domain": cross_domain,
            "learner_domain": learner_domain,
            "inventory_domain": inv_domain,
        }
        tiers[tier].append(record)
        if tier == "auto" and apply:
            conn.execute(
                "UPDATE concepts SET inventory_concept_id = ?, binding_match_count = MAX(COALESCE(binding_match_count,0), 2) WHERE id = ?",
                (inv_id, cid),
            )
            cur = conn.execute(
                "UPDATE claim_results SET inventory_concept_id = ? WHERE concept_id = ? AND COALESCE(inventory_concept_id,'') = ''",
                (inv_id, cid),
            )
            claim_rows_bound += cur.rowcount
            applied += 1
    if apply:
        conn.commit()

    return {
        "ok": True,
        "applied": apply,
        "thresholds": {"auto_bind": AUTO_BIND_THRESHOLD, "provisional": PROVISIONAL_THRESHOLD},
        "counts": {
            "total_concepts": len(rows),
            "already_bound": len(tiers["already_bound"]),
            "auto": len(tiers["auto"]),
            "provisional": len(tiers["provisional"]),
            "unbindable": len(tiers["unbindable"]),
            "concepts_bound_this_run": applied,
            "claim_results_bound_this_run": claim_rows_bound,
        },
        "auto": tiers["auto"],
        "provisional": tiers["provisional"],
        "unbindable": tiers["unbindable"],
    }


def bind_reviewed(
    conn: sqlite3.Connection,
    inv: sqlite3.Connection,
    pairs: list[tuple[int, str]],
) -> dict[str, object]:
    """Apply agent-reviewed bindings for the provisional tier (one at a time).

    Validates the inventory id exists before writing; idempotent per concept.
    """
    valid_ids = {str(r["id"]) for r in inv.execute("SELECT id FROM concepts")}
    bound = 0
    claim_rows = 0
    errors: list[str] = []
    for learner_id, inv_id in pairs:
        if inv_id not in valid_ids:
            errors.append(f"unknown inventory id: {inv_id}")
            continue
        conn.execute(
            "UPDATE concepts SET inventory_concept_id = ?, binding_match_count = MAX(COALESCE(binding_match_count,0), 2) WHERE id = ?",
            (inv_id, learner_id),
        )
        cur = conn.execute(
            "UPDATE claim_results SET inventory_concept_id = ? WHERE concept_id = ? AND COALESCE(inventory_concept_id,'') = ''",
            (inv_id, learner_id),
        )
        claim_rows += cur.rowcount
        bound += 1
    conn.commit()
    return {"ok": not errors, "bound": bound, "claim_results_bound": claim_rows, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy learner concepts onto the inventory")
    parser.add_argument("--apply", action="store_true", help="Write the auto-tier bindings (default: dry-run report)")
    parser.add_argument("--json", action="store_true", help="Emit the full per-concept report as JSON")
    parser.add_argument("--limit", type=int, default=15, help="Per-tier rows to show in the human summary")
    parser.add_argument(
        "--bind", action="append", default=[], metavar="LEARNER_ID=INVENTORY_ID",
        help="Apply a reviewed provisional binding (repeatable); skips auto-tier logic",
    )
    args = parser.parse_args(argv)

    import study_memory  # noqa: PLC0415
    from concept_inventory import _open_inventory  # noqa: PLC0415

    conn = study_memory._get_db()
    inv = _open_inventory()
    try:
        if args.bind:
            pairs: list[tuple[int, str]] = []
            for item in args.bind:
                lid, _, iid = item.partition("=")
                pairs.append((int(lid), iid.strip()))
            result = bind_reviewed(conn, inv, pairs)
            print(_json_dumps(result))
            return 0 if result["ok"] else 1
        report = migrate(conn, inv, apply=args.apply)
    finally:
        inv.close()
        conn.close()

    if args.json:
        print(_json_dumps(report))
        return 0
    c = report["counts"]
    db_path = os.environ.get("NEURO_STUDY_MEMORY_DB", "data/study_memory.db")
    print(f"DB: {db_path}  (applied={report['applied']})")
    print(f"concepts: {c['total_concepts']}  already_bound={c['already_bound']}  "
          f"auto={c['auto']}  provisional={c['provisional']}  unbindable={c['unbindable']}")
    if args.apply:
        print(f"bound this run: {c['concepts_bound_this_run']} concepts, {c['claim_results_bound_this_run']} claim_results")
    for tier in ("auto", "provisional", "unbindable"):
        rows = report[tier][: args.limit]
        if not rows:
            continue
        print(f"\n[{tier}]")
        for r in rows:
            flag = " CONFLATED" if r["conflated_label"] else ""
            print(f"  {r['score']:.3f}  {r['name'][:46]:46} -> {r['best_inventory_id']}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
