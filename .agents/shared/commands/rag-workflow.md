# RAG Knowledge Workflow

Use only for explicit textbook/database lookup requests. For ordinary clinical questions, answer directly unless the user asks for RAG.

Follow `.agents/shared/commands/learning-session-contract.md`.

Pipeline: assess, retrieve, transform, gap check, present, log, finalize.

## Step 0: Preflight

```bash
python3 src/study_memory.py recall --topic "<query topic>"
```

Use recall output silently: apply `Next strategy` if relevant, target gaps and open errors, skip known concepts, never repeat recent exchanges. Shape the drill questions around the learner's weakest areas for this topic.

## Step 1: Assess

Single concept: one `compare` call. Multi-axis or comparison query: decompose into at most 3 subqueries and use `compare_multi`.

Frontier search is for current protocols, guidelines, trials, outcomes, devices, or recent evidence. Skip it for stable anatomy, physiology, and mechanisms.

## Step 2: Retrieve

```bash
python3 src/lance_retriever.py compare "<query>"
python3 src/lance_retriever.py compare_multi "<sq1>" "<sq2>" "<sq3>"
python3 src/frontier_search.py "<query>"
```

Use frontier before retrieval only when the gating rule above says it is useful.

## Step 3: Transform

Choose a template:

| Intent | Template |
|---|---|
| default explanation | `neuro-scaffold` |
| board review | `board-exam` |
| brief/on-call | `quick-ref` |
| tutor/drill | `socratic-drill` |
| deep teaching | `textbook-chapter` |

Delegate or run a transform task with:

`QUERY`, `TEMPLATE`, `CONTEXT_PATH=data/Sessions/scratch_context.md`, `DIRECTIVES_PATH=data/Sessions/transform_directives.json`.

The transform task follows `.agents/shared/commands/rag-transform.md`. The main agent reads only `transform_output.md`, never raw scratch context.

## Step 4: Gap Check

Read `data/Sessions/retrieval_gap.json`.

| State | Action |
|---|---|
| `has_gap=false` | Present |
| `has_gap=true` | Run one focused `compare "<gap_query>" --append`, then one follow-up transform |
| unresolved web gap | Present synthesis first, then ask whether to search the recommended external source |

Hard cap: one local follow-up retrieval.

## Step 5: Present and Drill

Deliver the synthesis. For Gym follow-up, ask one question at a time and apply the shared memory contract with `--skill "rag-workflow"`. Follow the Cognitive Friction Protocol: the Gym prompt ends at the question, with no appended answer context or hints. After the learner answers, use Progressive Landscape Reveal so retrieved source terrain is gradually elicited rather than dumped.

Routing:

| Learner result | Next move |
|---|---|
| Correct | Confirm mechanism, then transfer scenario |
| Partial | Isolate missing step |
| Incorrect | Guide to the discriminating feature before revealing |

After clear error typing, offer one remediation: numbers quiz, causal walkthrough, disambiguation table, application scenario, scaffolded reasoning, or a compression card.

## Step 6: Finalize

Standalone sessions write a rich final draft to `data/Sessions/rag_workflow_<slug>_artifact.md`, then install and validate with the Final Artifact Guard (see shared contract).

The final note must include retrieval summary, source coverage, synthesis, gap check, drill/application log, and next targets.

Run `end-session` with a specific `--next-strategy`. Run concept extraction per CLAUDE.md protocol. Clean up workflow-owned `data/Sessions/` files.
