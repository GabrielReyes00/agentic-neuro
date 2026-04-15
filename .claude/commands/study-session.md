---
name: study_session
description: Generates a prioritized 30-minute study session plan based on knowledge graph gaps, spaced review queue, error patterns, and transfer candidates. Triggers on "what should I study today", "generate a study session", "custom study plan", "study session", "plan my study", "30 minute study plan".
---

# Study Session Architect

Explicit user request only. Never proactively generated.

**Philosophy**: Deliberate practice — retrieval-first, error-targeted, interleaved, transfer as gold standard, adaptive difficulty.

---

## Step 0: ACGME Readiness Survey

Check ACGME Readiness on every invocation:

```bash
head -80 "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/ACGME Readiness.md" 2>/dev/null
```

If exists: extract domain coverage percentages, rank by lowest coverage (core domains first among ties: Brain Tumor, Critical Care, TBI, Vascular). Present top 3 with recommendation. Wait for user to choose domain, "general", or "skip". Store as `DOMAIN_FILTER` for gaps call.

---

## Step 0b: Session Continuity Check (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
  python3 src/knowledge_graph.py last_session_narrative --skill "study-session"
```

If non-null result:
- Read `next_session_strategy` — use it to shape Component 2 (Remediation) topic selection and mode
- Read `key_confusions_json` — if any entries exist, prioritize those concepts in the Recall Bridge
- Read `teaching_failures` — avoid repeating failed teaching approaches; try alternative modes from the Remediation Mode Routing table
- Open session with a 1-sentence continuity bridge: "Last session covered [topics]. Strategy: [strategy]. Picking up from there."

If null: proceed normally (first session for this skill).

---

## Step 1: Data Gathering

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
  echo "=== REVIEW_QUEUE ===" && python3 src/knowledge_graph.py review_queue --n 5 && \
  echo "=== GAPS ===" && python3 src/knowledge_graph.py gaps --top 5 [--rotation "DOMAIN_FILTER"] && \
  echo "=== TRANSFER ===" && python3 src/knowledge_graph.py transfer_candidates --n 3 && \
  echo "=== COGNITIVE_PATTERNS ===" && python3 src/knowledge_graph.py cognitive_patterns && \
  echo "=== CALIBRATION ===" && python3 src/knowledge_graph.py calibration_profile && \
  echo "=== DASHBOARD ===" && python3 src/knowledge_graph.py dashboard
```

Optional: if no DOMAIN_FILTER, check GCal for rotation context and re-run gaps with `--rotation`.

---

## Step 2: Adaptive Session Composition

### Component Matrix (30 min)

| # | Component | Time | Source | Mode | Skip If |
|---|---|---|---|---|---|
| 1 | **Recall Bridge** | 3 min | `review_queue` top 2 | Retrieval-first questions (no RAG) | queue empty |
| 2 | **Targeted Remediation** | 8 min | `gaps` with `error_type` | Mode matched to error type (see below) | no error_type concepts |
| 3 | **New Territory** | 12 min | Top gap (highest score, never_encountered/shallow) | Full RAG workflow | Never skipped |
| 4 | **Transfer Challenge** | 7 min | `transfer_candidates` | Bootcamp scenario in new context | no candidates |

**Cognitive Pattern Override**: If `cognitive_patterns` shows >=3 occurrences across >=2 topics → insert 5-min Process Intervention before Remediation: explain the pattern, teach process fix, 1-min drill.

**Calibration Awareness**: If `calibration_score` < 0.5 → add confidence estimation to Recall Bridge answers.

**Discrimination Training** (Component 3): If New Territory topic has a confusable pair → teach A (3 min), teach B (3 min), present discriminating feature with mnemonic, run 2 rapid-fire discrimination vignettes.

### Remediation Mode Routing

| error_type | Mode |
|---|---|
| `numerical_recall` | Rapid-fire fill-in-the-blank (no RAG) |
| `conceptual_confusion` | RAG `socratic-drill`, force single discriminating feature |
| `cross_contamination` | Board-exam vignette from `confusion_matrix.json` |
| `application_failure` | Focused bootcamp scenario with decision tension |
| `reasoning_gap` | RAG `neuro-scaffold`, step-by-step causal chain |

**Redistribution** when components skipped: reallocate time to remaining components (extend New Territory or add second topic).

---

## Step 3: Present the Plan

```
## Study Session Plan (30 minutes)

### 1. Recall Bridge (3 min)
- **Verify:** [concept] (from [topic], [X days] overdue)
- *Mode: Retrieval-first*

### 2. Targeted Remediation (8 min)
- **Target:** [concept] — [error_type] (missed [N]x)
- *Mode: [mode] — [1-sentence rationale]*

### 3. New Territory (12 min)
- **Topic:** [gap] — Domain: [domain]
- *Mode: RAG neuro-scaffold*

### 4. Transfer Challenge (7 min)
- **Test:** [concept] mastered in [original topic]
- **New Context:** [different domain scenario]

Approve, modify, or choose a starting component.
```

---

## Step 4: Execute on Approval

**Session timestamp (set once, reuse for all exchanges):**
```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```
Initialize a turn counter at 0. Increment before each `record-answer` call.

### Component 1: Recall Bridge
Ask open-ended questions, WAIT for answer. Evaluate. If incorrect: correct + 1-sentence why + follow-up verification. If both correct instantly → compress. If both wrong → extend + flag intervals.

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
Execute mode-matched teaching per the routing table above. After each user answer to a remediation question, log with `record-answer` as in Component 1.

**Heartbeat after Components 1+2** (silent): `heartbeat.sh --session-mode --skill "study-session" --obsidian-write`

### Component 3: New Territory
Full RAG workflow on gap topic. After delivery, ask: "What is the single most important thing you just learned, and why does it matter clinically?"

### Component 4: Transfer Challenge
Bootcamp scenario requiring mastered concept in new domain. Design so original context's surface features are absent — learner must identify relevant concept from clinical picture alone.

**After the learner answers, run both (silent):**

```bash
# Call 1 — Transfer outcome
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
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

---

## Step 5: Session Summary

```
## Session Complete

| Component | Outcome | Signal |
|---|---|---|
| Recall Bridge | 2/2 verified | Intervals reset |
| Remediation | [concept] — correct on 2nd attempt | Partially resolved |
| New Territory | [topic] covered | New topic logged |
| Transfer | [concept in new context] | Applied correctly |

**Session insight:** [One sentence about learner pattern]
*Next session priority: [preview]*
```

Offer: Save to Anki | Continue studying | End session.

### Session-End Logging (Silent)

1. Final heartbeat: `--status "complete" --obsidian-write`
2. Write full session log to `Review Sessions/<primary-topic-slug>.md` via Write tool:
   - Content: Components table, Atomic Topic Detail table, Session Insight, Next Focus, Related in This Vault
   - Metadata at bottom: date, skill, topic, outcome, tags
3. Cross-reference discovery per CLAUDE.md §7a
4. Post-Session Hook per CLAUDE.md §8

---

## Tone

Direct, efficient, structured. User's time is the most constrained resource. But acknowledge growth: "Last time you confused CSW and SIADH — you nailed the volume status distinction this time."
