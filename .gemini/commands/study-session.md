---
name: study_session
description: Generates a prioritized 30-minute study session plan based on knowledge graph gaps, spaced review queue, error patterns, and transfer candidates. Triggers on "what should I study today", "generate a study session", "custom study plan", "study session", "plan my study", "30 minute study plan".
---

# Agent Skill: Study Session Architect

## MANDATORY BACKGROUND HOOKS

Execute these at every trigger point. None are narrated to the user.

| Trigger | Action | Skip condition |
|---------|--------|----------------|
| Before presenting the session plan | Single bash call: review_queue + gaps + transfer + cognitive_patterns + calibration + dashboard | Never skip |
| After each Component 1 and 2 learner response | `./src/log_turn.sh` (single call writes both tables) | Never skip |
| After Component 1 completes | `heartbeat.sh --session-mode ... --status "in-progress" --turn-num 1` | Never skip |
| After Component 2 completes | `heartbeat.sh --session-mode ... --status "in-progress" --turn-num 2` | Never skip |
| After Transfer Challenge | `log_transfer` (success or failure) | Skip only if Component 4 was skipped entirely |
| After presenting session summary | `heartbeat.sh --session-mode ... --status "complete"` + Obsidian file write | Never skip |
| After Obsidian write | Universal Post-Session Hook (apply_decay + dashboard + gaps) | Never skip — FINAL mandatory step |

**Execution rule:** Run each background step at the trigger point, verify success, then continue the session. The session is not complete until the post-session hook finishes.

---

## When This Skill Triggers

User says things like: "what should I study today", "generate a study session", "custom study plan", "study session", "plan my study", "30 minute study plan", "what do I need to review"

This skill is ONLY triggered on explicit user request. The system never proactively generates study sessions.

---

## Pedagogical Philosophy

A study session is not a content dump — it is a **deliberate practice protocol**. The goal is not "cover topics" but "strengthen specific weak points and extend the frontier of knowledge." Every minute of the session must have a clear learning objective and a measurable outcome.

Principles:
1. **Retrieval practice over re-reading.** Start with recall, not review. The learner should attempt to produce the answer before seeing it. This is why the Recall Bridge comes first.
2. **Error-targeted remediation over broad review.** Studying a topic "again" is low-yield. Studying the specific concept that was wrong, using a mode matched to the error type, is high-yield.
3. **Interleaving over blocking.** The 4-component structure deliberately mixes recall, remediation, new learning, and transfer — this interleaving strengthens discrimination and prevents the illusion of fluency.
4. **Transfer testing as the gold standard.** A concept is not "known" until it can be applied in a novel context. The Transfer Challenge is the most important validation signal in the session.
5. **Difficulty calibration.** If recall is too easy, compress it. If new territory is too hard, scaffold more. The session adapts to the learner's state, not a fixed curriculum.

---

## Step 1: Data Gathering

Run all knowledge graph queries in a single bash call:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
  echo "=== REVIEW_QUEUE ===" && python3 src/knowledge_graph.py review_queue --n 5 && \
  echo "=== GAPS ===" && python3 src/knowledge_graph.py gaps --top 5 && \
  echo "=== TRANSFER ===" && python3 src/knowledge_graph.py transfer_candidates --n 3 && \
  echo "=== COGNITIVE_PATTERNS ===" && python3 src/knowledge_graph.py cognitive_patterns && \
  echo "=== CALIBRATION ===" && python3 src/knowledge_graph.py calibration_profile && \
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
| 1 | **Recall Bridge** | 3 min | `review_queue` top 2 concepts | Retrieval-first verification questions (no RAG needed) | review_queue is empty |
| 2 | **Targeted Remediation** | 8 min | Concepts from `gaps` with `error_type` populated, or `remediation_directives` from a context check | Mode matched to error_type (see below) | No concepts with error_type in output |
| 3 | **New Territory** | 12 min | Top gap topic from `gaps` (highest gap_score, never_encountered or shallow) | Full RAG workflow with `neuro-scaffold` or `board-exam` template. **If the topic has a confusable pair** (check `confusable_pairs --topic "topic"`), automatically pull in both members and use discrimination format (see below). | Never skipped — always available |
| 4 | **Transfer Challenge** | 7 min | Top candidate from `transfer_candidates` | Bootcamp-style scenario testing the mastered concept in a new clinical context | No transfer candidates |

### Cognitive Pattern Override

**Before composing the session**, check the `cognitive_patterns` output. If a process-level cognitive error pattern is detected (≥3 occurrences across ≥2 topics), **insert a 5-minute Process Intervention** as Component 2a, before or replacing Targeted Remediation:
- This is NOT content teaching — it is a meta-cognitive intervention about the thinking error itself
- Explain the pattern: "You've made [error_type] errors [N] times across [topics]. This isn't about any one topic — it's about how you think."
- Teach the process fix: Use the `intervention_hint` from the `cognitive_patterns` output
- Practice with a 1-minute drill: Present a quick scenario requiring the learner to apply the process fix
- Log (background, no narration):
  ```bash
  cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
  python3 src/knowledge_graph.py log_pattern --type "[error_type]_addressed" --description "Process intervention delivered" --evidence "study session [date]"
  ```

### Calibration Awareness

If the `calibration_profile` shows a `calibration_score` below 0.5 or has `domain_alerts`, adapt the session:
- In the **Recall Bridge**, silently tag each response with confidence level inferred from linguistic cues (declarative statements = high confidence; hedging/qualifiers/"I think"/"maybe" = low confidence). Do NOT ask the user to rate their confidence numerically.
- When a high-confidence answer is wrong: address it explicitly — "You sounded certain on that — the correct answer is X because Y. The feeling of certainty and actual correctness are two different things."
- When a low-confidence answer is right: reinforce the reasoning — "That was right, and your reasoning was sound. Trust the process — you derived it correctly."
- In the **Session Summary**, add a calibration line based on your silent tags: "You were most confident on [concepts] — accuracy there was [match/mismatch]."

### Discrimination Training Format (for Component 3)

When a New Territory topic has a confusable pair (check via the KG command below):
1. Teach concept A (compressed — key features only, 3 min)
2. Teach concept B (compressed — key features only, 3 min)
3. Present the **single discriminating feature** that separates them with a mnemonic or rule
4. **Discrimination drill** (3 min): Present 2 rapid-fire vignettes — one where surface features suggest A but the discriminating feature points to B, and vice versa
5. State: "Whenever you see [shared feature], your first question should be: [discriminating question]?"

To find confusable pairs for a topic:
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py confusable_pairs --topic "topic name"
```

### Remediation Mode Routing (Component 2)

| error_type | Mode | Execution | Teaching Principle |
|---|---|---|---|
| `numerical_recall` | Rapid-fire quiz | Present fill-in-the-blank questions on exact values. No RAG needed. | Automaticity through repetition — these facts need to be instant-access, not derivable |
| `conceptual_confusion` | Forced disambiguation | Run RAG with `socratic-drill` template. Force a side-by-side comparison, isolating the single discriminating feature. | The learner's schema has the two concepts entangled — the fix is explicit separation at the point of confusion |
| `cross_contamination` | Board-exam vignette | Run `python3 src/knowledge_graph.py confusable_pairs --topic "topic name"` to get the contaminating concept, then generate a vignette where the distractor IS that concept. | The error is applying a correct rule to the wrong context — test discrimination, not recall |
| `application_failure` | Focused scenario | Generate a bootcamp-style scenario scoped to one concept. The scenario must create decision tension. | The knowledge exists but is inert — it needs to be activated under pressure |
| `reasoning_gap` | Scaffold walkthrough | Run RAG with `neuro-scaffold` template, focus on the Build layers that reconstruct the causal chain step-by-step. | The learner skipped a link in the chain — rebuild the full chain with explicit dependencies |

### Redistribution Rules (Skip Targets)

When a skip condition fires, apply the redistribution and continue to the next step:

| Skip Condition | SKIP THIS | Redistribution |
|----------------|-----------|----------------|
| review_queue is empty | Component 1 (Recall Bridge) | SKIP TO Component 2 — New Territory gets +3 min (now 15 min) |
| No gap entries with error_type | Component 2 (Remediation) | SKIP TO Component 3 — add second New Territory topic or extend primary to 20 min |
| No transfer_candidates | Component 4 (Transfer) | SKIP TO Step 5 (Summary) — New Territory gets +7 min (now 19 min) |
| Only New Territory available | Components 1, 2, 4 | SKIP TO single deep 30-min RAG session on top gap |

---

## Step 3: Present the Plan

Format the session plan as a structured table for user review:

```
## Study Session Plan (30 minutes)
*[Rotation context if detected, e.g., "Vascular rotation — prioritizing vascular gaps"]*

### 1. Recall Bridge (3 min)
- **Verify:** [concept 1] (from [topic], [X days] overdue)
- **Verify:** [concept 2] (from [topic], [X days] overdue)
- *Mode: Retrieval-first questions — you answer before I show the answer*

### 2. Targeted Remediation (8 min)
- **Target:** [concept] — [error_type_label] issue (missed [N]x)
- *Mode: [drill/socratic/disambiguation/scenario/scaffold]*
- *Why this mode: [1-sentence rationale linking error type to learning mode]*

### 3. New Territory (12 min)
- **Topic:** [gap topic name] — Domain: [domain]
- *Mode: RAG → neuro-scaffold*
- *Why: [gap_type explanation — never encountered / decaying / shallow]*

### 4. Transfer Challenge (7 min)
- **Test:** [concept] (mastered in [original topic/domain])
- **New Context:** [suggested clinical context from a different domain]
- *Mode: Focused scenario — same concept, different pathology*

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

**Retrieval-first protocol:** Ask the verification question and WAIT for the learner to answer before revealing the correct response. Do not present the question and answer together — that's re-reading, not recall practice.

For each question:
1. Ask the question (open-ended, not multiple choice — force generation, not recognition)
2. Wait for the learner's response
3. Evaluate: correct, partially correct, or incorrect
4. If incorrect: provide the correct answer with a 1-sentence "Why" — then immediately ask one follow-up question to verify the correction landed
5. Log outcome (single call — writes activity feed + concept mastery):

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
./src/log_turn.sh --topic "topic" --source "study-session" \
  --signal-type "<correct_recall|incorrect_recall|partial_recall>" --depth 2 --category "<domain>" \
  --topics "topic" --understood "concept"
# If incorrect — include gap-details with specific error_type, error_process, root_cause, and misconception:
# ./src/log_turn.sh --topic "topic" --source "study-session" --signal-type "incorrect_recall" --depth 2 --category "<domain>" --topics "topic" --gaps "concept" --gap-details '[{"concept":"concept","error_type":"<type>","error_process":"<process>","misconception":"<what user specifically got wrong>","root_cause":"<why they got it wrong>","remediation":"<what to review>"}]'
```

**Logging quality rule**: Never log `--gaps` without `--gap-details`. Never use vague misconceptions like "user was unsure" — describe the specific incorrect belief or missing reasoning step.

**Difficulty calibration:** If both recall questions are answered instantly and correctly, note this and compress Component 1. If both are wrong, extend to 3 more questions from the review queue and flag that spaced review intervals may be too long.

### Component 2: Targeted Remediation

Based on the error_type, execute the matched mode:

- **`numerical_recall` (drill):** Present 3-5 fill-in-the-blank questions on exact values (doses, thresholds, timing windows). After each answer, state the correct value AND the clinical consequence of getting it wrong ("Mannitol is 1 g/kg, not 0.5 — at 0.5 you won't generate enough osmotic gradient to reduce ICP meaningfully"). No RAG needed.
- **`conceptual_confusion` (forced disambiguation):** Run the full RAG workflow with `socratic-drill` template. The drill must force the learner to identify the single feature that discriminates the two confused concepts. End with: "If you could only check ONE thing to tell these apart, what would it be?"
- **`cross_contamination` (board-exam vignette):** Run `python3 src/knowledge_graph.py confusable_pairs --topic "topic name"` (full prefix required) to retrieve the contaminating concept from the KG. Generate a board-style vignette where the close distractor IS the contaminating concept. The learner must choose correctly AND explain why the distractor is wrong.
- **`application_failure` (scenario):** Generate a focused bootcamp-style scenario (Phase 1 mechanics from `intern-bootcamp` but scoped to a single concept, ~5 minutes). The scenario must create decision tension where the correct action requires applying the concept under time pressure.
- **`reasoning_gap` (scaffold):** Run RAG with `neuro-scaffold` template, then walk through the causal chain step-by-step. At each link, ask the learner to predict the next step before revealing it.

Log outcomes after each remediation attempt using `log_turn.sh` (preferred) or `log_study` when no activity signal is needed.

**Crash-safe heartbeat (silent — after Component 1 and Component 2):** After completing each component, fire a checkpoint heartbeat to ensure progress survives unexpected exit:
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
./src/heartbeat.sh --session-mode \
  --skill "study-session" --slug "<primary-topic-slug>" --topics "<topics>" \
  --depth 2 --domain "<domain>" \
  --understood "<verified concepts so far>" --gaps "<failed concepts so far>" \
  --turn-num <component_number> --status "in-progress" --obsidian-write \
  --topic-name "<Primary Topic Name>" \
  --understood-detail "<understood concepts detail>" \
  --gaps-detail "<gaps detail>"
```
Do not narrate this to the user.

### Component 3: New Territory

Execute the full RAG workflow (Step 0-5 from rag-workflow.md) on the selected gap topic. Use `neuro-scaffold` template by default, or `board-exam` if the user asked for board review.

**Engagement check:** After delivering the material, do not just move on. Ask one calibration question: "What is the single most important thing you just learned, and why does it matter clinically?" This forces the learner to consolidate, and their answer reveals whether they extracted the right takeaway.

### Component 4: Transfer Challenge

Generate a bootcamp scenario that requires the mastered concept in a new domain context. Keep it focused — single-concept, ~7 minutes.

**Design the scenario so the original context's surface features are absent.** The learner should not recognize this as a "test of concept X" — they should have to identify the relevant concept from the clinical picture alone. This tests whether the knowledge is generalizable or context-locked.

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
| Recall Bridge | 2/2 verified | Intervals reset |
| Remediation | nimodipine dosing — correct on 2nd attempt | Partially resolved — will re-test next session |
| New Territory | Cerebral venous sinus thrombosis — covered | New topic logged |
| Transfer | ICP management in post-op tumor — applied correctly | Transfer validated |

**Session insight:** [One sentence about the learner's overall pattern — e.g., "Your recall is solid but application under time pressure remains the weak link — next session will weight scenarios more heavily."]

*Next session priority: [brief preview of what would be prioritized based on today's outcomes]*
```

Then offer:
> *"Would you like to:*
> 1. **Save to Anki** — Create cards for everything covered in this session
> 2. **Continue studying** — Generate another 30-minute session
> 3. **End session**"

### Obsidian Session Log (Silent — after session summary)

After presenting the session summary, finalize the crash-safe session file by running the completion heartbeat:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
./src/heartbeat.sh --session-mode \
  --skill "study-session" --slug "<primary-topic-slug>" --topics "<topics>" \
  --depth 2 --domain "<domain>" \
  --understood "<all verified concepts>" --gaps "<all failed concepts>" \
  --gap-details '<gap-details JSON>' \
  --turn-num 4 --status "complete" --obsidian-write \
  --topic-name "<Primary Topic Name>" --score "<N/N (pct%)>" \
  --understood-detail "<understood detail>" \
  --gaps-detail "<gaps detail>"
```

This finalizes the `Review Sessions/<primary-topic-slug>.md` file that was incrementally built via checkpoint heartbeats during the session. The last `IN-PROGRESS` status is replaced with `COMPLETE` and the full session summary is appended.

**After heartbeat completes**, use the file write tool to REPLACE the checkpoint-style content with the full session log format:

**File**: `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Review Sessions/<primary-topic-slug>.md`

**Naming rules:**
- Filename is `<primary-topic-slug>.md` — lowercase, underscores, no dates, no skill prefix
- Topic slug derived from the dominant topic covered (e.g., `pcoma_fetal_variant.md`)
- **NO EMOJIS anywhere in the file**

```markdown
---
date: YYYY-MM-DD
skill: "study-session"
topic: "comma-separated topics covered"
outcome: "pass|partial|fail"
tags:
  - type/session
  - skill/study-session
  - domain/<domain>
  - source/agent
---
# Study Session — <Primary Topic Name>

## Components
| Component | Topic | Outcome |
|-----------|-------|---------|
| Recall Bridge | [concepts verified] | N/N verified |
| Remediation | [concept + error_type] | Resolved / Partially resolved / Unresolved |
| New Territory | [gap topic] | Covered |
| Transfer | [concept in new context] | Applied correctly / Failed |

## Atomic Topic Detail
| Q# | Concept | User Response (Summary) | Assessment | Error Type | Correction Delivered |
|----|---------|------------------------|------------|-----------|---------------------|
| 1 | <concept> | <what they said> | correct/partial/incorrect | -- or <type> | -- or <1-sentence fix> |

## Session Insight
[One sentence about the learner's overall pattern from the session summary]

## Next Focus
- [Wikilinked recommendation if matching vault content exists]

## Related in This Vault
[Wikilinks to matching Reports/, Study Material/, Concepts/ content]
```

**Cross-reference discovery:** Before writing, check for matching vault content:
```bash
ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/"*.md "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/"*.md 2>/dev/null
```

Wikilink Next Focus recommendations to matching vault content where it exists (e.g., `[[Reports/topic_slug|Topic Name]]` or `[[Concepts/Note Name]]`).

**INDEX update** is handled by heartbeat.sh `--obsidian-write`. Do not duplicate.

Do not narrate this write to the user.

### Post-Session Hook (Silent)

After the Obsidian write, run the Universal Post-Session Hook (see GEMINI.md) to update Dashboard.md.

---

## Tone

Direct and efficient. This is a structured session, not a casual conversation. Present the plan cleanly, execute briskly, summarize at the end. The user's time is the most constrained resource — treat every minute as valuable.

But efficiency does not mean coldness. When the learner gets something right that they previously got wrong, acknowledge the growth: "Last time you confused CSW and SIADH — you nailed the volume status distinction this time. That's progress." Positive reinforcement of improvement is as important as error correction.
