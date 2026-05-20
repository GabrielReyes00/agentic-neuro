# Memory Curation

Single-purpose contract for the curated cross-session synthesis layer.

The curation layer writes `memory_summaries` and `concept_relationships`. It runs after Anki flush, never before. It is bookkeeping, not a teaching step.

## Trigger And Ordering

Trigger detection happens during Session End:

```bash
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "..." \
  --next-strategy "..." \
  --json
```

Read the returned `curation.recommended` flag silently and remember it while completing the Anki queue workflow.

Always run Anki review/check/flush after `end-session`. After Anki flush completes, stop if `curation.recommended` is `false`; if it is `true`, continue with the curation steps below.

## Curation Steps

1. Build the compact candidate packet:

   ```bash
   python3 src/study_memory.py curate-candidates --mode compact --recent-sessions 5 --limit 80
   ```

   Use `--topic "<slug>"` to narrow when recent sessions cluster around one topic. Use `--mode detailed` only if compact evidence is insufficient.

2. Read the packet and author an apply payload that obeys the doctrine below. Stamp the packet's `built_at_version` into the payload unchanged.

3. Apply via stdin or file:

   ```bash
   python3 src/study_memory.py apply-curation --stdin < payload.json
   # or
   python3 src/study_memory.py apply-curation --input data/Sessions/curation_payload.json
   ```

4. Clean up any curation payload file you wrote under `data/Sessions/`.

If `apply-curation` rejects the payload with a stale-version error, another session committed curation between build and apply. Rebuild candidates and retry.

## Doctrine

The summaries and graph edges produced here are durable cross-session memory. Hold them to a higher bar than per-session handoffs.

- **Evidence floor**: every summary must cite at least 2 `claim_result_id`s. Single-claim observations belong in `claim_state`, not curated summaries. Every relationship must cite `claim_result_id`s, an `evidence_summary_client_id`, or both.
- **Skill weighting**: treat `skill = quick-answer` claim results as low-stakes reference captures. They can support topic/context awareness or low-importance synthesis only when paired with stronger evidence. They must not independently create a high-importance `memory_summary`, a `confused_with` edge, or a learner-state conclusion.
- **Confused-with criterion**: assert `confused_with` only when evidence shows cross-contamination errors or repeated misses on one concept whose corrections name the other.
- **Prerequisite criterion**: `prerequisite` is directed. `source_concept_id` is the foundation required before `target_concept_id`. Use it only when evidence shows repeated target failure and corrections point to an unmastered upstream concept.
- **Prefer supersede over duplicate**: use `supersede_summary_ids` for stale or near-duplicate existing summaries rather than writing a parallel summary.
- **Per-pass budget**: cap each pass at roughly 5 summaries and 5 relationships. Narrow by topic instead of flooding.
- **Strength is required for visibility**: set `strength` on every relationship. Retrieval filters `graph_signals` at `strength >= 0.6`. Use 0.6-0.7 for real, useful confusion or prerequisite edges and 0.8-0.9 for dominant fault lines.
- **Importance is required for useful ordering**: set `importance_score` on summaries with the same intent as relationship strength.
- **Compactness**: summary `content` should be 1-3 sentences naming a recurring pattern, not recapping a session.
- **Scope discipline**: set exactly one of `topic_slug` or `concept_id`, or neither only for genuinely global synthesis.
