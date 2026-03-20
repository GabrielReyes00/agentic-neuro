---
name: study_session
description: Generates a prioritized 30-minute study session plan based on knowledge graph gaps, spaced review queue, error patterns, and transfer candidates. Triggers on "what should I study today", "generate a study session", "custom study plan", "study session", "plan my study", "30 minute study plan".
---

# Agent Skill: Study Session Architect

## When This Skill Triggers

User says things like: "what should I study today", "generate a study session", "custom study plan", "study session", "plan my study", "30 minute study plan", "what do I need to review"

This skill is ONLY triggered on explicit user request. The system never proactively generates study sessions.

---

## Step 1: Data Gathering

Run all four knowledge graph queries in a single bash call:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
  echo "=== REVIEW_QUEUE ===" && python3 src/knowledge_graph.py review_queue --n 5 && \
  echo "=== GAPS ===" && python3 src/knowledge_graph.py gaps --top 5 && \
  echo "=== TRANSFER ===" && python3 src/knowledge_graph.py transfer_candidates --n 3 && \
  echo "=== DASHBOARD ===" && python3 src/knowledge_graph.py dashboard
```

**Optional rotation context:** Check GCal for current rotation to filter gap recommendations:
- Use the `gcal_list_events` MCP tool to check the current week's calendar
- Look for event titles containing rotation keywords (Vascular, Spine, Trauma, Tumor, Pediatric, Functional, Critical Care)
- If found, re-run gaps with `--rotation "RotationName"`
- If GCal is unavailable or no rotation detected, proceed without rotation filtering

---

## Step 2: Adaptive Session Composition

Build a 4-component session plan from the gathered data. Each component has a time allocation, a data source, an execution mode, and a skip condition.

### Component Matrix

| # | Component | Time | Data Source | Execution Mode | Skip Condition |
|---|-----------|------|-------------|----------------|----------------|
| 1 | **Recall Bridge** | 3 min | `review_queue` top 2 concepts | Quick inline verification questions (no RAG needed) | review_queue is empty |
| 2 | **Targeted Remediation** | 8 min | Concepts from `gaps` with `error_type` populated, or `remediation_directives` from a context check | Mode matched to error_type (see below) | No concepts with error_type in output |
| 3 | **New Territory** | 12 min | Top gap topic from `gaps` (highest gap_score, never_encountered or shallow) | Full RAG workflow with `neuro-scaffold` or `board-exam` template | Never skipped — always available |
| 4 | **Transfer Challenge** | 7 min | Top candidate from `transfer_candidates` | Bootcamp-style scenario testing the mastered concept in a new clinical context | No transfer candidates |

### Remediation Mode Routing (Component 2)

| error_type | Mode | Execution |
|---|---|---|
| `numerical_recall` | Rapid-fire quiz | Present fill-in-the-blank questions on exact values. No RAG needed. |
| `conceptual_confusion` | Socratic drill | Run RAG with `socratic-drill` template on the confused concept. |
| `cross_contamination` | Disambiguation table | Read `data/confusion_matrix.json`, generate side-by-side table, then quiz. |
| `application_failure` | Focused scenario | Generate a bootcamp-style scenario scoped to one concept. |
| `reasoning_gap` | Scaffold walkthrough | Run RAG with `textbook-chapter` template, walk through the causal chain. |

### Redistribution Rules

When a component is skipped, redistribute its time to remaining components:
- Skip Recall Bridge (3 min) → add to New Territory (now 15 min)
- Skip Targeted Remediation (8 min) → add a second New Territory topic (8 min) or extend primary to 20 min
- Skip Transfer Challenge (7 min) → extend New Territory to 19 min
- If only New Territory is available → single deep 30-min RAG session on the top gap

---

## Step 3: Present the Plan

Format the session plan as a structured table for user review:

```
## 📚 Study Session Plan (30 minutes)
*[Rotation context if detected, e.g., "Vascular rotation — prioritizing vascular gaps"]*

### 1. Recall Bridge (3 min)
- **Verify:** [concept 1] (from [topic], [X days] overdue)
- **Verify:** [concept 2] (from [topic], [X days] overdue)
- *Mode: Quick inline questions*

### 2. Targeted Remediation (8 min)
- **Target:** [concept] — [error_type_label] issue (missed [N]x)
- *Mode: [drill/socratic/disambiguation/scenario/scaffold]*
- *Framing: [framing_hint]*

### 3. New Territory (12 min)
- **Topic:** [gap topic name] — Domain: [domain]
- *Mode: RAG → neuro-scaffold*
- *Why: [gap_type explanation — never encountered / decaying / shallow]*

### 4. Transfer Challenge (7 min)
- **Test:** [concept] (mastered in [original topic/domain])
- **New Context:** [suggested clinical context from a different domain]
- *Mode: Focused bootcamp scenario*

---
*Approve this plan, modify it, or tell me which component to start with.*
```

If a component was skipped, show the redistribution:

```
### ~~1. Recall Bridge~~ (skipped — no overdue concepts)
*Time redistributed to New Territory (+3 min)*
```

---

## Step 4: Execute on Approval

On user approval (or after modifications), execute each component sequentially:

### Component 1: Recall Bridge
Ask the 2 verification questions directly — no skill invocation needed. These are quick inline questions about specific concepts from the review queue.

Log outcomes immediately after each answer:
```bash
# If correct:
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py log_study --topics "topic" --understood "concept" --depth 2
# If incorrect:
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py log_study --topics "topic" --gaps "concept" --depth 2
```

### Component 2: Targeted Remediation
Based on the error_type, execute the matched mode:
- **`numerical_recall` (drill):** Present 3-5 fill-in-the-blank questions on exact values (doses, thresholds, timing windows). No RAG needed — use knowledge from prior sessions or the gap details.
- **`conceptual_confusion` (socratic):** Run the full RAG workflow with `socratic-drill` template on the confused concept.
- **`cross_contamination` (disambiguation):** Read `data/confusion_matrix.json`, generate a side-by-side comparison table, then quiz the user with a scenario where the two concepts could be confused.
- **`application_failure` (scenario):** Generate a focused bootcamp-style scenario (Phase 1 mechanics from `intern-bootcamp` but scoped to a single concept, ~5 minutes).
- **`reasoning_gap` (scaffold):** Run RAG with `textbook-chapter` template, then walk through the causal chain step-by-step.

Log outcomes after each remediation attempt using `log_study`.

### Component 3: New Territory
Execute the full RAG workflow (Step 0-5 from CLAUDE.md) on the selected gap topic. Use `neuro-scaffold` template by default, or `board-exam` if the user asked for board review.

### Component 4: Transfer Challenge
Generate a bootcamp scenario that requires the mastered concept in a new domain context. Keep it focused — single-concept, ~7 minutes.

Log the transfer outcome:
```bash
# If user demonstrates concept correctly in new context:
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py log_transfer --concept "concept text" --topic "original topic" --context "new clinical context" --success
# If user fails:
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py log_transfer --concept "concept text" --topic "original topic" --context "new clinical context"
```

---

## Step 5: Session Summary

After all components complete, present a brief summary:

```
## Session Complete

| Component | Outcome | Signal |
|-----------|---------|--------|
| Recall Bridge | 2/2 verified | ✅ Intervals reset |
| Remediation | nimodipine dosing — correct on 2nd attempt | ⚠️ Partially resolved |
| New Territory | Cerebral venous sinus thrombosis — covered | 📚 New topic logged |
| Transfer | ICP management in post-op tumor — applied correctly | 🔄 Transfer validated |

*Next session: [brief preview of what would be prioritized based on today's outcomes]*
```

---

## Tone

Direct and efficient. This is a structured session, not a casual conversation. Present the plan cleanly, execute briskly, summarize at the end. The user's time is the most constrained resource — treat every minute as valuable.
