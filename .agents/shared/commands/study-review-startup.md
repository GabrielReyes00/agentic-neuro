# Study Review Startup

Startup-only contract for `/study-review`. Load this file and
`memory-retrieval.md` before the first learner-facing question. Do not load Anki card-quality,
curation, or semantic vault-retrieval instructions unless later needed.

## Invariants

Startup is silent. Do not narrate contract loading, document lookup,
`startup-recall`, Anki status, or timestamp setup. On success, ask one clinical
question and stop; at most, precede it with one short orientation clause. Do
not quote `handoff.summary` or explain the memory system's choice.

The sole pre-question exception is a non-empty
`planning_brief.alignment_proposals`: database realignment is a user-approved
mutation, so show the compact proposal and ask permission instead of asking a
clinical question. Never auto-apply it.

Set one `SESSION_TS` and reuse it through logging and closure:

```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```

## Select A Mode

- **Document:** a reviewable vault document is named or clearly inferable.
- **Topic:** a topic is named without a document.
- **Memory:** Gabriel requests weak spots, open errors, custom review, or a
  board-style case without naming a topic.
- **Service:** Gabriel asks about a named service or site's local practice.

## Document Startup

1. Resolve a document whose workflow is `reviewable` in
   `.agents/shared/workflow-registry.json`. Clarify only genuine ambiguity. If
   none exists, use topic mode or the matching generation workflow; never
   invent a document path.
2. Read the full document. `## Mastery Objectives` is a coverage checksum, not
   a substitute for the body.
3. Run:

```bash
python3 src/study_memory.py startup-recall --profile doc --topic "<topic>" --doc "<folder>/<file>.md" --session "$SESSION_TS"
```

Document mode is formal; never add `--lens service`.

4. If `planning_brief.artifact_alignment.status` is `missing`, `stale`, or
   `family_match_unverified`, build or verify the map from the document already
   read, then rerun startup once:

```bash
python3 src/study_memory.py artifact-map-upsert --topic "<topic>" --doc "<folder>/<file>.md" --stdin
```

Use the payload defined in `memory-operations.md`. Map the body, not just its
objectives. Keep the requested artifact primary: use
`artifact_remaining_high_yield` before `map_context_only`, and reserve
`horizon_expansion` until the artifact-native core is stable. The inventory is
a skeleton, not a ceiling; if unavailable, proceed from the document and
SQLite learner state.

## Other Startup Commands

```bash
# Topic
python3 src/study_memory.py startup-recall --topic "<topic>" --lens general --session "$SESSION_TS"

# Global memory routing (not yet teachable)
python3 src/study_memory.py startup-recall --global --lens general --session "$SESSION_TS"

# Service/site
python3 src/study_memory.py startup-recall --lens service --service "<service>" --site "<site>" --session "$SESSION_TS" [--context "<case/topic>"]
```

Global recall selects candidate topics from `startup_recall.deferred_high_signal`;
run topic-scoped recall before teaching. Service mode uses only `service_gaps`
and `conventions` unless Gabriel requests comparison with formal knowledge.

## Interpret And Open

`memory-retrieval.md` is the canonical owner of the `planning_brief` schema.
Read `startup_recall`, `planning_brief`, `counts`, `omitted`, and
`retrieval_guidance`, then apply these startup decisions:

- If `routing_required=true`, validate a returned candidate and rerun scoped
  recall; clarify only if scope remains ambiguous.
- If `new_topic_orientation.status=new_topic_no_learner_history`, proceed in
  ORIENT from the inventory map. Weak lexical neighbors are leads, not prior
  mastery and not a reason to block teaching.
- If `alignment_proposals` is non-empty, follow the authorization exception
  above. After approval, apply the documented `realign-concept --apply`
  operation and report its result.
- Treat `coverage_gaps` as unassessed artifact-native priorities, not inferred
  weaknesses and not permission to mutate data.
- When `ready_to_teach=true` and `pre_question_expansion_allowed=false`, do not
  run audit expansion before the first question.
- Obey `knowledge_map` and `sequential_teaching_plan`; never pick the macro
  phase yourself. ORIENT, DEEPEN, CONNECT, `interrupts.remediate`, and
  `interrupts.consolidate` follow `adaptive-teaching-doctrine.md` and its
  Signal Precedence. If the plan is empty or `knowledge_map_status` is
  `empty_no_inventory_scope`, the session is ORIENT by definition.
- Use `handoff.next_action` privately within the current phase. If it conflicts,
  the plan and interrupts win.
- In document mode, use `teaching_priorities`; there is no separate `open_first` list in doc mode.
  Requested-document priority still holds.
- Use `planning_brief.anki_overlay` only to avoid fresh-card direct quizzes,
  prime lightly, or shape transfer. Anki never clears SQLite misconceptions.
- Validate `contextual_frontier` silently and accept only central,
  scope-compatible candidates. Do not query vault intelligence at startup.

During ORIENT, the opening remains one answerable clinical question. A broader
"lay of the land" menu belongs at a phase boundary after learner engagement,
not beside the opening question.

After Gabriel answers, load `study-review-turn.md`.
