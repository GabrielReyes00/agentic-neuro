# Memory Maintenance

Single-purpose contract for deliberate learner-memory maintenance. Do not run these commands inside routine teaching loops.

## Identity Audit

Run before advanced graph work, after repeated topic-resolution drift, or during a memory-layer audit:

```bash
python3 src/study_memory.py identity-audit
python3 src/study_memory.py telemetry-audit
```

Review output manually. Duplicate-topic and duplicate-claim-state candidates are audit surfaces, not automatic merge instructions.

## Topic Merge

`merge-topics` is dry-run by default:

```bash
python3 src/study_memory.py merge-topics \
  --from-topic "<exact source slug or alias>" \
  --into-topic "<exact target slug or alias>"
```

Review `affected_rows` and `concept_collisions`. Apply only after review:

```bash
python3 src/study_memory.py merge-topics \
  --from-topic "<exact source slug or alias>" \
  --into-topic "<exact target slug or alias>" \
  --apply
```

The command refuses same-slug concept collisions rather than guessing. Resolve those explicitly before merging.

## Reference Graph

The reviewed reference graph is separate from the learner graph:

- `concept_relationships`, `shadow_rules`: learner-specific evidence authored through post-session curation.
- `reference_nodes`, `reference_edges`: reviewed clinical context used only for bounded context weighting.

Load a reviewed JSON sidecar with a dry-run first:

```bash
python3 src/study_memory.py load-reference-graph --input data/reference_graph_seed.json
python3 src/study_memory.py load-reference-graph --input data/reference_graph_seed.json --apply
```

Every reference node and edge requires provenance and a review date. Use typed edges and `required_context_any` predicates where a relationship applies only under a clinical condition. Retrieval traversal is capped at two hops and never overrides urgent learner gaps.

## Routine Maintenance Cadence

The commands above are for *deliberate* audits — explicit memory-layer reviews, repeated topic-resolution drift, or seeding the reference graph. They are not part of the teaching loop.

Routine identity and telemetry audits do not need a separate invocation: the post-flush curation pass already carries them. When `curation.recommended` is `true`, `curate-candidates` returns a `maintenance` block with `identity_audit` and `telemetry_audit` results, and any duplicate-topic merges are proposed from there. See `memory-curation.md`. Run the standalone commands in this file only when auditing outside that cadence.

## Guardrails

- Never auto-merge identity candidates.
- Never generate reference edges from learner misses.
- Never write learner relationships or shadow rules outside `apply-curation`.
- Never treat a graph path as a teaching mandate; verify that the path fits the clinical context.
