# Memory Retrieval Intelligence

Single-purpose contract for interpreting `study_memory.py startup-recall` output. Raw `summary` remains available for deeper audits.

The database stores facts. The agent supplies judgment. Memory is evidence for teaching design, not a rigid routing table and not learner-facing narration.

Memory is not the only knowledge source. `startup-recall` itself is SQLite learner-state plus optional Anki overlay, not Obsidian vault search. When Gabriel's own notes can improve a repair, contrast, local-practice clarification, or artifact workflow, use `.agents/shared/commands/vault-intelligence.md` as a point-of-need supplemental tool. In document-anchored `study-review`, the requested document is already read directly, so do not query the vault at startup for the same document. The vault can supply discriminators, durable mental models, evidence cards, local clarifications, and mastery objectives; it is not exhaustive neurosurgery knowledge and never prevents the agent from using native clinical knowledge or formal verification.

## Read Path

Use a staged agent-facing read path:

```bash
python3 src/study_memory.py startup-recall --profile doc --topic "<topic>" --doc "<folder>/<file>.md"
```

For topic-only or memory-driven review:

```bash
python3 src/study_memory.py startup-recall --topic "<topic>" --lens general
```

For memory-driven global review only:

```bash
python3 src/study_memory.py startup-recall --global --lens general
```

For service/site-specific review only:

```bash
python3 src/study_memory.py startup-recall --lens service --service "<service>" --site "<site>"
```

Always read `startup_recall`, `planning_brief`, `counts`, `omitted`, and `retrieval_guidance` before teaching. `planning_brief` is the ordered first-read tutor context.

Startup profiles:
- `--profile doc`: default for document-anchored review. It is compact and document-primary: it returns handoff, top open gaps, top recent repairs, due scaffolds, capped related-context candidates, and no pre-question audit command. Use this for `/study-review --doc`.
- `--profile memory`: topic/global review planning. With `--lens general`, topic-scoped memory recall includes assessed learner state plus pending Brain Dump review candidates and expands omitted high-signal cards automatically; global startup stays compact and returns `ready_to_teach = false`.
- `--profile audit`: full rich startup surface for troubleshooting, learner-model audits, or ambiguous/safety-critical compact briefs.
- `--profile auto`: chooses `doc` when `--doc` is present, otherwise `memory`.

For doc review, do not expand just because `counts`, `omitted`, or `retrieval_guidance.deferred_high_signal_counts` are nonzero. Those counts preserve awareness of compacted learner evidence; they are not a pre-question fetch instruction. If `startup_recall.ready_to_teach=true` and `startup_recall.pre_question_expansion_allowed=false`, ask the first question from `planning_brief`. Use audit expansion only if startup is blocked, the compact brief is incoherent, or the learner explicitly asks for a memory audit. For memory-driven global review, use `startup_recall.deferred_high_signal` as a prompt for candidate selection, then run topic-scoped startup recall for selected topics.

If `planning_brief.resolution_warning` is present, do not begin teaching from an empty or guessed topic envelope. Validate one of `resolution_candidates` as the intended existing learner-state anchor, rerun topic-scoped recall with that anchor, and clarify with the learner only when the correct curriculum scope remains ambiguous.

If scaffold cards were omitted, expand `--scaffold-limit` only when you need a coverage map or transfer-question premises. Scaffolds are confirmed knowledge, not primary drill targets. For memory-driven global review, use `--include-global-scaffolds` only when no stronger due gaps dominate.

Inspect the full non-brief summary, raw exchange rows, or claim rows only when the compact brief is incoherent, startup is blocked, topic-scoped memory mode still reports unresolved omitted high-signal material, or you are auditing the learner model.

## Planning Brief

This file is the canonical owner of the `planning_brief` JSON schema. If another contract names a `planning_brief` field that is not defined here, this file wins.

**`knowledge_map` and `sequential_teaching_plan` lead the brief.** `startup-recall` builds them from the scoped concept inventory plus SQLite learner-state overlay. They are present in both `profile=doc` and `profile=memory`/`audit`. In `profile=memory`/`audit` they are carried verbatim. In `profile=doc` the emitted map is deterministically bounded: capped at the highest-signal entries (misconceptions, safety-critical, open states, superficial first) with `knowledge_map_omitted` reporting `{count, by_exposure_status}`, and `target_concepts` is capped with `target_concepts_omitted` when truncated. The policy is always computed from the full map before truncation — trust the phase even when the emitted map is capped. Per-turn `policy=` lines patch the live session map incrementally. Read them first and obey the policy — you never pick the macro phase yourself (see `adaptive-teaching-doctrine.md`):

- **`knowledge_map`**: one entry per scoped inventory concept, each with inventory `concept_id`, `exposure_status` (`unexposed` | `exposed_superficial` | `exposed_deep`), `knowledge_state`, `attempts_count`, `sqlite_success_rate`, `anki_reviews_count`/`anki_success_rate` (advisory overlay only), `matched_learner_concepts` (each carrying `binding_source` = `explicit` when an inventory binding drove the match, else `lexical`), optional compact `learner_surface` (`open_claims`, `top_gap`, `last_misconception_verbatim`), optional `escalation_directive`, `binding_tier`, `safety_critical`, `active_misconception`, `tier`, and `role`. Matching is **Identity-first**: a learner concept with an explicit `inventory_concept_id` is assigned directly to that node (so many fragmented legacy rows consolidate onto one canonical concept); only unbound concepts fall back to lexical matching.
- **`escalation_directives`**: capped curated summaries with explicit `Escalation:` clauses, preferably inventory-ID scoped. Use silently to raise demand after demonstrated mastery; never quote prior-session handoffs across unrelated topics.
- **`acgme_readiness`** (global memory-driven startup only): lean PGY-scoped `domain_gaps` and `top_blind_spots` from inventory ACGME links + learner bindings. Reports `explicit_inventory_bindings` vs `lexically_projected_concepts` so you can see how much is firm binding vs estimate. Use for “what should I study before PGY2?” style reviews, not doc-anchored sessions.
- **`orient_skip`**: ORIENT is bypassed deterministically when the learner already holds a schema — `reason` is `all_entry_nodes_have_prior_exposure` (every entry exposed) or `predominant_prior_exposure` (exposed entries ≥ 60% and ≥ 3). The few still-unexposed entries fold into DEEPEN; do not re-orient a clearly-engaged topic.
- **`knowledge_map_provenance`**: `inventory` (the rich inventory-grounded map — the healthy path), `sqlite_fallback` (degraded: SQLite-only map, no graph structure/domain boundaries), or `none`. If it is not `inventory`, the session is running degraded; proceed but treat the map as thin.
- **Open-gap cards** may include `cognitive_op` from the last assessed miss on that claim.
- **`knowledge_map_status`**: `ok`, `empty_no_inventory_scope`, `empty_no_learner_concepts` (SQLite-only fallback), `no_topic`, or `error: ...`.
- **`inventory_unmatched_learner_concepts`**: legacy learner concepts not yet bound to inventory IDs; retry matching when resurfaced.
- **`sequential_teaching_plan`**: `mode` (`orient` | `deepen` | `connect`) and `current_phase`, plus `interrupts.remediate` (misconception/shadow-rule re-teach targets) and `interrupts.consolidate` (due claims to interleave), `target_concepts`, `pedagogical_directives`, `socratic_choice_directives` (how to offer Gabriel a choice at phase boundaries), and `decision_inputs` (the counts that produced the phase, for audit). The same full plan is persisted to `policy_events.plan_json` and re-emitted after every assessed `log-answer` as a self-sufficient `policy=` line. Interrupts overlay the current phase; the tie-break order is "Signal Precedence" in `adaptive-teaching-doctrine.md`.

In `profile=doc`, read the rest of `planning_brief` as a compact session-start contract:

1. **`handoff`**: the previous session directive, if any. Use `handoff.next_action` as private question-design input. Treat `handoff.summary` as audit/debug context only; do not narrate it to the learner.
2. **`teaching_priorities`**: the ranked blend of open gaps, recent repairs, and stale scaffolds.
3. **`contextual_frontier`**: capped related-context candidates. Accept only candidates central to the requested document.
4. **`question_design_bias`** and **`domain_patterns`**: small shaping signals, not a mandate.
5. **`anki_overlay`**: optional scoped Anki feedback. Use it only to shape sequencing, scaffolds, and redundant-card avoidance after the document curriculum and SQLite priorities are set.
6. **`deferred_evidence`**: compacted-evidence counts retained for awareness; do not fetch them before the first question.
7. **`fallback.audit_profile_available`**: reminder that a richer audit exists for blocked or explicit audit situations; it is not a pre-question step.

In `profile=memory` or `profile=audit`, read `planning_brief` in order:

1. **`handoff`**: the latest learner-session directive. Use `handoff.next_action` to select the next probe; do not quote or paraphrase `handoff.summary` as an opening recap. Artifact-generation anchors do not compete with this surface.
2. **`open_first`**: unresolved claims that deserve the first questions. Each card may carry `prerequisites`, `active_prerequisite_gaps`, and `semantic_competitors` (the same graph relations as the schema map); `open_first` is pre-sorted so prerequisite concepts precede their dependents.
3. **`recent_repairs`** and **`known_scaffolds_due`**: changed-frame retention checks and stale premises.
4. **`domain_patterns`** and **`misconception_rules`**: curated cross-session fault lines and evidence-backed false rules.
5. **`contextual_frontier`**: bounded neighboring foundations from learner graph edges, reviewed reference-graph paths, report-local scaffolds, and cautious cross-topic overlap.
6. **`question_design_bias`**: confidence calibration, weak cognitive operations, and teaching-move evidence.
7. **`anki_overlay`**: optional scoped Anki feedback. Read exact atomic facts, but apply them only after SQLite priorities; see **Anki Overlay** below.
8. **`low_confidence_leads`**: curiosity and artifact hints only.

Before teaching, execute `agent_validation_checkpoint` silently. Accept only 1-3 frontier candidates that are clinically central, within the requested curriculum boundary, and likely to explain an active gap or deepen transfer. Reject tangents. Frontier candidates shape questions; they never override urgent open claims.

## Retrieval Surfaces

Read the JSON in this order:

1. **`cards`**: per-claim-state retrieval cards: `must_retest`, `recent_repair`, `scaffold`, `session_handoff`. This is the raw triage evidence behind `planning_brief`.
2. **`curated_summaries`**: agent-authored cross-session synthesis. This is the strategic surface: recurring patterns across sessions.
3. **Learner graph surfaces**: `graph_signals` and `shadow_rule_signals`. These are evidence-backed discrimination and false-rule repair inputs.
4. **Model surfaces**: `due_claims`, `calibration_profile`, `operation_profile`, `teaching_move_profile`, `telemetry_profile`, `tutor_efficacy_profile`, `coverage_frontier`, `brain_dump_review_candidates`, and `shadow_queue`.
5. **Context surfaces**: optional `context_focus` and `context_graph_focus` when `--context` is present. These weight session planning; they do not override urgent gaps.
6. **Anki feedback overlay**: optional `planning_brief.anki_overlay`, sourced from live Anki scheduling/review metadata. Detailed atomic signals appear only on resolved topic/doc startup; global startup exposes status or topic headlines only and requires a topic-scoped rerun before teaching.

## Cards

- Each card and due-claim carries `inventory_concept_id` when its concept is bound. Group hits that share an `inventory_concept_id` — they are the same canonical concept (one node may have several distinct open claims); address them together rather than as unrelated rows.
- Open from the most recent `session_handoff.next_action` when present; it is the previous agent's directive. Convert it into a question or case setup, not a learner-facing recap.
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

## Shadow Rule Signals

- `shadow_rule_signals` represent coherent false decision rules that can leak across contexts. Inject one bounded discriminator probe without telegraphing the rule.
- `active` or `regressed` rules deserve changed-frame testing. `repaired` rules still need transfer evidence.
- Do not declare a rule extinguished from conversation alone. Extinction is enforced through `record-shadow-check` per `memory-curation.md`.

## Quick-Answer Entries

Quick-answer entries normally do not appear as `cards` because they do not create `claim_state` or `retrieval_cards`. If encountered in curation packets or raw `claim_results`, interpret `skill = quick-answer` as "Gabriel asked about this concept and received an explanation." It is useful for topic adjacency and future context, but it is not evidence that the learner knew, missed, repaired, or mastered the concept.

## Model Surfaces

- `due_claims`: conceptual claims whose retrievability has decayed, deduplicated against the active triage cards — a claim already shown as a `must_retest` or `recent_repair` card is omitted here, so this surface is the pure-decay remainder (including decayed scaffolds). Use changed-frame retention checks; do not repeat the original wording. Each entry carries `claim_state_id`, matching the `claim_state_id` now on every card for cross-reference.
- `calibration_profile`: prioritize high-confidence misses because they are safety-relevant and high-yield to correct. Low-confidence correct answers may need confidence-building transfer, not re-teaching.
- `operation_profile`: recurring weakness by domain and cognitive operation. Use it to choose question shape: sequencing drills for sequencing weakness, contrastive probes for discrimination weakness, order sets for quantification/management gaps.
- `teaching_move_profile`: early n=1 feedback on which teaching moves are landing. Treat as suggestive until repeated.
- `telemetry_profile`: metadata completeness and controlled-value violations. Historical gaps remain visible but are not clean efficacy evidence.
- `tutor_efficacy_profile`: repair-episode outcomes. Treat `evidence_level = insufficient` as instrumentation only; use directional preferences only after the returned gate is satisfied.
- `coverage_frontier`: read-only ACGME coverage map, populated only in memory-driven/global review — it is emitted empty during a topic-anchored drill, where the global map is irrelevant. Coverage is tiered by token overlap against tested learner topics: `tested_catalog_topics` counts catalog topics with strong overlap, `frontier_candidates` are adjacent untested topics (a single shared term), and `blind_spots` are high-yield topics with no overlap. Untested means unknown, not weak.
- `brain_dump_review_candidates`: atomic concepts captured from Brain Dumps but not yet tested. They are outstanding review opportunities, not mastery evidence, misses, or durable claims. Ask a Socratic probe before assigning learner state, and pass the candidate id to `log-answer`.
- `shadow_queue`: low-weight implied interest from quick answers, generated artifacts, and pending Brain Dump candidates. Probe later, but never treat it as mastery or a miss until tested.
- `contextual_frontier`: bounded candidate foundations for agent validation. It is intentionally broader than the final session plan. Reject weakly connected candidates rather than treating lexical or graph adjacency as a teaching mandate.
- `context_focus`: only appears when the command includes `--context "<case/rotation/upcoming focus>"`; use it to weight, not override, due and safety-critical gaps.
- `context_graph_focus`: reviewed reference-graph paths, capped at two hops and filtered by context predicates. Verify the path makes clinical sense before using it. Learner graph edges and the reference graph are separate layers.

## Anki Overlay

`planning_brief.anki_overlay` is a compact live-Anki advisory surface for the resolved topic or document scope. If it is absent, offline, unresolved, `no_matches`, or only present as `startup_recall.anki_feedback_status`, proceed from SQLite and normal document/topic context.

Scoping uses explicit deck/tag/phrase matches plus SQLite vector cache semantic candidates from the Anki cache. Strong semantic hits may contribute even when the card lacks a literal topic token; weak or generic hits need a real scope anchor. Generic words such as "emergency", "acute", or "management" never define scope by themselves.

- `atomic_focus`: exact card facts with fragile review state such as `active_lapse`, `leech`, `shaky_success`, or central `mature_stale`. After `open_first`, `recent_repairs`, and urgent `due_claims`, use these to sharpen changed-frame probes or Socratic repairs.
- `atomic_scaffolds`: exact stable or recent-success facts. Use them as transfer premises, not first-order recall targets.
- `atomic_primes`: exact stale-new facts. Use at most as one brief recognition prime when central to the requested topic.
- `avoid_direct_quiz`: fresh or transition cards. Suppress direct quizzes on these facts; if central, use them only as premise or context.
- `concept_rollup` and `macro_counts`: orientation only. `concept_rollup` may be structured dictionaries or compact `Concept:worst_state(count)` strings; never use it as a question queue.

Guardrails:
- SQLite precedence: Anki shapes the queue; it does not own the queue. Anki never overrides `handoff`, `open_first`, `recent_repairs`, urgent `due_claims`, or requested-document priority.
- Mastery evidence: Do not let Anki success clear a SQLite misconception. Anki success does not clear a known misconception, and Anki lapse does not become `claim_state` until Gabriel answers an agent-assessed probe.
- Scope: ignore off-topic atomic facts, service-local cards in formal/doc review when identifiable, and low-confidence mappings unless the fact is clinically central and independently sensible.
- Visibility: use Anki signals silently. Do not narrate Anki scheduling, lapses, or ease ratings to Gabriel unless he asks.

## Invisibility Rule

Do not echo summary content, paste curated summary text, list previously reviewed topics, or telegraph graph signals to the learner; specifically, do not narrate `handoff.summary`. "You've been confusing X and Y" is design input, not a teaching opening.

## Writing Better Memory

Each `log-answer` entry must let a future agent reconstruct what was tested, what the learner got wrong, and what the correct rule is.

**Four-layer field discipline.** A log entry has four layers, each with one job; keep them separate (this is the canonical statement — `study-review-turn.md` summarizes it):

1. **Identity** — `--inventory-concept-id` (the canonical key), topic, claim-state ids. Matching, sequencing, and calibration run on this layer **only**. Resolve the probed concept to its inventory id; never let a prose label stand in as identity.
2. **Categorical** — controlled vocabularies: `--cognitive-op`, `--error-type`, `--answer-mode`, `--confidence-observed`, `--teaching-move`, `--coverage-role`, `--priority`, `--correct`. These drive calibration.
3. **Numerical** — attempts, successes, stability, retrievability. Managed by the engine; never reconstructed from a rounded value.
4. **Subjective** — verbatim judgment the next agent *reads*: `tested_claim`, `learner_claim`, `misconception`, `corrected_rule`, `clinical_consequence`, `retest_prompt_shape`. Put all specifics here.

- `concept`: a short, atomic, canonical concept name (ideally the inventory node's name) — **not** a verbose phrase, a conjunction (`"X and Y"`), a comparison (`"X vs Y"`), or a sentence with embedded trial/evidence detail. Those belong in `tested_claim`. `log-answer` emits `WARN atomicity ...` when a label violates this; relabel rather than ignore.
- `tested_claim`: the atomic rule/threshold/discriminator under test — the agent's verdict on the answer ("Correct:", "Partial —") does not belong here.
- `misconception`: specific wrong belief when `correct=0`. `correction`: right answer. `error_type`: teaching-relevant failure mode.
- Retrieval metadata: `teaching_intent`, `expected_answer_edge`, `coverage_role`, source fields make future retrieval concise.
- Claim-state flags: use `--match-claim-state-id`, `--repairs-claim-state-ids`, and `--new-claim` instead of relying on token overlap.
- Read the `binding={...}` line after each assessed exchange: `explicit` (target state), `inferred` (provisional — pass `--inventory-concept-id` next turn), or `unresolved` (a possible inventory gap — propose a node via `inventory-authoring.md`, do not force a wrong binding).
