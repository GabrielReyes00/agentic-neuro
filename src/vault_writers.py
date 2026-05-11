"""Vault interface regenerators driven by study_memory.db + curriculum spec.

Four writers, one shared mapping layer:
  - regenerate_dashboard(conn)        -> Dashboard.md
  - regenerate_readiness(conn)        -> ACGME Readiness.md
  - regenerate_canvases(conn)         -> ACGME Canvases/*.canvas
  - regenerate_concepts_index()       -> Concepts/INDEX.md
  - regenerate_all(conn)              -> all of the above (call at session end)

Pure I/O. No LLM. Reads memory state, projects onto the curriculum, writes
human-readable markdown / canvases. Idempotent: safe to call after every
end-session.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CURRICULUM_PATH = DATA_DIR / "acgme_curriculum.json"
VAULT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
CANVAS_DIR = VAULT / "ACGME Canvases"
CONCEPTS_DIR = VAULT / "Concepts"

STOPWORDS = frozenset(
    "the a an of in for with and or to on by is at as it its from that this "
    "after before per via vs versus during over under into onto".split()
)

# Color codes for Obsidian canvases.
CANVAS_COLOR = {
    "not_studied": "1",   # red
    "surface": "2",       # orange
    "developing": "3",    # yellow
    "mastered": "4",      # green
}


# ---------------------------------------------------------------------------
# Curriculum + memory mapping
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[\(\)\[\]]", " ", text)
    text = re.sub(r"[^\w\s\-/]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokens(text: str) -> set[str]:
    return {w for w in _normalize(text).split() if w not in STOPWORDS and len(w) > 1}


def _load_curriculum() -> dict:
    return json.loads(CURRICULUM_PATH.read_text())


def _classify_topic(curriculum_title: str, memory_state: dict) -> dict:
    """Match a curriculum topic against memory state.

    Returns: {status, exchange_count, correct_pct, last_studied, last_misconception, concepts_seen}
    """
    cur_tokens = _expand_tokens(_tokens(curriculum_title))
    if not cur_tokens:
        return {"status": "not_studied"}

    matched_topics: list[str] = []
    for mem_topic, mem_tokens in memory_state["topic_tokens"].items():
        if not mem_tokens:
            continue
        overlap_tokens = cur_tokens & mem_tokens
        # Coverage-of-memory: what fraction of memory tokens land inside the curriculum title.
        # Short memory topics ("sah management") matched against long curriculum titles need
        # this asymmetric metric -- jaccard alone underweights the match.
        coverage = len(overlap_tokens) / max(len(mem_tokens), 1)
        jaccard = len(overlap_tokens) / len(cur_tokens | mem_tokens)
        if jaccard >= 0.30 or (coverage >= 0.60 and len(overlap_tokens) >= 2):
            matched_topics.append(mem_topic)

    if not matched_topics:
        return {"status": "not_studied"}

    # Aggregate stats across matched topics
    ex_count = 0
    correct_count = 0
    last_ts = ""
    last_misc = ""
    concept_states: list[str] = []
    for mt in matched_topics:
        stats = memory_state["topic_stats"].get(mt, {})
        ex_count += stats.get("ex_count", 0)
        correct_count += stats.get("correct_count", 0)
        ts = stats.get("last_ts", "")
        if ts > last_ts:
            last_ts = ts
            last_misc = stats.get("last_misconception", last_misc)
        concept_states.extend(stats.get("concept_states", []))

    if ex_count == 0:
        return {"status": "not_studied"}

    correct_pct = (correct_count / ex_count) if ex_count else 0.0
    known = sum(1 for s in concept_states if s == "known")
    unknown = sum(1 for s in concept_states if s == "unknown")

    if known >= 2 and correct_pct >= 0.7 and unknown == 0:
        status = "mastered"
    elif ex_count >= 3 and correct_pct >= 0.5:
        status = "developing"
    else:
        status = "surface"

    return {
        "status": status,
        "exchange_count": ex_count,
        "correct_pct": correct_pct,
        "last_studied": last_ts[:10] if last_ts else "",
        "last_misconception": last_misc,
        "matched_topics": matched_topics,
    }


ALIAS_EXPANSIONS = {
    "evd": "external ventricular drain",
    "icp": "intracranial pressure",
    "cpp": "cerebral perfusion pressure",
    "sah": "subarachnoid hemorrhage",
    "tbi": "traumatic brain injury",
    "ich": "intracerebral hemorrhage",
    "sdh": "subdural hematoma",
    "edh": "epidural hematoma",
    "acha": "anterior choroidal artery",
    "mca": "middle cerebral artery",
    "pca": "posterior cerebral artery",
    "aca": "anterior cerebral artery",
    "gbm": "glioblastoma",
    "dci": "delayed cerebral ischemia",
    "mfs": "modified fisher",
    "hh": "hunt hess",
    "rsi": "rapid sequence intubation",
    "csw": "cerebral salt wasting",
    "dvt": "deep vein thrombosis",
    "pe": "pulmonary embolism",
    "dcml": "dorsal column medial lemniscus",
    "stt": "spinothalamic tract",
    "cst": "corticospinal tract",
    "asia": "american spinal injury association",
    "noac": "novel oral anticoagulant",
}


def _expand_tokens(toks: set[str]) -> set[str]:
    out = set(toks)
    for t in toks:
        if t in ALIAS_EXPANSIONS:
            out.update(ALIAS_EXPANSIONS[t].split())
    return out


def _build_memory_state(conn: sqlite3.Connection) -> dict:
    """Snapshot the memory layer once for fast classification."""
    topic_stats: dict[str, dict] = {}
    topic_tokens: dict[str, set[str]] = {}

    for row in conn.execute("SELECT DISTINCT topic FROM exchanges"):
        topic = row["topic"]
        # Pull associated concept names too -- they carry discriminating signal
        concept_rows = conn.execute(
            "SELECT DISTINCT concept FROM exchanges WHERE topic = ?", (topic,)
        ).fetchall()
        concept_blob = " ".join(r["concept"] for r in concept_rows)
        topic_tokens[topic] = _expand_tokens(_tokens(topic + " " + concept_blob))
        ex_rows = conn.execute(
            "SELECT correct, ts, misconception FROM exchanges WHERE topic = ? ORDER BY ts DESC",
            (topic,),
        ).fetchall()
        ex_count = len(ex_rows)
        correct_count = sum(1 for r in ex_rows if r["correct"] >= 1)
        last_ts = ex_rows[0]["ts"] if ex_rows else ""
        last_misc = next((r["misconception"] for r in ex_rows if r["misconception"]), "")
        concept_state_rows = conn.execute(
            "SELECT status FROM concepts WHERE topic = ?", (topic,)
        ).fetchall()
        topic_stats[topic] = {
            "ex_count": ex_count,
            "correct_count": correct_count,
            "last_ts": last_ts,
            "last_misconception": last_misc,
            "concept_states": [r["status"] for r in concept_state_rows],
        }
    # also include topics that have concepts but no exchanges yet
    for row in conn.execute("SELECT DISTINCT topic FROM concepts"):
        topic = row["topic"]
        if topic not in topic_tokens:
            cn_rows = conn.execute(
                "SELECT DISTINCT concept FROM concepts WHERE topic = ?", (topic,)
            ).fetchall()
            blob = " ".join(r["concept"] for r in cn_rows)
            topic_tokens[topic] = _expand_tokens(_tokens(topic + " " + blob))
            topic_stats[topic] = {
                "ex_count": 0,
                "correct_count": 0,
                "last_ts": "",
                "last_misconception": "",
                "concept_states": [],
            }
    return {"topic_stats": topic_stats, "topic_tokens": topic_tokens}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def regenerate_dashboard(conn: sqlite3.Connection) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    curriculum = _load_curriculum()
    mem = _build_memory_state(conn)

    # Overall counts
    total_sessions = conn.execute("SELECT COUNT(*) as c FROM sessions WHERE ended IS NOT NULL").fetchone()["c"]
    total_exchanges = conn.execute("SELECT COUNT(*) as c FROM exchanges").fetchone()["c"]
    total_concepts = conn.execute("SELECT COUNT(*) as c FROM concepts").fetchone()["c"]
    open_errors = conn.execute("SELECT COUNT(*) as c FROM errors WHERE retested = 0").fetchone()["c"]

    # Coverage across curriculum
    touched_count = 0
    pgy1_touched = 0
    pgy1_total = 0
    by_milestone_progress: list[tuple[str, str, int, int]] = []  # (ms, name, touched, total)
    for ms, m in curriculum["milestones"].items():
        ms_touched = 0
        for t in m["topics"]:
            cls = _classify_topic(t["title"], mem)
            if t["pgy_target"] == 1:
                pgy1_total += 1
                if cls["status"] != "not_studied":
                    pgy1_touched += 1
            if cls["status"] != "not_studied":
                ms_touched += 1
                touched_count += 1
        by_milestone_progress.append((ms, m["name"], ms_touched, len(m["topics"])))
    total_topics = curriculum["total_topics"]

    # Last session
    last_session = conn.execute(
        "SELECT * FROM sessions WHERE ended IS NOT NULL ORDER BY started DESC LIMIT 1"
    ).fetchone()

    # Recent activity (last 14 days)
    cutoff = (datetime.now(timezone.utc).date()).isoformat()
    recent_exchanges = conn.execute(
        "SELECT topic, COUNT(*) as c, SUM(CASE WHEN correct >= 1 THEN 1 ELSE 0 END) as right_c "
        "FROM exchanges WHERE ts >= date('now','-14 days') GROUP BY topic ORDER BY c DESC LIMIT 8"
    ).fetchall()

    # Open errors with detail
    open_err_rows = conn.execute(
        "SELECT topic, concept, misconception, ts FROM errors WHERE retested = 0 ORDER BY ts DESC LIMIT 12"
    ).fetchall()

    # Stale knowledge (known concepts not tested in >21 days)
    stale = conn.execute(
        "SELECT topic, concept, last_tested FROM concepts "
        "WHERE status = 'known' AND last_tested IS NOT NULL "
        "AND date(last_tested) < date('now','-21 days') "
        "ORDER BY last_tested ASC LIMIT 10"
    ).fetchall()

    # Top weak concepts (most missed, still unknown)
    weak = conn.execute(
        "SELECT topic, concept, times_wrong, last_misconception FROM concepts "
        "WHERE status = 'unknown' ORDER BY times_wrong DESC LIMIT 8"
    ).fetchall()

    # Recent sessions
    recent_sessions = conn.execute(
        "SELECT session_id, started, skill, topics_json, stats_json, summary, next_strategy "
        "FROM sessions WHERE ended IS NOT NULL ORDER BY started DESC LIMIT 5"
    ).fetchall()

    # Vault inventory
    inv_counts = {
        "Reports": _count_md(VAULT / "Reports"),
        "Study Material": _count_md(VAULT / "Study Material"),
        "Consults": _count_md(VAULT / "Consults"),
        "Operative Guides": _count_md(VAULT / "Operative Guides"),
        "Presentations": _count_md(VAULT / "Presentations"),
        "Concepts": _count_md(VAULT / "Concepts"),
    }

    # ----- compose markdown -----
    out: list[str] = []
    out.append(f"*Auto-regenerated {today}. Source: study_memory.db.*")
    out.append("")
    out.append(f"> **Curriculum coverage**: {touched_count}/{total_topics} topics touched "
               f"({100*touched_count/total_topics:.1f}%) | **PGY-1**: {pgy1_touched}/{pgy1_total} "
               f"({100*pgy1_touched/pgy1_total:.1f}%) | **Sessions logged**: {total_sessions} | "
               f"**Exchanges**: {total_exchanges} | **Open errors**: {open_errors}")
    out.append("")

    if last_session:
        date = last_session["started"][:10]
        skill = last_session["skill"] or "session"
        out.append(f"## Last Session ({date}, {skill})")
        out.append("")
        if last_session["summary"]:
            out.append(f"**Summary**: {last_session['summary']}")
            out.append("")
        if last_session["next_strategy"]:
            out.append(f"**Next strategy**: {last_session['next_strategy']}")
            out.append("")

    # Coverage by milestone
    out.append("## Curriculum Progress")
    out.append("")
    out.append("| Domain | Milestone | Touched | Coverage | Progress |")
    out.append("|--------|-----------|---------|----------|----------|")
    for ms, name, touched, total in sorted(by_milestone_progress, key=lambda x: -x[2] / max(x[3], 1)):
        pct = 100 * touched / total if total else 0
        bar = "#" * int(pct / 10) + "." * (10 - int(pct / 10))
        ms_label = "-" if ms == "ANATOMY" else ms
        out.append(f"| {name} | {ms_label} | {touched}/{total} | {pct:.1f}% | {bar} |")
    out.append("")

    # Open errors to retest
    if open_err_rows:
        out.append(f"## Open Errors To Retest ({len(open_err_rows)})")
        out.append("")
        for e in open_err_rows:
            misc = (e["misconception"] or "").strip()
            if not misc:
                continue
            out.append(f"- **{e['topic']}** — {e['concept']}: \"{misc}\" *(last seen {e['ts'][:10]})*")
        out.append("")

    # Weak concepts
    if weak:
        out.append("## Weakest Concepts")
        out.append("")
        for w in weak:
            line = f"- **{w['topic']}** — {w['concept']} (missed {w['times_wrong']}x)"
            if w["last_misconception"]:
                line += f": \"{w['last_misconception']}\""
            out.append(line)
        out.append("")

    # Stale knowledge
    if stale:
        out.append("## Stale Knowledge (>21d Since Confirmation)")
        out.append("")
        for s in stale:
            out.append(f"- **{s['topic']}** — {s['concept']} *(last {s['last_tested'][:10]})*")
        out.append("")

    # Recent activity
    if recent_exchanges:
        out.append("## Recent Activity (Last 14 Days)")
        out.append("")
        out.append("| Topic | Exchanges | Accuracy |")
        out.append("|-------|-----------|----------|")
        for r in recent_exchanges:
            acc = 100 * r["right_c"] / r["c"] if r["c"] else 0
            out.append(f"| {r['topic']} | {r['c']} | {acc:.0f}% |")
        out.append("")

    # Recent sessions
    if recent_sessions:
        out.append("## Recent Sessions")
        out.append("")
        out.append("| Date | Skill | Topics | Stats |")
        out.append("|------|-------|--------|-------|")
        for s in recent_sessions:
            topics_list = json.loads(s["topics_json"] or "[]")
            stats = json.loads(s["stats_json"] or "{}")
            stat_str = (f"{stats.get('correct',0)}/{stats.get('total',0)}"
                        if stats.get("total") else "-")
            out.append(f"| {s['started'][:10]} | {s['skill'] or 'session'} | "
                       f"{', '.join(topics_list[:3])} | {stat_str} |")
        out.append("")

    # Vault inventory
    out.append("## Vault Inventory")
    out.append("")
    out.append(f"Reports: {inv_counts['Reports']} | Study Material: {inv_counts['Study Material']} | "
               f"Consults: {inv_counts['Consults']} | Operative Guides: {inv_counts['Operative Guides']} | "
               f"Presentations: {inv_counts['Presentations']} | Concepts: {inv_counts['Concepts']}")
    out.append("")
    out.append("---")
    out.append(f"updated: {today}")
    out.append("tags: [type/reference, source/agent]")
    out.append("---")

    (VAULT / "Dashboard.md").write_text("\n".join(out) + "\n")


def _count_md(p: Path) -> int:
    if not p.is_dir():
        return 0
    return sum(1 for f in p.iterdir() if f.suffix == ".md" and f.name != "INDEX.md")


# ---------------------------------------------------------------------------
# ACGME Readiness
# ---------------------------------------------------------------------------

def regenerate_readiness(conn: sqlite3.Connection) -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    curriculum = _load_curriculum()
    mem = _build_memory_state(conn)

    pgy1_total = sum(
        1 for m in curriculum["milestones"].values() for t in m["topics"] if t["pgy_target"] == 1
    )
    pgy1_touched = 0
    pgy1_mastered = 0
    for m in curriculum["milestones"].values():
        for t in m["topics"]:
            if t["pgy_target"] != 1:
                continue
            cls = _classify_topic(t["title"], mem)
            if cls["status"] != "not_studied":
                pgy1_touched += 1
            if cls["status"] == "mastered":
                pgy1_mastered += 1

    out: list[str] = []
    out.append(f"*Auto-regenerated {today}. Source: study_memory.db + data/acgme_curriculum.json.*")
    out.append("")
    out.append(f"> **{pgy1_total} PGY-1 topics in scope** | **{pgy1_mastered} mastered** | "
               f"**{pgy1_touched} touched** | **{pgy1_total - pgy1_touched} never studied**")
    out.append("")
    out.append("Status legend: **mastered** (multi-confirmed, no open errors) | **developing** "
               "(3+ exchanges, >50% accuracy) | **surface** (touched, partial) | **not studied**.")
    out.append("")

    out.append("## PGY-1 Coverage by Milestone")
    out.append("")

    # PGY-1 topics, by milestone, full list with progress
    for ms in sorted(curriculum["milestones"].keys()):
        m = curriculum["milestones"][ms]
        pgy1_topics = [t for t in m["topics"] if t["pgy_target"] == 1]
        if not pgy1_topics:
            continue
        touched = mastered = developing = surface = 0
        rows: list[str] = []
        for t in sorted(pgy1_topics, key=lambda x: x["title"]):
            cls = _classify_topic(t["title"], mem)
            status = cls["status"]
            if status == "mastered": mastered += 1; touched += 1
            elif status == "developing": developing += 1; touched += 1
            elif status == "surface": surface += 1; touched += 1
            ex = cls.get("exchange_count", "-")
            acc = f"{100*cls['correct_pct']:.0f}%" if cls.get("correct_pct") is not None and status != "not_studied" else "-"
            last = cls.get("last_studied", "") or "-"
            rows.append(f"| [[{t['title']}]] | {status} | {ex} | {acc} | {last} |")
        ms_label = "-" if ms == "ANATOMY" else ms
        out.append(f"### {m['name']} ({ms_label})")
        out.append(f"**{len(pgy1_topics)} topics** | {mastered} mastered | {developing} developing | "
                   f"{surface} surface | {len(pgy1_topics) - touched} not studied")
        out.append("")
        out.append("| Topic | Status | Exchanges | Accuracy | Last Studied |")
        out.append("|-------|--------|-----------|----------|--------------|")
        out.extend(rows)
        out.append("")

    # Full curriculum (PGY 2+)
    out.append("## Full Curriculum (PGY 2+ Topics)")
    out.append("")
    out.append("These are tracked but not PGY-1-priority. They appear when studied or referenced.")
    out.append("")
    for ms in sorted(curriculum["milestones"].keys()):
        m = curriculum["milestones"][ms]
        higher = [t for t in m["topics"] if t["pgy_target"] > 1]
        if not higher:
            continue
        ms_label = "-" if ms == "ANATOMY" else ms
        out.append(f"### {m['name']} ({ms_label}) -- {len(higher)} higher-PGY topics")
        for t in sorted(higher, key=lambda x: (x["pgy_target"], x["title"])):
            cls = _classify_topic(t["title"], mem)
            status_tag = "" if cls["status"] == "not_studied" else f" *[{cls['status']}]*"
            out.append(f"- [[{t['title']}]] (PGY {t['pgy_target']}){status_tag}")
        out.append("")

    out.append("---")
    out.append(f"updated: {today}")
    out.append(f"total_pgy1: {pgy1_total}")
    out.append(f"pgy1_touched: {pgy1_touched}")
    out.append(f"pgy1_mastered: {pgy1_mastered}")
    out.append("tags: [type/reference, source/agent]")
    out.append("---")

    (VAULT / "ACGME Readiness.md").write_text("\n".join(out) + "\n")


# ---------------------------------------------------------------------------
# ACGME Canvases
# ---------------------------------------------------------------------------

def regenerate_canvases(conn: sqlite3.Connection) -> None:
    curriculum = _load_curriculum()
    mem = _build_memory_state(conn)
    CANVAS_DIR.mkdir(exist_ok=True)
    index_rows: list[str] = []

    for ms, m in curriculum["milestones"].items():
        ms_label = "-" if ms == "ANATOMY" else ms
        nodes = []
        # Header card
        touched = sum(1 for t in m["topics"]
                      if _classify_topic(t["title"], mem)["status"] != "not_studied")
        nodes.append({
            "id": f"header_{ms}",
            "type": "text",
            "x": 0, "y": -340, "width": 1100, "height": 200,
            "text": (f"# {ms_label} -- {m['name']}\n\n"
                     f"**Coverage**: {touched}/{len(m['topics'])} topics touched "
                     f"({100*touched/len(m['topics']):.1f}%)\n\n"
                     f"Card color = mastery: red (not studied), orange (surface), "
                     f"yellow (developing), green (mastered).\n\n"
                     f"_Regenerated {datetime.now(timezone.utc).date().isoformat()}_"),
            "color": "6",
        })

        # Group cards by PGY target (PGY-1 top, PGY-2+, PGY-3+)
        bands: dict[int, list[dict]] = {}
        for t in m["topics"]:
            bands.setdefault(t["pgy_target"], []).append(t)

        y_base = 0
        for pgy in sorted(bands.keys()):
            row_topics = sorted(bands[pgy], key=lambda x: x["title"])
            # Band header
            nodes.append({
                "id": f"band_{ms}_pgy{pgy}",
                "type": "text",
                "x": -260, "y": y_base + 30, "width": 220, "height": 90,
                "text": f"## PGY-{pgy}\n\n{len(row_topics)} topics",
                "color": "6",
            })
            x = 80
            for t in row_topics:
                cls = _classify_topic(t["title"], mem)
                color = CANVAS_COLOR.get(cls["status"], "1")
                slug = re.sub(r"[^a-z0-9]+", "_", t["title"].lower()).strip("_")
                node = {
                    "id": f"n_{ms}_{slug}",
                    "type": "text",
                    "x": x, "y": y_base, "width": 320, "height": 150,
                    "text": (f"**[[{t['title']}]]**\n\n"
                             f"Status: {cls['status']}"
                             + (f"\nExchanges: {cls.get('exchange_count', '-')}"
                                f" | Accuracy: {100*cls.get('correct_pct',0):.0f}%"
                                if cls['status'] != 'not_studied' else "")
                             + (f"\nLast: {cls.get('last_studied','')}"
                                if cls.get("last_studied") else "")),
                    "color": color,
                }
                nodes.append(node)
                x += 360
                if x > 4000:
                    x = 80
                    y_base += 180
            y_base += 220

        canvas = {"nodes": nodes, "edges": []}
        out_path = CANVAS_DIR / f"ACGME {ms_label}.canvas"
        out_path.write_text(json.dumps(canvas, indent=2))
        index_rows.append(f"- [[ACGME {ms_label}.canvas|{ms_label} -- {m['name']}]] -- "
                          f"{touched}/{len(m['topics'])} touched")

    # Remove old canvas files no longer in curriculum
    valid = {f"ACGME {('-' if ms == 'ANATOMY' else ms)}.canvas"
             for ms in curriculum["milestones"]}
    for f in CANVAS_DIR.glob("*.canvas"):
        if f.name not in valid:
            f.unlink()

    today = datetime.now(timezone.utc).date().isoformat()
    idx = ["*Auto-regenerated " + today + ".*", "", "## ACGME Milestone Canvases", ""]
    idx.extend(sorted(index_rows))
    idx.append("")
    idx.append("---")
    idx.append(f"updated: {today}")
    idx.append("tags: [type/reference, source/agent]")
    idx.append("---")
    (CANVAS_DIR / "INDEX.md").write_text("\n".join(idx) + "\n")


# ---------------------------------------------------------------------------
# Concepts INDEX
# ---------------------------------------------------------------------------

def regenerate_concepts_index() -> None:
    if not CONCEPTS_DIR.is_dir():
        return
    by_domain: dict[str, list[str]] = {}
    for p in sorted(CONCEPTS_DIR.glob("*.md")):
        if p.name == "INDEX.md":
            continue
        text = p.read_text()
        # Extract domain tag from bottom YAML
        domain = "uncategorized"
        m = re.findall(r"domain/([a-z\-]+)", text)
        if m:
            domain = m[0].replace("-", " ").title()
        by_domain.setdefault(domain, []).append(p.stem)

    today = datetime.now(timezone.utc).date().isoformat()
    total = sum(len(v) for v in by_domain.values())
    out = [f"*Auto-regenerated {today}. {total} concept notes.*", ""]
    for domain in sorted(by_domain):
        out.append(f"## {domain} ({len(by_domain[domain])})")
        out.append("")
        for title in sorted(by_domain[domain]):
            out.append(f"- [[{title}]]")
        out.append("")
    out.append("---")
    out.append(f"updated: {today}")
    out.append(f"total: {total}")
    out.append("tags: [type/reference, source/agent]")
    out.append("---")
    (CONCEPTS_DIR / "INDEX.md").write_text("\n".join(out) + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def regenerate_all(conn: sqlite3.Connection) -> list[str]:
    """Regenerate every vault interface. Returns list of warnings (empty on success)."""
    warnings: list[str] = []
    for name, fn, needs_conn in [
        ("Dashboard.md", regenerate_dashboard, True),
        ("ACGME Readiness.md", regenerate_readiness, True),
        ("ACGME Canvases/", regenerate_canvases, True),
        ("Concepts/INDEX.md", regenerate_concepts_index, False),
    ]:
        try:
            if needs_conn:
                fn(conn)
            else:
                fn()
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{name}: {e}")
    return warnings


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(BASE_DIR / "src"))
    from study_memory import _get_db
    conn = _get_db()
    warnings = regenerate_all(conn)
    if warnings:
        for w in warnings:
            print(f"WARN: {w}", file=sys.stderr)
        sys.exit(1)
    print("Regenerated: Dashboard.md, ACGME Readiness.md, ACGME Canvases/, Concepts/INDEX.md")
