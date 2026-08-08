# Repository Hygiene Audit

Date: 2026-08-08  
Branch: `codex/repo-architecture-overhaul`

## Outcome

The repository now has one active store per role, no persistent database
backups, no alternate Lance dataset, no loose workflow scratch files, and no
known disposable build/test debris. The audit is enforced by
`src/repository_hygiene.py --check` in CI.

The cleanup was intentionally asymmetric: reproducible and superseded files
were removed, while a file without a proven canonical replacement was kept.

## Database and vector cleanup

All eight active logical stores remain intact:

- five SQLite stores: learner memory, curriculum inventory, vault index, Anki
  vector cache, and Mini-RAG FTS;
- three Lance stores: textbook, Mini-RAG, and vault vectors.

Removed after explicit approval:

- 12 historical SQLite backup databases;
- four SQLite backup WAL/SHM sidecars;
- one explicit vault-vector Lance backup;
- one retired textbook-nested vault-vector fallback.

The health check now treats recreation of
`neurosurgery_v4.lance/vault_notes.lance` as a failure. Future migrations must
use an external temporary snapshot, verify the active store, and remove the
snapshot after success.

## Generated-file findings

Before cleanup, `data/Sessions` contained 1,950 unmanaged files totaling
226,032,688 logical bytes. These came from older workflows that wrote directly
to a shared directory before run manifests and retention classes existed.

| Finding | Why it existed | Decision |
|---|---|---|
| 105 `knowledge_map_*.json` files | Live study maps and benchmark/test scenarios were written to the shared Sessions root. | Removed. New maps use `data/runtime/study_maps`; tests and the memory benchmark redirect to temporary roots. |
| Duplicate FastEmbed cache | Anki code hard-coded `data/Sessions/fastembed_cache` while Mini-RAG used `data/fastembed_cache`. The two copies had identical file hashes. | Removed the Sessions copy. All callers now use the centralized runtime path. |
| Vault redesign snapshot | A prior migration copied the complete Obsidian vault, including its `.git`, into Sessions. The current vault and all 34 indexed binaries passed integrity review. | Removed the 1,360-file snapshot and its one-use receipts. |
| Nine journal-club work directories | PDF extraction, page renders, source manifests, drafts, and validation ledgers remained after final dossiers and PDFs were installed in the vault. | Removed after matching all nine topics to current vault notes and source PDFs. |
| Report research directories | Source cards and prior report versions remained after final Lumbar Interbody, Vestibular Schwannoma, and Spine Emergencies reports were installed. | Removed after confirming current vault reports. |
| Grand-rounds intermediates | Contact sheets, deck plans, scripts, manifests, and visual-QA files remained after decks/notes were installed. | Removed where installed artifacts were verified. |
| Anki exports and maintenance packets | Live Anki had been exported repeatedly for audits; live Anki and the current cache are authoritative. | Removed exports, plans, apply receipts, and flush logs; retained the active queue. |
| Dry runs, workflow ledgers, shadow tests, and loose RAG packets | Older workflow-development and optimization runs had no lifecycle owner. | Removed. Behavioral cases and benchmark JSON now provide durable regression evidence. |
| One-use audit scripts and reports | April session audits, RAG provenance packets, and old hook reports were never consumed at runtime. | Removed after retaining the current architecture report, benchmark summaries, and automated tests. |
| Build/test debris | `build/`, editable-install metadata, `.pytest_cache`, `__pycache__`, `.DS_Store`, and PDF render pages accumulated normally. | Removed; ignored and reported as rebuildable debris if recreated. |

After cleanup, `data/Sessions` contains five files totaling 69,733 logical
bytes:

- `.gitkeep` — keeps the runtime root available in a clean checkout;
- `anki_queue.jsonl` — active session queue;
- `bns_jeopardy_ta_review.md` — retained because no canonical replacement was
  proven;
- `Lab_3_Long_Tracts_artifact.md` and
  `reconciliation-preserved/3d_mental_model_review_plan.md` — retained because
  their names and contents indicate deliberate learning artifacts without a
  verified installed replacement.

The three retained historical learning artifacts are not runtime inputs. They
remain an explicit user-retention decision rather than being deleted by an
automated hygiene rule.

## Intentionally retained large paths

These are large but not obsolete:

- `neurosurgery_v4.lance` — active 15 GB textbook corpus;
- `data/models` — active local embedding and reranking models;
- `.venv` — current development environment;
- `data/fastembed_cache` — the sole centralized Mini-RAG/Anki FastEmbed cache;
- current SQLite and Lance stores;
- tracked workflow adapters, runtime specifications, benchmark summaries, and
  behavioral evaluation cases.

Generated adapters are deliberate compiled surfaces, not duplicate authority.
The synchronization check detects both drift and unexpected generated files.

## Prevention controls

1. `docs/maintenance/Repository Maintenance Principles.md` defines one active
   store per role and one lifecycle per generated artifact.
2. `src/repository_hygiene.py --check` rejects database copies, unexpected Lance
   stores, deprecated Sessions caches, loose study maps, and `tmp_*` outputs.
3. CI runs the hygiene check before the test suite.
4. Test configuration redirects databases, queues, caches, retrieval scratch,
   and study maps to one disposable temporary root.
5. The learner-memory benchmark now redirects its study-map output before
   importing application modules.
6. Retrieval scratch and frontier handoff files use
   `data/runtime/retrieval`, not `data/Sessions`.
7. FastEmbed callers share `data/fastembed_cache` through
   `src/runtime_paths.py`.
8. New artifact workflows use run manifests and retention classes beneath
   `data/Sessions/runs/` instead of unowned loose files.
9. A terminal workflow can run `run_artifacts.py prune --apply` to delete only
   its registered transient files while preserving deliverables and audit
   evidence.

## Maintenance decision rule

Delete automatically only when an artifact is reproducible, transient,
superseded by a verified canonical destination, or explicitly approved. Retain
and surface anything that may be a unique clinical, educational, or
user-authored artifact.
