# Memory Curation

Single-purpose contract for the curated cross-session synthesis layer.

The curation layer writes `memory_summaries`, learner `concept_relationships`, and evidence-backed `shadow_rules` as rows in `data/study_memory.db`. `study_memory.py` manages the schema and commands; memory is not compressed into Python source files. Curation runs after Anki flush, never before. It is bookkeeping, not a teaching step.

## Trigger And Ordering

Trigger detection happens during Session End:

```bash
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "..." \
  --next-strategy "..." \
  --json
```

Read the returned `curation.recommended` flag silently and check if any concepts mentioned in active summaries or relationships were successfully answered (`correct=2`) during this session.

Always run Anki review/check/flush after `end-session`. After Anki flush completes, stop if `curation.recommended` is `false` AND no active summaries need to be superseded/escalated; otherwise, continue with the curation and escalation steps below.

## Curation, Escalation & Maintenance Pass

When curation is triggered (due to `curation.recommended=true` or to escalate resolved gaps), run the bookkeeping pass once the Anki flush completes. Curation and routine maintenance fire together from one command, so the identity and telemetry audits cannot silently fall stale.

1. Build the candidate packet:
   ```bash
   python3 src/study_memory.py curate-candidates --mode compact --recent-sessions 5 --limit 40
   ```
   Use `--topic "<slug>"` to narrow when recent sessions cluster on one topic. Use `--mode detailed` only if compact evidence is insufficient. The packet carries a `maintenance` block with `identity_audit` and `telemetry_audit` results, so topic-identity redundancy and telemetry integrity are reviewed in the same pass.

2. Author an apply payload that obeys the doctrine below. Mark resolved summaries as superseded and author replacement summaries containing explicit escalation directives for future sessions. Stamp the packet's `built_at_version` into the payload unchanged.

3. If `maintenance.identity_audit` lists `duplicate_topic_candidates`, dry-run the merge to verify safety and row impact:
   ```bash
   python3 src/study_memory.py merge-topics --from-topic "<source>" --into-topic "<target>"
   ```

4. Present the curated candidates (summaries, shadow rules, concept relationships) and any proposed topic merges as a single proposal for explicit user validation.

5. On confirmation, apply in sequence, then clean up payload files under `data/Sessions/`:
   ```bash
   python3 src/study_memory.py apply-curation --input data/Sessions/curation_payload.json
   python3 src/study_memory.py merge-topics --from-topic "<source>" --into-topic "<target>" --apply
   ```

If `apply-curation` rejects the payload with a stale-version error, another session committed curation between build and apply. Rebuild candidates and retry.

## Doctrine

The summaries, learner-graph edges, and shadow rules produced here are durable cross-session memory. Hold them to a higher bar than per-session handoffs.

- **Evidence floor**: every summary and shadow rule must cite at least 2 `claim_result_id`s. Single-claim observations belong in `claim_state`, not curated summaries. Every relationship must cite `claim_result_id`s, an `evidence_summary_client_id`, or both.
- **Skill weighting**: treat `skill = quick-answer` claim results as low-stakes reference captures. They can support topic/context awareness or low-importance synthesis only when paired with stronger evidence. They must not independently create a high-importance `memory_summary`, a `confused_with` edge, or a learner-state conclusion.
- **Confused-with criterion**: assert `confused_with` only when evidence shows cross-contamination errors or repeated misses on one concept whose corrections name the other.
- **Prerequisite criterion**: `prerequisite` is directed. `source_concept_id` is the foundation required before `target_concept_id`. Use it only when evidence shows repeated target failure and corrections point to an unmastered upstream concept.
- **Prefer supersede over duplicate**: use `supersede_summary_ids` for stale or near-duplicate existing summaries rather than writing a parallel summary.
- **Escalation summary rule**: when superseding a summary due to resolved gaps or demonstrated mastery, write a new active summary with an explicit `Escalation` clause. This instructs future agents on how to probe with higher-level questions, clinical transfer scenarios, or related topics (e.g. *"Gabriel has mastered X. Escalation: test on Y or Z"*).
- **Shadow-rule criterion**: author a shadow rule only for a coherent false decision rule that can leak across contexts. Bind it to explicit concepts and provide a changed-frame `probe_shape`. Do not recast an isolated miss as a rule.
- **Per-pass budget**: cap each pass at roughly 5 summaries, 5 relationships, and 3 shadow rules. Narrow by topic instead of flooding.
- **Strength is required for visibility**: set `strength` on every relationship. Retrieval filters `graph_signals` at `strength >= 0.6`. Use 0.6-0.7 for real, useful confusion or prerequisite edges and 0.8-0.9 for dominant fault lines.
- **Importance is required for useful ordering**: set `importance_score` on summaries with the same intent as relationship strength.
- **Compactness**: summary `content` should be 1-3 sentences naming a recurring pattern, not recapping a session.
- **Scope discipline**: set exactly one of `topic_slug` or `concept_id`, or neither only for genuinely global synthesis.

## Shadow-Rule Extinction

After a shadow-rule probe is logged as a normal assessed `claim_result`, record the reviewed outcome:

```bash
python3 src/study_memory.py record-shadow-check \
  --rule-id <id> --claim-result-id <id> \
  --context-label "<changed clinical frame>" \
  --check-type <changed_frame|transfer> --outcome <pass|fail>
```

The command is dry-run by default. Review the metadata, then repeat with `--apply`. A failure marks the rule `regressed`. Extinction requires at least one changed-frame pass and two distinct transfer-context passes; curation cannot bypass this checkpoint.
