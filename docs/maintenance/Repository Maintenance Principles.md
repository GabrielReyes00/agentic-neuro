# Repository Maintenance Principles

This document is the canonical maintenance policy for agents and developers
changing Agentic Neuro. `AGENTS.md` still owns user posture, routing, safety,
and system boundaries. The workflow registry and shared contracts still own
runtime behavior. This file owns how repository changes, generated files,
persistent stores, and cleanup are handled.

The initial repository-wide classification and cleanup evidence is recorded in
`docs/maintenance/Repository Hygiene Audit.md`.

## Start From Authority

1. Read `AGENTS.md` and this document before repository-wide work.
2. Change the smallest canonical authority:
   - workflow identity and graph: `.agents/shared/workflow-registry.json`;
   - workflow behavior: `.agents/shared/commands/`;
   - runtime paths: `src/runtime_paths.py`;
   - store schemas: `src/store_contracts.py` and `src/store_migrations.py`;
   - generated adapters: regenerate with `src/sync_agent_adapters.py`; never
     hand-edit generated copies.
3. Search for producers, consumers, tests, and generated mirrors before moving,
   renaming, or deleting a file.
4. Preserve unrelated worktree changes. Use an isolated branch and a measured
   baseline for broad optimization.

## Prefer Executable Boundaries

- Put deterministic sequencing, approvals, state transitions, persistence, and
  validation in code or typed workflow specifications.
- Keep clinical reasoning, synthesis, teaching, and judgment in the model.
- Load only the current workflow node's contracts. Add context only after a
  declared transition.
- Centralize a rule once and reference it. Do not duplicate policy across
  Codex, Claude, Gemini, plugins, or phase modules.
- Add a behavioral test for routing or agent decisions and a deterministic test
  for code, schemas, graphs, or validators.

## Protect The Eight Active Stores

The repository has eight active logical stores and no repo-local alternate
copy is authoritative:

| Role | Active path |
|---|---|
| Learner memory | `data/study_memory.db` |
| Curriculum inventory | `data/concept_inventory.db` |
| Vault metadata/index | `data/vault_index.db` |
| Anki semantic cache | `data/anki_vector_cache.db` |
| Mini-RAG lexical index | `data/mini_rag_fts.db` |
| Textbook vectors | `neurosurgery_v4.lance` |
| Mini-RAG vectors | `data/mini_rag.lance` |
| Vault vectors | `data/vault_index.lance` |

- Resolve mutable paths through `src/runtime_paths.py`; do not introduce a
  second hard-coded path.
- Tests must redirect every mutable store to a temporary directory before
  importing source modules.
- Test migrations on a copied database first. For a live migration, use a
  transaction and an external temporary snapshot created with `mktemp -d`.
  Delete that snapshot after successful integrity, behavior, and hash checks.
  If migration fails, stop and report the external recovery path.
- Do not leave database, Lance, vault, or model snapshots inside the repository.
- Never infer that the newest-looking file is authoritative. Only the paths in
  `runtime_paths.py` and this table are active.

## Give Every Generated File A Lifecycle

Every generated file must be one of four classes:

- `deliverable`: the requested durable artifact; store it once at its canonical
  destination.
- `audit`: compact evidence needed to validate or reproduce a decision; keep it
  only when it has continuing review value.
- `cache`: rebuildable performance state; use the centralized cache directory
  and permit deletion at any time.
- `transient`: extraction, rendering, intermediate retrieval, scratch, or
  conversion output; delete it after successful use.

New artifact workflows must write beneath
`data/Sessions/runs/<workflow>/<run-id>/`, register artifacts in the run
manifest, and assign a retention class. Do not create loose files directly in
`data/Sessions/`. Temporary tools should use `tempfile` or `mktemp -d`, not a
persistent `tmp_*` path in the repository.

Normal cleanup rules:

- delete transient artifacts when the workflow reaches a terminal state;
- expire abandoned live study maps after 48 hours;
- keep caches in one configured location, never under `data/Sessions/`;
- remove `.DS_Store`, Python bytecode, test caches, build products, editable
  install metadata, and repository `tmp/` outputs after their producing task;
- never broadly delete `data/Sessions/`, the vault, or an active store;
- require explicit user approval before deleting deliverables, historical
  clinical/study artifacts, or ambiguous legacy outputs.

## Measure Before Claiming Improvement

- Establish the baseline under the same data, cache, model, and machine-load
  conditions.
- Measure the dimension being claimed: tokens, latency, calls, bytes, quality,
  recall, behavior, or failure detection.
- Retain a change only when it preserves required behavior and improves the
  intended frontier.
- Do not equate fewer prompt tokens with equal total-workflow latency, or a
  passing schema check with correct clinical behavior.

## Required Handoff

Before handing off a repository change:

1. Run adapter synchronization, workflow validation, instruction lint,
   architecture audit, store health, `src/repository_hygiene.py --check`,
   targeted tests, and the full suite in proportion to risk.
   For study-review changes also run `src/study_review_eval.py validate` and
   `benchmarks/benchmark_study_review.py --check`; real teaching-effectiveness
   claims require judged candidate transcripts, not contract keywords.
2. Run `git diff --check` and review every changed, deleted, untracked, and
   ignored path relevant to the task.
3. Report measured before/after results, active-store health, retained warnings,
   and anything deliberately not deleted.
4. Do not commit, push, merge, publish, or delete branches unless the user has
   requested that action.

The governing maintenance rule is: **one authority, one active store per role,
one durable copy per artifact, and no generated file without an owner and an
end-of-life rule.**
