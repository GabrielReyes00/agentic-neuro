---
name: rag_workflow
description: Full textbook-grounded RAG workflow with retrieval, transform, gap-check, Socratic follow-up, and learning-state logging.
---

# RAG Knowledge Workflow

Use for explicit textbook/database lookup requests. Do not auto-trigger for general clinical questions.

Pipeline: Assess → Retrieve → Transform → Gap Check → Present → Log → Finalize

All §7 session-end hooks mandatory (preflight, `record-answer` after every Gym response, heartbeat checkpoints, concept extraction, post-session hook).

## Step 0: Pre-Flight + Directives (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && ./src/preflight.sh "query"
```

Read: `learner_context.json`, `transform_directives.json`, `case_log_sync.txt`. New case logs → sync per GEMINI.md.

**Session continuity** (silent):
```bash
python3 src/knowledge_graph.py last_session_narrative --skill "rag-workflow" --topic "<query topic>"
```
If the query topic matches a prior session (non-null result):
- Read `next_session_strategy` — shape Gym questions to follow the recommended approach
- Read `key_confusions_json` — re-test previously confused concepts before advancing
- Read `teaching_failures` — avoid repeating failed approaches
- Surface prior gaps in the Learner Context Adaptation table below

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

**Session timestamp (set once at first Gym question, reuse for all exchanges):**
```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```
Initialize a turn counter at 0. Increment before each `record-answer` call.

After every significant Gym response, run the atomic memory logger:

**Atomic per-answer memory log:**
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/memory_orchestrator.py record-answer \
  --session-ts "$SESSION_TS" --turn <N> --skill "rag-workflow" \
  --topic "<topic>" --concept "<specific concept tested>" \
  --question "<your question, verbatim>" \
  --answer "<user's answer, verbatim or close paraphrase>" \
  --correct <0|1|2> \
  [--correction "<your correction/explanation if incorrect>"] \
  [--error-type "<type>"] [--misconception "<specific wrong belief>"] \
  [--root-cause "<why>"] [--remediation "<what should fix it>"] \
  [--teaching-approach "<approach used>"] \
  [--retrieval-sources "<source_book: heading>"] \
  [--depth <N>] [--domain "<domain>"] [--response-confidence "high|low"]
```
Correctness routing: correct with no hints = `--correct 2` | partial = `--correct 1` | wrong or misconception = `--correct 0`. Capture the ACTUAL question and answer. For breakthroughs, add `--breakthrough --insight "<what clicked>"`.

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

If user changes topic without Gym response, run `log_study` once. Do not double-log after `record-answer`.

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
