---
name: knowledge_map
description: Knowledge Map — Learner Knowledge Graph dashboard. Invoke when the user asks about their learning progress, gaps, or knowledge state — "what are my gaps", "knowledge map", "show my weaknesses", "dashboard", "milestones", "ACGME". Needs knowledge graph DB access.
---

# Knowledge Map — Learner Knowledge Graph

## When This Skill Triggers

User says things like: "what are my gaps", "knowledge map", "show my weaknesses", "what have I studied", "learning progress", "topic status", "how am I doing", "show me my brain", "show my dashboard", "show my topics", "recent activity", "what have I covered"

> **Note:** If the user asks "what should I study today", "generate a study session", or "custom study plan", route to the `study-session` skill instead — it generates an executable study plan, not just gap recommendations.

---

## Visual Dashboard

When the user asks for an overview, dashboard, or "show me my brain":

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py dashboard
```

This returns JSON. Format it as a **rich visual summary** in your response using this template:

### Domain Progress Heatmap

For each domain, render a progress bar using block characters and show key stats:

```
## Knowledge Dashboard
**6 / 287 topics studied** · Avg confidence: 0.001 · 6 total events

| Domain | Coverage | Confidence | Strongest | Needs Work |
|--------|----------|------------|-----------|------------|
| Vascular | ██░░░░░░░░ 4% (2/45) | 0.03 | Vasospasm (0.03) | SAH Presentation (0.03) |
| Spine | █░░░░░░░░░ 2% (1/46) | 0.03 | Lumbar Disc (0.03) | — |
| Trauma | ███░░░░░░░ 7% (2/28) | 0.10 | ICP Monitoring (0.12) | Epidural Hematoma (0.08) |
| Tumor | ░░░░░░░░░░ 0% (0/55) | 0.00 | — | — |
| Pediatric | █░░░░░░░░░ 3% (1/39) | 0.00 | — | VP Shunt (0.00) |
| Functional | ░░░░░░░░░░ 0% (0/25) | 0.00 | — | — |
| Critical Care | ░░░░░░░░░░ 0% (0/48) | 0.00 | — | — |
```

Use filled block for filled (coverage percentage / 10, rounded up) and empty block for empty, 10 chars total.

After the table, show the **Recent Activity** feed from the JSON (last 10 events) formatted as a timeline:

```
### Recent Activity
| When | Source | Signal | Topic | Change in Confidence |
|------|--------|--------|-------|----------------------|
| Mar 16 | sim (incorrect) | incorrect_recall | VP Shunt Surgery | -0.10 |
| Mar 16 | search | query | Lumbar Disc Herniation | +0.03 |
| Mar 16 | search | lecture_received | Epidural Hematoma | +0.08 |
| Mar 16 | sim (correct) | correct_recall | ICP Monitoring | +0.12 |
```

Source labels: search, sim (correct/incorrect), procedure, cards, manual

---

## Topic Explorer

When the user asks "show my topics", "list topics", "what have I covered", or wants to browse:

```bash
# All studied topics, sorted by confidence (highest first)
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py topics --only-studied --sort confidence

# Domain-specific (e.g., user asks "show me my spine topics")
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py topics --domain "Spine" --sort confidence

# Weakest topics (lowest confidence first)
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py topics --only-studied --sort confidence_asc

# Most recently studied
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py topics --only-studied --sort recent --limit 20
```

Format the JSON output as a clean table:

```
| Topic | Domain | Confidence | Depth | Encounters | Last Seen |
|-------|--------|------------|-------|------------|-----------|
| ICP Monitoring | Trauma | 0.120 ████░ | decision-making | 1 | Mar 16 |
| Epidural Hematoma | Trauma | 0.080 ███░░ | mechanistic | 1 | Mar 16 |
| Vasospasm | Vascular | 0.030 █░░░░ | mechanistic | 1 | Mar 16 |
```

Confidence bar: 5 chars, each filled block = 0.20 confidence. Round up.

---

## Activity Feed

When the user asks "show recent activity", "what have I done", "show my learning log":

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py activity --n 30
```

Format as the timeline table shown in the Dashboard section.

---

## Status & Topic Exploration

### Quick Status Overview

When the user asks for a general status or progress check:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py status
```

Present the output in a clean, formatted summary. Highlight:
- Total topics tracked vs curriculum coverage
- Average confidence level
- Distribution across depth levels
- Most recently studied topics

### Topic Detail

When the user asks about a specific topic ("how am I on vasospasm", "what do I know about spine trauma"):

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py topic_detail "topic name"
```

Present the topic's confidence, depth, encounter history, and signal timeline.

### Add a Topic

When the user wants to add a topic to track (e.g., "my attending said to read up on X", "add muscular dystonia to my list"):

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py add_topic --name "topic name" --category "category" --source "attending-directive" --priority 1
```

Categories: vascular, spine, tumor, functional, trauma, pediatric, critical_care

### Backfill Historical Data

If this is the first time using the knowledge map and the user wants to populate it from historical queries:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py backfill --telemetry data/Sessions/search_telemetry.jsonl
```

---

## Gap Detection & Study Recommendations

### Study Recommendations (User-Initiated)

When the user asks "what should I study", "show my gaps", "study plan":

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py gaps --top 15
```

With rotation context (check GCal first for current rotation, or ask the user):

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py gaps --top 15 --rotation "Vascular"
```

Valid rotation filters: Vascular, Spine, Tumor, Functional and Stereotactic, Trauma, Pediatric Neurosurgery, Critical Care and General Neurosurgery

The gap algorithm applies forgetting-curve decay, then scores by:
- **Priority weight** (board-critical topics weighted 3x)
- **Confidence gap** (1.0 minus current confidence after decay)
- **Depth penalty** (surface-only knowledge on priority-1 topics)
- **Error clustering** (repeated failures in bootcamp/Anki in last 30 days)
- **Rotation boost** (+0.3 for topics matching current rotation)

Present the output grouped by gap type (urgent, decaying, shallow, error clusters, general). After presenting, offer to start a study session on the top-priority gap.

### Spaced Verification Queue

When the user asks about gaps, study plan, or dashboard, also run the review queue to show concepts that were previously "known" but are now overdue for verification:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py concept_review_queue --n 10
```

Present as a separate section after the gap recommendations:

```
CONCEPTS DUE FOR RE-VERIFICATION
---------------------------------
| Concept | Topic | Days Overdue | Last Confirmed | Error History |
|---------|-------|-------------|----------------|---------------|
| Fisher grade 3 highest risk | SAH | 5.2 days | Mar 10 | Yes |
| nimodipine 60mg q4h | Vasospasm | 3.1 days | Mar 12 | No |
```

After presenting, offer to run a quick verification quiz or note that these will be woven into future Gym questions and bootcamp scenarios automatically.

### Curriculum Management

Load or reload the ABNS/ACGME curriculum skeleton:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py load_curriculum
```

---

## ACGME Milestone Competency Report

When the user asks "show my milestones", "ACGME progress", "competency dashboard", "milestone report", "how am I on milestones", "show my competency":

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py milestone_report
```

This returns JSON grouped by ACGME milestone, sorted weakest-first. Format as a milestone competency table:

```
## ACGME Milestone Competency Report
**N milestones tracked**

| Milestone | Domain | Coverage | Avg Conf | Gaps | Progress |
|-----------|--------|----------|----------|------|----------|
| PC-14 | Critical Care | 0% (0/27) | 0.000 | 27 | ░░░░░░░░░░ |
| PC-1  | Vascular | 0% (0/11) | 0.000 | 11 | ░░░░░░░░░░ |
| MK-1  | Trauma | 12% (3/25) | 0.080 | 22 | █░░░░░░░░░ |
```

Progress bar: 10 chars, each filled block = 10% coverage (round down).

After the table, list the **3 Priority Targets** — the milestones with lowest coverage that contain priority-1 topics:

```
### Priority Targets
1. **PC-14 (Critical Care)** — 0% coverage, 27 topics untouched. Key gaps: ICP Monitoring, Multimodal Neuromonitoring, Brain Tissue O2...
2. **PC-1 (Vascular)** — 0% coverage, 11 topics untouched. Key gaps: Subarachnoid Hemorrhage, Cerebral Vasospasm...
3. **MK-1 (Trauma)** — 12% coverage, 3/25 topics studied. Confidence: 0.080.
```

After presenting, offer to drill into any milestone or start a study session on the top gap.

---

## Anki Review Sync

When generating study recommendations and the last Anki sync is >7 days old (or has never been done), ask the user:

> "Your Anki review data is [N days] stale — is Anki open so I can pull fresh retention stats for better recommendations?"

If yes:
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py sync_anki
```

If no, proceed with existing data. The Anki sync also runs automatically after every `anki-sync` card creation.

---

## Tone

Direct and informative. Present data cleanly. When showing status, frame it encouragingly but honestly — highlight both strengths and gaps. This is a personal dashboard, not a clinical interaction.

## Obsidian Dashboard Write (Silent — after presenting to user)

After rendering the dashboard, gap analysis, milestone report, or any visual summary to the user, silently write/update the Dashboard.md file at `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Dashboard.md` using the Write tool.

**Coverage numbers MUST come from `dashboard` JSON using `domain.encountered / domain.total` (both fields are correct after the COUNT(DISTINCT curriculum_id) fix). Never hallucinate or carry forward stale percentages from memory.**

**Dashboard.md structure:**
```markdown
---
updated: YYYY-MM-DD
---

> [!abstract] Overview
> **Curriculum coverage**: X.X% — N of 264 topics touched | **Events logged**: N | **Last session**: Mon DD, YYYY

---

## Curriculum Progress

Coverage is measured against the ACGME curriculum (264 topics across 10 domains). A topic is "touched" only when a session, RAG search, or bootcamp encounter is logged against a curriculum-mapped entry.

| Domain | Milestone | Touched | Coverage |
|--------|-----------|---------|----------|
[rows from dashboard JSON, sorted by coverage_pct descending, using encountered/total from the JSON]

---

## Study Queue

> [!tip] This Week
> [2-3 sentence synthesized recommendation based on top gap domain and unresolved concept gaps]

### Priority Gaps

| Topic | Domain | Note |
|-------|--------|------|
[top gaps from `gaps --top 8`, plain text — wikilink only if a vault doc exists for the topic]

### Concept Gaps to Address

These concepts were missed in previous sessions and have not yet been confirmed correct.

| Concept | Topic | Error Type |
|---------|-------|------------|
[deduplicated entries from `concept_review_queue`, capitalize concept names, omit duplicates]

---

## Recent Activity

| Date | Source | Activity |
|------|--------|----------|
[last 7-10 events from `recent_activity`, grouped by date, cleaned topic names — no sentence fragments]

---

## Patterns & Calibration

> [!note] No calibration data yet
> Complete a `/intern-bootcamp` session to build your confidence calibration profile and surface recurring error patterns.

[Replace callout with actual data once calibration_profile and cognitive_patterns return results]

---

## Vault Assets

> [!example] Notes in this vault
> **Reports** (N): [wikilinked list or "None yet"]
> **Operative Guides** (N): [wikilinked list or "None yet — use /intraoperative-guide to generate one"]
> **Study Material** (N): [wikilinked list or "None yet"]
> **Concepts** (N): [wikilinked list]

---

## What Changed (Last Session)

> [!info] Last session — Mon DD, YYYY
> **Skill**: <skill that ran>
> **Topics Touched**: <topics>
> **Vault Writes**: <files created/updated>
> **Next Priority**: <top gap or next action>
```

**Cross-reference discovery:** Before writing, run:
```bash
ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/"*.md 2>/dev/null
```

Use filenames to populate Vault Assets with accurate wikilinks.

**Style rules (enforced):**
- No `# Dashboard` H1 in the body — the filename is already the title; adding it creates a duplicate in Obsidian
- No `tags:` in frontmatter — only `updated:` date
- No emojis anywhere
- Use Obsidian callout blocks (`> [!type] Title`) for all prose/stat sections — they provide visual backdrop separation
- Tables for structured data (curriculum progress, gaps, activity)
- Concept names in the review table are Title Cased, not lowercase sentence fragments

Do not narrate the Dashboard.md write to the user.

If the knowledge graph returns empty results for a section, write "No data yet — complete a study session or bootcamp to populate." for that section.

Do not narrate the Dashboard.md write to the user.

## Future Phases (Not Yet Implemented)

- **Phase 5**: Rotation-aware recommendations via GCal integration (auto-detect rotation from calendar events)

---

## Final Cleanup (Silent)

After the session ends, remove temporary session files:

```bash
RUN="cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate" && eval "$RUN" && rm -f data/Sessions/*.json data/Sessions/*.md data/Sessions/*.jsonl
```
