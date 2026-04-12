---
name: knowledge_map
description: Knowledge Map — Learner Knowledge Graph. Triggers on "what are my gaps", "knowledge map", "show my weaknesses", "what have I studied", "learning progress", "dashboard", "show my topics", "recent activity", "ACGME", "milestones". Route "what should I study today" to study-session instead.
---

# Knowledge Map

## Visual Dashboard

Trigger: overview, dashboard, "show me my brain"

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py dashboard
```

Format JSON as rich summary: Domain progress table (bar chars, coverage %, confidence, strongest/weakest), Recent Activity timeline (date, source, signal, topic, confidence delta).

## Topic Explorer

```bash
# All studied, by confidence
python3 src/knowledge_graph.py topics --only-studied --sort confidence
# Domain-specific
python3 src/knowledge_graph.py topics --domain "Spine" --sort confidence
# Weakest / most recent
python3 src/knowledge_graph.py topics --only-studied --sort confidence_asc
python3 src/knowledge_graph.py topics --only-studied --sort recent --limit 20
```

Format as table: Topic, Domain, Confidence (bar), Depth, Encounters, Last Seen.

## Activity Feed

```bash
python3 src/knowledge_graph.py activity --n 30
```

## Status & Topic Detail

- General status: `python3 src/knowledge_graph.py status`
- Specific topic: `python3 src/knowledge_graph.py topic_detail "topic"`
- Add topic: `python3 src/knowledge_graph.py add_topic --name "X" --category "Y" --source "attending-directive" --priority 1`

## Gap Detection

```bash
python3 src/knowledge_graph.py gaps --top 15 [--rotation "Vascular"]
```

Valid rotations: Vascular, Spine, Tumor, Functional and Stereotactic, Trauma, Pediatric Neurosurgery, Critical Care and General Neurosurgery.

Also run `review_queue --n 10` and present as "Concepts Due for Re-Verification" section.

## ACGME Milestone Report

```bash
python3 src/knowledge_graph.py milestone_report
```

Format as milestone table (coverage, avg confidence, gaps, progress bar). List 3 Priority Targets. Offer to drill or start study session.

## Anki Sync

If last sync >7d, ask if Anki is open. If yes: `python3 src/knowledge_graph.py sync_anki`

## Dashboard.md Write (Silent — after every presentation)

Write to `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Dashboard.md`:

```markdown
---
updated: YYYY-MM-DD
---

> [!abstract] Overview
> **Curriculum coverage**: X.X% — N of 264 topics | **Events**: N | **Last session**: date

---

## Curriculum Progress
| Domain | Milestone | Touched | Coverage |
|--------|-----------|---------|----------|
[from dashboard JSON: domain.encountered / domain.total]

---

## Study Queue

> [!tip] This Week
> [synthesized recommendation]

### Priority Gaps
| Topic | Domain | Note |
[from gaps --top 8]

### Concept Gaps to Address
| Concept | Topic | Error Type |
[from concept_review_queue, deduplicated, Title Cased]

---

## Recent Activity
| Date | Source | Activity |
[last 7-10 events]

---

## Patterns & Calibration
[data from cognitive_patterns/calibration_profile, or callout if none yet]

---

## Vault Assets
> [!example] Notes
> **Reports** (N): [wikilinks] | **Operative Guides** (N): [...] | **Study Material** (N): [...] | **Concepts** (N): [...]

---

## What Changed (Last Session)
> [!info] Last session — date
> **Skill**: ... | **Topics**: ... | **Vault Writes**: ... | **Next Priority**: ...
```

Style: No H1 (filename is title). No emojis. `updated:` only in frontmatter. Obsidian callout blocks for prose. Tables for data.

Cross-reference discovery (CLAUDE.md §7a) for Vault Assets wikilinks.

## ACGME Readiness Update (Silent — after Dashboard write)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
  python3 src/knowledge_graph.py acgme_readiness > /tmp/acgme_data.json && \
  python3 src/knowledge_graph.py export_concept_stubs --only-studied > /tmp/stubs_studied.json && \
  python3 scripts/write_acgme_readiness.py --json /tmp/acgme_data.json
```

Read `/tmp/stubs_studied.json` → update rich stubs in `Concepts/`. Do NOT overwrite protected notes (CLAUDE.md §4). Delete temp files.

## Initial Batch Setup (one-time)

If `Concepts/INDEX.md` doesn't exist: `python3 scripts/write_concept_stubs.py && python3 scripts/write_acgme_readiness.py`
