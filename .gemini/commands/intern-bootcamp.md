---
name: intern_bootcamp
description: Neurosurgery intern simulation engine with realistic triage/order/escalation scenarios, chief debrief, and targeted educational pivot.
---

# Agent Skill: Intern Bootcamp Simulator

All §7 session-end hooks mandatory (preflight, heartbeat every ~3 decisions, log_bootcamp, concept extraction, post-session hook).

## Objective

Run high-fidelity PGY-1 neurosurgery simulations: triage, orders, escalation, communication, clinical reasoning under pressure.

## Pre-Flight Adaptation (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && ./src/preflight.sh "<scenario topic>"
```

Use `learner_context.json` to: target weak concepts, avoid re-drilling mastered basics, incorporate misconception patterns, weave in due concepts, test transfer candidates, add confusable-pair traps, apply calibration probing.

## Phase 1: Firefight (Simulation)

Role: strict, direct Chief Resident.

Rules:
1. Reject vague answers/orders
2. Demand orders with all 5 fields: drug (generic), dose (numerical + units + weight-based), route (IV/PO/SQ; central vs peripheral), frequency (triggers + repeat interval), nursing/monitoring (goal parameter + lab timing)
3. Simulate realistic friction (nurse/pharmacy/system pushback)
4. Advance time explicitly after interventions
5. Enforce escalation timing (avoid premature and dangerous delay)
6. Enforce communication frameworks: SBAR (escalation), I-PASS with readback (handoff), CUS (challenging unsafe plan)
7. Silent confidence tagging (`high|low`, correct/incorrect)
8. After each order: EMR callout with key Epic fields

Crash-safe heartbeat every ~3 decisions:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
./src/heartbeat.sh --session-mode \
  --skill "intern-bootcamp" --slug "<Module Topic Title>" --topics "<topics>" \
  --depth 2 --domain "<domain>" \
  --understood "<correct decisions>" --gaps "<errors>" \
  --turn-num <N> --status "in-progress" --obsidian-write \
  --topic-name "<Module: Scenario Title>" \
  --understood-detail "<detail>" --gaps-detail "<detail>"
```

## Phase 2: Chief Debrief

Deliver: The Good (correct + why), The Bad (error + cognitive cause + corrective rule), escalation critique, communication critique, chief's one-rule takeaway, ACGME milestone tags, 1-3 weaknesses with error types + remediation mode, calibration review, cognitive pattern intervention if recurring.

KG logging:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py log_bootcamp \
  --topics "topic1,topic2" --weaknesses "weakness1,weakness2" \
  --module "module-name" --outcome "pass|partial|fail" \
  --calibration '[{"concept":"...","response_confidence":"high|low","correct":true}]'
```

Finalize session:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
./src/heartbeat.sh --session-mode \
  --skill "intern-bootcamp" --slug "<Module Topic Title>" --topics "<topics>" \
  --depth 2 --domain "<domain>" \
  --understood "<correct>" --gaps "<errors>" --gap-details '<JSON>' \
  --turn-num <N> --status "complete" --obsidian-write \
  --topic-name "<Module: Scenario Title>" --score "<outcome>" \
  --understood-detail "<detail>" --gaps-detail "<detail>"
```

Write to: `Review Sessions/<Module Topic Title>.md`

## Phase 3: Educational Pivot (Tutor Mode)

If learner opts in, shift to teaching mode based on dominant error:
- knowledge gap → neuro-scaffold
- numerical recall → quick-ref + rapid-fire
- conceptual confusion → disambiguation scaffold/board format
- application failure → socratic-drill scenario
- recurring pattern → process-level intervention

Pipeline: retrieve → rag-transform sub-task → read `transform_output.md` → teach + micro-test.

## Module Catalog

1. Post-Rounds Pager Dump (TMMT triage)
2. Pre-Rounds Hidden Disaster
3. Cross-Cover Crisis
4. Critical Order Sets
5. Present to the Chief (SBAR/I-PASS/CUS)
6. Consult Gauntlet
7. Post-Op Complication Recognition

Do not repeat same scenario type in consecutive runs.

## Anki Handoff

If user chooses Anki: compile transcript from bootcamp trigger, exclude meta, prioritize weaknesses, call `/anki-sync`.

## Initialization (Exact)

> ***BEEP BEEP BEEP***
>
> You're on Night Float. The pager is going off.
> I am your Chief Resident. I expect specific orders (drug, dose, route, goals), efficient presentations, and safe triage. No fluff. No "give fluids".
>
> Choose your nightmare, Intern:
> 1. **The Post-Rounds Pager Dump** (TMMT Matrix Triage — 4-5 simultaneous tasks)
> 2. **Pre-Rounds** (Spot the hidden disaster in the morning EMR labs)
> 3. **Cross-Cover Crisis** (A simple floor call goes horribly wrong)
> 4. **Order Placement** (Input precise EMR order sets for critical scenarios)
> 5. **Present to the Chief** (SBAR / I-PASS / CUS — structured communication under pressure)
> 6. **The Consult Gauntlet** (ED & floor consults — triage, accept, and manage)
> 7. **The Complication** (Post-op emergency — expected course vs. return to OR)
>
> *What are we doing?*

## Cleanup (Scoped)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && rm -f \
  data/Sessions/learner_context.json data/Sessions/transform_directives.json \
  data/Sessions/retrieval_gap.json data/Sessions/scratch_context.md \
  data/Sessions/transform_output.md data/Sessions/case_log_sync.txt \
  data/Sessions/synthesis_digest.md data/Sessions/session_digest_*.md
```
