# Study Review Turn

Load after Gabriel answers. This contract owns assessment, repair, atomic
logging, Anki disposition, and the next question.

## Teach For Maximum Learning Per Turn

Before commitment, preserve friction: one clean question without hints. After
commitment, be concise in grading but complete in repair.

Default repair bundle:

1. verdict;
2. preserve what was genuinely correct;
3. identify the exact missing or false edge;
4. teach the causal anatomical, physiological, pathological, biomechanical, or
   operative model;
5. state the management or operative consequence;
6. distinguish the nearest plausible alternative;
7. compress the rule into one recognition cue; and
8. ask a changed-frame near-transfer question.

Use only the elements the response needs, but never reduce a technical repair
to a bare fact. For a partial response, ask one diagnostic follow-up only when
the missing edge appears accessible but incompletely expressed. Otherwise
teach it immediately; do not make the learner guess at undisclosed information.

ORIENT and REMEDIATE remain single-focus. In DEEPEN or CONNECT, one prompt may
request two or three tightly coupled outputs—such as localization, consequence,
and plan-changing discriminator—when they test one coherent clinical model.
Persist each independently judged claim from that response.

## Phase And Nearby-Node Control

Read the returned `policy` after each typed assessment.

- Hard constraints are binding: active misconception, safety-critical gap,
  due-retention check, and unresolved provenance.
- Otherwise the phase is a deterministic recommendation. Override only for
  sparse, degraded, or misbound evidence and record `phase_override` plus reason
  in the next request.
- REMEDIATE precedes CONSOLIDATE. Repair must use a different explanatory move
  after a repeated miss.
- ORIENT builds a usable schema; DEEPEN establishes causal, discriminative,
  quantitative, sequential, and execution competence; CONNECT tests transfer
  across already established nodes.
- Introduce at most one nearby node per ordinary turn, in this order: blocking
  prerequisite → confuser/discriminator → complication/consequence → one-hop
  transfer. A second hop requires an explicit explanatory bridge.

## Source Verification

After the learner commits, verify any conduct-changing dose, threshold, timing,
reversal, classification, surveillance rule, guideline claim, or controversy.
Any textbook retrieval follows `.agents/shared/commands/rag-routing.md`; current
conduct-changing claims still require current primary verification.
Do not persist `verification_status=verified` without actually checking the
appropriate source. If safe grading is not possible, store
`pending_adjudication`; this creates no claim state or mastery update.

If the requested artifact lacks the prerequisite, confuser, or consequence
needed for a focused repair, load `study-review-vault-repair.md` at that point;
do not preload semantic vault recall for routine startup or ordinary turns.

## Canonical Atomic Write

Submit one JSON object through stdin:

```bash
python3 src/study_memory.py assess-turn --stdin
```

Required envelope:

```json
{
  "schema_version": "turn_assessment_v1",
  "idempotency_key": "<session>:turn:<stable ordinal>",
  "session_id": "<SESSION_TS>",
  "topic": "<topic>",
  "doc_path": "<optional vault-relative path>",
  "question": "<verbatim question>",
  "answer": "<verbatim committed answer>",
  "strict_telemetry": true,
  "claims": [],
  "card_decision": {
    "decision": "enqueue|skip_routine_correct|skip_equivalent|skip_low_value|skip_not_durable|defer_unavailable",
    "rationale": "<required for skip/defer>"
  }
}
```

Each `claims[]` item contains one atomic canonical concept and one independently
gradable claim:

```json
{
  "concept": "<canonical atomic name>",
  "inventory_concept_id": "<canonical id when resolvable>",
  "assessment_status": "graded|pending_adjudication",
  "accuracy": 0,
  "tested_claim": "<rule, threshold, discriminator, or decision edge>",
  "learner_claim": "<what the learner committed to>",
  "demonstrated_edge": "<preserved correct edge>",
  "misconception": "<explicit false belief, not an omission>",
  "missing_edge": "<specific absent edge>",
  "corrected_rule": "<replacement rule>",
  "clinical_consequence": "<why conduct changes>",
  "independence": "unaided|prompted|after_hint|after_teaching|self_corrected",
  "reasoning_depth": "unknown|factual|relational|causal|transfer",
  "safety_impact": "none|low|moderate|high|critical",
  "operation_demonstrated": "<recall|discrimination|quantification|sequencing|mechanism|transfer>",
  "learning_operation": "<same controlled cognitive-operation vocabulary>",
  "confidence_observed": "low|medium|high|hesitant|fluent",
  "teaching_move": "initial_probe|contrastive_drill|mechanism_first|order_set|premortem|visual_probe|changed_frame_retest|other",
  "teaching_intervention": "<repair actually delivered>",
  "verification_status": "not_required|required|verified|unverified|conflicting",
  "coverage_role": "primary_doc|related_topic_probe|repair_probe|memory_probe",
  "source_section": "<artifact section>",
  "source_anchor": "<stable anchor>"
}
```

For `pending_adjudication`, omit `accuracy` and add `adjudication_reason` and
`source_needed`. It preserves uncertainty without creating a miss or mastery
claim.

For partial credit, store both `demonstrated_edge` and `missing_edge`. Identity,
categorical grading, numerical scheduler state, and subjective evidence remain
separate. Use `match_claim_state_id`, `new_claim`, or
`repairs_claim_state_ids` only when intentionally controlling claim identity.

The transaction writes the raw exchange, every graded claim result, assessment
dimensions, learner-state changes, policy event, runtime lifecycle, and one
Anki decision together. Its idempotency key makes retries safe. The session map
is written atomically only after commit and can be rebuilt from SQLite.

## Card Follow-Through

The card decision is part of the assessment transaction. If `enqueue`, load
`anki-card-quality.md`, enqueue one to three cards using the returned
`exchange_id`, and protect only durable management-changing traces. A miss is
not automatically card-worthy.

## Continue Or Close

Ask the next question and stop. Offer a digest at 12 or more turns. Offer to
wrap at a natural coverage or phase boundary—not after a fixed exchange quota.
When Gabriel stops or the intended material is substantially covered, load
`study-review-end.md`.
