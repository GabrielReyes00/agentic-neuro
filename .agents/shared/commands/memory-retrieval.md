# Memory Retrieval Intelligence

Single-purpose contract for interpreting `study_memory.py summary --include-curated` output.

The database stores facts. The agent supplies judgment. Memory is evidence for teaching design, not a rigid routing table and not learner-facing narration.

## Read Path

Use a staged agent-facing read path:

```bash
python3 src/study_memory.py summary --topic "<topic>" --limit 8 --scaffold-limit 2 --include-curated
```

For memory-driven global review only:

```bash
python3 src/study_memory.py summary --limit 12 --scaffold-limit 0 --include-curated
```

Always read `counts`, `omitted`, and `retrieval_guidance` before teaching. If `retrieval_guidance.omitted_high_signal` is non-empty, run one of the suggested expansion commands before designing the session.

If scaffold cards were omitted, expand `--scaffold-limit` only when you need a coverage map or transfer-question premises. Scaffolds are confirmed knowledge, not primary drill targets. For memory-driven global review, use `--include-global-scaffolds` only when no stronger due gaps dominate.

Inspect raw exchange or claim rows only when compact cards are ambiguous or when auditing the learner model.

## Retrieval Surfaces

Read the JSON in this order:

1. **`cards`**: per-claim-state retrieval cards: `must_retest`, `recent_repair`, `scaffold`, `session_handoff`. This is the triage surface: the exact claim open now.
2. **`curated_summaries`**: agent-authored cross-session synthesis. This is the strategic surface: recurring patterns across sessions.
3. **`graph_signals`**: asserted adjacent concepts related to the current `must_retest` set. This is the transfer/discrimination surface.

## Cards

- Open from the most recent `session_handoff.next_action` when present; it is the previous agent's directive.
- Map each `must_retest` card to a question that forces confrontation with the specific `missing_edge` or `corrected_rule`.
- Repeated misses on the same concept mean the previous teaching approach failed; use a different teaching move.
- `scaffold` cards are premises for transfer questions, not drill targets.
- `recent_repair` cards require changed-framing retest before durable mastery is assumed.

## Curated Summaries

Each summary should name a pattern, not a recap.

- Use summaries to shape the session arc, not to pick the immediate question.
- Higher `importance_score` means a more durable or dominant fault line.
- When a summary and a `must_retest` card point to the same fault line, the summary is the why and the card is the what.
- Selection policy: retrieval returns the top 2 summaries by importance plus summaries whose evidence overlaps concepts in returned cards. Non-anchor unrelated summaries are filtered out intentionally.

## Graph Signals

- `confused_with`: use the neighbor as a discrimination probe after drilling the current concept.
- `prerequisite` is directional. `prerequisite_of_current` means check the upstream foundation before re-drilling the current card. `depends_on_current` means the neighbor is downstream and may become easier after repair.
- Strength >= 0.6 is the visibility floor. Strength 0.8-0.9 names dominant fault lines worth designing around.
- Selection policy: signals fire only from the top 3 `must_retest` concepts by priority.

## Quick-Answer Entries

Quick-answer entries normally do not appear as `cards` because they do not create `claim_state` or `retrieval_cards`. If encountered in curation packets or raw `claim_results`, interpret `skill = quick-answer` as "Gabriel asked about this concept and received an explanation." It is useful for topic adjacency and future context, but it is not evidence that the learner knew, missed, repaired, or mastered the concept.

## Invisibility Rule

Do not echo summary content, paste curated summary text, or telegraph graph signals to the learner. "You've been confusing X and Y" is design input, not a teaching opening.

## Writing Better Memory

Each `log-answer` entry must let a future agent reconstruct what was tested, what the learner got wrong, and what the correct rule is.

- `concept`: specific testable fact, not the topic name.
- `misconception`: specific wrong belief when `correct=0`.
- `correction`: right answer replacing the misconception.
- `error_type`: teaching-relevant failure mode.
- Structured fields: `tested_claim`, `learner_claim`, `missing_edge`, `corrected_rule`, `clinical_consequence`, and `retest_prompt_shape` are the agent's judgment layer.
- Retrieval metadata: `teaching_intent`, `expected_answer_edge`, `coverage_role`, source fields, `answer_mode`, and `confidence_observed` make future retrieval concise.
- Claim-state flags: use `--match-claim-state-id`, `--repairs-claim-state-ids`, and `--new-claim` instead of relying on token overlap.
