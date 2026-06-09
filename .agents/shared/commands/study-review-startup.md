# Study Review Startup

Lean startup contract for `/study-review`. Use this file before the first learner-facing question. Do not load Anki card-quality, curation, or vault-intelligence contracts at startup unless blocked.

## Startup Invariant

Startup is silent. Do not narrate contract loading, document lookup/read, `startup-recall`, Anki status, or timestamp setup. If startup succeeds, the first learner-facing message is one clinical question, with at most one short orientation clause. Do not quote `handoff.summary`, list prior-session topics, or explain why memory chose the opening.

Set one `SESSION_TS` at the first learner-facing question and reuse it for all later logging, Anki, and session-end commands:

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
python3 src/study_memory.py startup-recall --profile doc --topic "<topic>" --doc "<folder>/<file>.md"
```

Doc review uses the formal lens. Never pass `--lens service`.

4. **Mandatory landscape pass (artifact-anchored sessions).** Before the first question, build the knowledge landscape that borders the document with one bounded, deterministic lookup (vault wikilink graph + ACGME catalog; no embeddings, no LLM, no textbook RAG):

```bash
python3 src/vault_index.py landscape --note "<folder>/<file>.md" --max-neighbors 8
```

Read `neighbors` (each carries `direction`, `edge_type`, `shared_domain`) and `acgme_neighbors`. This is silent bookkeeping that loads neighboring concepts, prerequisites, and competencies into your context so you have somewhere to go when signals appear mid-session: probe or repair a confused neighbor, introduce a needed prerequisite, or extend into an adjacent node when Gabriel shows near-mastery. The neighbors do not have to be surfaced or used — but the pass is not optional. The `landscape` command is a deterministic graph lookup (wikilinks + ACGME), not vault intelligence; semantic/section vault-intelligence recall stays deferred to point-of-need (`study-review-vault-repair.md`).

The landscape is a **skeleton, not a ceiling**: vault wikilinks only reach notes Gabriel has already generated, and ACGME entries are coarse. Complete it from your own clinical knowledge of bordering prerequisites and pathology for planning — the graph leads, native knowledge fills it out. See "The Landscape Is A Skeleton, Not A Ceiling" in `adaptive-teaching-doctrine.md`.

## Non-Document Startup

Topic-only review:

```bash
python3 src/study_memory.py startup-recall --topic "<topic>" --lens general
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
- Use `handoff.next_action` privately to choose the first probe. Treat `handoff.summary` as audit context only.
- **Pedagogical Policy Invariant**: Read `planning_brief.comprehensive_schema_map` and obey `planning_brief.sequential_teaching_plan`. The `mode`/`current_phase` is deterministic — never override it. See `.agents/shared/commands/adaptive-teaching-doctrine.md` for the full mode/interrupt contract.
  - **ORIENT** (`phase_1_clear_fog`): open with a superficial introduction to the listed unexposed concepts plus one concrete exemplar; present a "lay of the land" menu at boundaries.
  - **DEEPEN** (`phase_2_recalibrate_gaps`): drill active gaps/superficial concepts; prioritize prerequisites and address confused semantic competitors.
  - **CONNECT** (`phase_3_force_connections`): test synthesis/transfer across two or more already-seen concepts.
  - **Interrupts**: handle `sequential_teaching_plan.interrupts.remediate` (misconception re-teach + changed-frame retest) and `interrupts.consolidate` (interleaved spaced retrieval of due claims) ahead of new content; they overlay the current phase.
- Prioritize SQLite signals first: `open_first`, `recent_repairs`, urgent `due_claims`, and requested-document priority.
- Use `planning_brief.anki_overlay` only as an advisory overlay: avoid fresh-card direct quizzes, add lightweight primes, choose transfer scaffolds, or sharpen changed-frame checks. Anki never clears SQLite misconceptions.
- Validate `contextual_frontier` silently. Accept only 1-3 candidates that are clinically central, scope-compatible, and useful for a prerequisite, discriminator, mechanism, or transfer probe. Reject tangential adjacency.
- The startup context is the document itself, SQLite recall, the Anki overlay, and the deterministic `landscape` neighbor map. Do not query vault intelligence at startup for the requested document — semantic/section recall stays deferred to point-of-need.

## First Question

Ask one question and stop. Do not provide hints, answer context, expected findings, named signs, thresholds, or teaching explanation until Gabriel answers or requests a reveal. Follow the phase-specific startup directives (e.g. presenting the "lay of the land" menu or opening with a superficial introduction for Phase 1).

After Gabriel answers an assessed clinical question, load `.agents/shared/commands/study-review-turn.md`.

