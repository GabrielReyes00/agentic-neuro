"""case_log_sync.py — Find case log files not yet recorded in knowledge_graph.db.

Writes new file paths to data/Sessions/case_log_sync.txt and prints the count.
Called by preflight.sh; designed to run from the repo root with the venv active.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

CASE_LOG_DIR = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Case Log")
SYNC_FILE = Path("data/Sessions/case_log_sync.txt")
DB_PATH = Path("data/knowledge_graph.db")


def find_new_case_logs() -> list[str]:
    """Return paths of case log .md files not yet recorded in knowledge_graph.db."""
    existing: set[str] = set()
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        try:
            rows = conn.execute(
                "SELECT se.metadata FROM signal_events se WHERE se.source='case_log'"
            ).fetchall()
            for (raw_meta,) in rows:
                if not raw_meta:
                    continue
                try:
                    meta = json.loads(raw_meta)
                except Exception:
                    continue
                source_file = meta.get("source_file")
                if source_file:
                    existing.add(Path(source_file).name)
        finally:
            conn.close()

    case_files = sorted(
        p for p in CASE_LOG_DIR.glob("*.md")
        if p.name != "INDEX.md" and not p.name.startswith("_")
    )
    return [str(p) for p in case_files if p.name not in existing]


def main() -> None:
    new_files = find_new_case_logs()
    SYNC_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYNC_FILE.write_text("\n".join(new_files) + ("\n" if new_files else ""), encoding="utf-8")
    print(len(new_files))


if __name__ == "__main__":
    main()
