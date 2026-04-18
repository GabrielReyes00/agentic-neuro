# RAG Transform

Internal transform task. Convert retrieved context into a cited synthesis and write deterministic artifacts. Do not invoke directly for user-facing answers.

## Inputs

- `QUERY`
- `TEMPLATE`: `neuro-scaffold`, `board-exam`, `quick-ref`, `socratic-drill`, or `textbook-chapter`
- `CONTEXT_PATH`: default `data/Sessions/scratch_context.md`
- `DIRECTIVES_PATH`: default `data/Sessions/transform_directives.json`
- `LEARNER_CONTEXT_PATH`: default `data/Sessions/learner_context.json`

## Steps

1. Load directives and learner context. Directives win on overlap.
2. Read only retrieved context from `CONTEXT_PATH`.
3. Render the requested template using retrieved evidence only.
4. Write `data/Sessions/transform_output.md` with YAML frontmatter.
5. Write `data/Sessions/retrieval_gap.json`.
6. Return template used, source count, coverage quality, and gap status.

## Personalization

Apply silently:

| Signal | Action |
|---|---|
| skip foundations | Start at mechanisms |
| due concept | Include one natural verification |
| misconception metadata | Build a diagnostic wrong-answer trap |
| remediation directive | Match gym style to recommended mode |
| transfer candidate | Add a novel-context test marker |
| cognitive pattern | Add a probe marker |
| confusable pair | Force discriminating-feature reasoning |
| calibration alert | Ask for confidence before answer |

Every gym scenario needs decision tension, stakes or time pressure, and `<!-- WRONG_ANSWER_DIAGNOSTIC: ... -->`.

For any `## Gym` output, preserve cognitive friction. Write the learner-facing prompt so it ends at the question. Keep answer rationale, expected findings, named signs, and diagnostic targets out of the visible prompt; store diagnostic intent only in internal comments such as `<!-- WRONG_ANSWER_DIAGNOSTIC: ... -->`.

Also prepare a progressive post-answer reveal. It should not appear before the learner answers. Include the expected answer, the next discriminator, and 1-3 follow-up probes. Do not prepare a full topic dump unless the task is explicitly a summary or full reveal.

## Gap Signal

Write:

```json
{"has_gap": false}
```

or:

```json
{
  "has_gap": true,
  "gap_query": "...",
  "gap_reason": "...",
  "axis": "...",
  "web_search_candidate": true,
  "web_search_reason": "..."
}
```

Set `web_search_candidate` only for non-local gaps such as new guidelines, trials, devices, scoring systems, or stale treatment guidance.

## Universal Constraints

1. Cite every factual claim with source IDs from retrieved context.
2. Never invent evidence, numbers, citations, or figure references.
3. Preserve safety-critical values, thresholds, anatomy, timing, doses, and contraindications.
4. Embed figure display commands only when figures are present in context.
5. Open with a concise coverage signal.
6. Target PGY neurosurgery. No filler.

## Templates

### `neuro-scaffold`

`## Anchor` (max 3-4 sentences), `## Build` (1-3 mechanism layers), `## Compress` (3-5 reconstructable sentences), `## Gym`. Add operative protocol, illness script, evidence reconciliation, or critical highlights only when relevant.

### `board-exam`

Coverage line, 5-10 high-yield facts with testing pattern, ABNS-style vignette with close distractors and why-not analysis, rapid-fire associations, board pearl.

### `quick-ref`

Definition, key numbers, decision algorithm, red flags, compact differential, one-rule takeaway.

### `socratic-drill`

Write `active_lesson_sections.json`, `active_lesson_plan.md`, and a short `transform_output.md` telling the caller where the drill artifacts are.

### `textbook-chapter`

Introduction, fundamentals, clinical presentation/diagnosis, management/decision-making, complications/pitfalls, summary, and 2-3 self-assessment questions.

## Follow-Up Pass

When called after gap retrieval, read the existing output plus updated context, integrate only the new evidence, and set the gap file to `{"has_gap": false}`.
