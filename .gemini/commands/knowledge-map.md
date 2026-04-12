---
name: knowledge_map
description: Learner knowledge graph dashboard and gap analysis for progress, milestones, and study-state queries.
---

# Knowledge Map — Learner Knowledge Graph

## Triggering

Use for progress/gap/dashboard/milestone/activity queries. Route "what should I study today" to `study-session`.

Shell prefix for all commands below:
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate
```

## Core Views

### 1) Dashboard Overview

```bash
python3 src/knowledge_graph.py dashboard
```

Render: coverage summary, domain table (coverage/confidence/strongest/needs work), recent activity timeline.

### 2) Topic Explorer

```bash
python3 src/knowledge_graph.py topics --only-studied --sort confidence
python3 src/knowledge_graph.py topics --domain "<Domain>" --sort confidence
python3 src/knowledge_graph.py topics --only-studied --sort confidence_asc
python3 src/knowledge_graph.py topics --only-studied --sort recent --limit 20
```

### 3) Activity Feed

```bash
python3 src/knowledge_graph.py activity --n 30
```

### 4) Status + Topic Detail

```bash
python3 src/knowledge_graph.py status
python3 src/knowledge_graph.py topic_detail "<topic>"
```

### 5) Add Topic

```bash
python3 src/knowledge_graph.py add_topic --name "<topic>" --category "<category>" --source "attending-directive" --priority 1
```

### 6) Backfill Historical Data

```bash
python3 src/knowledge_graph.py backfill --telemetry data/Sessions/search_telemetry.jsonl
```

## Gap Analysis

```bash
python3 src/knowledge_graph.py gaps --top 15 [--rotation "<Rotation>"]
python3 src/knowledge_graph.py concept_review_queue --n 10
```

Present grouped by urgency/decay/shallow/error clusters. Include due concepts table. Offer to start `study-session` on top gap.

## ACGME Milestone Report

```bash
python3 src/knowledge_graph.py milestone_report
```

Present weakest-first competency table + top 3 priority milestone targets.

## Anki Sync Freshness

If recommendations may be stale due to old/no sync:
```bash
python3 src/knowledge_graph.py sync_anki
```
Proceed if user declines.

## Obsidian Dashboard Write (Silent)

After any dashboard/gap/milestone render, update `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Dashboard.md`.

Rules:
1. Use real JSON values from KG output (no stale carryover)
2. Sections: overview, curriculum progress, study queue, concept gaps, recent activity, patterns/calibration, vault assets, what changed (last session)
3. Callouts for prose, tables for data
4. No H1, no emojis, no extra frontmatter

Cross-reference discovery for vault assets:
```bash
ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/"*.md \
   "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/"*.md \
   "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/"*.md \
   "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/"*.md 2>/dev/null
```

"No data yet" placeholder for empty sections. Do not narrate dashboard writes.

## Cleanup

No wildcard cleanup from this command. Read/dashboard oriented — do not remove shared session artifacts.
