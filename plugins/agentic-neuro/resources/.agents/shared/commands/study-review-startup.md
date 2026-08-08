# Study Review Startup

Startup-only contract for `/study-review`. Load this file with `tutor-state.md`.

## Learner-Facing Invariant

Startup is silent. On success, ask one answerable clinical question and stop;
at most add one short orientation clause. Do not narrate memory, retrieval,
Anki, the prior handoff, contract loading, or graph transitions.

The only pre-question exception is non-empty `tutor_state.alignment_proposals`:
show the compact identity proposal and request approval because realignment is a
persistent learner-memory mutation.

## Typed Entry

Create one UTC session id and submit a JSON request through stdin:

```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
python3 src/study_memory.py start-session --stdin
```

Payload:

```json
{
  "session_id": "<SESSION_TS>",
  "mode": "document|topic|memory",
  "topic": "<canonical topic when known>",
  "doc_path": "<vault-relative path when document mode>",
  "context": "<optional upcoming case, rotation, or responsibility>",
  "lens": "general"
}
```

- **Document:** resolve a reviewable vault document through
  `.agents/shared/workflow-registry.json`. Read the full file
  only when its artifact map is missing, stale, unverified, or when global
  synthesis is explicitly required. With a verified map, load the selected
  source section just in time.
- **Topic:** named topic without a document.
- **Memory:** weak spots, open errors, custom review, or board case without a
  named topic. Global output is routing-only; after selecting a candidate, start
  a topic-scoped session before teaching.

Service/site-local teaching remains provenance-isolated in `shift-debrief` and
`service-log`; never route it through this formal assessed-memory entry point.

`start-session` returns `startup_recall`, `tutor_state`, and
`retrieval_guidance`. `tutor-state.md` owns their runtime interpretation.

## Artifact Map Gate

In document mode, `tutor_state.artifact_alignment.status=available` means the
persisted map matches the current document hash. Any `missing`, `stale`, or
`unverified` state requires reading the current artifact, building its concept
map from the body, and upserting with a content hash before restarting once:

```bash
python3 src/study_memory.py artifact-map-upsert \
  --topic "<topic>" --doc "<folder>/<file>.md" --stdin
```

The map must preserve artifact-native concepts, section anchors, inventory
identities, prerequisites/confusers, clinical or operative consequences, and
unresolved concepts. The artifact remains primary. Nearby nodes enter only as a
blocking prerequisite, discriminator, consequence, or one-hop transfer bridge.

## Opening Decision

- If routing or identity remains ambiguous, resolve it before teaching.
- If the map is empty but the topic is legitimate, begin ORIENT from the
  artifact/native curriculum rather than inventing prior mastery.
- Otherwise use the recommended phase, active target, exact learner trace, and
  one accepted nearby node at most.
- Never expand merely because `omitted_nodes` is nonzero.

After Gabriel answers, transition to `study-review-turn.md`.
