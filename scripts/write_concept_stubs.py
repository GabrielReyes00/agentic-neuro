#!/usr/bin/env python3
"""Batch-write 265 curriculum concept stubs to Obsidian Concepts/ folder.

Usage: python3 scripts/write_concept_stubs.py
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import date

VAULT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
CONCEPTS_DIR = VAULT / "Concepts"

# Existing hand-written notes that must NOT be overwritten
PROTECTED = {
    "Neurosurgery Consult Checklists by Pathology.md",
    "Neurosurgery Consult Workflow.md",
    "Peripheral Nerve Injury Classifications (Seddon & Sunderland).md",
}

DEPTH_LABEL_MAP = {
    0: "not_studied",
    1: "surface",
    2: "mechanistic",
    3: "applied",
}


def depth_label(depth: int) -> str:
    return DEPTH_LABEL_MAP.get(depth, f"depth-{depth}")


def priority_label(priority: int) -> str:
    return {1: "core", 2: "important", 3: "advanced"}.get(priority, "core")


def status_display(status: str) -> str:
    return {"not_studied": "not-studied", "gap": "gap", "known": "known"}.get(status, status)


def build_stub_minimal(s: dict) -> str:
    dt = s.get("domain_tag", "general")
    pgy = s.get("pgy_target", 1)
    pri = priority_label(s.get("priority", 1))
    acgme = s.get("acgme_milestone", "")
    domain = s.get("domain", "")
    title = s.get("title", s["filename"].replace(".md", ""))

    tags = [
        "type/concept",
        f"domain/{dt}",
        "status/not-studied",
        f"pgy/{pgy}",
        f"priority/{pri}",
    ]
    tags_yaml = "\n".join(f"  - {t}" for t in tags)

    return f"""---
aliases: []
confidence: 0.0
depth: 0
depth_label: not_studied
domain: {domain}
domain_tag: {dt}
acgme: {acgme}
pgy_target: {pgy}
status: not_studied
encounter_count: 0
priority: {pri}
tags:
{tags_yaml}
---

# {title}

**ACGME**: {acgme} ({domain}) | **PGY Target**: Year {pgy} | **Priority**: {pri.capitalize()}

Not yet studied.
"""


def build_stub_rich(s: dict) -> str:
    dt = s.get("domain_tag", "general")
    pgy = s.get("pgy_target", 1)
    pri = priority_label(s.get("priority", 1))
    acgme = s.get("acgme_milestone", "")
    domain = s.get("domain", "")
    conf = s.get("confidence", 0.0)
    depth = s.get("depth", 1)
    dlabel = depth_label(depth)
    enc = s.get("encounter_count", 0)
    last_studied = s.get("last_studied") or ""
    status = s.get("status", "gap")
    title = s.get("title", s["filename"].replace(".md", ""))
    atlas_entries = s.get("confusable_atlas_entries", [])

    tags = [
        "type/concept",
        f"domain/{dt}",
        f"status/{status_display(status)}",
        f"depth/{dlabel}",
        f"pgy/{pgy}",
        f"priority/{pri}",
    ]
    tags_yaml = "\n".join(f"  - {t}" for t in tags)

    aliases_yaml = ""
    slug = s.get("slug", "")
    if slug:
        aliases_yaml = f'  - "{slug}"'
    else:
        aliases_yaml = ""

    aliases_block = f"aliases:\n{aliases_yaml}" if aliases_yaml else "aliases: []"

    last_studied_line = f"last_studied: {last_studied}" if last_studied else "last_studied: ~"

    body = f"""---
{aliases_block}
confidence: {conf:.3f}
depth: {depth}
depth_label: {dlabel}
domain: {domain}
domain_tag: {dt}
acgme: {acgme}
pgy_target: {pgy}
status: {status}
encounter_count: {enc}
{last_studied_line}
priority: {pri}
tags:
{tags_yaml}
---

# {title}

**ACGME**: {acgme} ({domain}) | **PGY Target**: Year {pgy} | **Confidence**: {conf:.3f} | **Depth**: {dlabel.capitalize()} ({depth})

Encountered {enc} time{"s" if enc != 1 else ""}."""

    if last_studied:
        body += f" Last studied: {last_studied}."

    if atlas_entries:
        body += "\n\n## Known Confusion Points\n"
        for entry in atlas_entries:
            body += f"- [[Error Atlas/{entry}]]\n"

    body += "\n\n## Related Vault Content\n\n*Agent fills this during vault write phase with matching Reports/Operative Guides wikilinks.*\n"

    return body


def build_index(stubs: list[dict], today: str) -> str:
    total = len(stubs)
    studied = sum(1 for s in stubs if s["studied"])
    pct = round(studied / total * 100, 1) if total else 0.0

    rows = []
    for s in stubs:
        title = s.get("title", s["filename"].replace(".md", ""))
        fname = s["filename"].replace(".md", "")
        link = f"[[Concepts/{fname}|{title[:50]}{'...' if len(title) > 50 else ''}]]"
        domain = s.get("domain", "")
        pgy = s.get("pgy_target", 1)
        status = s.get("status", "not_studied")
        conf_str = f"{s['confidence']:.3f}" if s["studied"] else "-"
        rows.append(f"| {link} | {domain} | {pgy} | {status} | {conf_str} |")

    rows_str = "\n".join(rows)

    return f"""---
updated: {today}
total_stubs: {total}
studied: {studied}
tags:
  - type/reference
  - source/agent
---

# Concepts -- Curriculum Index

{total} curriculum topics | {studied} studied ({pct}%) | {total - studied} not yet started

Filter by tag in Graph View: `status/known`, `status/gap`, `status/not-studied`, `domain/*`, `pgy/1`, `priority/core`

| Topic | Domain | PGY | Status | Confidence |
|-------|--------|-----|--------|------------|
{rows_str}
"""


def main():
    project_root = Path(__file__).parent.parent
    result = subprocess.run(
        ["python3", "src/knowledge_graph.py", "export_concept_stubs"],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    if result.returncode != 0:
        print(f"ERROR: {result.stderr[:500]}", file=sys.stderr)
        sys.exit(1)

    stubs = json.loads(result.stdout)
    today = date.today().isoformat()

    CONCEPTS_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped_protected = 0
    skipped_existing = 0

    for s in stubs:
        fname = s["filename"]
        if fname in PROTECTED:
            skipped_protected += 1
            continue

        dest = CONCEPTS_DIR / fname

        # Do not overwrite existing protected notes that might have a different name
        # but same content — only skip explicitly protected filenames above

        if s["studied"]:
            content = build_stub_rich(s)
        else:
            content = build_stub_minimal(s)

        dest.write_text(content, encoding="utf-8")
        written += 1

    # Write INDEX.md
    index_path = CONCEPTS_DIR / "INDEX.md"
    index_content = build_index(stubs, today)
    index_path.write_text(index_content, encoding="utf-8")

    print(f"Written {written} concept stubs to {CONCEPTS_DIR}")
    print(f"Skipped {skipped_protected} protected notes")
    print(f"Written INDEX.md ({len(stubs)} entries)")


if __name__ == "__main__":
    main()
