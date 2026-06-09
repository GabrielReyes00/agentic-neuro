# Study Review Startup

Lean startup contract for `/study-review`. Use this file before the first learner-facing question. Do not load Anki card-quality, curation, or vault-intelligence contracts at startup unless blocked.

## Startup Invariant

Startup is silent. Do not narrate contract loading, document lookup/read, `startup-recall`, Anki status, or timestamp setup. If startup succeeds, the first learner-facing message is one clinical question, with at most one short orientation clause. Do not quote `handoff.summary`, list prior-session topics, or explain why memory chose the opening.

Set one `SESSION_TS` before startup recall (invisible bookkeeping) and reuse it for all logging, Anki, and session-end commands:

```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
```

## Mode Selection

- **Doc-anchored**: a vault document is named or inferable. The document is the curriculum boundary.
- **Topic-only**: a topic is named but no vault document is known.
- **Memory-driven**: Gabriel asks what to review, weak spots, open errors, custom review, or board-style cases without a specific topic.
- **Service/site-specific**: Gabriel asks how something is done on a named service/site; use service memory only.

## Document Startup

1. Resolve the requested document from `Reports/`, `Study Material/`, or `Brain Dumps/`. If ambiguous, ask one clarification. If none exists, route to the matching generation/capture workflow.
2. Read the full vault document before teaching. If the document has `## Mastery Objectives`, use them only as a coverage checksum after reading the body.
3. Once the relative doc path is known, run the document read and startup recall in the same tool turn when possible:

```bash
python3 src/study_memory.py startup-recall --profile doc --topic "<topic>" --doc "<folder>/<file>.md" --session "$SESSION_TS"
```

Doc review uses the formal lens. Never pass `--lens service`.

`startup-recall` internally runs the concept-inventory projection (scoped subgraph from `data/concept_inventory.db`; no embeddings, no LLM, no textbook RAG) and writes the live session map to `data/Sessions/knowledge_map_<SESSION_TS>.json` for per-turn patching. Read `planning_brief` silently:
- **`knowledge_map`**: one entry per scoped inventory concept with inventory `concept_id`, `exposure_status` (`unexposed`/`exposed_superficial`/`exposed_deep`), `knowledge_state`, `active_misconception`, `safety_critical`, `tier`, `role` (`entry` vs `neighbor_*`), and `matched_learner_concepts`. Unexposed here means "in the domain map but Gabriel has never been tested on it" — what ORIENT needs.
- **`sequential_teaching_plan`**: deterministic phase/interrupts from the inventory-grounded map plus SQLite urgency signals.
- **`teaching_priorities`** / **`open_first`**: SQLite learner-state urgency layered on top of the map.
- **`inventory_unmatched_learner_concepts`**: legacy learner concepts without inventory IDs yet; retry matching when they resurface.

**Artifact Priority (doc-anchored):** the requested document is the primary curriculum. Teach from the artifact body first. Borrow from the knowledge map only for prerequisite gaps, misconception repair, phase-boundary choices, or transfer after artifact material is substantially covered. The map informs context; it does not pull teaching off-artifact.

The inventory map is a **skeleton, not a ceiling**. If the inventory DB is unavailable, fall back to the document body plus SQLite recall signals and proceed.

## Non-Document Startup

Topic-only review:

```bash
python3 src/study_memory.py startup-recall --topic "<topic>" --lens general --session "$SESSION_TS"
```

Memory-driven review:

```bash
python3 src/study_memory.py startup-recall --global --lens general
```

Global recall is not teachable. Select candidate topics from `startup_recall.deferred_high_signal`, then run topic-scoped startup recall before teaching.

Service/site review:

```bash
python3 src/study_memory.py startup-recall --lens service --service "<service>" --site "<site>" [--context "<case/topic>"]
```

Use only `service_gaps` and `conventions` unless Gabriel asks to compare local practice with formal knowledge.

## Read The Recall Packet

Read `startup_recall`, `planning_brief`, `counts`, `omitted`, and `retrieval_guidance`.

- If `routing_required=true`, validate a returned candidate and rerun topic/doc recall. Clarify only if still ambiguous.
- If `ready_to_teach=true` and `pre_question_expansion_allowed=false`, do not run audit expansion before the first question.
- Use `handoff.next_action` privately to choose the first probe **within** the plan's current phase and interrupts; if the handoff conflicts with the plan, the plan and interrupts win (see "Signal Precedence" in `adaptive-teaching-doctrine.md`). Treat `handoff.summary` as audit context only.
- **Pedagogical Policy Invariant**: Read `planning_brief.knowledge_map` and obey `planning_brief.sequential_teaching_plan`. The `mode`/`current_phase` is deterministic — never override it. See `.agents/shared/commands/adaptive-teaching-doctrine.md` for the full mode/interrupt contract. In `profile=doc` the emitted map is capped (`knowledge_map_omitted` reports what was truncated) and `target_concepts` may carry `target_concepts_omitted`; the policy was computed from the full map before truncation, so trust the phase. If `sequential_teaching_plan` is `{}` or `knowledge_map_status` is `empty_no_inventory_scope`, the session is ORIENT by definition.
  - **ORIENT** (`phase_1_clear_fog`): open with a superficial introduction to the listed unexposed concepts plus one concrete exemplar; present a "lay of the land" menu at boundaries.
  - **DEEPEN** (`phase_2_recalibrate_gaps`): drill active gaps/superficial concepts; prioritize prerequisites and address confused semantic competitors.
  - **CONNECT** (`phase_3_force_connections`): test synthesis/transfer across two or more already-seen concepts.
  - **Interrupts**: handle `sequential_teaching_plan.interrupts.remediate` (misconception re-teach + changed-frame retest) and `interrupts.consolidate` (interleaved spaced retrieval of due claims) ahead of new content; they overlay the current phase.
- Prioritize SQLite signals first, by profile. In `profile=doc`, the compact brief carries `teaching_priorities` (the ranked blend of open gaps, recent repairs, and stale scaffolds) — there is no separate `open_first` list in doc mode. In `profile=memory`/`audit`, read `open_first`, `recent_repairs`, and `known_scaffolds_due`. In both, requested-document priority holds.
- Use `planning_brief.anki_overlay` only as an advisory overlay: avoid fresh-card direct quizzes, add lightweight primes, choose transfer scaffolds, or sharpen changed-frame checks. Anki never clears SQLite misconceptions.
- Validate `contextual_frontier` silently. Accept only 1-3 candidates that are clinically central, scope-compatible, and useful for a prerequisite, discriminator, mechanism, or transfer probe. Reject tangential adjacency.
- The startup context is the document itself, SQLite recall, the Anki overlay, and the inventory-grounded `knowledge_map` inside `planning_brief`. Do not query vault intelligence at startup for the requested document — semantic/section recall stays deferred to point-of-need.

## First Question

Ask one question and stop. Do not provide hints, answer context, expected findings, named signs, thresholds, or teaching explanation until Gabriel answers or requests a reveal. Follow the phase-specific startup directives (e.g. presenting the "lay of the land" menu or opening with a superficial introduction for Phase 1).

After Gabriel answers an assessed clinical question, load `.agents/shared/commands/study-review-turn.md`.

