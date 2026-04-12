---
name: rag_workflow
description: Full textbook-grounded RAG workflow with retrieval, transform, gap-check, Socratic follow-up, and learning-state logging.
---

# RAG Knowledge Workflow

Use for explicit textbook/database lookup requests. Do not auto-trigger for general clinical questions.

Pipeline: Assess → Retrieve → Transform → Gap Check → Present → Log → Finalize

All §7 session-end hooks mandatory (preflight, log_turn after every Gym response, heartbeat checkpoints, concept extraction, post-session hook).

## Step 0: Pre-Flight + Directives (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && ./src/preflight.sh "query"
```

Read: `learner_context.json`, `transform_directives.json`, `case_log_sync.txt`. New case logs → sync per GEMINI.md.

## Step 1: Complexity Assess

Simple single-concept → one `compare`. Multi-axis/comparison → `compare_multi` with up to 3 subqueries.

## Step 2: Retrieve

Frontier gating: include for guidelines/trials/devices/outcomes, skip for foundational anatomy/pathophys.

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/frontier_search.py "query" && python3 src/lance_retriever.py compare "query"
# Without frontier: omit frontier_search.py
# Complex: use compare_multi "sq1" "sq2" "sq3"
```

## Step 3: Transform (Sub-task)

Template by intent: `neuro-scaffold` (default) | `board-exam` | `quick-ref` | `socratic-drill` | `textbook-chapter`

Delegate with: QUERY, TEMPLATE, CONTEXT_PATH, LEARNER_CONTEXT_PATH, DIRECTIVES_PATH. Read only `transform_output.md` afterward.

## Step 3.5: Gap Check

Read `retrieval_gap.json`:
- `has_gap=false` → continue
- `has_gap=true` → one follow-up retrieval with `--append`, re-run transform as integration pass

## Step 3.75: Web Evidence Gap (User-Gated)

Only for unresolved non-local gaps. Deliver synthesis first, then append one-line optional evidence-gap prompt.

## Step 3.8: Learner Context Adaptation

| Condition | Behavior |
|---|---|
| Prior errors on this topic | Target specific gap, not generic re-teach |
| `anki_struggling` alert | Re-anchor before advancing |
| `never_encountered` | Start from first principles |
| Topic in review queue | Include Recall Bridge verification |
| `cross_contamination_prone` | Trigger disambiguation pass |
| Transfer candidate | Run `log_transfer` after learner responds |

## Step 4: Present

Read only `transform_output.md`. Deliver synthesis. Handle follow-up/Gym directly. Recall Bridge: include only when naturally connected, prefer due concepts from spaced verification.

## Gym Follow-Up + Logging

After every significant Gym response:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
./src/log_turn.sh --topic "<topic>" --source "rag" \
  --signal-type "<correct_recall|partial_recall|incorrect_recall>" --depth <N> --category "<domain>" \
  --topics "<topic>" --understood "<concept if correct>" \
  --gap-details '[{"concept":"...","error_type":"...","error_process":"...","misconception":"...","root_cause":"...","remediation":"..."}]'
```

Then heartbeat:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
./src/heartbeat.sh --session-mode \
  --skill "rag-workflow" --slug "<Topic Title>" --topics "<topics>" \
  --depth <N> --domain "<domain>" \
  --understood "<understood>" --gaps "<gaps>" \
  --turn-num <N> --status "in-progress" --obsidian-write \
  --topic-name "<Topic Name>" --understood-detail "<detail>" --gaps-detail "<detail>"
```

## Step 5: Topic-Shift Logging

If user changes topic without Gym response, run `log_study` once. Do not double-log after `log_turn.sh`.

## Step 5.5: Session File + Finalization

Standalone: finalize heartbeat `--status complete` + write `Review Sessions/<Topic Title>.md`. Doc-anchored: use `<Title> Review.md` per §9.

After write: concept extraction + post-session hook per §7.

## Post-Interaction Routing

After clear error-type logging, offer targeted remediation:
- numerical_recall → rapid numbers quiz
- conceptual_confusion → causal walkthrough
- cross_contamination → disambiguation table
- application_failure → focused scenario
- reasoning_gap → scaffolded walkthrough

## Cleanup (Scoped)

```bash
cd /Users/gabrielreyes/agentic-neuro && rm -f \
  data/Sessions/learner_context.json data/Sessions/transform_directives.json \
  data/Sessions/retrieval_gap.json data/Sessions/scratch_context.md \
  data/Sessions/transform_output.md data/Sessions/synthesis_digest.md \
  data/Sessions/case_log_sync.txt data/Sessions/passage_manifest.json \
  data/Sessions/citation_audit.json data/Sessions/pipeline_attrition.jsonl
```
