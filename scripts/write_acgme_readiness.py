#!/usr/bin/env python3
"""Generate ACGME Readiness.md from acgme_readiness JSON.

Usage: python3 scripts/write_acgme_readiness.py [--json /tmp/acgme_data.json]
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import date

VAULT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
OUTPUT = VAULT / "ACGME Readiness.md"
PROJECT_ROOT = Path(__file__).parent.parent

DEPTH_LABELS = {0: "-", 1: "Surface", 2: "Mechanistic", 3: "Applied"}


def depth_label(depth: int) -> str:
    return DEPTH_LABELS.get(depth, f"Depth-{depth}")


def build_topic_row(t: dict) -> str:
    name = t.get("display_name", t.get("slug", "?"))
    stub_file = t.get("concept_stub", "")
    if stub_file:
        fname = stub_file.replace("Concepts/", "").replace(".md", "")
        display = name[:55] + ("..." if len(name) > 55 else "")
        name_cell = f"[[Concepts/{fname}|{display}]]"
    else:
        name_cell = name[:60]
    studied = "Yes" if t.get("studied") else "No"
    conf = f"{t['confidence']:.3f}" if t.get("studied") else "-"
    dlabel = depth_label(t.get("depth", 0)) if t.get("studied") else "-"
    return f"| {name_cell} | {studied} | {conf} | {dlabel} |"


def build_domain_section(dom: dict) -> str:
    name = dom["domain"]
    acgme = dom.get("acgme_milestone", "")
    total = dom["total_topics"]
    touched = dom["topics_touched"]
    at_target = dom["topics_at_target"]
    cov_pct = dom["coverage_pct"]

    lines = []
    lines.append(f"### {name} -- {acgme}")
    lines.append(f"**{total} topics in scope | {touched} touched ({cov_pct}%) | {at_target} at target depth**")
    lines.append("")
    lines.append("| Topic | Studied | Confidence | Depth |")
    lines.append("|-------|---------|------------|-------|")

    topics = dom.get("topics", [])
    # Show studied first, then not studied (up to 5 not-studied visible, rest collapsed)
    studied_topics = [t for t in topics if t.get("studied")]
    not_studied = [t for t in topics if not t.get("studied")]

    for t in studied_topics:
        lines.append(build_topic_row(t))

    show_limit = 5
    for t in not_studied[:show_limit]:
        lines.append(build_topic_row(t))

    if len(not_studied) > show_limit:
        remaining = len(not_studied) - show_limit
        lines.append(f"| *[{remaining} more not yet started...]* | | | |")

    lines.append("")

    # Highest-priority gaps (not studied, priority <= 1)
    priority_gaps = [
        t for t in not_studied
        if not t.get("studied")
    ][:3]
    if priority_gaps:
        gap_links = []
        for t in priority_gaps:
            stub = t.get("concept_stub", "")
            name_t = t.get("display_name", t.get("slug", ""))
            if stub:
                fname = stub.replace("Concepts/", "").replace(".md", "")
                short = name_t[:50] + ("..." if len(name_t) > 50 else "")
                gap_links.append(f"[[Concepts/{fname}|{short}]]")
            else:
                gap_links.append(name_t[:60])
        lines.append("**Highest-priority gaps**: " + ", ".join(gap_links))
        lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def build_never_started_section(data: dict) -> str:
    lines = []
    lines.append("## Never Started")
    lines.append(f"These PGY-{data['current_pgy']} curriculum topics have zero encounters.")
    lines.append("")

    for dom in data["domains"]:
        not_studied = [t for t in dom.get("topics", []) if not t.get("studied")]
        if not not_studied:
            continue
        lines.append(f"### {dom['domain']} ({len(not_studied)} not started)")
        for t in not_studied:
            stub = t.get("concept_stub", "")
            name_t = t.get("display_name", t.get("slug", ""))
            if stub:
                fname = stub.replace("Concepts/", "").replace(".md", "")
                short = name_t[:60] + ("..." if len(name_t) > 60 else "")
                lines.append(f"- [[Concepts/{fname}|{short}]]")
            else:
                lines.append(f"- {name_t}")
        lines.append("")

    return "\n".join(lines)


def build_document(data: dict, today: str) -> str:
    pgy = data["current_pgy"]
    total = data["total_in_scope"]
    at_target = data["topics_at_target"]
    touched = data["topics_touched"]
    never = data["topics_never_studied"]
    cov_pct = data["coverage_pct"]

    # Frontmatter
    fm = f"""---
resident_year: PGY-{pgy}
updated: {today}
total_in_scope: {total}
topics_at_target: {at_target}
topics_touched: {touched}
topics_never_studied: {never}
coverage_pct: {cov_pct}
tags:
  - type/reference
  - source/agent
---"""

    header = f"""
# ACGME Readiness -- PGY-{pgy}
*Gabriel Reyes | Baylor College of Medicine | Updated: {today}*

> **{total} topics** in scope for PGY-{pgy} | **{at_target}/{total}** at target depth | **{touched}/{total}** touched | **{never}/{total}** never studied

*"At target" = mechanistic depth (2+) with confidence >= 0.15*

## Domain Coverage

"""

    domain_sections = ""
    for dom in data["domains"]:
        domain_sections += build_domain_section(dom)

    never_section = build_never_started_section(data)

    return fm + header + domain_sections + never_section


def main():
    json_path = "/tmp/acgme_data.json"
    if len(sys.argv) > 2 and sys.argv[1] == "--json":
        json_path = sys.argv[2]

    try:
        with open(json_path) as f:
            data = json.load(f)
    except FileNotFoundError:
        # Regenerate
        result = subprocess.run(
            ["python3", "src/knowledge_graph.py", "acgme_readiness"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        if result.returncode != 0:
            print(f"ERROR: {result.stderr[:500]}", file=sys.stderr)
            sys.exit(1)
        data = json.loads(result.stdout)

    today = date.today().isoformat()
    content = build_document(data, today)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"Written {OUTPUT}")
    print(f"  PGY-{data['current_pgy']} | {data['total_in_scope']} topics | {data['topics_touched']} touched | {data['topics_at_target']} at target")


if __name__ == "__main__":
    main()
