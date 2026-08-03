# Learner Memory Layer Overhaul

## Objective

Preserve a longitudinal, claim-centered learner model that future agents can use to reconstruct what Gabriel knows, what remains fragile, the exact misconception or missing edge, what teaching move was tried, and how evidence transfers across documents, rotations, topics, and time. Improve fidelity and efficiency without weakening the shared Codex, Claude, or Gemini workflows.

## Baseline

The initial behavioral benchmark passed 1 of 7 cases (mean score 0.2143). The live EVD topic startup packet was 96,564 bytes at roughly 92 ms median warm latency. Important failures were:

- concept-wide misconceptions leaked onto unrelated atomic claims;
- the store could not separately represent what a partial answer got right, the explicit false belief, and the intervention actually used;
- the same inventory concept lost history when learned under another report, service, or topic envelope;
- explicit cross-domain comparison queries were pruned to one domain;
- one successful transfer probe immediately labeled a concept `transfer_ready`;
- the identity audit treated every multi-claim concept as a duplicate;
- weak one-word historical matches blocked valid new inventory-grounded topics;
- routine startup repeated rich evidence and grew further to 128,451 bytes after exact traces were added;
- copied/test databases could accidentally receive the production learner overlay;
- curation relationship hints treated a single same-session co-miss as relationship evidence.

## Implemented Design

### Claim fidelity

Schema version 6 adds `demonstrated_edge`, `misconception_text`, and `teaching_intervention` to `claim_results`. Strict partial logging requires a demonstrated edge. Retrieval uses an exact topic + concept + claim-slug trace, so one EVD claim cannot inherit another EVD claim's misconception. The trace preserves the tested claim, learner commitment, raw answer, preserved and missing edges, explicit misconception, corrected rule, clinical consequence, retest shape, prior intervention, cognitive operation, calibration metadata, and recent outcomes.

### Canonical longitudinal identity

Inventory projection now aggregates every assessed claim explicitly bound to an in-scope canonical node across all topic/document/service envelopes. Unbound lexical evidence remains topic-scoped. The map retains the source memory context count, while exact claim states remain separate beneath the canonical node.

### Conservative mastery

Mastery is derived from counted cognitive-operation evidence and distinct session IDs. One successful transfer probe produces `relational`; `transfer_ready` requires at least two successful transfer probes across at least two sessions and no active gap. The same rule is used during startup projection, SQLite fallback, artifact overlays, and live session-map patching.

### Routing and scope

Queries explicitly using compare/across/versus preserve multiple domains. A valid inventory-grounded new topic may enter ORIENT when no existing learner topic has a strong overlap; weak one-word neighbors remain visible as leads but do not block teaching. Stronger historical overlaps still require validation to prevent identity fragmentation.

### Efficient agent surface

Routine topic-memory startup computes policy from the full evidence set, then returns a bounded agent-ready packet: the highest-priority exact claim traces, a compact canonical map, explicit deferred counts, and node-level drilldown. `profile=audit` remains the full diagnostic surface. The live EVD packet is now about 41.5 KB, with full-policy computation and drilldown discoverability preserved.

### Audit and curation precision

The identity audit now performs pairwise semantic near-duplicate detection within the same topic, concept, and provenance envelope. Distinct atomic claims are not duplicates. Telemetry separates legacy, incomplete-modern, and calibration-grade cohorts; only calibration-grade rows are appropriate for tutor-efficacy inference. Curation packets preserve partial-answer evidence, and relationship hints require either explicit concept cross-reference or recurrence across at least two sessions. No candidate is auto-applied.

### Isolation and agent compatibility

Inventory projection reads the SQLite database held by the caller, preventing copied dry-runs or tests from silently overlaying production state. Shared contracts remain the authority. Codex skills, Claude commands, Gemini commands, and repo-local Codex slash commands remain thin adapters to the same startup, turn, end, memory, and curation contracts.

## Final Benchmark

Run:

```bash
source .venv/bin/activate
python3 benchmarks/benchmark_memory_layer.py
```

Final result: 9 of 9 cases pass (mean score 1.0).

| Case | Result |
|---|---:|
| Exact claim-trace precision | 1.0 |
| Cross-topic canonical recall | 1.0 |
| Cross-domain query coverage | 1.0 |
| Conservative mastery calibration | 1.0 |
| Longitudinal repair state machine | 1.0 |
| Capture-schema fidelity | 1.0 |
| Identity-audit precision and recall | 1.0 |
| New-topic orientation | 1.0 |
| Startup packet efficiency/discoverability | 1.0 |

Representative final live-copy measurement: 41,502 bytes, 99.34 ms median, with node drilldown discoverable. Packet size is approximately 57% below the original routine packet and 68% below the unbounded exact-trace intermediate.

## Live-Data Audit on a Migrated Copy

- SQLite integrity: `ok`
- schema version: 6
- topics: 40
- assessed claim results: 295
- duplicate topic candidates: 0
- duplicate atomic-claim candidates: 1 plausible pair (induced hypertension for DCI)
- legacy imports: 172
- modern rows: 123
- calibration-grade modern rows: 30
- incomplete modern rows: 93
- sessions since curation: 9 (threshold 5; curation recommended)
- high-precision relationship hints in the current compact five-session packet: 0

The zero historical coverage for the three newly introduced subjective fields is expected: partial-answer preserved edges, explicit misconception text, and prior teaching intervention cannot be reconstructed safely from old rows. They remain valid historical evidence but are not silently upgraded to calibration-grade evidence.

## Preserved Boundaries

- No historical learner claim was deleted, rewritten, or fabricated.
- No topic merge, concept realignment, relationship, summary, or shadow rule was auto-applied.
- Sparse curated graph state is not treated as failure when the evidence floor is unmet; the canonical inventory graph still supplies curriculum structure.
- Deferred startup evidence remains queryable through `node-recall` and the audit profile.
- Anki remains advisory and cannot clear a SQLite misconception.

## Remaining Reviewed Work

The live database has one plausible near-duplicate atomic-claim pair and is due for a user-reviewed curation pass. Those are review queues, not blockers and not permission for automatic mutation. Future assessed partial answers should use strict telemetry so demonstrated edges, explicit misconceptions, and teaching interventions accrue prospectively.
