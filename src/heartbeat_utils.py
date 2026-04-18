"""heartbeat_utils.py — Python helpers extracted from heartbeat.sh.

Subcommands:
  mark-complete <path>                Replace last 'Status: IN-PROGRESS' with
                                      'Status: COMPLETE' in a session vault file.
  update-review-metadata <path> <date> <session_num> <coverage>
                                      Update doc-anchored review metadata fields.
  update-session-index <index> <slug> <topic> <date> <skill> <status>
                                      Update a slug row in a session-mode INDEX.md table.
  update-docanchor-index <index> <slug> <topic> <date> <session_num> <coverage>
                                      Update a slug_review row in a doc-anchored INDEX.md table.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def mark_session_complete(path_str: str) -> None:
    path = Path(path_str)
    content = path.read_text(encoding="utf-8")
    idx = content.rfind("Status: IN-PROGRESS")
    if idx >= 0:
        content = content[:idx] + "Status: COMPLETE" + content[idx + len("Status: IN-PROGRESS"):]
    path.write_text(content, encoding="utf-8")


def update_session_index(
    index_path: str,
    slug: str,
    topic_name: str,
    date: str,
    skill: str,
    status: str,
) -> None:
    path = Path(index_path)
    new_row = f"| [{topic_name}]({slug}.md) | {date} | {skill} | {status} |"
    content = path.read_text(encoding="utf-8")
    content = re.sub(rf"\|[^\n]*{re.escape(slug)}\.md[^\n]*", new_row, content)
    path.write_text(content, encoding="utf-8")


def update_docanchor_index(
    index_path: str,
    slug: str,
    topic_name: str,
    date: str,
    session_num: str,
    coverage: str,
) -> None:
    path = Path(index_path)
    new_row = f"| [{topic_name}]({slug}_review.md) | {date} | {session_num} | {coverage}% |"
    content = path.read_text(encoding="utf-8")
    content = re.sub(rf"\|[^\n]*{re.escape(slug)}_review\.md[^\n]*", new_row, content)
    path.write_text(content, encoding="utf-8")


def update_review_metadata(
    review_path: str,
    date: str,
    session_num: str,
    coverage: str,
) -> None:
    path = Path(review_path)
    content = path.read_text(encoding="utf-8")
    replacements = {
        "last_studied": date,
        "session_count": session_num,
        "coverage_pct": coverage,
    }
    for key, value in replacements.items():
        content = re.sub(rf"(?m)^{re.escape(key)}:.*$", f"{key}: {value}", content)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(prog="heartbeat_utils")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mc = sub.add_parser("mark-complete", help="Replace last IN-PROGRESS with COMPLETE")
    p_mc.add_argument("path", help="Path to session vault file")

    p_rm = sub.add_parser("update-review-metadata", help="Update doc-anchored review metadata")
    p_rm.add_argument("path")
    p_rm.add_argument("date")
    p_rm.add_argument("session_num")
    p_rm.add_argument("coverage")

    p_si = sub.add_parser("update-session-index", help="Update slug row in session INDEX.md")
    p_si.add_argument("index")
    p_si.add_argument("slug")
    p_si.add_argument("topic_name")
    p_si.add_argument("date")
    p_si.add_argument("skill")
    p_si.add_argument("status")

    p_di = sub.add_parser("update-docanchor-index", help="Update slug_review row in doc-anchored INDEX.md")
    p_di.add_argument("index")
    p_di.add_argument("slug")
    p_di.add_argument("topic_name")
    p_di.add_argument("date")
    p_di.add_argument("session_num")
    p_di.add_argument("coverage")

    args = parser.parse_args()

    if args.cmd == "mark-complete":
        mark_session_complete(args.path)
    elif args.cmd == "update-review-metadata":
        update_review_metadata(args.path, args.date, args.session_num, args.coverage)
    elif args.cmd == "update-session-index":
        update_session_index(args.index, args.slug, args.topic_name, args.date, args.skill, args.status)
    elif args.cmd == "update-docanchor-index":
        update_docanchor_index(args.index, args.slug, args.topic_name, args.date, args.session_num, args.coverage)


if __name__ == "__main__":
    main()
