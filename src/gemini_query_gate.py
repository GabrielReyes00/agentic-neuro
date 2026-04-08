#!/usr/bin/env python3
"""Deterministic query gate for Gemini CLI routing.

Classifies an incoming user query into the expected route using the repository's
Tier 1 / Tier 2 trigger policy, and can optionally hydrate learner context for
non-RAG direct clinical answers.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
SESSIONS_DIR = BASE_DIR / "data" / "Sessions"
LEARNER_CONTEXT_PATH = SESSIONS_DIR / "learner_context.json"


ROUTE_KEYWORDS = [
    ("anki-sync", ["save to anki", "make cards", "flashcards", "sync to anki"]),
    ("list-textbooks", ["what books", "inventory", "what's loaded", "list textbooks"]),
    ("inbox-workflow", ["inbox", "triage emails", "check my mail", "process inbox"]),
    ("knowledge-map", ["gaps", "knowledge map", "weaknesses", "dashboard", "milestones", "acgme"]),
    ("study-session", ["what should i study", "study session", "study plan"]),
    (
        "rag-workflow",
        [
            "search my textbooks for",
            "look this up in the database",
            "what do my textbooks say about",
            "rag this",
        ],
    ),
    ("intern-bootcamp", ["drill me", "run a scenario", "night float sim", "bootcamp", "cross-cover sim", "pager sim"]),
    ("intraoperative-guide", ["operative walkthrough for", "walk me through the surgery for"]),
    ("study-material", ["make study material from", "quiz me on this file", "prep me for"]),
    ("generate-report", ["generate a report on", "research report on", "comprehensive review of"]),
]

CALENDAR_HINTS = ("calendar", "schedule", "meeting", "event", "appointment")
DIRECT_CLINICAL_HINTS = (
    "why",
    "how",
    "what",
    "compare",
    "explain",
    "mechanism",
    "pathophysiology",
    "management",
    "treatment",
    "differential",
    "workup",
    "surgery",
    "aneurysm",
    "stroke",
    "tumor",
    "spine",
    "trauma",
)
NON_CLINICAL_HINTS = (
    "python",
    "javascript",
    "typescript",
    "bug",
    "stack trace",
    "compile",
    "refactor",
    "git",
    "repo",
    "docker",
    "api",
)


def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def _detect_slash_command(text: str) -> Optional[str]:
    m = re.match(r"^\s*/([a-z0-9][a-z0-9_-]*)", text.lower())
    if not m:
        return None
    cmd = m.group(1)
    return cmd


def _is_clinical_direct_query(text: str) -> bool:
    q = _normalize(text)
    if any(tok in q for tok in NON_CLINICAL_HINTS):
        return False
    if "?" in text:
        return any(tok in q for tok in DIRECT_CLINICAL_HINTS)
    return any(q.startswith(prefix + " ") for prefix in ("why", "how", "what", "explain", "compare"))


def classify_query(raw_query: str) -> dict:
    query = raw_query.strip()
    normalized = _normalize(query)

    slash = _detect_slash_command(query)
    if slash:
        route = slash
        if route == "rag-transform":
            return {
                "route": "direct",
                "reason": "rag-transform is internal-only and cannot be user-invoked",
                "matched_trigger": "slash:/rag-transform",
                "explicit_rag_request": False,
                "should_load_learner_context": _is_clinical_direct_query(query),
            }

        explicit_rag = route == "rag-workflow"
        return {
            "route": route,
            "reason": "explicit slash command",
            "matched_trigger": f"slash:/{route}",
            "explicit_rag_request": explicit_rag,
            "should_load_learner_context": route == "direct" and _is_clinical_direct_query(query),
        }

    if any(h in normalized for h in CALENDAR_HINTS):
        return {
            "route": "calendar",
            "reason": "calendar/scheduling keyword",
            "matched_trigger": "calendar",
            "explicit_rag_request": False,
            "should_load_learner_context": False,
        }

    for route, phrases in ROUTE_KEYWORDS:
        for phrase in phrases:
            if phrase in normalized:
                return {
                    "route": route,
                    "reason": "explicit trigger phrase",
                    "matched_trigger": phrase,
                    "explicit_rag_request": route == "rag-workflow",
                    "should_load_learner_context": False,
                }

    should_context = _is_clinical_direct_query(query)
    return {
        "route": "direct",
        "reason": "no tool-dependent trigger detected",
        "matched_trigger": None,
        "explicit_rag_request": False,
        "should_load_learner_context": should_context,
    }


def hydrate_context(query: str) -> dict:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python3",
        "src/knowledge_graph.py",
        "context",
        query,
        "--output",
        str(LEARNER_CONTEXT_PATH),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
    )
    return {
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "context_path": str(LEARNER_CONTEXT_PATH),
        "stdout_tail": proc.stdout[-400:].strip(),
        "stderr_tail": proc.stderr[-400:].strip(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini query routing gate")
    parser.add_argument("query", help="Raw user query")
    parser.add_argument(
        "--hydrate-context",
        action="store_true",
        help="If route=direct and clinical, run knowledge_graph context prepass",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON only (default true; kept for CLI symmetry)",
    )
    args = parser.parse_args()

    result = classify_query(args.query)

    if args.hydrate_context and result["route"] == "direct" and result["should_load_learner_context"]:
        result["context_hydration"] = hydrate_context(args.query)
    else:
        result["context_hydration"] = None

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
