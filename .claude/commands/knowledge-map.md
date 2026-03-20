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
## 🧠 Knowledge Dashboard
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

Use `█` for filled (coverage percentage / 10, rounded up) and `░` for empty, 10 chars total.

After the table, show the **Recent Activity** feed from the JSON (last 10 events) formatted as a timeline:

```
### Recent Activity
| When | Source | Signal | Topic | Δ Confidence |
|------|--------|--------|-------|--------------|
| Mar 16 | 🔴 sim | incorrect_recall | VP Shunt Surgery | -0.10 |
| Mar 16 | 🔍 search | query | Lumbar Disc Herniation | +0.03 |
| Mar 16 | 🔍 search | lecture_received | Epidural Hematoma | +0.08 |
| Mar 16 | 🟢 sim | correct_recall | ICP Monitoring | +0.12 |
```

Source icons: 🔍 search, 🟢/🔴 sim (green=correct, red=incorrect/weakness), 🔬 procedure, 📇 cards, ✏️ manual

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

Confidence bar: 5 chars, each `█` = 0.20 confidence. Round up.

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
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py review_queue --n 10
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
## 🏥 ACGME Milestone Competency Report
**N milestones tracked**

| Milestone | Domain | Coverage | Avg Conf | Gaps | Progress |
|-----------|--------|----------|----------|------|----------|
| PC-14 | Critical Care | 0% (0/27) | 0.000 | 27 | ░░░░░░░░░░ |
| PC-1  | Vascular | 0% (0/11) | 0.000 | 11 | ░░░░░░░░░░ |
| MK-1  | Trauma | 12% (3/25) | 0.080 | 22 | █░░░░░░░░░ |
```

Progress bar: 10 chars, each `█` = 10% coverage (round down).

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

## Future Phases (Not Yet Implemented)

- **Phase 5**: Rotation-aware recommendations via GCal integration (auto-detect rotation from calendar events)
