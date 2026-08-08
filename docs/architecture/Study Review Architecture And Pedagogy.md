# Study Review Architecture And Pedagogy

Date: 2026-08-08  
Runtime state: `tutor_state_v1`  
Turn schema: `turn_assessment_v1`  
Learner-memory schema: 8

## Operational Summary

Study-review is now a bounded teaching loop rather than a large prompt followed
by several loosely coordinated writes:

```text
typed start-session
    -> compact TutorState
    -> one clean question
    -> learner commits
    -> grade each claim independently
    -> complete, bounded repair
    -> one atomic assess-turn transaction
    -> policy + next target
    -> repeat or integrity-gated close-session
```

The workflow still uses the canonical curriculum graph, learner evidence,
requested artifact, Obsidian context, native clinical reasoning, source
verification, and Anki. The difference is that each source enters only when it
can change the current teaching decision.

## What Changed

| Prior behavior | Current behavior |
|---|---|
| Startup exposed a large `planning_brief` and often required the agent to interpret many raw surfaces. | `start-session --stdin` emits a bounded TutorState with the current phase, active target, exact evidence, at most eight active map nodes, at most five queued targets, and at most three one-hop context candidates. |
| Rich memory/audit instructions loaded at workflow entry. | Entry loads only the runtime projection, startup contract, and TutorState contract. Rich retrieval interpretation is an audit-only branch. |
| One learner answer could require separate exchange, claim, policy, and card-decision writes. | One idempotent `assess-turn --stdin` transaction writes the raw answer, every independently graded claim, evidence dimensions, learner-state changes, policy event, lifecycle state, and one card disposition. |
| A partial answer could be collapsed into a single score. | The ledger preserves `demonstrated_edge` and `missing_edge`, plus independence, reasoning depth, safety impact, cognitive operation, and verification status. |
| An uncertain current rule could be forced into correct/incorrect. | `pending_adjudication` records the unresolved claim without creating a miss, mastery update, or Anki card. |
| Filesystem session maps behaved like live state. | SQLite is authoritative; the session map is an atomic, rebuildable projection written only after database commit. |
| Document maps could be reused without proving that the document was unchanged. | Artifact maps are usable only at schema v2 with a matching current content hash. Section hashes and source provenance support just-in-time section loading. |
| Vault SQLite and vector results could represent different generations. | Every recall filters stale paths and reports SQLite/vector generation agreement. `complete_fresh` is required for a clean combined result. |
| PGY was partly implicit or hard-coded. | `learner_profile` stores explicit PGY/service expectations. PGY determines expected responsibility; observed concept evidence determines mastery and scaffolding. |

## Teaching Policy

The optimization target is learning per turn, not minimal prose and not maximal
question count.

Before commitment, preserve cognitive friction: one answerable question, no
hints, thresholds, diagnosis labels, or embedded answer context. After
commitment, grade briefly and repair completely enough to change the learner's
model. The default repair sequence is:

1. verdict;
2. preserve the genuinely correct edge;
3. identify the missing or false edge;
4. teach the causal anatomical, physiological, pathological, biomechanical, or
   operative model;
5. state the management or operative consequence;
6. contrast the nearest plausible alternative;
7. compress the rule into a recognition cue; and
8. test near transfer in a changed frame.

Not every response needs every sentence. A partial response gets one diagnostic
follow-up only when the missing edge appears accessible but incompletely
expressed. Otherwise the tutor teaches the missing information immediately
instead of forcing blind guessing. Correct-but-shallow performance escalates to
mechanism, discriminator, threshold, sequence, complication, or transfer; it
does not become mastery from repeated factual recall.

ORIENT and REMEDIATE remain single-focus. DEEPEN and CONNECT may request two or
three tightly coupled outputs when they test one coherent clinical model. Those
outputs are stored as separate claims, so a strong localization answer cannot
hide a weak management answer.

## Phase And Expansion Control

The phase controller is deterministic where safety and evidence require it:
active misconceptions, safety-critical gaps, due retention, and unresolved
provenance are binding. Otherwise its phase is a recommendation. A tutor may
override sparse, degraded, or misbound evidence only by recording the override
and reason.

The current artifact or active curriculum target remains central. Nearby
knowledge expands in this order:

```text
artifact/core target
    -> blocking prerequisite
    -> confuser or discriminator
    -> clinical/operative consequence
    -> one-hop transfer bridge
```

Ordinary turns introduce at most one nearby node. A second hop requires an
explicit explanatory bridge. Omitted-node counts are pointers, not an
instruction to load the whole map; `node-recall` retrieves one selected node.

## Persistence Contract

One raw learner response has one `turn_assessments` envelope and one Anki card
decision. It may have multiple `claim_assessments` and graded `claim_results`.
The idempotency key makes a retry non-duplicating.

The durable evidence dimensions are intentionally separate:

- categorical accuracy: incorrect, partial, or correct;
- independence: unaided, prompted, hinted, after teaching, or self-corrected;
- reasoning depth: unknown, factual, relational, causal, or transfer;
- safety impact: none through critical;
- cognitive operation: recall, discrimination, quantification, sequencing,
  mechanism, or transfer;
- verification status: not required, verified, unverified, conflicting, or
  pending adjudication.

Session closure first verifies that every assessed exchange has a typed turn
envelope and card disposition and every graded claim has dimensions. The
handoff and `done` lifecycle state commit before the ephemeral map is deleted.

Service/site-local learning remains provenance-isolated. Formal study-review
refuses the service lens; local teaching enters through shift-debrief/service-log
and becomes formal learner evidence only after portable content is explicitly
reviewed under the proper boundary.

## Measured Results

The current benchmark uses exact `cl100k_base` token counts and an ephemeral
SQLite backup of the active learner database:

| Measure | Rich/flat comparator | Current routine path | Change |
|---|---:|---:|---:|
| Study-review instruction entry | 8,873 tokens | 2,473 tokens | 72.1% reduction |
| Learner-state startup packet | 32,268 tokens | 3,056 tokens | 90.5% reduction |
| Local startup median | 175.33 ms audit | 150.04 ms TutorState | 14.4% lower |

The routine packet retained eight active nodes, three nearby candidates, exact
learner-evidence pointers, and a one-hop limit. The database migration preserved
78 sessions, 302 raw exchanges, 295 claim results, and 235 claim-state rows with
clean quick-check and foreign keys. Four existing artifact maps were revalidated
against current file bodies, upgraded to hash-matched v2 maps, and six incorrect
ABNS cortex/cerebellum bindings were corrected.

The vault index now contains 97 current notes and 786 sections with zero stale,
missing, unindexed, or parse-error paths. The vector table was regenerated from
the same SQLite generation; a live EVD repair query returned
`complete_fresh`, generation match, and zero discarded stale hits.

## Evaluation Boundary

Deterministic tests prove schema, transaction, idempotency, lifecycle, freshness,
graph, and context-budget behavior. They do not prove that a prose explanation
causes better retention. `evals/study_review_cases.json` therefore defines seven
transcript scenarios covering the opening boundary, partial and wrong-answer
repair, correct-but-shallow escalation, current-source uncertainty, multi-claim
grading, PGY calibration, and nearby-node limits. Candidate transcripts must be
judged by a human or independent model before claiming a teaching-effectiveness
gain; the repository grader checks those judgments exactly and does not use
keyword matching as a substitute.

## How To Use It

- Invoke study-review with a topic, current vault document, weak-spot request,
  or board-style review request as before.
- Expect the first response to be one question, not a memory summary or menu.
- Answer the question directly; the tutor can now distinguish multiple claims
  within one response and preserve partial knowledge precisely.
- Ask for rapid-fire or oral-board posture when desired. Posture changes tone
  and surface form, while evidence still determines phase and safety gates.
- Stop naturally. The workflow no longer tries to end after an arbitrary five
  or six turns; it offers a digest after 12 turns and closes at a meaningful
  phase or coverage boundary.
