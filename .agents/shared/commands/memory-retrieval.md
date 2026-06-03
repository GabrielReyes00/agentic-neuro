# Memory Retrieval Intelligence

Single-purpose contract for interpreting `study_memory.py startup-recall` output. Raw `summary` remains available for deeper audits.

The database stores facts. The agent supplies judgment. Memory is evidence for teaching design, not a rigid routing table and not learner-facing narration.

## Read Path

Use a staged agent-facing read path:

```bash
python3 src/study_memory.py startup-recall --profile doc --topic "<topic>" --doc "<folder>/<file>.md"
```

For memory-driven global review only:

```bash
python3 src/study_memory.py startup-recall --global
```

Always read `startup_recall`, `planning_brief`, `counts`, `omitted`, and `retrieval_guidance` before teaching. `planning_brief` is the ordered first-read tutor context.

Startup profiles:
- `--profile doc`: default for document-anchored review. It is compact and document-primary: it returns handoff, top open gaps, top recent repairs, due scaffolds, capped related-context candidates, and a fallback `full_evidence_command`. Use this for `/study-review --doc`.
- `--profile memory`: topic/global review planning. Topic-scoped memory recall expands omitted high-signal cards automatically; global startup stays compact and returns `ready_to_teach = false`.
- `--profile audit`: full rich startup surface for troubleshooting, learner-model audits, or ambiguous/safety-critical compact briefs.
- `--profile auto`: chooses `doc` when `--doc` is present, otherwise `memory`.

For doc review, do not expand just because `counts` or `omitted` are nonzero. Expand only when the compact brief is ambiguous, safety-critical high-signal material appears omitted, or the learner explicitly asks for a memory-driven detour. For memory-driven global review, use `startup_recall.deferred_high_signal` as a prompt for candidate selection, then run topic-scoped startup recall for selected topics.

If `planning_brief.resolution_warning` is present, do not begin teaching from an empty or guessed topic envelope. Validate one of `resolution_candidates` as the intended existing learner-state anchor, rerun topic-scoped recall with that anchor, and clarify with the learner only when the correct curriculum scope remains ambiguous.

If scaffold cards were omitted, expand `--scaffold-limit` only when you need a coverage map or transfer-question premises. Scaffolds are confirmed knowledge, not primary drill targets. For memory-driven global review, use `--include-global-scaffolds` only when no stronger due gaps dominate.

Inspect the full non-brief summary, raw exchange rows, or claim rows only when the compact brief is ambiguous, when truncation requires expansion, or when auditing the learner model.

## Planning Brief

In `profile=doc`, read `planning_brief` as a compact session-start contract:

1. **`handoff`**: the previous session directive, if any.
2. **`teaching_priorities`**: the ranked blend of open gaps, recent repairs, and stale scaffolds.
3. **`contextual_frontier`**: capped related-context candidates. Accept only candidates central to the requested document.
4. **`question_design_bias`** and **`domain_patterns`**: small shaping signals, not a mandate.
5. **`fallback.full_evidence_command`**: use only when compact startup is insufficient.

In `profile=memory` or `profile=audit`, read `planning_brief` in order:

1. **`handoff`**: the latest learner-session directive. Artifact-generation anchors do not compete with this surface.
2. **`open_first`**: unresolved claims that deserve the first questions.
3. **`recent_repairs`** and **`known_scaffolds_due`**: changed-frame retention checks and stale premises.
4. **`domain_patterns`** and **`misconception_rules`**: curated cross-session fault lines and evidence-backed false rules.
5. **`contextual_frontier`**: bounded neighboring foundations from learner graph edges, reviewed reference-graph paths, report-local scaffolds, and cautious cross-topic overlap.
6. **`question_design_bias`**: confidence calibration, weak cognitive operations, and teaching-move evidence.
7. **`low_confidence_leads`**: curiosity and artifact hints only.

Before teaching, execute `agent_validation_checkpoint` silently. Accept only 1-3 frontier candidates that are clinically central, within the requested curriculum boundary, and likely to explain an active gap or deepen transfer. Reject tangents. Frontier candidates shape questions; they never override urgent open claims.

## Retrieval Surfaces

Read the JSON in this order:

1. **`cards`**: per-claim-state retrieval cards: `must_retest`, `recent_repair`, `scaffold`, `session_handoff`. This is the raw triage evidence behind `planning_brief`.
2. **`curated_summaries`**: agent-authored cross-session synthesis. This is the strategic surface: recurring patterns across sessions.
3. **Learner graph surfaces**: `graph_signals` and `shadow_rule_signals`. These are evidence-backed discrimination and false-rule repair inputs.
4. **Model surfaces**: `due_claims`, `calibration_profile`, `operation_profile`, `teaching_move_profile`, `telemetry_profile`, `tutor_efficacy_profile`, `coverage_frontier`, and `shadow_queue`.
5. **Context surfaces**: optional `context_focus` and `context_graph_focus` when `--context` is present. These weight session planning; they do not override urgent gaps.

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
- `shadow_queue`: low-weight implied interest from quick answers and generated artifacts. Probe later, but never treat it as mastery or a miss until tested.
- `contextual_frontier`: bounded candidate foundations for agent validation. It is intentionally broader than the final session plan. Reject weakly connected candidates rather than treating lexical or graph adjacency as a teaching mandate.
- `context_focus`: only appears when the command includes `--context "<case/rotation/upcoming focus>"`; use it to weight, not override, due and safety-critical gaps.
- `context_graph_focus`: reviewed reference-graph paths, capped at two hops and filtered by context predicates. Verify the path makes clinical sense before using it. Learner graph edges and the reference graph are separate layers.

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
