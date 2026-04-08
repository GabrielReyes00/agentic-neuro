---
name: study_session
description: Generates a prioritized 30-minute study session plan based on knowledge graph gaps, spaced review queue, error patterns, and transfer candidates. Triggers on "what should I study today", "generate a study session", "custom study plan", "study session", "plan my study", "30 minute study plan".
---

# Agent Skill: Study Session Architect

## When This Skill Triggers

User says things like: "what should I study today", "generate a study session", "custom study plan", "study session", "plan my study", "30 minute study plan", "what do I need to review"

This skill is ONLY triggered on explicit user request. The system never proactively generates study sessions.

---

## Pedagogical Philosophy

**Deliberate practice protocol** — strengthen weak points and extend the knowledge frontier. Core principles:
1. **Retrieval-first** — recall before review (Recall Bridge comes first)
2. **Error-targeted** — remediate specific wrong concepts using mode matched to error type, not broad re-study
3. **Interleaved** — mix recall, remediation, new learning, transfer to strengthen discrimination
4. **Transfer = gold standard** — a concept isn't "known" until applied in novel context
5. **Adaptive difficulty** — compress easy recalls, scaffold hard territory

---

## Step 0: ACGME Readiness Survey

Before gathering knowledge graph data, check whether the user would benefit from an ACGME-guided domain focus. This runs on EVERY study session invocation.

Read the ACGME Readiness file:

```bash
head -80 "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/ACGME Readiness.md" 2>/dev/null
```

If the file does not exist (empty or missing output): skip Step 0 silently and proceed to Step 1.

If the file exists:
1. Extract the domain coverage percentages from the `## Domain Coverage` section (the `N touched (X%)` values per domain heading).
2. Rank domains by lowest coverage_pct first. Among tied coverage: core domains (Brain Tumor, Critical Care, TBI, Vascular) before others. Among remaining ties: prefer a domain not prominently featured in the last session's review file (check `data/Sessions/last_session_narrative.json` if present).
3. Select the top 3 domains by this ranking.
4. Present to the user before proceeding:

> "Based on your ACGME Readiness for PGY-1, your coverage gaps are:
>
> 1. [Domain A] ([Milestone]): [X]% -- [N] of [T] PGY-1 topics studied
> 2. [Domain B] ([Milestone]): [X]% -- [N] of [T] PGY-1 topics studied
> 3. [Domain C] ([Milestone]): [X]% -- [N] of [T] PGY-1 topics studied
>
> I recommend [Domain A] because [1-sentence rationale — e.g., 'it is a core competency with zero coverage and the most PGY-1 topics remaining'].
>
> Would you like to focus on [Domain A] today, choose another domain, or build a gap-based session without domain filtering?"

Wait for the user's response. Accept natural language:
- Domain name ("Brain Tumor", "Critical Care", "Vascular", etc.) → set `DOMAIN_FILTER="[domain]"` and use as `--rotation "[domain]"` in Step 1's gaps call
- "General" / "no preference" / "anything" / "surprise me" → proceed to Step 1 without domain filter
- "Skip" / "no" → proceed to Step 1 without domain filter

---

## Step 1: Data Gathering

Run all knowledge graph queries in a single bash call. If `DOMAIN_FILTER` was set in Step 0, use it in the gaps call:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
  echo "=== REVIEW_QUEUE ===" && python3 src/knowledge_graph.py review_queue --n 5 && \
  echo "=== GAPS ===" && python3 src/knowledge_graph.py gaps --top 5 [--rotation "DOMAIN_FILTER if set"] && \
  echo "=== TRANSFER ===" && python3 src/knowledge_graph.py transfer_candidates --n 3 && \
  echo "=== COGNITIVE_PATTERNS ===" && python3 src/knowledge_graph.py cognitive_patterns && \
  echo "=== CALIBRATION ===" && python3 src/knowledge_graph.py calibration_profile && \
  echo "=== DASHBOARD ===" && python3 src/knowledge_graph.py dashboard
```

Concretely:
- If `DOMAIN_FILTER` is set (e.g., "Brain Tumor"): `python3 src/knowledge_graph.py gaps --top 5 --rotation "Brain Tumor"`
- If no domain filter: `python3 src/knowledge_graph.py gaps --top 5`

**Optional rotation context:** If Step 0 did not produce a DOMAIN_FILTER, check GCal for current rotation:
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
- Log: `python3 src/knowledge_graph.py log_pattern --type "[error_type]_addressed" --description "Process intervention delivered" --evidence "study session [date]"`

### Calibration Awareness

If the `calibration_profile` shows a `calibration_score` below 0.5 or has `domain_alerts`, adapt the session:
- In the **Recall Bridge**, after each answer, ask: "How confident are you in that answer, 1-10?" Then reveal the correct answer. The gap between their stated confidence and their accuracy IS the teaching moment.
- In the **Session Summary**, add a calibration line: "Your confidence matched your accuracy on X/Y items this session."

### Discrimination Training Format (for Component 3)

When a New Territory topic has a confusable pair in `confusion_matrix.json`:
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
| `cross_contamination` | Board-exam vignette | Read `data/confusion_matrix.json`, generate a vignette where the distractor IS the contaminating concept. | The error is applying a correct rule to the wrong context — test discrimination, not recall |
| `application_failure` | Focused scenario | Generate a bootcamp-style scenario scoped to one concept. The scenario must create decision tension. | The knowledge exists but is inert — it needs to be activated under pressure |
| `reasoning_gap` | Scaffold walkthrough | Run RAG with `neuro-scaffold` template, focus on the Build layers that reconstruct the causal chain step-by-step. | The learner skipped a link in the chain — rebuild the full chain with explicit dependencies |

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
5. Log outcome (two calls — activity feed + concept mastery):

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
# Activity feed signal (real-time, feeds Dashboard)
python3 src/knowledge_graph.py log_event --topic "topic" --source "study-session" \
  --signal-type "<correct_recall|incorrect_recall|partial_recall>" --depth 2 --category "<domain>" && \
# Concept mastery update
python3 src/knowledge_graph.py log_study --topics "topic" --understood "concept" --depth 2
# If incorrect — MUST include gap-details with specific error_type and misconception:
# python3 src/knowledge_graph.py log_study --topics "topic" --gaps "concept" --gap-details '[{"concept":"concept","error_type":"<type>","misconception":"<what user specifically got wrong>","remediation":"<what to review>"}]' --depth 2
```

**Logging quality rule**: Never log `--gaps` without `--gap-details`. Never use vague misconceptions like "user was unsure" — describe the specific incorrect belief or missing reasoning step.

**Difficulty calibration:** If both recall questions are answered instantly and correctly, note this and compress Component 1. If both are wrong, extend to 3 more questions from the review queue and flag that spaced review intervals may be too long.

### Component 2: Targeted Remediation

Based on the error_type, execute the matched mode:

- **`numerical_recall` (drill):** Present 3-5 fill-in-the-blank questions on exact values (doses, thresholds, timing windows). After each answer, state the correct value AND the clinical consequence of getting it wrong ("Mannitol is 1 g/kg, not 0.5 — at 0.5 you won't generate enough osmotic gradient to reduce ICP meaningfully"). No RAG needed.
- **`conceptual_confusion` (forced disambiguation):** Run the full RAG workflow with `socratic-drill` template. The drill must force the learner to identify the single feature that discriminates the two confused concepts. End with: "If you could only check ONE thing to tell these apart, what would it be?"
- **`cross_contamination` (board-exam vignette):** Read `data/confusion_matrix.json`, generate a board-style vignette where the close distractor IS the contaminating concept. The learner must choose correctly AND explain why the distractor is wrong.
- **`application_failure` (scenario):** Generate a focused bootcamp-style scenario (Phase 1 mechanics from `intern-bootcamp` but scoped to a single concept, ~5 minutes). The scenario must create decision tension where the correct action requires applying the concept under time pressure.
- **`reasoning_gap` (scaffold):** Run RAG with `neuro-scaffold` template, then walk through the causal chain step-by-step. At each link, ask the learner to predict the next step before revealing it.

Log outcomes after each remediation attempt using `log_study`.

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

Execute the full RAG workflow (Step 0-5 from CLAUDE.md) on the selected gap topic. Use `neuro-scaffold` template by default, or `board-exam` if the user asked for board review.

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

**After heartbeat completes**, use the Write tool to REPLACE the checkpoint-style content with the full session log format:

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

After the Obsidian write, run the Universal Post-Session Hook (see shared-system.md) to update Dashboard.md.

---

## Tone

Direct and efficient. This is a structured session, not a casual conversation. Present the plan cleanly, execute briskly, summarize at the end. The user's time is the most constrained resource — treat every minute as valuable.

But efficiency does not mean coldness. When the learner gets something right that they previously got wrong, acknowledge the growth: "Last time you confused CSW and SIADH — you nailed the volume status distinction this time. That's progress." Positive reinforcement of improvement is as important as error correction.
