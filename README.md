# Agentic Neuro

Agentic Neuro is a local agent harness for neurosurgical learning and durable
clinical documentation. It combines deterministic workflow contracts, learner
memory, a canonical curriculum, textbook and vault retrieval, Anki integration,
and validators for generated artifacts.

The repository is intentionally not one monolithic agent. `AGENTS.md` owns
system posture and routing, `.agents/shared/workflow-registry.json` owns the
workflow catalog, and `.agents/shared/commands/` owns workflow behavior. Runtime
adapters are generated from those authorities and should remain thin.

## Workflow execution model

Each canonical workflow has a typed execution graph in
`.agents/shared/workflow-registry.json`. The graph declares its entry node,
allowed transitions, context boundary, and state backend. Generated
`.agents/shared/runtime/<workflow>.json` projections are the normal startup
surface, so invoking one workflow does not load the full registry or unrelated
contracts. The Markdown files named by the current node still own clinical and
artifact behavior; the graph owns orchestration.

Use `conversation` context for ordinary turns, `run_scoped` context for phases
that communicate through registered artifacts, and `isolated` only for a real
independent review. Durable artifact workflows persist their current node in a
run manifest. Direct answers create no traversal files, and study review keeps
using assessed learner memory. Validate the graph and inspect an individual
plan with:

```bash
python3 src/workflow_runtime.py validate
python3 src/workflow_runtime.py plan intraoperative-guide
```

The instruction audit measures entry-load cost against the former full-registry
startup path. This keeps prompt optimization testable without treating total
repository documentation size as runtime context size.

## Setup

Python 3.11 through 3.14 is supported. Create the repository virtual
environment and install the complete local stack:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[full,dev]"
```

For instruction, database, and validator development without embedding models,
install only `.[dev]`. `requirements.txt` remains a compatibility entry point
for a full editable install. `requirements.lock` records the exact Python 3.14
environment used for the August 2026 audit; use it when reproducing that
benchmark environment on a compatible platform, then install the repository
itself without re-resolving dependencies:

```bash
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
```

Model weights and user databases are deliberately not installed or committed.
The retrieval stack defaults to offline model loading after its caches have
been provisioned.

## Validate

Run commands from the repository environment:

```bash
source .venv/bin/activate
python3 src/sync_agent_adapters.py --check
python3 src/workflow_runtime.py validate
python3 src/instruction_audit.py all
python3 src/code_architecture_audit.py
python3 src/system_health.py --json
python3 src/repository_hygiene.py --check
python3 src/run_artifacts.py audit
pytest -q
```

The test harness redirects mutable runtime, Anki cache, and queue paths to a
disposable directory before test collection. A test run must not modify live
learner, curriculum, vault, retrieval, Anki, or session state.

## Data boundaries

- `data/study_memory.db`: assessed learner evidence; access through
  `src/study_memory.py`.
- `data/concept_inventory/` and `data/concept_inventory.db`: canonical
  curriculum sources and compiled index, not learner state.
- `data/vault_index.db` and `data/vault_index.lance`: supplemental Obsidian
  retrieval indexes, not curriculum or learner state.
- `neurosurgery_v4.lance`: textbook corpus only.
- `data/vault_index.lance`: isolated Obsidian vault vector index (`vault_notes`).
- `data/anki_vector_cache.db`: rebuildable Anki similarity cache; live Anki is
  authoritative.
- `data/Sessions/`: workflow run artifacts with explicit manifests and scoped
  cleanup; never delete it broadly.

New durable workflow runs live under
`data/Sessions/runs/<workflow>/<run-id>/`. Their `run_manifest.json` records
status, artifact roles, and retention classes using only run-relative paths.
`run_artifacts.py plan-prune` is deliberately advisory: it never deletes legacy
files or even eligible transient files.

See `AGENTS.md` before changing workflow behavior or persistent user data.
Read
`docs/maintenance/Repository Maintenance Principles.md` before repository-wide
maintenance, migrations, generated-file changes, or cleanup.
