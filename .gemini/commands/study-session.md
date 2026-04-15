---
name: study_session
description: Adaptive 30-minute study session generated from KG gaps, concept review queue, patterns, and transfer candidates.
---

# Agent Skill: Study Session Architect

All §7 session-end hooks mandatory (`record-answer` after Components 1-2, heartbeat checkpoints, log_transfer, post-session hook).

## Triggering

Use only on explicit user request for study planning/session execution.

## Step 0b: Session Continuity Check (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
  python3 src/knowledge_graph.py last_session_narrative --skill "study-session"
```

If non-null result:
- Read `next_session_strategy` — shape Component 2 (Remediation) topic selection and mode
- Read `key_confusions_json` — prioritize those concepts in the Recall Bridge
- Read `teaching_failures` — avoid repeating failed approaches; try alternative modes
- Open with a 1-sentence continuity bridge: "Last session covered [topics]. Strategy: [strategy]. Picking up from there."

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

**Session timestamp (set once, reuse for all exchanges):**
```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```
Initialize a turn counter at 0. Increment before each `record-answer` call.

### Component 1: Recall Bridge

Open recall question → wait → evaluate → if wrong: correction + verification follow-up.

**Per-answer memory logging (silent, after each user answer):**
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/memory_orchestrator.py record-answer \
  --session-ts "$SESSION_TS" --turn <N> --skill "study-session" \
  --topic "<topic>" --concept "<specific concept tested>" \
  --question "<your question, verbatim>" \
  --answer "<user's answer, verbatim or close paraphrase>" \
  --correct <0|1|2> \
  [--correction "<your correction/explanation if incorrect>"] \
  [--error-type "<type>"] [--misconception "<specific wrong belief>"] \
  [--root-cause "<why>"] [--remediation "<what should fix it>"] \
  [--teaching-approach "<approach used>"] \
  [--depth <N>] [--domain "<domain>"] [--response-confidence "high|low"]
```
Correctness routing: correct with no hints = `--correct 2` | right direction but missing key details = `--correct 1` | wrong answer or misconception = `--correct 0`. Capture the ACTUAL question and answer. For breakthroughs, add `--breakthrough --insight "<what clicked>"`.

### Component 2: Targeted Remediation

Execute mode-matched remediation. After each user answer to a remediation question, log with `record-answer` as in Component 1. After Components 1-2, heartbeat checkpoint:

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

**After the learner answers, run both (silent):**

```bash
# Call 1 — Transfer outcome
python3 src/knowledge_graph.py log_transfer --concept "<concept>" --topic "<topic>" \
  --context "<new clinical context>" [--success]

# Call 2 — Active answer memory content
python3 src/memory_orchestrator.py record-answer \
  --session-ts "$SESSION_TS" --turn <N> --skill "study-session" \
  --topic "<topic>" --concept "<concept in new context>" \
  --question "<transfer scenario presented>" \
  --answer "<learner's response>" \
  --correct <0|1|2> \
  [--correction "<if failed>"] [--error-type "<type>"] \
  [--teaching-approach "transfer-validation"] [--domain "<domain>"]
```

## Step 5: Session Summary

Component outcomes, resolved vs unresolved gaps, one-line insight, next-session priority.

Offer: 1. Save to Anki, 2. Another 30-min session, 3. End.

## Finalization (Silent)

Final heartbeat with `--status complete`, `--gap-details`, `--obsidian-write`. Write `Review Sessions/<Primary Topic Title>.md` with: components summary, atomic detail table (`Q# | Concept | Response | Assessment | Error Type | Correction`), session insight, next focus, vault links.

Post-session hook per §7. Do not narrate.

## Tone

Direct, efficient, high-yield. Acknowledge concrete improvement.
