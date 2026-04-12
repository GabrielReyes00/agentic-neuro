---
name: study_session
description: Adaptive 30-minute study session generated from KG gaps, concept review queue, patterns, and transfer candidates.
---

# Agent Skill: Study Session Architect

All §7 session-end hooks mandatory (log_turn after Components 1-2, heartbeat checkpoints, log_transfer, post-session hook).

## Triggering

Use only on explicit user request for study planning/session execution.

## Step 1: Data Gathering

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
  echo "=== CONCEPT_REVIEW_QUEUE ===" && python3 src/knowledge_graph.py concept_review_queue --n 5 && \
  echo "=== GAPS ===" && python3 src/knowledge_graph.py gaps --top 5 && \
  echo "=== TRANSFER ===" && python3 src/knowledge_graph.py transfer_candidates --n 3 && \
  echo "=== COGNITIVE_PATTERNS ===" && python3 src/knowledge_graph.py cognitive_patterns && \
  echo "=== CALIBRATION ===" && python3 src/knowledge_graph.py calibration_profile && \
  echo "=== DASHBOARD ===" && python3 src/knowledge_graph.py dashboard
```

## Step 2: Compose Adaptive 4-Component Session

| Component | Time | Source |
|---|---|---|
| Recall Bridge | 3 min | `concept_review_queue` |
| Targeted Remediation | 8 min | Gap concepts with `error_type` |
| New Territory | 12 min | Top gap topic (never skip) |
| Transfer Challenge | 7 min | `transfer_candidates` |

### Remediation Mode Routing

`numerical_recall` → rapid drill | `conceptual_confusion` → forced disambiguation | `cross_contamination` → confusable-pair vignette | `application_failure` → focused scenario | `reasoning_gap` → causal scaffold

### Cognitive Pattern Override

Recurring process-level pattern → insert 5-min process intervention before/instead of remediation.

### Calibration Adaptation

High-confidence wrong → explicit recalibration. Low-confidence right → reinforce reasoning.

### Skip Redistribution

| Skip condition | Redistribution |
|---|---|
| review queue empty | +3 min to New Territory |
| no error-typed gaps | extend New Territory |
| no transfer candidates | +7 min to New Territory |
| only New Territory | single deep 30-min block |

## Step 3: Present Plan

30-minute plan with component objectives, selected topics, mode rationale, skip/redistribution notes. Ask for approval.

## Step 4: Execute

### Component 1: Recall Bridge

Open recall question → wait → evaluate → if wrong: correction + verification follow-up → log with `log_turn.sh`.

### Component 2: Targeted Remediation

Execute mode-matched remediation. After Components 1-2, heartbeat checkpoint:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
./src/heartbeat.sh --session-mode \
  --skill "study-session" --slug "<Primary Topic Title>" --topics "<topics>" \
  --depth 2 --domain "<domain>" \
  --understood "<verified>" --gaps "<failed>" \
  --turn-num <N> --status "in-progress" --obsidian-write \
  --topic-name "<Topic>" --understood-detail "<detail>" --gaps-detail "<detail>"
```

### Component 3: New Territory

If confusable pair exists: teach A (3 min) → teach B (3 min) → discriminating feature → 2 rapid-fire vignettes → discrimination question.

Run full RAG workflow on gap topic (`neuro-scaffold` default, `board-exam` if requested).

Consolidation question before Transfer: "What is the single most important takeaway and why does it matter clinically?"

### Component 4: Transfer Challenge

One scenario testing mastered concept in novel context.

```bash
# success
python3 src/knowledge_graph.py log_transfer --concept "<concept>" --topic "<topic>" --context "<new context>" --success
# failure (omit --success)
```

## Step 5: Session Summary

Component outcomes, resolved vs unresolved gaps, one-line insight, next-session priority.

Offer: 1. Save to Anki, 2. Another 30-min session, 3. End.

## Finalization (Silent)

Final heartbeat with `--status complete`, `--gap-details`, `--obsidian-write`. Write `Review Sessions/<Primary Topic Title>.md` with: components summary, atomic detail table (`Q# | Concept | Response | Assessment | Error Type | Correction`), session insight, next focus, vault links.

Post-session hook per §7. Do not narrate.

## Tone

Direct, efficient, high-yield. Acknowledge concrete improvement.
