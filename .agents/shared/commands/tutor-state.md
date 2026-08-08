# Tutor State

Runtime contract for the token-bounded `tutor_state_v1` returned by
`study_memory.py start-session` and `startup-recall --profile tutor`.

## Authority

SQLite is the learner-evidence authority. The live knowledge-map file is an
atomic, rebuildable working projection. `tutor_state` is the smallest actionable
view of those stores; it is not a replacement database and omitted nodes are not
absent knowledge.

Read in this order:

1. `lifecycle`: proceed only from `teach`; `paused` or `close` requires the
   corresponding transition.
2. `phase_controller`: honor remediation, due-retention, safety, and provenance
   constraints. The recommended phase governs by default. Override only when its
   evidence is sparse, degraded, or misbound, and record the reason in the next
   typed turn assessment.
3. `active_target` and `learner_evidence`: design the immediate question from the
   exact claim trace, not a generic topic weakness.
4. `knowledge_map.active_nodes`: this is a ranked window over the full map.
   `omitted_nodes` means use `node-recall` after selecting one canonical node,
   never preload the whole map.
5. `context_expansion.nearby_nodes`: accept only a central one-hop prerequisite,
   confuser, consequence, or transfer bridge. A second hop requires naming the
   explanatory bridge first.
6. `artifact_alignment`: a document map is usable only when status is
   `available` and its content hash is matched. Stale or unverified maps must be
   rebuilt from the current artifact before teaching from their anchors.
7. `learner_profile`: PGY/service set expected responsibility, not mastery.
   Observed concept-specific evidence determines scaffolding.
8. `source_verification`: after learner commitment, verify conduct-changing
   thresholds, doses, timing, reversal, classifications, guidelines, and
   controversies before persisting a confident graded rule.

Routine startup must not request the audit profile merely because nodes or
evidence were omitted. Use `node-recall` for one selected concept. Use
`profile=audit` only for an incoherent state, identity repair, explicit memory
audit, or safety-critical ambiguity.

`response_contract.after_commitment` defines the complete repair bundle:
verdict, preserved edge, missing/false edge, causal model, clinical consequence,
nearest alternative, compression rule, then near transfer. Deliver only the
elements needed by this answer, but do not reduce a technical repair to a bare
correction.
