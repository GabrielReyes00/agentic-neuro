# Study Review Turn

Load this after Gabriel answers an assessed clinical question. It governs grading, repair, logging, Anki enqueue, and next-question selection.

## Response Pattern

1. Grade briefly: correct, partial, or incorrect.
2. Reveal only the next useful layer. Do not dump the topic map after a shallow answer.
3. If wrong or partial, repair the exact missing edge, false rule, discriminator, threshold, mechanism, or sequence.
4. Choose the next question from the deterministic policy. `log-answer` recomputes it from the updated learner state and prints a self-sufficient `policy=...` line carrying `mode`, `phase`, `interrupts`, `target_concepts`, `pedagogical_directives`, and `socratic_choice_directives` (see Memory Logging below). Obey it — never pick the phase yourself. Each turn's policy line supersedes the startup plan; you do not need to retain the startup brief to follow it.
   - **ORIENT** (`phase_1_clear_fog`): keep questions superficial; present a "lay of the land" menu at boundaries.
   - **DEEPEN** (`phase_2_recalibrate_gaps`): deepen with Socratic drills on active gaps, prerequisites, and discriminators.
   - **CONNECT** (`phase_3_force_connections`): ask multi-concept transfer cases across already-seen concepts; encourage boards-style defense.
   - **Interrupts**: if `interrupts.remediate` is non-empty, re-teach the flagged misconception and retest with a changed frame before new material; if `interrupts.consolidate` is non-empty, interleave a brief spaced-retrieval probe of a due claim. Interrupts overlay the current phase. When both fire, remediate comes first; the full tie-break order is "Signal Precedence" in `adaptive-teaching-doctrine.md`.
   - **Socratic Choice**: proactively offer Gabriel choices at boundaries per `socratic_choice_directives`.
5. Ask one question or choice menu, then stop.

Use high-friction Socratic questioning before commitment; use clarity and depth after commitment. Push beyond generic recall toward discrimination, quantification, sequencing, mechanism, management consequence, or transfer as performance supports.

## Point-Of-Need Vault

Load `.agents/shared/commands/study-review-vault-repair.md` only when a miss, partial answer, shallow safety-critical edge, explicit request, local/service issue, or adjacent-note comparison would benefit from targeted Obsidian context. Vault recall is not routine between turns.

## Memory Logging

Log every assessed clinical answer silently:

```bash
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" --topic "<topic>" --concept "<specific concept>" \
  --question "<verbatim question>" --answer "<verbatim answer>" \
  --correct <0|1|2> \
  --doc "<folder>/<file>.md" --skill "study-review" \
  --tested-claim "<tested rule/threshold/discriminator>" \
  --learner-claim "<committed answer summary>" \
  --answer-mode "<unaided|prompted|after_hint|after_teaching|self_corrected>" \
  --confidence-observed "<low|medium|high|hesitant|fluent>" \
  --teaching-move "<initial_probe|contrastive_drill|mechanism_first|order_set|premortem|visual_probe|changed_frame_retest|other>" \
  --strict-telemetry \
  [--correction "<right rule>"] [--error-type "<type>"] [--misconception "<wrong belief>"] \
  [--missing-edge "<missing edge>"] [--corrected-rule "<replacement rule>"] \
  [--clinical-consequence "<why it matters>"] [--retest-prompt-shape "<future probe>"] \
  [--learning-operation "<recall|discrimination|quantification|sequencing|mechanism|transfer>"] \
  [--teaching-intent "<new_material|retest_open_gap|repair_after_miss|transfer_check|retention_check|synthesis>"] \
  [--expected-answer-edge "<edge needed for full credit>"] [--coverage-role "<primary_doc|related_topic_probe|repair_probe|memory_probe>"] \
  [--source-section "<heading>"] [--source-anchor "<anchor>"] [--curriculum-unit "<unit>"] \
  [--priority "<urgent|high|medium|low>"] \
  [--match-claim-state-id <id>] [--new-claim] [--repairs-claim-state-ids "<id,id,...>"] \
  [--brain-dump-candidate-id <id>] \
  [--inventory-concept-id "<inventory.concept_id>"]
```

Correctness: `2` correct without help, `1` partial, `0` wrong/misconception.

`log-answer` prints `OK exchange_id=N` followed by a `policy={...}` line with the recomputed `mode`, `phase`, `interrupts` (`remediate`, `consolidate`, `escalate`), `target_concepts` (capped, with `target_concepts_omitted` when truncated), `pedagogical_directives`, `socratic_choice_directives`, `decision_inputs` (including lean `weak_operations` and `binding_quality`), optional `probe_feedback` after misses/partials (`cognitive_op` + `retest_hint`), optional `orient_skip`, and during ORIENT an `orient_menu` of inventory nodes. An optional compact `session_progress={...}` line may include `probe_quality`. Parse both silently. Policy is computed from the live session knowledge map (patched incrementally each turn). Pass `--inventory-concept-id` whenever the probed concept is on the session map — required for assessed `study-review` exchanges when resolvable. Pass `--cognitive-op` when the failed operation is obvious; otherwise the classifier infers it from the tested claim. Legacy concepts without IDs are lexically matched when possible; unmatched rows retry on future surfacing.

Before probing a map node whose `learner_surface` is absent or thin, run point-of-need drilldown:

```bash
python3 src/study_memory.py node-recall --inventory-concept-id "<id>" --topic "<topic>" --session "$SESSION_TS"
```

Use `learner_surfaces`, `shadow_rules`, and `inventory_edges` silently to design the next question.

The same full plan is persisted to `policy_events.plan_json` for audit only; you do not write it yourself. If a `policy_status={"status":"unavailable",...}` line appears instead, keep the current phase, continue teaching, and rerun `startup-recall` if it persists — never invent a phase change yourself.

`--coverage-role` in study-review uses `primary_doc`, `related_topic_probe`, `repair_probe`, or `memory_probe`. The `synthesis` value exists for other workflows only; study-review never logs synthesis prompts (see below).

Use `--match-claim-state-id` for intentional retests from recall. Use `--repairs-claim-state-ids` only for explicitly repaired open claims. Use the primary document topic for native document concepts; use the related topic's canonical name for validated related-topic probes.

Never log a tracked claim for a synthesis/self-assessment prompt.

## Anki Enqueue

After `log-answer`, use the printed `exchange_id` for any card enqueue. Create cards for incorrect, partial, high-yield corrected rules, and fragile transfer edges; skip trivial correct recall.

Load `.agents/shared/commands/anki-card-quality.md` before drafting cards if card wording is nontrivial. Use `anki_queue.py enqueue` per turn (flush at session end); pass `--inventory-concept-id` when known. Do not write directly to Anki. Preserve stable metadata tags produced by flush: `topic/<slug>`, `concept/<slug>`, `claim/<claim_id>`, `inv/<inventory_concept_id>`, and provenance tags.

## Continue Or End

After 5-6 evaluated exchanges, ask whether to wrap up or continue. At 12+ turns, offer a brief digest before continuing.

When Gabriel wants to stop, the checkpoint triggers a wrap-up, or the key material is substantially covered, load `.agents/shared/commands/study-review-end.md`.

