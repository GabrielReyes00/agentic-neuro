# Memory Maintenance

Single-purpose contract for deliberate learner-memory maintenance. Do not run these commands inside routine teaching loops.

This is audit-only by default and uses the runtime-provided `RUN_DIR`. Preserve
the exact audit findings and any proposed mutation payload there as `audit`
artifacts. Stop at the approval node before `--apply`, `--vacuum`, or any other
learner-memory mutation. After approval, take an exact database backup, apply
only the reviewed target, and rerun health plus the originating audit.

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

## Database Maintenance

`maintain` refreshes the query planner statistics and reclaims space. It is fast, idempotent, and never alters learner rows:

```bash
python3 src/study_memory.py maintain
```

This runs `ANALYZE` (repopulates `sqlite_stat1` so the hot recall/rollup queries keep resolving via index instead of table scans) and `PRAGMA optimize`. Run it after a bulk change — migration, consolidation, large `merge-topics` apply, or a node import — anytime row counts shift enough that the planner's stats go stale.

Add `--vacuum` only after large row deletions, to reclaim freed pages:

```bash
python3 src/study_memory.py maintain --vacuum
```

`--vacuum` rewrites the whole file under a write lock, so it is heavier — reserve it for post-deletion cleanup, not routine refreshes. Schema upgrades do not need a manual call: `_get_db` is schema-versioned (`PRAGMA user_version` gated against `SCHEMA_VERSION`) and runs the migration plus `ANALYZE` once when it first opens a database below the current version, then skips that work on every later connection.

## Knowledge Map Overview

`knowledge-map` is a read-only rollup of the learner's per-concept mastery by inventory domain, sourced from the `v_concept_mastery` SQL view. It is the queryable "what is known across the domain map" surface, distinct from per-session `startup-recall`:

```bash
python3 src/study_memory.py knowledge-map
python3 src/study_memory.py knowledge-map --domain vascular --limit 10
```

It returns `bound_concepts`, a `domain_rollup` (per domain: `concepts`, `deep`, `superficial`, `unexposed`, `open_gaps`), `due_now`, and the top `weak_spots` (low success rate or many open gaps). Use it for orientation and audits — "where is the learner weakest across domains", coverage sanity checks after a migration — not as a teaching queue inside a session. The view counts only concepts bound to an inventory id (Identity-first); unbound legacy concepts have no domain and are excluded by design, so a rising `bound_concepts` count is also a binding-health signal. The view is fan-out-safe (per-concept aggregates come from correlated subqueries, not joins), so `attempts`/`successes`/`open_gaps` are exact.

## Routine Maintenance Cadence

The commands above are for *deliberate* audits — explicit memory-layer reviews, repeated topic-resolution drift, or seeding the reference graph. They are not part of the teaching loop.

Routine identity and telemetry audits do not need a separate invocation: the post-flush curation pass already carries them. When `curation.recommended` is `true`, `curate-candidates` returns a `maintenance` block with `identity_audit` and `telemetry_audit` results, and any duplicate-topic merges are proposed from there. See `memory-curation.md`. Run the standalone commands in this file only when auditing outside that cadence.

## Guardrails

- Never auto-merge identity candidates.
- Never generate reference edges from learner misses.
- Never write learner relationships or shadow rules outside `apply-curation`.
- Never treat a graph path as a teaching mandate; verify that the path fits the clinical context.
