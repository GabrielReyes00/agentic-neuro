"""Pillar B (complete): reshape every legacy learner concept/claim to the new
logging architecture on the migration COPY.

This goes beyond the conservative auto-binder (legacy_migration.py). It produces a
full triage of all concepts with ranked inventory candidates and a proposed action,
then applies an agent-reviewed decision file:

  bind          set inventory_concept_id (+ backfill claim_results)
  relabel_bind  bind AND rewrite the verbose/conflated display_name to the canonical
                inventory node name (the specifics already live in claim_text)
  split         create a second concept row for a conflated label and move the
                matching claim_results to it, binding each side to its own node
  drop          mark a non-clinical row (synthesis/self-assessment/artifact) as
                not a tracked clinical claim (origin -> 'reference')
  propose_node  no good inventory home -> Pillar C input (left unbound, surfaced)

Operates only on the DB that NEURO_STUDY_MEMORY_DB points to. Idempotent.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "src"))

AUTO_BIND = 0.6
REVIEW_FLOOR = 0.42
# Legacy concepts in the learner's own concrete domain bind on a weaker lexical
# signal: domain coherence plus any real token overlap is a strong indicator, and
# the specifics are preserved in claim_text regardless.
IN_DOMAIN_FLOOR = 0.28

# Substrings that mark a row as not a durable clinical concept (drop -> reference).
NON_CLINICAL_MARKERS = (
    "synthesis", "self-assessment", "self assessment", "artifact anchor",
    "test-topic", "test topic", "context regression", "scratch",
    "session length", "checkpoint", "coverage anchor", "generate-report",
    "report coverage", "consequence transfer scenario", "checklist/presentation",
    "you mentioned", "you correctly", "youve got", "you got the", "handoff data",
)
# Prefixes that mark a logged row as a conversational fragment, not a concept.
_CONVERSATIONAL_PREFIXES = ("you ", "youve ", "you've ", "your ", "if ", "next ", "that mean", "the snowball")


def _json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _reshape_index(inv: sqlite3.Connection):
    """(id, name, domain, name_tokens, full_tokens, alias_token_sets) per concept.

    Keeps the node NAME tokens separate from aliases so a verbose learner label can
    be matched by node-name coverage, not just diluted symmetric overlap.
    """
    from concept_inventory import _tokens  # noqa: PLC0415

    base = {
        str(r["id"]): (str(r["name"]), str(r["domain"]), _tokens(r["name"]))
        for r in inv.execute("SELECT id, name, domain FROM concepts")
    }
    alias_sets: dict[str, list[frozenset]] = {}
    for r in inv.execute("SELECT concept_id, alias FROM aliases"):
        cid = str(r["concept_id"])
        if cid in base:
            alias_sets.setdefault(cid, []).append(_tokens(r["alias"]))
    out = []
    for cid, (name, domain, name_toks) in base.items():
        a_sets = alias_sets.get(cid, [])
        full = name_toks
        for a in a_sets:
            full = full | a
        out.append((cid, name, domain, name_toks, full, a_sets))
    return out


def _match_score(label_tokens: frozenset, name_toks: frozenset, full_toks: frozenset, alias_sets) -> float:
    """Migration matcher: reward the node name (or a multi-word alias) appearing
    inside a verbose label, then fall back to symmetric lexical overlap."""
    from concept_inventory import _lexical_score  # noqa: PLC0415

    if not label_tokens or not name_toks:
        return 0.0
    best = _lexical_score(label_tokens, full_toks)
    # Full multi-word node name contained in the label -> the label is about it.
    if len(name_toks) >= 2 and name_toks <= label_tokens:
        best = max(best, 0.9)
    elif len(name_toks) >= 2:
        coverage = len(name_toks & label_tokens) / len(name_toks)
        if coverage >= 0.66:
            best = max(best, 0.6 + 0.25 * coverage)
    for a in alias_sets:
        if len(a) >= 2 and a <= label_tokens:
            best = max(best, 0.85)
    return best


def _ranked(name: str, index) -> list[dict]:
    """All inventory concepts scored against the label (migration matcher), best first."""
    from concept_inventory import _tokens  # noqa: PLC0415

    query = _tokens(name)
    if not query:
        return []
    scored: list[tuple[float, str, str, str]] = []
    for cid, cname, domain, name_toks, full_toks, alias_sets in index:
        score = _match_score(query, name_toks, full_toks, alias_sets)
        if score > 0:
            scored.append((score, cid, cname, domain))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"inventory_concept_id": cid, "concept": cname, "domain": domain, "score": round(score, 3)}
        for score, cid, cname, domain in scored
    ]


def _choose(ranked: list[dict], learner_domain: str) -> tuple[dict | None, bool]:
    """Pick the binding: prefer the best in-domain candidate when the learner topic
    carries a concrete domain; otherwise fall back to the global best."""
    if not ranked:
        return None, False
    global_best = ranked[0]
    if learner_domain and learner_domain != "general":
        in_domain = next((c for c in ranked if c["domain"] == learner_domain), None)
        if in_domain and in_domain["score"] >= IN_DOMAIN_FLOOR:
            return in_domain, True
    return global_best, global_best["domain"] == learner_domain


def _is_non_clinical(name: str) -> bool:
    low = name.lower().strip()
    if len(low) <= 2 or low.endswith(" vs"):
        return True
    if any(low.startswith(p) for p in _CONVERSATIONAL_PREFIXES):
        return True
    return any(m in low for m in NON_CLINICAL_MARKERS)


def analyze(conn: sqlite3.Connection, inv: sqlite3.Connection) -> dict:
    """Full per-concept triage with ranked candidates and a proposed action."""
    from concept_inventory import _MEMORY_DOMAIN_ALIASES  # noqa: PLC0415
    from memory_logging import atomicity_warnings  # noqa: PLC0415

    index = _reshape_index(inv)
    domain_by_id = {cid: domain for cid, _n, domain, _nt, _ft, _a in index}
    rows = conn.execute(
        """SELECT c.id, c.display_name, COALESCE(c.inventory_concept_id,'') AS bound,
                  COALESCE(t.domain,'') AS learner_domain,
                  COALESCE(a.attempts,0) AS attempts
             FROM concepts c
             LEFT JOIN topics t ON t.id = c.topic_id
             LEFT JOIN (SELECT concept_id, COUNT(*) AS attempts FROM claim_results
                        WHERE origin='assessed' GROUP BY concept_id) a ON a.concept_id = c.id
            ORDER BY a.attempts DESC, c.id"""
    ).fetchall()

    records = []
    tally = {"bind": 0, "relabel_bind": 0, "split": 0, "drop": 0, "propose_node": 0, "already_bound": 0}
    pattern_tally = {
        "conflated_concept": 0, "comparison_as_concept": 0, "evidence_in_label": 0,
        "verbose_label": 0, "non_clinical": 0, "cross_domain_best": 0, "no_candidate": 0,
    }
    for r in rows:
        name = str(r["display_name"])
        ranked = _ranked(name, index)
        cands = ranked[:3]
        flags = atomicity_warnings(name)
        flag_keys = [f.split(":")[0] for f in flags]
        non_clinical = _is_non_clinical(name)
        learner_domain = _MEMORY_DOMAIN_ALIASES.get(str(r["learner_domain"]), str(r["learner_domain"]))
        chosen, in_domain = _choose(ranked, learner_domain)
        global_top = ranked[0] if ranked else None
        cross_domain = bool(
            global_top and learner_domain and global_top["domain"]
            and learner_domain != "general" and global_top["domain"] != learner_domain
        )
        for k in flag_keys:
            if k in pattern_tally:
                pattern_tally[k] += 1
        if non_clinical:
            pattern_tally["non_clinical"] += 1
        if cross_domain:
            pattern_tally["cross_domain_best"] += 1
        if not ranked:
            pattern_tally["no_candidate"] += 1

        floor = IN_DOMAIN_FLOOR if in_domain else REVIEW_FLOOR
        if r["bound"]:
            action = "already_bound"
        elif non_clinical:
            action = "drop"
        elif not chosen or chosen["score"] < floor:
            action = "propose_node"
        elif flags:
            # A conflated/verbose label that still matches a node well: bind + relabel.
            action = "relabel_bind"
        elif chosen["score"] >= AUTO_BIND:
            action = "bind"
        else:
            action = "relabel_bind"
        tally[action] += 1

        records.append({
            "learner_concept_id": int(r["id"]),
            "display_name": name,
            "attempts": int(r["attempts"]),
            "learner_domain": learner_domain,
            "atomicity_flags": flag_keys,
            "non_clinical": non_clinical,
            "cross_domain_best": cross_domain,
            "chosen_in_domain": in_domain,
            "candidates": cands,
            "proposed_action": action,
            "proposed_inventory_id": chosen["inventory_concept_id"] if (chosen and action in ("bind", "relabel_bind")) else "",
            "proposed_label": (chosen["concept"] if (chosen and action == "relabel_bind") else name),
        })
    return {
        "ok": True,
        "counts": {"total": len(rows), **tally},
        "pattern_tally": pattern_tally,
        "records": records,
    }


_ANATOMY_CST = ("corticospinal", "cst ", " cst", "lcst", "cst.", "cst,")
_ANATOMY_TRACTS = (
    "dcml", "dorsal column", "medial lemniscus", "lemniscus", "stt", "spinothalamic",
    "anterolateral", "long tract", "somatotopy", "syrinx", "ventral horn", "lmn",
    "internal arcuate", "decussation", "spinal trigeminal", "lateral medullary",
    "brainstem lesion", "als ", "horn anatomy", "fiber",
)


def _cluster_target(label: str, domain: str) -> str:
    """Agent-reviewed cluster mapping for legacy concepts whose phrasing does not
    lexically match the canonical node. Returns '' for a genuine gap."""
    low = f" {label.lower()} "
    # Specific overrides for partial-token mis-matches caught in review.
    if "metastatic" in low and ("cord compression" in low or "spinal cord" in low or "mscc" in low):
        return "spi.oncology.metastatic-cord-compression"
    if "epidural abscess" in low or "spinal epidural abscess" in low:
        return "spi.infection.spinal-epidural-abscess"
    if "epidural hematoma" in low and ("postop" in low or "post-op" in low or "spinal" in low):
        return "spi.complications.postop-epidural-hematoma"
    # Long-tract / brainstem anatomy: the abbreviations are unambiguous regardless of
    # the (often 'general') learner topic domain.
    if any(k in low for k in ("spinal trigeminal", "lateral medullary", "medullary crossed")):
        return "ana.brainstem.medulla"
    if any(k in low for k in _ANATOMY_CST):
        return "ana.cortex.corticospinal-tract"
    if any(k in low for k in _ANATOMY_TRACTS):
        return "ana.spine.spinal-cord-tracts"
    if "lgn" in low or "mgn" in low or "geniculate" in low:
        return "ana.deep.thalamus"
    if any(k in low for k in ("evd", "stopcock", "csf return", "catheter", "drain", "ventriculitis")):
        if "wean" in low:
            return "ncc.monitoring.evd-weaning"
        if any(k in low for k in ("antibiotic", "prophyla", "ventriculitis", "infection")):
            return "ncc.monitoring.evd-infection-prevention"
        return "ncc.monitoring.evd-management"
    if "osmotherapy" in low or "hyperosmolar" in low or "osmotic" in low:
        return "fnd.pharm.osmotherapy"
    if "herniation" in low:
        return "fnd.icp.herniation-syndromes"
    if "xanthochromia" in low:
        return "vasc.sah.lumbar-puncture-xanthochromia"
    if "syringomyelia" in low or "syrinx" in low:
        return "spi.intradural.syringomyelia"
    if "mri signal" in low:
        return "fnd.imaging.mri-sequences"
    if any(k in low for k in ("nicardipine", "nitroprusside", "antihypertensive", "blood pressure", " bp ", "permissive hypertension", "pres ")):
        if "ich" in low:
            return "ncc.hemodynamics.bp-management-ich"
        if "sah" in low or "asah" in low:
            return "ncc.hemodynamics.bp-management-sah"
        return "ncc.hemodynamics.hypertensive-emergency"
    return ""


def gen_decisions(report: dict, inv: sqlite3.Connection) -> list[dict]:
    """Convert the triage into an executable decision list (the auditable artifact).

    bind/relabel_bind/drop pass through; propose_node is routed through the cluster
    map and becomes a relabel_bind when a canonical node is found, else stays a gap.
    """
    name_by_id = {str(r["id"]): str(r["name"]) for r in inv.execute("SELECT id, name FROM concepts")}
    decisions: list[dict] = []
    gaps: list[dict] = []
    for rec in report["records"]:
        action = rec["proposed_action"]
        lid = rec["learner_concept_id"]
        if action == "already_bound":
            continue
        if action == "drop":
            decisions.append({"action": "drop", "learner_concept_id": lid})
            continue
        # Agent-reviewed cluster rules win over the fuzzy matcher's choice — they
        # correct partial-token mis-matches (e.g. "metastatic spinal cord
        # compression" -> spinal-cord-anatomy) that the matcher gets wrong.
        target = _cluster_target(rec["display_name"], rec["learner_domain"])
        if not target and action in ("bind", "relabel_bind"):
            target = rec["proposed_inventory_id"]
        if target and target in name_by_id:
            decisions.append({
                "action": "relabel_bind", "learner_concept_id": lid,
                "inventory_concept_id": target, "new_label": name_by_id[target],
            })
        else:
            gaps.append({"learner_concept_id": lid, "display_name": rec["display_name"],
                         "attempts": rec["attempts"], "learner_domain": rec["learner_domain"]})
    return decisions, gaps  # type: ignore[return-value]


def apply_decisions(conn: sqlite3.Connection, inv: sqlite3.Connection, decisions: list[dict]) -> dict:
    """Execute an agent-reviewed decision list. Idempotent per concept."""
    valid_ids = {str(r["id"]) for r in inv.execute("SELECT id FROM concepts")}
    summary = {"bind": 0, "relabel_bind": 0, "split": 0, "drop": 0, "skipped": 0, "errors": []}
    for d in decisions:
        action = d.get("action")
        lid = int(d["learner_concept_id"])
        inv_id = str(d.get("inventory_concept_id", ""))
        if action in ("bind", "relabel_bind", "split") and inv_id and inv_id not in valid_ids:
            summary["errors"].append(f"{lid}: unknown inventory id {inv_id}")
            continue
        if action == "drop":
            conn.execute(
                "UPDATE claim_results SET origin='reference' WHERE concept_id=? AND origin='assessed'",
                (lid,),
            )
            conn.execute(
                "UPDATE claim_state SET origin='reference' WHERE concept_id=? AND origin='assessed'",
                (lid,),
            )
            summary["drop"] += 1
            continue
        if action in ("bind", "relabel_bind"):
            conn.execute(
                "UPDATE concepts SET inventory_concept_id=?, binding_match_count=MAX(COALESCE(binding_match_count,0),2) WHERE id=?",
                (inv_id, lid),
            )
            conn.execute(
                "UPDATE claim_results SET inventory_concept_id=? WHERE concept_id=? AND COALESCE(inventory_concept_id,'')=''",
                (inv_id, lid),
            )
            if action == "relabel_bind" and d.get("new_label"):
                conn.execute("UPDATE concepts SET display_name=? WHERE id=?", (d["new_label"], lid))
            summary[action] += 1
            continue
        if action == "split":
            # Move claim_results whose claim_slug is in claim_slugs to a new concept
            # bound to second_inventory_id; the primary keeps inv_id.
            second_inv = str(d.get("second_inventory_id", ""))
            second_label = str(d.get("second_label", ""))
            slugs = d.get("claim_slugs", [])
            if second_inv and second_inv not in valid_ids:
                summary["errors"].append(f"{lid}: unknown second inventory id {second_inv}")
                continue
            trow = conn.execute("SELECT topic_id FROM concepts WHERE id=?", (lid,)).fetchone()
            if not trow:
                summary["errors"].append(f"{lid}: concept not found")
                continue
            new_slug = str(d.get("second_slug") or (second_label.lower().replace(" ", "-")))
            new_cid = conn.execute(
                "INSERT INTO concepts (topic_id, canonical_slug, display_name, inventory_concept_id, binding_match_count) VALUES (?,?,?,?,2)",
                (int(trow["topic_id"]), new_slug, second_label, second_inv),
            ).lastrowid
            # primary binding
            conn.execute(
                "UPDATE concepts SET inventory_concept_id=?, binding_match_count=MAX(COALESCE(binding_match_count,0),2) WHERE id=?",
                (inv_id, lid),
            )
            if d.get("new_label"):
                conn.execute("UPDATE concepts SET display_name=? WHERE id=?", (d["new_label"], lid))
            placeholders = ",".join("?" for _ in slugs)
            if slugs:
                conn.execute(
                    f"UPDATE claim_results SET concept_id=?, inventory_concept_id=? WHERE concept_id=? AND claim_slug IN ({placeholders})",
                    (new_cid, second_inv, lid, *slugs),
                )
                conn.execute(
                    f"UPDATE claim_state SET concept_id=? WHERE concept_id=? AND claim_slug IN ({placeholders})",
                    (new_cid, lid, *slugs),
                )
            conn.execute(
                "UPDATE claim_results SET inventory_concept_id=? WHERE concept_id=? AND COALESCE(inventory_concept_id,'')=''",
                (inv_id, lid),
            )
            summary["split"] += 1
            continue
        summary["skipped"] += 1
    conn.commit()
    return summary


import re as _re

# Grading / feedback lead-ins that polluted the canonical claim_text; the claim
# should state the rule, not the agent's verdict on the answer.
_FEEDBACK_PREFIX = _re.compile(
    r"^(correct|incorrect|partial|partially correct|close|nearly|good|right|yes|exactly|"
    r"strong\s+\w+|this correctly\s+\w+|nice|well done|great|spot on)"
    r"\s*[:,.—-]+\s*",
    _re.IGNORECASE,
)


def clean_claim_text_value(text: str) -> str:
    """Strip a leading grading verdict and normalize whitespace (idempotent)."""
    cleaned = _re.sub(r"\s+", " ", str(text or "")).strip()
    original = cleaned
    prev = None
    while cleaned != prev:
        prev = cleaned
        cleaned = _FEEDBACK_PREFIX.sub("", cleaned).strip()
    # Capitalize the first letter if we stripped a prefix and left a lowercase start.
    if cleaned and cleaned != original and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned or original


def clean_claim_text(conn: sqlite3.Connection) -> dict:
    """Strip feedback-prefix pollution from claim_text in claim_results and claim_state.

    Touches only the human-readable claim_text (NOT claim_slug), so existing
    claim_state <-> claim_results links by slug are preserved.
    """
    updated = {"claim_results": 0, "claim_state": 0}
    for table in ("claim_results", "claim_state"):
        rows = conn.execute(f"SELECT id, claim_text FROM {table} WHERE COALESCE(claim_text,'') != ''").fetchall()
        for r in rows:
            cleaned = clean_claim_text_value(r["claim_text"])
            if cleaned != r["claim_text"]:
                conn.execute(f"UPDATE {table} SET claim_text = ? WHERE id = ?", (cleaned, int(r["id"])))
                updated[table] += 1
    conn.commit()
    return {"ok": True, "updated": updated}


def consolidate_bound_concepts(conn: sqlite3.Connection) -> dict:
    """Collapse fragmented learner-concept rows that share an inventory binding.

    The old logging created a new concept row per verbose label variant, so one
    canonical inventory concept (e.g. "Spinal cord tracts") is split across many
    rows. The Identity-first projection already aggregates the knowledge map, but
    the SQLite retrieval layer (open_first / due_claims / cards / learner graph /
    curation) operates per concept row, so a concept's gaps are scattered. This
    merges each (inventory_concept_id, topic_id) group onto one canonical row
    (lowest id), reassigning every concept reference and resolving unique-constraint
    collisions, so review-query hits for a concept surface together.
    """
    groups = conn.execute(
        """SELECT inventory_concept_id, topic_id, MIN(id) AS canonical
             FROM concepts WHERE COALESCE(inventory_concept_id,'') != ''
            GROUP BY inventory_concept_id, topic_id HAVING COUNT(*) > 1"""
    ).fetchall()
    stats = {"groups": len(groups), "rows_merged": 0, "claim_state_collisions": 0,
             "alias_collisions": 0, "relationships_dropped": 0}
    plain_tables = ("claim_results", "exchanges", "memory_summaries",
                    "shadow_rule_bindings", "shift_debrief_review_candidates")
    for g in groups:
        canonical = int(g["canonical"])
        topic_id = g["topic_id"]
        redundant = [int(r["id"]) for r in conn.execute(
            "SELECT id FROM concepts WHERE inventory_concept_id=? AND topic_id IS ? AND id!=?",
            (g["inventory_concept_id"], topic_id, canonical))]
        for rid in redundant:
            # claim_state: UNIQUE(topic_id, concept_id, claim_slug) -> on collision keep canonical's.
            for cs in conn.execute("SELECT id, claim_slug FROM claim_state WHERE concept_id=?", (rid,)).fetchall():
                clash = conn.execute(
                    "SELECT 1 FROM claim_state WHERE topic_id IS ? AND concept_id=? AND claim_slug=?",
                    (topic_id, canonical, cs["claim_slug"])).fetchone()
                if clash:
                    conn.execute("DELETE FROM claim_state WHERE id=?", (cs["id"],))
                    stats["claim_state_collisions"] += 1
                else:
                    conn.execute("UPDATE claim_state SET concept_id=? WHERE id=?", (canonical, cs["id"]))
            for tbl in plain_tables:
                conn.execute(f"UPDATE {tbl} SET concept_id=? WHERE concept_id=?", (canonical, rid))
            # concept_aliases: UNIQUE(concept_id, alias) -> dedup.
            for a in conn.execute("SELECT id, alias FROM concept_aliases WHERE concept_id=?", (rid,)).fetchall():
                clash = conn.execute("SELECT 1 FROM concept_aliases WHERE concept_id=? AND alias=?",
                                     (canonical, a["alias"])).fetchone()
                if clash:
                    conn.execute("DELETE FROM concept_aliases WHERE id=?", (a["id"],))
                    stats["alias_collisions"] += 1
                else:
                    conn.execute("UPDATE concept_aliases SET concept_id=? WHERE id=?", (canonical, a["id"]))
            # concept_relationships: remap, dropping self-edges and duplicate (src,tgt,type).
            rels = conn.execute(
                """SELECT id, source_concept_id, target_concept_id, relation_type
                     FROM concept_relationships WHERE source_concept_id=? OR target_concept_id=?""",
                (rid, rid)).fetchall()
            for rel in rels:
                new_src = canonical if rel["source_concept_id"] == rid else rel["source_concept_id"]
                new_tgt = canonical if rel["target_concept_id"] == rid else rel["target_concept_id"]
                if new_src == new_tgt:
                    # self-edge: drop the relationship and its evidence link rows.
                    conn.execute("DELETE FROM concept_relationship_evidence WHERE relationship_id=?", (rel["id"],))
                    conn.execute("DELETE FROM concept_relationships WHERE id=?", (rel["id"],))
                    stats["relationships_dropped"] += 1
                    continue
                survivor = conn.execute(
                    """SELECT id FROM concept_relationships
                        WHERE source_concept_id=? AND target_concept_id=? AND relation_type=? AND id!=?""",
                    (new_src, new_tgt, rel["relation_type"], rel["id"])).fetchone()
                if survivor:
                    # duplicate edge: preserve its evidence on the survivor, then drop it.
                    conn.execute(
                        """INSERT OR IGNORE INTO concept_relationship_evidence (relationship_id, claim_result_id)
                           SELECT ?, claim_result_id FROM concept_relationship_evidence WHERE relationship_id=?""",
                        (int(survivor["id"]), rel["id"]))
                    conn.execute("DELETE FROM concept_relationship_evidence WHERE relationship_id=?", (rel["id"],))
                    conn.execute("DELETE FROM concept_relationships WHERE id=?", (rel["id"],))
                    stats["relationships_dropped"] += 1
                else:
                    conn.execute(
                        "UPDATE concept_relationships SET source_concept_id=?, target_concept_id=? WHERE id=?",
                        (new_src, new_tgt, rel["id"]))
            conn.execute("DELETE FROM concepts WHERE id=?", (rid,))
            stats["rows_merged"] += 1
    conn.commit()
    return {"ok": True, **stats}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Comprehensive legacy reshape (migration copy)")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--gen-decisions", default="", help="Write an executable decisions JSON from the triage")
    parser.add_argument("--apply-decisions", default="", help="Path to an agent-reviewed decisions JSON")
    parser.add_argument("--clean-claim-text", action="store_true", help="Strip feedback-prefix pollution from claim_text")
    parser.add_argument("--consolidate", action="store_true", help="Collapse fragmented concept rows sharing an inventory binding")
    parser.add_argument("--out", default="", help="Write analysis JSON to this path")
    args = parser.parse_args(argv)

    import study_memory  # noqa: PLC0415
    from concept_inventory import _open_inventory  # noqa: PLC0415

    conn = study_memory._get_db()
    inv = _open_inventory()
    try:
        if args.clean_claim_text:
            print(_json_dumps(clean_claim_text(conn)))
            return 0
        if args.consolidate:
            print(_json_dumps(consolidate_bound_concepts(conn)))
            return 0
        if args.apply_decisions:
            decisions = json.loads(Path(args.apply_decisions).read_text())
            result = apply_decisions(conn, inv, decisions)
            print(_json_dumps(result))
            return 0 if not result["errors"] else 1
        if args.gen_decisions:
            report = analyze(conn, inv)
            decisions, gaps = gen_decisions(report, inv)
            Path(args.gen_decisions).write_text(_json_dumps(decisions))
            by_action: dict[str, int] = {}
            for d in decisions:
                by_action[d["action"]] = by_action.get(d["action"], 0) + 1
            print(_json_dumps({"ok": True, "decisions": len(decisions), "by_action": by_action,
                               "remaining_gaps": len(gaps), "gaps": gaps, "out": args.gen_decisions}))
            return 0
        report = analyze(conn, inv)
        if args.out:
            Path(args.out).write_text(_json_dumps(report))
            print(_json_dumps({"ok": True, "counts": report["counts"], "pattern_tally": report["pattern_tally"], "out": args.out}))
        else:
            print(_json_dumps(report))
        return 0
    finally:
        inv.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
