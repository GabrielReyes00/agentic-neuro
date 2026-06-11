# Fallback Retirement Gates

Pillar D discipline: every fallback is classified and either kept-and-instrumented
(resilience), kept-counted-and-time-boxed (migration bridge), or eliminated
(crutch). This file tracks the bridges that must be removed once the legacy memory
DB is fully migrated.

**Cutover status (2026-06-11):** the migrated + reshaped + consolidated DB is now
live at `data/study_memory.db` (120 concepts, 97 bound). The untouched legacy DB is
preserved at `data/study_memory.legacy.db` (both gitignored). The migration bridges
below are **retained for now** — they must stay until the new DB is validated with
real live review sessions on this branch. Retire them (per the steps at the bottom)
only after that validation, before merging to main.

## Resilience (keep, instrumented — do NOT remove)

- **SQLite-only schema map** when the inventory DB is unavailable. A resident must
  never hit a hard crash mid-shift. Observability: `planning_brief.knowledge_map_provenance`
  reports `inventory` vs `sqlite_fallback` vs `none`. Enforced by the healthy-path
  tests in `tests/test_fallback_provenance.py`.
- **Inferred binding** (lexical) when the agent omits `--inventory-concept-id`.
  Observability: the `binding={status:...}` line (`explicit` / `inferred` / `unresolved`).
  This is also how genuinely new concepts bootstrap, so it stays after migration.

## Migration bridges (remove after Pillar B is applied to the live DB)

- [ ] `session_map.patch_after_log` — `successes_count` reconstruction from the
  rounded `sqlite_success_rate`. Gate: once no legacy session maps exist and every
  projection emits `successes_count`, delete the fallback and read the field directly.
  (Marked `MIGRATION BRIDGE` in code.)
- [ ] `acgme_readiness.project_learner_history_onto_inventory` — lexical projection
  of *unbound* learner concepts. Gate: once `explicit_inventory_bindings` covers the
  attempted-concept set, the projection contributes ~0 and can be dropped in favor of
  explicit bindings only. Telemetered via `explicit_inventory_bindings` vs
  `lexically_projected_concepts` in the overlay output.

## Crutches (eliminated this redesign)

- Lexical inferred binding silently treated as equivalent to an explicit binding —
  now loudly distinguished by `binding.status` (Pillar A).
- Silent `except: pass` swallows that hid signal loss in `map_learner` and
  `node_recall` — now emit structured `WARN ...` lines (Pillar D).

## How to retire a bridge

1. Apply the migration to the live DB (with a backup), so the bridge's usage drops.
2. Confirm the telemetry shows ~0 usage (provenance `inventory`, projected ≈ 0).
3. Delete the bridge code and its compatibility tests; replace with the direct path
   and a healthy-path assertion that the direct path is taken.
