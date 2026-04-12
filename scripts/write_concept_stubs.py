#!/usr/bin/env python3
"""Batch-write every curriculum concept stub to the Obsidian Concepts/ folder.

Full-vault regeneration entrypoint. Delegates all rendering to
`src/vault_kg_sync.py` so the stub format stays in lockstep with what the
post-session hook produces. Use this script when you want to rebuild every
Concept file from scratch (e.g., after a schema migration or a vault reset).

Studied concepts get the full Learning-State + relationship + encounter-ledger
treatment. Unstudied concepts get the minimal placeholder stub.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledge_graph import KnowledgeGraph  # noqa: E402
from vault_kg_sync import (  # noqa: E402
    PROTECTED_CONCEPTS,
    safe_write_vault_file,
    stub_filename,
    sync_all_concepts,
)

VAULT = Path("/Users/gabrielreyes/Documents/Obsidian/agentic-neuro")
CONCEPTS_DIR = VAULT / "Concepts"


def build_index(stubs: list[dict], today: str) -> str:
    total = len(stubs)
    studied = sum(1 for s in stubs if s.get("studied"))
    pct = round(studied / total * 100, 1) if total else 0.0

    rows = []
    for s in stubs:
        fname = (s.get("filename") or stub_filename(s.get("title", ""))).replace(".md", "")
        link = f"[[Concepts/{fname}]]"
        domain = s.get("domain", "")
        pgy = s.get("pgy_target", 1)
        status = s.get("status", "not_studied")
        conf_str = f"{s['confidence']:.3f}" if s.get("studied") else "-"
        rows.append(f"| {link} | {domain} | {pgy} | {status} | {conf_str} |")

    rows_str = "\n".join(rows)
    return f"""**Curriculum Index** -- {total} topics | {studied} studied ({pct}%) | {total - studied} not yet started

Filter by tag in Graph View: `status/known`, `status/gap`, `status/not-studied`, `domain/*`, `pgy/1`, `priority/core`

| Topic | Domain | PGY | Status | Confidence |
|-------|--------|-----|--------|------------|
{rows_str}

---
updated: {today}
total_stubs: {total}
studied: {studied}
tags:
  - type/reference
  - source/agent
---
"""


def main() -> int:
    kg = KnowledgeGraph()
    result = sync_all_concepts(kg, CONCEPTS_DIR, protected=PROTECTED_CONCEPTS)

    # Build INDEX.md from the KG stub export.
    stubs = kg.export_concept_stubs(only_studied=False)
    today = date.today().isoformat()
    safe_write_vault_file(CONCEPTS_DIR / "INDEX.md", build_index(stubs, today))

    print(f"Wrote {result['written']} concept files "
          f"({result['rich']} rich, {result['minimal']} minimal) "
          f"to {CONCEPTS_DIR}")
    print(f"Skipped {result['skipped_protected']} protected notes")
    print(f"Wrote INDEX.md ({len(stubs)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
