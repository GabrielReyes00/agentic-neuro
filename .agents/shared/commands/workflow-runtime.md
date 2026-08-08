# Workflow Runtime

Use the selected generated runtime spec under `.agents/shared/runtime/` as the
execution map. The full workflow registry remains canonical but is an audit and
generation surface; do not preload it during ordinary execution.

At entry, load only the files listed by the entry node. On transition, load any
new files listed by the destination node. Markdown contracts own clinical and
artifact behavior; the graph owns ordering, branches, context boundaries, and
durable run-state requirements. A graph never replaces agent judgment.

Context values are operational:

- `conversation`: retain the user conversation and act in the current turn.
- `run_scoped`: use the durable run manifest and registered artifacts as the
  cross-phase data bus; do not assume unrecorded reasoning is available.
- `isolated`: the phase must be executed without access to prior draft
  reasoning. Record the independent verdict as an audit artifact before
  advancing. If the runtime cannot provide isolation, report that limitation;
  do not describe an ordinary continuation as independent review.

Only transitions declared for the current node are valid. Back-edges require an
explicit loop in the registry. Approval nodes never imply approval: an external
mutation or exceptional incomplete install still waits for the user’s explicit
authorization.

Workflows with `run_state: manifest` use
`data/Sessions/runs/<workflow>/<run-id>/run_manifest.json`. Workflows with
`run_state: learner_memory` persist the outer lifecycle in
`study_runtime_sessions` through typed `start-session`, `assess-turn`, and
`close-session` interfaces. These enforce `prepare → teach ↺ → close → done`;
the finer ORIENT/DEEPEN/CONNECT policy remains in `policy_events` and the live
knowledge-map projection. `run_state: none` creates no bookkeeping solely for
graph traversal.

For a manifest workflow, start once at entry with
`python3 src/workflow_runtime.py start <workflow> --run-id <stable-run-id>
--title "<title>"`; parse the returned path silently and call it `RUN_DIR` in
workflow instructions. The start marks the manifest `running`. Write recovery,
evidence, draft, and verdict artifacts only beneath that directory and register
each durable file with `run_artifacts.py register`, using `audit`, `deliverable`,
`cache`, or `transient` retention intentionally. Deliverables installed outside
the runtime directory are represented by their run-scoped source or receipt;
manifest paths never escape the run.

Advance only with an outcome named on the current node:
`python3 src/workflow_runtime.py advance --run-dir "$RUN_DIR" --outcome
<declared-outcome>`. Reaching a terminal node marks the run completed unless the
edge declares another terminal status. On a real failure, preserve diagnostic
artifacts and mark the manifest failed through `run_artifacts.py transition`.
Do not create a second run directory to work around a failed node.

After a terminal transition and successful installation or validation, remove
only manifest-registered transient files with `python3 src/run_artifacts.py
prune --run-dir "$RUN_DIR" --apply`. This command cannot prune a running workflow
and never removes audit, cache, or deliverable records.
