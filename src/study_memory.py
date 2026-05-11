#!/usr/bin/env python3
"""Lean persistent memory layer for study sessions.

Single file, 6 SQLite tables, 5 CLI commands.
Replaces the old 13K-line knowledge_graph + memory_orchestrator stack.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "study_memory.db"

STOPWORDS = frozenset(
    "the a an of in for with and or to on by is at as it its from that this"
    .split()
)

SEED_ALIASES: dict[str, str] = {
    "evd": "external ventricular drain",
    "icp": "intracranial pressure",
    "cpp": "cerebral perfusion pressure",
    "csf": "cerebrospinal fluid",
    "sah": "subarachnoid hemorrhage",
    "asah": "aneurysmal subarachnoid hemorrhage",
    "tbi": "traumatic brain injury",
    "avm": "arteriovenous malformation",
    "dbs": "deep brain stimulation",
    "vp": "ventriculoperitoneal",
    "srs": "stereotactic radiosurgery",
    "mca": "middle cerebral artery",
    "aca": "anterior cerebral artery",
    "pca": "posterior cerebral artery",
    "pica": "posterior inferior cerebellar artery",
    "gbm": "glioblastoma",
    "idh": "isocitrate dehydrogenase",
    "acdf": "anterior cervical discectomy and fusion",
    "sci": "spinal cord injury",
    "sdh": "subdural hematoma",
    "edh": "epidural hematoma",
    "ich": "intracerebral hemorrhage",
    "mfs": "modified fisher scale",
    "hh": "hunt hess",
    "gcs": "glasgow coma scale",
    "wfns": "world federation of neurosurgical societies",
    "crw": "cosman roberts wells",
    "acgme": "accreditation council for graduate medical education",
    "dci": "delayed cerebral ischemia",
    "cns": "central nervous system",
    "pns": "peripheral nervous system",
    "ct": "computed tomography",
    "mri": "magnetic resonance imaging",
    "cta": "ct angiography",
    "dsa": "digital subtraction angiography",
    "or": "operating room",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS exchanges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    ts          TEXT NOT NULL,
    turn        INTEGER NOT NULL,
    topic       TEXT NOT NULL,
    concept     TEXT NOT NULL,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    correct     INTEGER NOT NULL,
    correction  TEXT DEFAULT '',
    error_type  TEXT DEFAULT '',
    misconception TEXT DEFAULT '',
    doc_path    TEXT DEFAULT '',
    skill       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ex_session ON exchanges(session_id);
CREATE INDEX IF NOT EXISTS idx_ex_topic ON exchanges(topic);
CREATE INDEX IF NOT EXISTS idx_ex_concept ON exchanges(concept);

CREATE TABLE IF NOT EXISTS concepts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    topic           TEXT NOT NULL,
    concept         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'unknown',
    times_right     INTEGER DEFAULT 0,
    times_wrong     INTEGER DEFAULT 0,
    last_error_type TEXT DEFAULT '',
    last_misconception TEXT DEFAULT '',
    last_tested     TEXT,
    UNIQUE(topic, concept)
);
CREATE INDEX IF NOT EXISTS idx_con_topic ON concepts(topic);
CREATE INDEX IF NOT EXISTS idx_con_status ON concepts(status);

CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL UNIQUE,
    started         TEXT NOT NULL,
    ended           TEXT,
    skill           TEXT DEFAULT '',
    topics_json     TEXT DEFAULT '[]',
    summary         TEXT DEFAULT '',
    next_strategy   TEXT DEFAULT '',
    confusions_json TEXT DEFAULT '[]',
    stats_json      TEXT DEFAULT '{}',
    doc_path        TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS doc_progress (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_path        TEXT NOT NULL UNIQUE,
    session_count   INTEGER DEFAULT 0,
    last_studied    TEXT,
    sections_done   TEXT DEFAULT '[]',
    concepts_known  TEXT DEFAULT '[]',
    concepts_gap    TEXT DEFAULT '[]',
    notes           TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    topic       TEXT NOT NULL,
    concept     TEXT NOT NULL,
    error_type  TEXT DEFAULT '',
    misconception TEXT NOT NULL,
    correction  TEXT DEFAULT '',
    retested    INTEGER DEFAULT 0,
    retest_ts   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_err_topic ON errors(topic);
CREATE INDEX IF NOT EXISTS idx_err_retested ON errors(retested);

CREATE TABLE IF NOT EXISTS aliases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alias       TEXT NOT NULL UNIQUE,
    canonical   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alias_canonical ON aliases(canonical);
"""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_db(path: Path | None = None) -> sqlite3.Connection:
    p = path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    _seed_aliases(conn)
    return conn


def _seed_aliases(conn: sqlite3.Connection) -> None:
    for alias, canonical in SEED_ALIASES.items():
        conn.execute(
            "INSERT OR IGNORE INTO aliases (alias, canonical) VALUES (?, ?)",
            (alias, canonical),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Text normalization and matching
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s\-/]", "", text)
    return text


def _tokenize(text: str) -> set[str]:
    return {w for w in _normalize(text).split() if w not in STOPWORDS}


def _expand_query(conn: sqlite3.Connection, query: str) -> set[str]:
    tokens = _tokenize(query)
    expanded = set(tokens)
    for token in list(tokens):
        row = conn.execute(
            "SELECT canonical FROM aliases WHERE alias = ?", (token,)
        ).fetchone()
        if row:
            expanded.update(_tokenize(row["canonical"]))
        for r in conn.execute(
            "SELECT alias FROM aliases WHERE canonical LIKE ?",
            (f"%{token}%",),
        ):
            expanded.add(r["alias"])
    return expanded


def _match_score(query_tokens: set[str], target_tokens: set[str]) -> float:
    if not target_tokens or not query_tokens:
        return 0.0
    intersection = query_tokens & target_tokens
    union = query_tokens | target_tokens
    return len(intersection) / len(union) if union else 0.0


def _topic_matches(conn: sqlite3.Connection, query: str) -> list[str]:
    expanded_q = _expand_query(conn, query)
    norm_q = _normalize(query)

    all_topics: set[str] = set()
    for row in conn.execute("SELECT DISTINCT topic FROM exchanges"):
        all_topics.add(row["topic"])
    for row in conn.execute("SELECT DISTINCT topic FROM concepts"):
        all_topics.add(row["topic"])

    scored: list[tuple[str, float]] = []
    for topic in all_topics:
        norm_t = _normalize(topic)
        if norm_q in norm_t or norm_t in norm_q:
            scored.append((topic, 1.0))
            continue
        expanded_t = _expand_query(conn, topic)
        score = _match_score(expanded_q, expanded_t)
        if score >= 0.25:
            scored.append((topic, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in scored]


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------

def recall(conn: sqlite3.Connection, topic: str | None, doc: str | None) -> str:
    lines: list[str] = []
    matched_topics: list[str] = []

    if topic:
        matched_topics = _topic_matches(conn, topic)
        label = topic
    elif doc:
        label = doc
        for row in conn.execute("SELECT DISTINCT topic FROM exchanges WHERE doc_path = ?", (doc,)):
            matched_topics.append(row["topic"])
    else:
        return "ERROR: provide --topic or --doc"

    if not matched_topics and not doc:
        return f"No prior data found for '{label}'."

    lines.append(f"=== RECALL: {label} ===")
    lines.append("")

    # --- Last session ---
    session = None
    if matched_topics:
        placeholders = ",".join("?" for _ in matched_topics)
        for t in matched_topics:
            rows = conn.execute(
                "SELECT DISTINCT session_id FROM exchanges WHERE topic = ? ORDER BY ts DESC LIMIT 3",
                (t,),
            ).fetchall()
            for r in rows:
                s = conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ? AND summary != ''",
                    (r["session_id"],),
                ).fetchone()
                if s and (session is None or s["started"] > session["started"]):
                    session = s
    if doc and not session:
        session = conn.execute(
            "SELECT * FROM sessions WHERE doc_path = ? AND summary != '' ORDER BY started DESC LIMIT 1",
            (doc,),
        ).fetchone()
    if session:
        date = session["started"][:10]
        skill = session["skill"] or "session"
        lines.append(f"LAST SESSION ({date}, {skill}):")
        if session["summary"]:
            lines.append(f"  Summary: {session['summary']}")
        if session["next_strategy"]:
            lines.append(f"  Next strategy: {session['next_strategy']}")
        lines.append("")

    # --- Concepts ---
    known: list[str] = []
    gaps: list[str] = []
    if matched_topics:
        for t in matched_topics:
            for row in conn.execute(
                "SELECT * FROM concepts WHERE topic = ? ORDER BY times_right DESC", (t,)
            ):
                entry = f"{row['concept']} (confirmed {row['times_right']}x)"
                if row["status"] == "known":
                    known.append(entry)
                elif row["status"] == "partial":
                    detail = f"{row['concept']} (partial, right {row['times_right']}x wrong {row['times_wrong']}x)"
                    gaps.append(detail)
                else:
                    detail = f"{row['concept']} (missed {row['times_wrong']}x"
                    if row["last_error_type"]:
                        detail += f", {row['last_error_type']}"
                    if row["last_misconception"]:
                        detail += f', misconception: "{row["last_misconception"]}"'
                    detail += ")"
                    gaps.append(detail)

    if known:
        lines.append(f"KNOWN CONCEPTS ({len(known)}):")
        for k in known[:10]:
            lines.append(f"  - {k}")
        if len(known) > 10:
            lines.append(f"  ... and {len(known) - 10} more")
        lines.append("")

    if gaps:
        lines.append(f"GAPS ({len(gaps)}):")
        for g in gaps[:10]:
            lines.append(f"  - {g}")
        if len(gaps) > 10:
            lines.append(f"  ... and {len(gaps) - 10} more")
        lines.append("")

    # --- Open errors ---
    open_errors: list[sqlite3.Row] = []
    if matched_topics:
        for t in matched_topics:
            for row in conn.execute(
                "SELECT * FROM errors WHERE topic = ? AND retested = 0 ORDER BY ts DESC",
                (t,),
            ):
                open_errors.append(row)
    if open_errors:
        lines.append(f"OPEN ERRORS TO RETEST ({len(open_errors)}):")
        for e in open_errors[:8]:
            lines.append(f'  - "{e["misconception"]}" ({e["ts"][:10]})')
        lines.append("")

    # --- Recent exchanges ---
    recent: list[sqlite3.Row] = []
    if matched_topics:
        for t in matched_topics:
            for row in conn.execute(
                "SELECT * FROM exchanges WHERE topic = ? ORDER BY ts DESC LIMIT 5",
                (t,),
            ):
                recent.append(row)
    if doc:
        for row in conn.execute(
            "SELECT * FROM exchanges WHERE doc_path = ? ORDER BY ts DESC LIMIT 5",
            (doc,),
        ):
            if not any(r["id"] == row["id"] for r in recent):
                recent.append(row)
    recent.sort(key=lambda r: r["ts"], reverse=True)
    if recent:
        lines.append(f"RECENT EXCHANGES (last {min(len(recent), 5)}):")
        correct_map = {0: "wrong", 1: "partial", 2: "correct"}
        for r in recent[:5]:
            q_short = r["question"][:80] + ("..." if len(r["question"]) > 80 else "")
            lines.append(f"  Q: {q_short} -> {correct_map.get(r['correct'], '?')} (turn {r['turn']})")
        lines.append("")

    # --- Doc progress ---
    if doc:
        dp = conn.execute(
            "SELECT * FROM doc_progress WHERE doc_path = ?", (doc,)
        ).fetchone()
        if dp:
            lines.append(f"DOC PROGRESS ({doc}):")
            lines.append(f"  Sessions: {dp['session_count']} | Last: {dp['last_studied'] or 'never'}")
            known_list = json.loads(dp["concepts_known"] or "[]")
            gap_list = json.loads(dp["concepts_gap"] or "[]")
            lines.append(f"  Concepts known: {len(known_list)} | Gaps: {len(gap_list)}")
            lines.append("")

    if len(lines) <= 2:
        return f"No prior data found for '{label}'."

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# log-answer
# ---------------------------------------------------------------------------

VALID_ERROR_TYPES = frozenset({
    "conceptual_confusion", "numerical_recall", "cross_contamination",
    "application_failure", "reasoning_gap", "omission",
})


def _validate_entry(topic: str, concept: str, correct: int,
                     error_type: str, misconception: str) -> list[str]:
    """Reject obviously malformed entries. Returns list of error messages."""
    problems: list[str] = []
    words_t = topic.split()
    if len(words_t) > 8:
        problems.append(f"TOPIC too long ({len(words_t)} words, max 8): '{topic}'")
    if len(words_t) < 2:
        problems.append(f"TOPIC too short ({len(words_t)} word, min 2): '{topic}'")
    words_c = concept.split()
    if len(words_c) < 2:
        problems.append(f"CONCEPT too vague (single word): '{concept}'")
    if re.match(r'^q\d+$', concept):
        problems.append(f"CONCEPT is a question ID, not a concept name: '{concept}'")
    if correct == 0 and not misconception.strip():
        problems.append("MISCONCEPTION required when correct=0 (state the specific wrong belief)")
    if misconception.strip().lower() in ("incorrect", "unsure", "wrong", "user was unsure"):
        problems.append(f"MISCONCEPTION too generic: '{misconception}'. State the specific wrong belief.")
    if error_type and error_type not in VALID_ERROR_TYPES:
        problems.append(f"ERROR_TYPE invalid: '{error_type}'. Must be one of: {', '.join(sorted(VALID_ERROR_TYPES))}")
    return problems


def log_answer(
    conn: sqlite3.Connection,
    session_id: str,
    topic: str,
    concept: str,
    question: str,
    answer: str,
    correct: int,
    correction: str = "",
    error_type: str = "",
    misconception: str = "",
    doc_path: str = "",
    skill: str = "",
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    topic = _normalize(topic)
    concept = _normalize(concept)

    problems = _validate_entry(topic, concept, correct, error_type, misconception)
    if problems:
        return "VALIDATION ERROR -- fix and retry:\n  " + "\n  ".join(problems)

    # Auto-create session if not exists
    existing = conn.execute(
        "SELECT id, topics_json FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO sessions (session_id, started, skill, topics_json, doc_path) VALUES (?, ?, ?, ?, ?)",
            (session_id, now, skill, json.dumps([topic]), doc_path),
        )
    else:
        topics_list = json.loads(existing["topics_json"] or "[]")
        if topic not in topics_list:
            topics_list.append(topic)
            conn.execute(
                "UPDATE sessions SET topics_json = ? WHERE session_id = ?",
                (json.dumps(topics_list), session_id),
            )

    # Count existing exchanges in this session for turn auto-assignment
    turn_count = conn.execute(
        "SELECT COUNT(*) as c FROM exchanges WHERE session_id = ?", (session_id,)
    ).fetchone()["c"]
    turn = turn_count + 1

    # Insert exchange
    conn.execute(
        """INSERT INTO exchanges
           (session_id, ts, turn, topic, concept, question, answer, correct,
            correction, error_type, misconception, doc_path, skill)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, now, turn, topic, concept, question, answer, correct,
         correction, error_type, misconception, doc_path, skill),
    )
    exchange_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Upsert concept mastery
    existing_concept = conn.execute(
        "SELECT * FROM concepts WHERE topic = ? AND concept = ?", (topic, concept)
    ).fetchone()
    if existing_concept:
        right = existing_concept["times_right"]
        wrong = existing_concept["times_wrong"]
        if correct >= 1:
            right += 1
        if correct == 0:
            wrong += 1
        status = "known" if right >= 2 and right > wrong else (
            "partial" if right >= 1 else "unknown"
        )
        conn.execute(
            """UPDATE concepts SET status = ?, times_right = ?, times_wrong = ?,
               last_error_type = CASE WHEN ? != '' THEN ? ELSE last_error_type END,
               last_misconception = CASE WHEN ? != '' THEN ? ELSE last_misconception END,
               last_tested = ?
               WHERE topic = ? AND concept = ?""",
            (status, right, wrong, error_type, error_type,
             misconception, misconception, now, topic, concept),
        )
    else:
        right = 1 if correct >= 1 else 0
        wrong = 1 if correct == 0 else 0
        status = "known" if correct == 2 else ("partial" if correct == 1 else "unknown")
        conn.execute(
            """INSERT INTO concepts
               (topic, concept, status, times_right, times_wrong,
                last_error_type, last_misconception, last_tested)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (topic, concept, status, right, wrong, error_type, misconception, now),
        )

    # Track errors
    error_msg = ""
    if correct == 0 and misconception:
        conn.execute(
            """INSERT INTO errors (ts, topic, concept, error_type, misconception, correction)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (now, topic, concept, error_type, misconception, correction),
        )
        error_msg = " [error logged]"
    elif correct == 2:
        # Check if this corrects a prior error
        open_err = conn.execute(
            "SELECT id FROM errors WHERE concept = ? AND retested = 0 ORDER BY ts DESC LIMIT 1",
            (concept,),
        ).fetchone()
        if open_err:
            conn.execute(
                "UPDATE errors SET retested = 1, retest_ts = ? WHERE id = ?",
                (now, open_err["id"]),
            )
            error_msg = f" [error #{open_err['id']} retested]"

    # Update doc_progress
    if doc_path:
        dp = conn.execute(
            "SELECT * FROM doc_progress WHERE doc_path = ?", (doc_path,)
        ).fetchone()
        if dp:
            known_list = json.loads(dp["concepts_known"] or "[]")
            gap_list = json.loads(dp["concepts_gap"] or "[]")
            if correct >= 1 and concept not in known_list:
                known_list.append(concept)
            if correct == 0 and concept not in gap_list:
                gap_list.append(concept)
            if concept in gap_list and correct == 2:
                gap_list.remove(concept)
            conn.execute(
                "UPDATE doc_progress SET concepts_known = ?, concepts_gap = ?, last_studied = ? WHERE doc_path = ?",
                (json.dumps(known_list), json.dumps(gap_list), now, doc_path),
            )
        else:
            known_list = [concept] if correct >= 1 else []
            gap_list = [concept] if correct == 0 else []
            conn.execute(
                "INSERT INTO doc_progress (doc_path, session_count, last_studied, concepts_known, concepts_gap) VALUES (?, 1, ?, ?, ?)",
                (doc_path, now, json.dumps(known_list), json.dumps(gap_list)),
            )

    conn.commit()
    return f"OK exchange_id={exchange_id}{error_msg}"


# ---------------------------------------------------------------------------
# end-session
# ---------------------------------------------------------------------------

def end_session(
    conn: sqlite3.Connection,
    session_id: str,
    summary: str,
    next_strategy: str,
    confusions: str = "[]",
) -> str:
    now = datetime.now(timezone.utc).isoformat()

    # Compute stats
    rows = conn.execute(
        "SELECT correct FROM exchanges WHERE session_id = ?", (session_id,)
    ).fetchall()
    total = len(rows)
    right = sum(1 for r in rows if r["correct"] == 2)
    partial = sum(1 for r in rows if r["correct"] == 1)
    wrong = sum(1 for r in rows if r["correct"] == 0)
    stats = json.dumps({"total": total, "correct": right, "partial": partial, "wrong": wrong})

    # Get topics for output
    session = conn.execute(
        "SELECT topics_json, doc_path FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    topics_str = ""
    if session:
        topics_list = json.loads(session["topics_json"] or "[]")
        topics_str = ", ".join(topics_list)

    # Update or create session
    existing = conn.execute(
        "SELECT id FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE sessions SET ended = ?, summary = ?, next_strategy = ?,
               confusions_json = ?, stats_json = ? WHERE session_id = ?""",
            (now, summary, next_strategy, confusions, stats, session_id),
        )
    else:
        conn.execute(
            """INSERT INTO sessions (session_id, started, ended, summary, next_strategy,
               confusions_json, stats_json) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, now, now, summary, next_strategy, confusions, stats),
        )

    # Update doc_progress session_count
    if session and session["doc_path"]:
        conn.execute(
            "UPDATE doc_progress SET session_count = session_count + 1 WHERE doc_path = ?",
            (session["doc_path"],),
        )

    conn.commit()
    out = [f"Session closed. {total} exchanges: {right} correct, {partial} partial, {wrong} wrong."]
    if topics_str:
        out.append(f"Topics: {topics_str}")
    out.append("Next strategy saved.")

    # Auto-regenerate vault interfaces (Dashboard, ACGME Readiness, Canvases, Concepts INDEX).
    # Silent on success; warn on failure but do not abort the session-end record.
    try:
        from vault_writers import regenerate_all  # type: ignore
        warnings = regenerate_all(conn)
        if warnings:
            for w in warnings:
                print(f"WARN vault-writer: {w}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"WARN vault-writer skipped: {e}", file=sys.stderr)

    return "\n".join(out)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def status(conn: sqlite3.Connection, topic: str | None = None) -> str:
    lines: list[str] = []

    total_sessions = conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()["c"]
    total_exchanges = conn.execute("SELECT COUNT(*) as c FROM exchanges").fetchone()["c"]
    total_concepts = conn.execute("SELECT COUNT(*) as c FROM concepts").fetchone()["c"]
    total_errors = conn.execute("SELECT COUNT(*) as c FROM errors WHERE retested = 0").fetchone()["c"]
    total_aliases = conn.execute("SELECT COUNT(*) as c FROM aliases").fetchone()["c"]

    lines.append("=== STUDY MEMORY STATUS ===")
    lines.append(f"Sessions: {total_sessions} | Exchanges: {total_exchanges} | Concepts: {total_concepts}")
    lines.append(f"Open errors: {total_errors} | Aliases: {total_aliases}")
    lines.append("")

    if topic:
        matched = _topic_matches(conn, topic)
        if matched:
            lines.append(f"Matching topics for '{topic}': {', '.join(matched[:5])}")
        else:
            lines.append(f"No matches for '{topic}'.")
        lines.append("")

    # Top weak concepts
    weak = conn.execute(
        "SELECT topic, concept, times_wrong, last_misconception FROM concepts WHERE status = 'unknown' ORDER BY times_wrong DESC LIMIT 5"
    ).fetchall()
    if weak:
        lines.append("TOP WEAK CONCEPTS:")
        for w in weak:
            line = f"  - {w['topic']}: {w['concept']} (missed {w['times_wrong']}x)"
            if w["last_misconception"]:
                line += f' -- "{w["last_misconception"]}"'
            lines.append(line)
        lines.append("")

    # Recent sessions
    recent = conn.execute(
        "SELECT session_id, started, skill, topics_json FROM sessions ORDER BY started DESC LIMIT 5"
    ).fetchall()
    if recent:
        lines.append("RECENT SESSIONS:")
        for s in recent:
            topics_list = json.loads(s["topics_json"] or "[]")
            topics_short = ", ".join(topics_list[:3])
            lines.append(f"  - {s['started'][:10]} ({s['skill'] or 'session'}): {topics_short}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# prep -- agent-only session-start context
# ---------------------------------------------------------------------------

def prep(conn: sqlite3.Connection) -> str:
    """Dense agent-facing context for opening a session.

    Surfaces unresolved work the agent should weave into questioning
    opportunistically when topics intersect. NEVER echoed to the user.
    """
    lines: list[str] = []
    lines.append("=== SESSION PREP (agent-only context, do not echo) ===")
    lines.append("")

    open_errs = conn.execute(
        "SELECT topic, concept, misconception, ts FROM errors "
        "WHERE retested = 0 AND misconception != '' "
        "ORDER BY ts ASC LIMIT 5"
    ).fetchall()
    if open_errs:
        lines.append(f"OPEN ERRORS ({len(open_errs)} oldest, unretested):")
        for r in open_errs:
            lines.append(f"  - {r['topic']} / {r['concept']}")
            lines.append(f'    "{r["misconception"]}" (since {r["ts"][:10]})')
        lines.append("")

    stale = conn.execute(
        "SELECT topic, concept, last_tested FROM concepts "
        "WHERE status = 'known' AND last_tested IS NOT NULL "
        "AND date(last_tested) < date('now','-21 days') "
        "ORDER BY last_tested ASC LIMIT 5"
    ).fetchall()
    if stale:
        lines.append(f"STALE KNOWN ({len(stale)}, >21d unverified):")
        for r in stale:
            lines.append(f"  - {r['topic']} / {r['concept']} (last {r['last_tested'][:10]})")
        lines.append("")

    confusions = conn.execute(
        "SELECT topic, concept, misconception, ts FROM errors "
        "WHERE error_type = 'cross_contamination' AND misconception != '' "
        "ORDER BY ts DESC LIMIT 8"
    ).fetchall()
    if confusions:
        lines.append(f"RECENT CONFUSION PATTERNS ({len(confusions)} cross_contamination):")
        for r in confusions:
            lines.append(f'  - {r["topic"]} / {r["concept"]}: "{r["misconception"]}" ({r["ts"][:10]})')
        lines.append("")

    last = conn.execute(
        "SELECT started, next_strategy FROM sessions "
        "WHERE ended IS NOT NULL AND next_strategy != '' "
        "ORDER BY started DESC LIMIT 1"
    ).fetchone()
    if last:
        lines.append(f"LAST SESSION NEXT-STRATEGY ({last['started'][:10]}):")
        lines.append(f'  "{last["next_strategy"]}"')
        lines.append("")

    if len(lines) <= 2:
        return "No prep signals -- new memory or no open work."

    lines.append("GUIDANCE: weave these into questioning when topics intersect. Do not echo this block.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# confusions -- cross-contamination pattern query
# ---------------------------------------------------------------------------

def confusions_query(conn: sqlite3.Connection, topic: str | None = None) -> str:
    """List cross_contamination errors, optionally scoped to a topic.

    Agent-facing utility for picking a teaching angle when a new topic opens
    that historically gets confused with another.
    """
    if topic:
        matched = _topic_matches(conn, topic)
        if not matched:
            return f"No confusion patterns for '{topic}'."
        rows: list[sqlite3.Row] = []
        for t in matched:
            for r in conn.execute(
                "SELECT topic, concept, misconception, correction, ts FROM errors "
                "WHERE error_type = 'cross_contamination' AND misconception != '' AND topic = ? "
                "ORDER BY ts DESC",
                (t,),
            ):
                rows.append(r)
        header = f"=== CONFUSION PATTERNS for '{topic}' ({len(rows)}) ==="
    else:
        rows = conn.execute(
            "SELECT topic, concept, misconception, correction, ts FROM errors "
            "WHERE error_type = 'cross_contamination' AND misconception != '' "
            "ORDER BY ts DESC"
        ).fetchall()
        header = f"=== ALL CONFUSION PATTERNS ({len(rows)}) ==="

    if not rows:
        return f"No cross_contamination errors logged{f' for {topic}' if topic else ''}."

    lines = [header, ""]
    for r in rows:
        lines.append(f'  - {r["topic"]} / {r["concept"]} ({r["ts"][:10]})')
        lines.append(f'    misconception: "{r["misconception"]}"')
        if r["correction"]:
            lines.append(f'    correction: "{r["correction"]}"')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# add-alias
# ---------------------------------------------------------------------------

def add_alias(conn: sqlite3.Connection, alias: str, canonical: str) -> str:
    alias = alias.strip().lower()
    canonical = canonical.strip().lower()
    conn.execute(
        "INSERT OR REPLACE INTO aliases (alias, canonical) VALUES (?, ?)",
        (alias, canonical),
    )
    conn.commit()
    return f"OK alias '{alias}' -> '{canonical}'"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="study_memory",
        description="Lean persistent memory for study sessions.",
    )
    sub = parser.add_subparsers(dest="command")

    # recall
    p_recall = sub.add_parser("recall")
    p_recall.add_argument("--topic", default=None)
    p_recall.add_argument("--doc", default=None)

    # log-answer
    p_log = sub.add_parser("log-answer")
    p_log.add_argument("--session", required=True)
    p_log.add_argument("--topic", required=True)
    p_log.add_argument("--concept", required=True)
    p_log.add_argument("--question", required=True)
    p_log.add_argument("--answer", required=True)
    p_log.add_argument("--correct", type=int, required=True, choices=[0, 1, 2])
    p_log.add_argument("--correction", default="")
    p_log.add_argument("--error-type", default="")
    p_log.add_argument("--misconception", default="")
    p_log.add_argument("--doc", default="")
    p_log.add_argument("--skill", default="")

    # end-session
    p_end = sub.add_parser("end-session")
    p_end.add_argument("--session", required=True)
    p_end.add_argument("--summary", required=True)
    p_end.add_argument("--next-strategy", required=True)
    p_end.add_argument("--confusions", default="[]")

    # status
    p_status = sub.add_parser("status")
    p_status.add_argument("--topic", default=None)

    # prep (agent-only session start context)
    sub.add_parser("prep")

    # confusions (cross_contamination pattern query)
    p_conf = sub.add_parser("confusions")
    p_conf.add_argument("--topic", default=None)

    # add-alias
    p_alias = sub.add_parser("add-alias")
    p_alias.add_argument("--alias", required=True)
    p_alias.add_argument("--canonical", required=True)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    conn = _get_db()

    try:
        if args.command == "recall":
            print(recall(conn, args.topic, args.doc))
        elif args.command == "log-answer":
            print(log_answer(
                conn,
                session_id=args.session,
                topic=args.topic,
                concept=args.concept,
                question=args.question,
                answer=args.answer,
                correct=args.correct,
                correction=args.correction,
                error_type=getattr(args, "error_type", ""),
                misconception=args.misconception,
                doc_path=args.doc,
                skill=args.skill,
            ))
        elif args.command == "end-session":
            print(end_session(
                conn,
                session_id=args.session,
                summary=args.summary,
                next_strategy=getattr(args, "next_strategy", ""),
                confusions=args.confusions,
            ))
        elif args.command == "status":
            print(status(conn, args.topic))
        elif args.command == "prep":
            print(prep(conn))
        elif args.command == "confusions":
            print(confusions_query(conn, args.topic))
        elif args.command == "add-alias":
            print(add_alias(conn, args.alias, args.canonical))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
