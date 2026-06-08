# Study Review Turn

Load this after Gabriel answers an assessed clinical question. It governs grading, repair, logging, Anki enqueue, and next-question selection.

## Response Pattern

1. Grade briefly: correct, partial, or incorrect.
2. Reveal only the next useful layer. Do not dump the topic map after a shallow answer.
3. If wrong or partial, repair the exact missing edge, false rule, discriminator, threshold, mechanism, or sequence.
4. Ask one follow-up or next question, then stop.

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
  [--brain-dump-candidate-id <id>]
```

Correctness: `2` correct without help, `1` partial, `0` wrong/misconception.

Use `--match-claim-state-id` for intentional retests from recall. Use `--repairs-claim-state-ids` only for explicitly repaired open claims. Use the primary document topic for native document concepts; use the related topic's canonical name for validated related-topic probes.

Never log a tracked claim for a synthesis/self-assessment prompt.

## Anki Enqueue

After `log-answer`, use the printed `exchange_id` for any card enqueue. Create cards for incorrect, partial, high-yield corrected rules, and fragile transfer edges; skip trivial correct recall.

Load `.agents/shared/commands/anki-card-quality.md` before drafting cards if card wording is nontrivial. Use `anki_queue.py enqueue`; do not write directly to Anki. Preserve stable metadata tags produced by flush: `topic/<slug>`, `concept/<slug>`, `claim/<claim_id>`, and provenance tags.

## Continue Or End

After 5-6 evaluated exchanges, ask whether to wrap up or continue. At 12+ turns, offer a brief digest before continuing.

When Gabriel wants to stop, the checkpoint triggers a wrap-up, or the key material is substantially covered, load `.agents/shared/commands/study-review-end.md`.

